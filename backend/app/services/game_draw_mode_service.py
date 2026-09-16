from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.game import Game, GameAutoDraw, GameCalledNumber
from app.services.game_auto_draw_service import AUTO_DRAW_INTERVALS
from app.services.game_event_service import GameEventService


DRAW_MODE_MANUAL = "MANUAL"
DRAW_MODE_AUTO = "AUTO"
DRAW_MODES = {DRAW_MODE_MANUAL, DRAW_MODE_AUTO}


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sequence_commitment(sequence: list[int]) -> str:
    canonical = ",".join(str(int(value)) for value in sequence)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GameDrawModeService:
    @staticmethod
    def _require_access(game: Game, admin_user_id: int, can_manage_any: bool) -> None:
        if not can_manage_any and int(game.admin_user_id) != int(admin_user_id):
            raise HTTPException(status_code=403, detail="only game admin can select draw mode")

    @staticmethod
    def _game_for_update(db: Session, game_id: int) -> Game:
        game = db.execute(
            select(Game).where(Game.id == int(game_id)).with_for_update()
        ).scalar_one_or_none()
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        return game

    @staticmethod
    def _sequence(max_number: int) -> list[int]:
        values = list(range(1, int(max_number) + 1))
        secrets.SystemRandom().shuffle(values)
        return values

    @staticmethod
    def select_mode(
        db: Session,
        *,
        game_id: int,
        admin_user_id: int,
        draw_mode: str,
        interval_seconds: int | None,
        max_number: int,
        can_manage_any: bool = False,
    ) -> dict[str, Any]:
        game = GameDrawModeService._game_for_update(db, game_id)
        GameDrawModeService._require_access(game, admin_user_id, can_manage_any)

        if str(game.status) != "LOBBY" or game.draw_mode_locked_at is not None:
            raise HTTPException(status_code=409, detail="draw mode is locked after game start")

        called_count = db.execute(
            select(GameCalledNumber.id).where(GameCalledNumber.game_id == int(game_id)).limit(1)
        ).scalar_one_or_none()
        if called_count is not None:
            raise HTTPException(status_code=409, detail="cannot select draw mode after numbers were called")

        mode = str(draw_mode or "").strip().upper()
        if mode not in DRAW_MODES:
            raise HTTPException(status_code=400, detail="draw_mode must be MANUAL or AUTO")

        control = db.execute(
            select(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)).with_for_update()
        ).scalar_one_or_none()

        if mode == DRAW_MODE_AUTO:
            if interval_seconds is None or int(interval_seconds) not in AUTO_DRAW_INTERVALS:
                raise HTTPException(status_code=400, detail="interval_seconds must be one of 5, 8, 10, 15")
            interval = int(interval_seconds)
            if (
                str(game.draw_mode or "").upper() == DRAW_MODE_AUTO
                and int(game.draw_interval_seconds or 0) == interval
                and control is not None
                and str(control.status) == "ARMED"
                and bool(control.sequence_commitment)
            ):
                return GameDrawModeService.state(db, int(game.id))
        else:
            if str(game.draw_mode or "").upper() == DRAW_MODE_MANUAL and control is None:
                return GameDrawModeService.state(db, int(game.id))

        now = _utcnow_naive()
        commitment: str | None = None

        if mode == DRAW_MODE_AUTO:
            interval = int(interval_seconds or 0)
            sequence = GameDrawModeService._sequence(max_number)
            commitment = sequence_commitment(sequence)

            if control is None:
                control = GameAutoDraw(
                    game_id=int(game_id),
                    status="ARMED",
                    interval_seconds=interval,
                    sequence_json=sequence,
                    sequence_commitment=commitment,
                    cursor=0,
                    next_draw_at=None,
                    started_by=int(admin_user_id),
                    started_at=None,
                    paused_at=None,
                    stopped_at=None,
                )
                db.add(control)
            else:
                control.status = "ARMED"
                control.interval_seconds = interval
                control.sequence_json = sequence
                control.sequence_commitment = commitment
                control.cursor = 0
                control.next_draw_at = None
                control.started_by = int(admin_user_id)
                control.started_at = None
                control.paused_at = None
                control.stopped_at = None

            game.draw_interval_seconds = interval
        else:
            if control is not None:
                db.execute(delete(GameAutoDraw).where(GameAutoDraw.game_id == int(game_id)))
            game.draw_interval_seconds = None

        game.draw_mode = mode
        game.draw_mode_selected_by = int(admin_user_id)
        game.draw_mode_selected_at = now
        game.draw_mode_locked_at = None
        db.flush()

        try:
            GameEventService.emit(
                db,
                kind="DRAW_MODE_SELECTED",
                game_id=int(game.id),
                tg_group_id=int(game.tg_group_id),
                actor_user_id=int(admin_user_id),
                idem_key=f"DRAW_MODE_SELECTED:{game.id}:{int(now.timestamp() * 1000)}",
                payload={
                    "draw_mode": mode,
                    "interval_seconds": int(game.draw_interval_seconds) if game.draw_interval_seconds else None,
                    "sequence_commitment": commitment,
                    "locked": False,
                    "tg_topic_id": int(game.tg_topic_id) if game.tg_topic_id is not None else None,
                },
            )
            if mode == DRAW_MODE_AUTO:
                GameEventService.emit(
                    db,
                    kind="AUTO_DRAW_ARMED",
                    game_id=int(game.id),
                    tg_group_id=int(game.tg_group_id),
                    actor_user_id=int(admin_user_id),
                    idem_key=f"AUTO_DRAW_ARMED:{game.id}:{commitment}",
                    payload={
                        "interval_seconds": int(game.draw_interval_seconds or 0),
                        "sequence_commitment": commitment,
                    },
                )
        except Exception:
            pass

        return GameDrawModeService.state(db, int(game.id))

    @staticmethod
    def state(db: Session, game_id: int) -> dict[str, Any]:
        game = db.execute(select(Game).where(Game.id == int(game_id))).scalar_one_or_none()
        if not game:
            raise HTTPException(status_code=404, detail="game not found")
        control = db.get(GameAutoDraw, int(game_id))
        sequence = control.sequence_json if control and isinstance(control.sequence_json, list) else []
        cursor = max(0, int(control.cursor or 0)) if control else 0
        return {
            "game_id": int(game.id),
            "game_status": str(game.status),
            "tg_group_id": int(game.tg_group_id),
            "tg_topic_id": int(game.tg_topic_id) if game.tg_topic_id is not None else None,
            "card_price": int(game.card_price),
            "draw_mode": str(game.draw_mode) if game.draw_mode else None,
            "interval_seconds": int(game.draw_interval_seconds) if game.draw_interval_seconds else None,
            "draw_mode_selected_by": int(game.draw_mode_selected_by) if game.draw_mode_selected_by else None,
            "draw_mode_selected_at": str(game.draw_mode_selected_at) if game.draw_mode_selected_at else None,
            "draw_mode_locked_at": str(game.draw_mode_locked_at) if game.draw_mode_locked_at else None,
            "locked": game.draw_mode_locked_at is not None or str(game.status) != "LOBBY",
            "auto_status": str(control.status) if control else None,
            "sequence_commitment": str(control.sequence_commitment) if control and control.sequence_commitment else None,
            "remaining_count": max(0, len(sequence) - cursor),
        }
