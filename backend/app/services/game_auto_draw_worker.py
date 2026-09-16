from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.core.db import SessionLocal
from app.core.redis_client import RedisLock
from app.models.game import Game, GameAutoDraw, GameCalledNumber
from app.services.game_draw_mode_service import sequence_commitment
from app.services.game_event_service import GameEventService
from app.services.game_service import GameService


log = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GameAutoDrawWorker:
    @staticmethod
    def run_once() -> dict[str, int]:
        stats = {"due": 0, "drawn": 0, "stopped": 0, "failed": 0}
        lock = RedisLock("davarna:game-auto-draw-worker", ttl_ms=8_000)
        try:
            if not lock.acquire():
                return stats
        except Exception:
            log.warning("auto draw worker lock unavailable; cycle skipped", exc_info=True)
            return stats

        try:
            with SessionLocal() as db:
                due_ids = db.execute(
                    select(GameAutoDraw.game_id).where(
                        GameAutoDraw.status == "RUNNING",
                        GameAutoDraw.next_draw_at.is_not(None),
                        GameAutoDraw.next_draw_at <= _utcnow_naive(),
                    ).limit(25)
                ).scalars().all()
            stats["due"] = len(due_ids)
            for game_id in due_ids:
                try:
                    if GameAutoDrawWorker._draw_game(int(game_id)):
                        stats["drawn"] += 1
                    else:
                        stats["stopped"] += 1
                except Exception:
                    stats["failed"] += 1
                    log.exception("automatic number draw failed: game_id=%s", game_id)
            return stats
        finally:
            try:
                lock.release()
            except Exception:
                log.warning("auto draw worker lock release failed", exc_info=True)

    @staticmethod
    def _draw_game(game_id: int) -> bool:
        with SessionLocal() as db:
            mysql_guard_set = False
            try:
                control = db.execute(
                    select(GameAutoDraw)
                    .where(GameAutoDraw.game_id == int(game_id))
                    .with_for_update()
                ).scalar_one_or_none()
                if not control or str(control.status) != "RUNNING":
                    db.rollback()
                    return False
                game = db.execute(
                    select(Game).where(Game.id == int(game_id)).with_for_update()
                ).scalar_one_or_none()
                if not game or str(game.status) != "RUNNING":
                    control.status = "STOPPED"
                    control.next_draw_at = None
                    control.stopped_at = _utcnow_naive()
                    db.commit()
                    return False

                if str(game.draw_mode or "").upper() != "AUTO" or game.draw_mode_locked_at is None:
                    control.status = "PAUSED"
                    control.next_draw_at = None
                    db.commit()
                    log.error("auto draw paused: game is not a locked AUTO game game_id=%s", game_id)
                    return False

                if int(game.draw_interval_seconds or 0) != int(control.interval_seconds or 0):
                    control.status = "PAUSED"
                    control.next_draw_at = None
                    db.commit()
                    log.critical("auto draw paused: interval mismatch game_id=%s", game_id)
                    return False

                sequence = control.sequence_json if isinstance(control.sequence_json, list) else []
                actual_commitment = sequence_commitment([int(value) for value in sequence]) if sequence else ""
                expected_commitment = str(control.sequence_commitment or "")
                if not expected_commitment or actual_commitment != expected_commitment:
                    control.status = "PAUSED"
                    control.next_draw_at = None
                    try:
                        GameEventService.emit(
                            db,
                            kind="AUTO_DRAW_TAMPER_DETECTED",
                            game_id=int(game_id),
                            tg_group_id=int(game.tg_group_id),
                            actor_user_id=int(control.started_by),
                            idem_key=f"AUTO_DRAW_TAMPER_DETECTED:{game_id}:{int(_utcnow_naive().timestamp())}",
                            payload={
                                "expected_commitment": expected_commitment or None,
                                "actual_commitment": actual_commitment or None,
                                "cursor": int(control.cursor or 0),
                            },
                        )
                    except Exception:
                        pass
                    db.commit()
                    log.critical("AUTO sequence commitment mismatch; game paused game_id=%s", game_id)
                    return False

                called = set(
                    int(value)
                    for value in db.execute(
                        select(GameCalledNumber.number).where(GameCalledNumber.game_id == int(game_id))
                    ).scalars().all()
                )
                cursor = max(0, int(control.cursor or 0))
                while cursor < len(sequence) and int(sequence[cursor]) in called:
                    cursor += 1
                if cursor >= len(sequence):
                    # Do not transition a still-running locked AUTO game to STOPPED.
                    # A game without a terminal winner must be inspected instead.
                    control.status = "PAUSED"
                    control.cursor = cursor
                    control.next_draw_at = None
                    db.commit()
                    log.error("AUTO sequence exhausted while game still RUNNING game_id=%s", game_id)
                    return False

                number = int(sequence[cursor])

                # MySQL trigger accepts number insertion for locked AUTO games only from
                # this worker connection. Always clear the session marker before the
                # pooled connection is returned.
                if db.get_bind().dialect.name == "mysql":
                    db.execute(text("SET @davarna_auto_draw_game_id = :gid"), {"gid": int(game_id)})
                    mysql_guard_set = True

                try:
                    result = GameService.call_number(
                        db=db,
                        game_id=int(game_id),
                        number=number,
                        admin_user_id=int(control.started_by),
                        idempotency_key=f"auto:{game_id}:{cursor}:{number}",
                        can_manage_any=True,
                        source="AUTO",
                    )
                finally:
                    if mysql_guard_set:
                        db.execute(text("SET @davarna_auto_draw_game_id = NULL"))
                        mysql_guard_set = False

                control.cursor = cursor + 1
                game_ended = str(game.status) != "RUNNING" or int(result.get("row_paid") or 0) == 1
                if game_ended:
                    control.status = "STOPPED"
                    control.next_draw_at = None
                    control.stopped_at = _utcnow_naive()
                elif control.cursor >= len(sequence):
                    control.status = "PAUSED"
                    control.next_draw_at = None
                else:
                    control.next_draw_at = _utcnow_naive() + timedelta(seconds=int(control.interval_seconds))
                db.commit()
                return True
            except Exception:
                if mysql_guard_set:
                    try:
                        db.execute(text("SET @davarna_auto_draw_game_id = NULL"))
                    except Exception:
                        pass
                db.rollback()
                raise


async def run_game_auto_draw_worker_forever(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            stats = await asyncio.to_thread(GameAutoDrawWorker.run_once)
            if stats["drawn"] or stats["failed"]:
                log.info("game auto draw worker cycle: %s", stats)
        except Exception:
            log.exception("game auto draw worker cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
