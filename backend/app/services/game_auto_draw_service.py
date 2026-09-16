from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.game import Game, GameAutoDraw
from app.services.game_event_service import GameEventService


AUTO_DRAW_INTERVALS = (5, 8, 10, 15)
AUTO_DRAW_STATUSES = {"ARMED", "RUNNING", "PAUSED", "STOPPED"}


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GameAutoDrawService:
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
    def _require_locked_auto_game(game: Game) -> None:
        if str(game.draw_mode or "").upper() != "AUTO":
            raise HTTPException(status_code=409, detail="this game is locked to MANUAL draw mode")
        if game.draw_mode_locked_at is None or str(game.status) != "RUNNING":
            raise HTTPException(status_code=409, detail="AUTO controls are available only after the AUTO game starts")

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
                    "sequence_commitment": str(control.sequence_commitment or "") or None,
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
        # Compatibility endpoint: after draw-mode locking, AUTO is armed before start
        # and activated atomically by a DB trigger when the game enters RUNNING.
        _ = max_number
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        if str(game.draw_mode or "").upper() != "AUTO":
            raise HTTPException(status_code=409, detail="select AUTO draw mode before game start")

        configured_interval = int(game.draw_interval_seconds or 0)
        if int(interval_seconds) != configured_interval:
            raise HTTPException(status_code=409, detail="AUTO interval is fixed by the pre-game selection")

        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if control is None:
            raise HTTPException(status_code=409, detail="AUTO draw is not armed")

        if str(game.status) == "LOBBY" and str(control.status) == "ARMED":
            return GameAutoDrawService.to_dict(game, control)
        if str(game.status) == "RUNNING" and str(control.status) == "RUNNING":
            return GameAutoDrawService.to_dict(game, control)
        if str(control.status) == "PAUSED":
            raise HTTPException(status_code=409, detail="AUTO draw is paused; use resume")
        raise HTTPException(status_code=409, detail="AUTO draw cannot be restarted or reseeded after game start")

    @staticmethod
    def pause(db: Session, *, game_id: int, admin_user_id: int, can_manage_any: bool = False) -> dict[str, Any]:
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        GameAutoDrawService._require_locked_auto_game(game)
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
        # Resume MUST keep the original sequence and cursor. Re-shuffling here would
        # make the published commitment meaningless and would permit manipulation.
        _ = max_number
        game = GameAutoDrawService._game_for_update(db, game_id)
        GameAutoDrawService._require_access(game, admin_user_id, can_manage_any)
        GameAutoDrawService._require_locked_auto_game(game)
        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if not control or str(control.status) != "PAUSED":
            raise HTTPException(status_code=400, detail="auto draw is not PAUSED")
        sequence = control.sequence_json if isinstance(control.sequence_json, list) else []
        cursor = max(0, int(control.cursor or 0))
        if cursor >= len(sequence):
            raise HTTPException(status_code=400, detail="no numbers remain to draw")
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
        if str(game.status) == "RUNNING" and game.draw_mode_locked_at is not None:
            raise HTTPException(status_code=409, detail="locked AUTO game cannot be stopped; pause or finish the game")
        control.status = "STOPPED"
        control.next_draw_at = None
        control.stopped_at = _utcnow_naive()
        db.flush()
        GameAutoDrawService._emit(db, game=game, control=control, action="STOPPED", actor_user_id=admin_user_id)
        return GameAutoDrawService.to_dict(game, control)

    @staticmethod
    def assert_manual_call_allowed(db: Session, game_id: int) -> None:
        game = db.get(Game, int(game_id))
        if game and str(game.draw_mode or "").upper() == "AUTO" and game.draw_mode_locked_at is not None:
            raise HTTPException(status_code=409, detail="manual calls are forbidden for this locked AUTO game")

    @staticmethod
    def to_dict(game: Game, control: GameAutoDraw | None) -> dict[str, Any]:
        if control is None:
            return {
                "game_id": int(game.id),
                "game_status": str(game.status),
                "draw_mode": str(game.draw_mode) if game.draw_mode else None,
                "locked": game.draw_mode_locked_at is not None,
                "status": "STOPPED",
                "interval_seconds": int(game.draw_interval_seconds or 0) or None,
                "next_draw_at": None,
                "remaining_count": 0,
                "sequence_commitment": None,
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
            "draw_mode": str(game.draw_mode) if game.draw_mode else None,
            "locked": game.draw_mode_locked_at is not None,
            "status": str(control.status),
            "interval_seconds": int(control.interval_seconds),
            "next_draw_at": next_draw_at_value,
            "remaining_count": max(0, len(sequence) - cursor),
            "sequence_commitment": str(control.sequence_commitment or "") or None,
        }