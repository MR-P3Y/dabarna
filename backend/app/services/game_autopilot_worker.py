from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select

from app.core import config as cfg
from app.core.db import SessionLocal
from app.core.redis_client import RedisLock
from app.models.game import Game, GameCard
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.services.game_autopilot_config_service import (
    AUTOPILOT_LEVELS,
    GameAutopilotConfigService,
)
from app.services.game_draw_mode_service import GameDrawModeService
from app.services.game_service import GameService


log = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class GameAutopilotWorker:
    @staticmethod
    def _lane_match(level: str, topic_id: int):
        # Compatibility: pre-autopilot games have game_level=NULL, but their
        # Telegram topic still identifies the LOW/MEDIUM/HIGH lane.
        return or_(
            Game.game_level == str(level),
            and_(
                Game.game_level.is_(None),
                Game.tg_topic_id == int(topic_id),
            ),
        )

    @staticmethod
    def _active_game(db, *, level: str, group_id: int, topic_id: int) -> Game | None:
        return (
            db.execute(
                select(Game)
                .where(
                    Game.tg_group_id == int(group_id),
                    GameAutopilotWorker._lane_match(level, topic_id),
                    Game.status.in_(["LOBBY", "RUNNING"]),
                )
                .order_by(Game.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    @staticmethod
    def _latest_ended_game(db, *, level: str, group_id: int, topic_id: int) -> Game | None:
        return (
            db.execute(
                select(Game)
                .where(
                    Game.tg_group_id == int(group_id),
                    GameAutopilotWorker._lane_match(level, topic_id),
                    Game.status == "ENDED",
                )
                .order_by(Game.ended_at.desc(), Game.id.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )

    @staticmethod
    def _unique_players(db, game_id: int) -> int:
        value = db.execute(
            select(func.count(func.distinct(GameCard.user_id))).where(
                GameCard.game_id == int(game_id)
            )
        ).scalar_one()
        return int(value or 0)

    @staticmethod
    def _ensure_draw_mode(
        db,
        *,
        game: Game,
        config: GameAutopilotConfig,
        actor_user_id: int,
    ) -> None:
        if str(game.status) != "LOBBY" or game.draw_mode_locked_at is not None:
            return
        if str(game.draw_mode or "").upper() in {"MANUAL", "AUTO"}:
            return

        desired = str(config.draw_mode or "MANUAL").upper()
        if desired == "AUTO" and not cfg.GAME_AUTO_DRAW_ENABLED:
            raise RuntimeError("GAME_AUTO_DRAW_ENABLED is false")

        interval = int(config.draw_interval_seconds) if desired == "AUTO" else None
        max_number = int(GameService._get_setting(db, GameService.KEY_MAX_NUMBER, 90))
        GameDrawModeService.select_mode(
            db,
            game_id=int(game.id),
            admin_user_id=int(actor_user_id),
            draw_mode=desired,
            interval_seconds=interval,
            max_number=max_number,
            can_manage_any=True,
        )

    @staticmethod
    def _manage_active(
        db,
        *,
        game: Game,
        config: GameAutopilotConfig,
        actor_user_id: int,
        now: datetime,
    ) -> str:
        if str(game.status) != "LOBBY":
            return "running"

        GameAutopilotWorker._ensure_draw_mode(
            db,
            game=game,
            config=config,
            actor_user_id=actor_user_id,
        )

        if str(config.start_mode or "MANUAL").upper() != "AUTO":
            return "lobby_manual_start"

        if str(game.draw_mode or "").upper() == "AUTO" and not cfg.GAME_AUTO_DRAW_ENABLED:
            return "blocked_auto_draw_disabled"

        players = GameAutopilotWorker._unique_players(db, int(game.id))
        minimum = max(2, int(config.min_unique_players or 2))
        if players < minimum:
            return "waiting_players"

        scheduled = _as_datetime(game.scheduled_start_at)
        if scheduled is None:
            game.scheduled_start_at = now + timedelta(
                seconds=max(5, int(config.countdown_seconds or 30))
            )
            db.flush()
            return "countdown_armed"

        if scheduled > now:
            return "countdown_wait"

        GameService.start_game(
            db=db,
            game_id=int(game.id),
            admin_user_id=int(actor_user_id),
            idempotency_key=f"autopilot:start:{int(game.id)}",
            can_manage_any=True,
        )
        return "started"

    @staticmethod
    def _run_level(level: str) -> str:
        now = _utcnow_naive()
        with SessionLocal() as db:
            config = db.get(GameAutopilotConfig, str(level))
            if config is None or not bool(int(config.enabled or 0)):
                return "disabled"

            topic_id = GameAutopilotConfigService.topic_id_for_level(str(level))
            group_id = cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID
            actor_user_id = cfg.GAME_AUTOPILOT_SYSTEM_USER_ID

            if topic_id is None:
                return "missing_topic"
            if group_id is None:
                return "missing_group"
            if actor_user_id is None:
                return "missing_system_user"
            if db.get(User, int(actor_user_id)) is None:
                return "invalid_system_user"

            active = GameAutopilotWorker._active_game(
                db,
                level=str(level),
                group_id=int(group_id),
                topic_id=int(topic_id),
            )
            if active is not None:
                result = GameAutopilotWorker._manage_active(
                    db,
                    game=active,
                    config=config,
                    actor_user_id=int(actor_user_id),
                    now=now,
                )
                db.commit()
                return result

            if str(config.scheduler_mode or "MANUAL").upper() != "AUTO":
                return "no_active_manual_scheduler"

            if config.card_price is None or int(config.card_price) <= 0:
                return "missing_card_price"

            if str(config.draw_mode or "MANUAL").upper() == "AUTO" and not cfg.GAME_AUTO_DRAW_ENABLED:
                return "blocked_auto_draw_disabled"

            latest = GameAutopilotWorker._latest_ended_game(
                db,
                level=str(level),
                group_id=int(group_id),
                topic_id=int(topic_id),
            )
            if latest is not None:
                ended_at = _as_datetime(latest.ended_at) or _as_datetime(latest.created_at)
                if ended_at is not None:
                    delay_seconds = max(
                        int(config.cooldown_seconds or 0),
                        int(config.repeat_interval_seconds or 0),
                    )
                    if now < ended_at + timedelta(seconds=max(0, delay_seconds)):
                        return "cooldown"

            game = GameService.create_game(
                db=db,
                admin_user_id=int(actor_user_id),
                tg_group_id=int(group_id),
                tg_topic_id=int(topic_id),
                card_price=int(config.card_price),
                game_level=str(level),
                execution_source="SYSTEM",
                scheduled_start_at=None,
            )
            GameAutopilotWorker._ensure_draw_mode(
                db,
                game=game,
                config=config,
                actor_user_id=int(actor_user_id),
            )
            db.commit()
            return "created"

    @staticmethod
    def run_once() -> dict[str, object]:
        result: dict[str, object] = {
            "runtime_enabled": bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED),
            "levels": {},
            "failed": 0,
        }
        if not cfg.GAME_AUTOPILOT_RUNTIME_ENABLED:
            return result

        ttl_ms = max(8_000, int(cfg.GAME_AUTOPILOT_TICK_SECONDS) * 4_000)
        lock = RedisLock("davarna:game-autopilot-worker", ttl_ms=ttl_ms)
        try:
            if not lock.acquire():
                result["lock"] = "busy"
                return result
        except Exception:
            result["lock"] = "unavailable"
            log.warning("autopilot worker lock unavailable; cycle skipped", exc_info=True)
            return result

        try:
            level_results: dict[str, str] = {}
            for level in AUTOPILOT_LEVELS:
                try:
                    state = GameAutopilotWorker._run_level(str(level))
                    level_results[str(level)] = state
                except Exception:
                    result["failed"] = int(result["failed"]) + 1
                    level_results[str(level)] = "failed"
                    log.exception("autopilot level cycle failed: level=%s", level)
            result["levels"] = level_results
            return result
        finally:
            try:
                lock.release()
            except Exception:
                log.warning("autopilot worker lock release failed", exc_info=True)


async def run_game_autopilot_worker_forever(stop_event: asyncio.Event) -> None:
    tick = max(1, int(cfg.GAME_AUTOPILOT_TICK_SECONDS))
    log.info(
        "game autopilot worker started: tick=%ss system_user_id=%s",
        tick,
        cfg.GAME_AUTOPILOT_SYSTEM_USER_ID,
    )
    while not stop_event.is_set():
        try:
            stats = await asyncio.to_thread(GameAutopilotWorker.run_once)
            levels = stats.get("levels") if isinstance(stats, dict) else {}
            if isinstance(levels, dict) and any(
                value in {"created", "countdown_armed", "started", "failed"}
                for value in levels.values()
            ):
                log.info("game autopilot worker cycle: %s", stats)
        except Exception:
            log.exception("game autopilot worker cycle failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=float(tick))
        except asyncio.TimeoutError:
            pass
