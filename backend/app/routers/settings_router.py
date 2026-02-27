from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.admin_guard import require_admin_any, AdminIdentity
from app.models.settings import AppSetting
from app.models.game import Game

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

LOCK_WHEN_ANY_RUNNING_OR_ENDED = {
    "commission_rate",
    "max_number",
}

LOCK_WHEN_ANY_RUNNING = {
    "commission_rate",
    "max_number",
}

class SettingUpdateIn(BaseModel):
    v_json: object

def _has_running_game(db: Session) -> bool:
    n = db.execute(
        select(func.count()).select_from(Game).where(Game.status == "RUNNING")
    ).scalar_one()
    return int(n) > 0

def _has_any_started_game(db: Session) -> bool:
    # RUNNING or ENDED => started
    n = db.execute(
        select(func.count()).select_from(Game).where(Game.status.in_(["RUNNING", "ENDED"]))
    ).scalar_one()
    return int(n) > 0

@router.put("/{key}")
def update_setting(
    key: str,
    body: SettingUpdateIn,
    ident: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    # سوپرادمین هست، اما باز هم قانون قفل را اعمال می‌کنیم
    if key in LOCK_WHEN_ANY_RUNNING and _has_running_game(db):
        raise HTTPException(status_code=409, detail=f"setting '{key}' is locked while a game is RUNNING")

    # اگر می‌خوای سخت‌ترش کنی (از لحظه اولین بازی شروع‌شده برای همیشه قفل):
    # if key in LOCK_WHEN_ANY_RUNNING_OR_ENDED and _has_any_started_game(db):
    #     raise HTTPException(status_code=409, detail=f"setting '{key}' is locked after games have started")

    s = db.get(AppSetting, key)
    if not s:
        s = AppSetting(k=key, v_json=body.v_json)
        db.add(s)
    else:
        s.v_json = body.v_json

    db.flush()
    return {"ok": True, "key": key, "v_json": s.v_json}
