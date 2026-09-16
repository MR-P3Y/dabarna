from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.game import Game, GameAutoDraw, GameCalledNumber
from app.services.game_event_service import GameEventService


AUTO_DRAW_INTERVALS = (5, 8, 10, 15)
AUTO_DRAW_STATUSES = {"RUNNING", "PAUSED", "STOPPED"}


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GameAutoDrawService:
    @staticmethod
    def _remaining_sequence(db: Session, game_id: int, max_number: int) -> list[int]:
        called = set(
            int(value)
            for value in db.execute(
                select(GameCalledNumber.number).where(GameCalledNumber.game_id == int(game_id))
            ).scalars().all()
        )
        remaining = [number for number in range(1, int(max_number) + 1) if number not in called]
        secrets.SystemRandom().shuffle(remaining)
        return remaining

    @staticmethod
    def _game_for_update(db: Session, game_id: int) -> Game:
        game = db.execute(
            select(Game).where(Game.id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        return game

    @staticmethod
    def _require_access(game: Game, admin_user_id: int, can_manage_any: bool) -> None:
        if not can_manage_any and int(game.admin_user_id) != int(admin_user_id):
            raise HTTPException(status_code=403, detail="only game admin can manage auto draw")

    @staticmethod
    def _emit(db: Session, *, game: Game, control: GameAutoDraw, action: str, actor_user_id: int) -> None:
        try:
            GameEventService.emit(
                db,
                kind=f"AUTO_DRAW_{action}",
                game_id=int(game.id),
                tg_group_id=int(game.tg_group_id),
                actor_user_id=int(actor_user_id),
                idem_key=(
                    f"AUTO_DRAW_{action}:{game.id}:{control.cursor}:"
                    f"{int(_utcnow_naive().timestamp() * 1000)}"
                ),
                payload={
                    "status": str(control.status),
                    "interval_seconds": int(control.interval_seconds),
                    "cursor": int(control.cursor),
                    "remaining_count": max(0, len(control.sequence_json or []) - int(control.cursor)),
                },
            )
        except Exception:
            pass

    @staticmethod
    def get(db: Session, game_id: int) -> dict[str, Any]:
        game = db.execute(select(Game).where(Game.id == int(game_id))).scalar_one_or_none()
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        control = db.get(GameAutoDraw, int(game_id))
        return GameAutoDrawService.to_dict(game, control)

    @staticmethod
    def start(
        db: Session,
        *,
        game_id: int,
        admin_user_id: int,
        interval_seconds: int,
        max_number: int,
        can_manage_any: bool = False,
    ) -> dict[str, Any]:
        interval = int(interval_seconds)
        if interval not in AUTO_DRAW_INTERVALS:
            raise HTTPException(status_code=400, detail="interval_seconds must be one of 5, 8, 10, 15")
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        if str(game.status) != "RUNNING":
            raise HTTPException(status_code=400, detail="game is not RUNNING")

        sequence = GameAutoDrawService._remaining_sequence(db, game_id, max_number)
        if not sequence:
            raise HTTPException(status_code=400, detail="no numbers remain to draw")
        now = _utcnow_naive()
        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if control is None:
            control = GameAutoDraw(
                game_id=int(game_id),
                status="RUNNING",
                interval_seconds=interval,
                sequence_json=sequence,
                cursor=0,
                next_draw_at=now + timedelta(seconds=interval),
                started_by=int(admin_user_id),
                started_at=now,
            )
            db.add(control)
        else:
            control.status = "RUNNING"
            control.interval_seconds = interval
            control.sequence_json = sequence
            control.cursor = 0
            control.next_draw_at = now + timedelta(seconds=interval)
            control.started_by = int(admin_user_id)
            control.started_at = now
            control.paused_at = None
            control.stopped_at = None
        db.flush()
        GameAutoDrawService._emit(db, game=game, control=control, action="STARTED", actor_user_id=admin_user_id)
        return GameAutoDrawService.to_dict(game, control)

    @staticmethod
    def pause(db: Session, *, game_id: int, admin_user_id: int, can_manage_any: bool = False) -> dict[str, Any]:
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if not control or str(control.status) != "RUNNING":
            raise HTTPException(status_code=400, detail="auto draw is not RUNNING")
        control.status = "PAUSED"
        control.next_draw_at = None
        control.paused_at = _utcnow_naive()
        db.flush()
        GameAutoDrawService._emit(db, game=game, control=control, action="PAUSED", actor_user_id=admin_user_id)
        return GameAutoDrawService.to_dict(game, control)

    @staticmethod
    def resume(
        db: Session,
        *,
        game_id: int,
        admin_user_id: int,
        max_number: int,
        can_manage_any: bool = False,
    ) -> dict[str, Any]:
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        if str(game.status) != "RUNNING":
            raise HTTPException(status_code=400, detail="game is not RUNNING")
        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if not control or str(control.status) != "PAUSED":
            raise HTTPException(status_code=400, detail="auto draw is not PAUSED")
        remaining = GameAutoDrawService._remaining_sequence(db, game_id, max_number)
        if not remaining:
            raise HTTPException(status_code=400, detail="no numbers remain to draw")
        control.sequence_json = remaining
        control.cursor = 0
        control.status = "RUNNING"
        control.paused_at = None
        control.next_draw_at = _utcnow_naive() + timedelta(seconds=int(control.interval_seconds))
        db.flush()
        GameAutoDrawService._emit(db, game=game, control=control, action="RESUMED", actor_user_id=admin_user_id)
        return GameAutoDrawService.to_dict(game, control)

    @staticmethod
    def stop(db: Session, *, game_id: int, admin_user_id: int, can_manage_any: bool = False) -> dict[str, Any]:
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if not control:
            raise HTTPException(status_code=400, detail="auto draw is not configured")
        control.status = "STOPPED"
        control.next_draw_at = None
        control.stopped_at = _utcnow_naive()
        db.flush()
        GameAutoDrawService._emit(db, game=game, control=control, action="STOPPED", actor_user_id=admin_user_id)
        return GameAutoDrawService.to_dict(game, control)

    @staticmethod
    def assert_manual_call_allowed(db: Session, game_id: int) -> None:
        control = db.get(GameAutoDraw, int(game_id))
        if control and str(control.status) == "RUNNING":
            raise HTTPException(status_code=409, detail="pause auto draw before a manual call")

    @staticmethod
    def to_dict(game: Game, control: GameAutoDraw | None) -> dict[str, Any]:
        if control is None:
            return {
                "game_id": int(game.id),
                "game_status": str(game.status),
                "status": "STOPPED",
                "interval_seconds": 10,
                "next_draw_at": None,
                "remaining_count": 0,
            }
        sequence = control.sequence_json if isinstance(control.sequence_json, list) else []
        cursor = max(0, int(control.cursor or 0))
        next_draw_at = control.next_draw_at
        if isinstance(next_draw_at, datetime):
            next_draw_at_value = next_draw_at.isoformat() + "Z"
        elif next_draw_at:
            next_draw_at_value = str(next_draw_at)
        else:
            next_draw_at_value = None
        return {
            "game_id": int(game.id),
            "game_status": str(game.status),
            "status": str(control.status),
            "interval_seconds": int(control.interval_seconds),
            "next_draw_at": next_draw_at_value,
            "remaining_count": max(0, len(sequence) - cursor),
        }
