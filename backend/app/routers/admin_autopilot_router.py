from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.core.admin_guard import AdminIdentity, AdminScope, require_admin_any
from app.core.db import get_db
from app.services.admin_audit_service import AdminAuditService
from app.services.game_autopilot_config_service import GameAutopilotConfigService


router = APIRouter(prefix="/admin/autopilot", tags=["admin-autopilot"])


class AutopilotConfigUpdateIn(BaseModel):
    enabled: bool | None = None
    scheduler_mode: str | None = None
    start_mode: str | None = None
    draw_mode: str | None = None
    card_price: int | None = None
    commission_rate: float | None = None
    announce_before_seconds: int | None = None
    countdown_seconds: int | None = None
    repeat_interval_seconds: int | None = None
    draw_interval_seconds: int | None = None
    cooldown_seconds: int | None = None


def _require_game_config_access(ident: AdminIdentity) -> None:
    if ident.has_any_role("ADMIN", "GAME_OPERATOR"):
        return
    raise HTTPException(status_code=403, detail="game operator access required")


@router.get("/runtime")
def get_autopilot_runtime(
    ident: AdminIdentity = Depends(require_admin_any),
):
    _require_game_config_access(ident)
    return {
        "runtime_enabled": bool(cfg.GAME_AUTOPILOT_RUNTIME_ENABLED),
        "auto_draw_enabled": bool(cfg.GAME_AUTO_DRAW_ENABLED),
        "tick_seconds": int(cfg.GAME_AUTOPILOT_TICK_SECONDS),
        "system_user_id": (
            int(cfg.GAME_AUTOPILOT_SYSTEM_USER_ID)
            if cfg.GAME_AUTOPILOT_SYSTEM_USER_ID is not None
            else None
        ),
        "group_id": (
            int(cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID)
            if (cfg.USER_FORUM_CHAT_ID or cfg.DEFAULT_TG_GROUP_ID) is not None
            else None
        ),
        "topics": {
            level: GameAutopilotConfigService.topic_id_for_level(level)
            for level in ("LOW", "MEDIUM", "HIGH")
        },
    }


@router.get("/config")
def get_autopilot_config(
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    _require_game_config_access(ident)
    items = [GameAutopilotConfigService.serialize(row) for row in GameAutopilotConfigService.list(db)]
    return {
        "items": items,
        "can_edit_commission": bool(ident.scope == AdminScope.SUPER_ADMIN or "SUPER_ADMIN" in ident.roles),
    }


@router.put("/config/{level}")
def update_autopilot_config(
    level: str,
    payload: AutopilotConfigUpdateIn,
    request: Request,
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    _require_game_config_access(ident)
    is_super_admin = bool(ident.scope == AdminScope.SUPER_ADMIN or "SUPER_ADMIN" in ident.roles)
    values = payload.model_dump(exclude_unset=True)

    before, after = GameAutopilotConfigService.update(
        db,
        level=level,
        values=values,
        updated_by=ident.user_id,
        allow_commission_change=is_super_admin,
    )
    changed = {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in after.keys()
        if before.get(key) != after.get(key)
    }
    AdminAuditService.record(
        db,
        admin=ident,
        action="autopilot.config.update",
        target_type="game_level",
        target_id=None,
        request=request,
        details={
            "level": str(after.get("level") or level).upper(),
            "changed": changed,
            "commission_changed": "commission_rate" in changed,
        },
    )
    db.commit()
    return {"ok": True, "item": after}
