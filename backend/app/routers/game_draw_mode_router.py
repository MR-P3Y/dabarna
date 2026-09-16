from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity, AdminScope, get_admin_identity
from app.core.db import get_db
from app.routers.bot_router import _require_admin_user_id, _require_game_admin_access
from app.services.admin_audit_service import AdminAuditService
from app.services.game_auto_draw_service import GameAutoDrawService
from app.services.game_draw_mode_service import GameDrawModeService
from app.services.game_service import GameService


router = APIRouter(prefix="/bot/admin/games", tags=["bot-game-draw-mode"])


class BotDrawModeIn(BaseModel):
    draw_mode: str
    interval_seconds: int | None = None


def _max_number(db: Session) -> int:
    return int(GameService._get_setting(db, GameService.KEY_MAX_NUMBER, 90))


@router.get("/{game_id}/draw-mode")
def get_bot_game_draw_mode(
    game_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_game_admin_access(db, int(game_id), admin)
    return GameDrawModeService.state(db, int(game_id))


@router.put("/{game_id}/draw-mode")
def set_bot_game_draw_mode(
    game_id: int,
    payload: BotDrawModeIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_game_admin_access(db, int(game_id), admin)
    admin_uid = _require_admin_user_id(admin)
    try:
        out = GameDrawModeService.select_mode(
            db,
            game_id=int(game_id),
            admin_user_id=int(admin_uid),
            draw_mode=str(payload.draw_mode),
            interval_seconds=payload.interval_seconds,
            max_number=_max_number(db),
            can_manage_any=admin.scope == AdminScope.SUPER_ADMIN,
        )
        AdminAuditService.record(
            db,
            admin=admin,
            action="game.draw_mode.select",
            target_type="game",
            target_id=int(game_id),
            request=request,
            details={
                "game_id": int(game_id),
                "draw_mode": out.get("draw_mode"),
                "interval_seconds": out.get("interval_seconds"),
                "sequence_commitment": out.get("sequence_commitment"),
                "locked": bool(out.get("locked")),
            },
        )
        db.commit()
        return GameDrawModeService.state(db, int(game_id))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"draw mode selection failed: {exc}")


@router.post("/{game_id}/auto-draw/pause")
def pause_bot_game_auto_draw(
    game_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_game_admin_access(db, int(game_id), admin)
    admin_uid = _require_admin_user_id(admin)
    try:
        out = GameAutoDrawService.pause(
            db,
            game_id=int(game_id),
            admin_user_id=int(admin_uid),
            can_manage_any=admin.scope == AdminScope.SUPER_ADMIN,
        )
        AdminAuditService.record(
            db,
            admin=admin,
            action="game.auto.pause",
            target_type="game",
            target_id=int(game_id),
            request=request,
            details={"game_id": int(game_id), "auto_status": out.get("status")},
        )
        db.commit()
        return GameDrawModeService.state(db, int(game_id))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"auto draw pause failed: {exc}")


@router.post("/{game_id}/auto-draw/resume")
def resume_bot_game_auto_draw(
    game_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_game_admin_access(db, int(game_id), admin)
    admin_uid = _require_admin_user_id(admin)
    try:
        out = GameAutoDrawService.resume(
            db,
            game_id=int(game_id),
            admin_user_id=int(admin_uid),
            max_number=_max_number(db),
            can_manage_any=admin.scope == AdminScope.SUPER_ADMIN,
        )
        AdminAuditService.record(
            db,
            admin=admin,
            action="game.auto.resume",
            target_type="game",
            target_id=int(game_id),
            request=request,
            details={"game_id": int(game_id), "auto_status": out.get("status")},
        )
        db.commit()
        return GameDrawModeService.state(db, int(game_id))
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"auto draw resume failed: {exc}")
