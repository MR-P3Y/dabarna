from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.redis_client import RedisLock
from app.models.game import Game, GameAutoDraw, GameCalledNumber
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

                sequence = control.sequence_json if isinstance(control.sequence_json, list) else []
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
                    control.status = "STOPPED"
                    control.cursor = cursor
                    control.next_draw_at = None
                    control.stopped_at = _utcnow_naive()
                    db.commit()
                    return False

                number = int(sequence[cursor])
                result = GameService.call_number(
                    db=db,
                    game_id=int(game_id),
                    number=number,
                    admin_user_id=int(control.started_by),
                    idempotency_key=f"auto:{game_id}:{cursor}:{number}",
                    can_manage_any=True,
                    source="AUTO",
                )
                control.cursor = cursor + 1
                game_ended = str(game.status) != "RUNNING" or int(result.get("row_paid") or 0) == 1
                if game_ended or control.cursor >= len(sequence):
                    control.status = "STOPPED"
                    control.next_draw_at = None
                    control.stopped_at = _utcnow_naive()
                else:
                    control.next_draw_at = _utcnow_naive() + timedelta(seconds=int(control.interval_seconds))
                db.commit()
                return True
            except Exception:
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
