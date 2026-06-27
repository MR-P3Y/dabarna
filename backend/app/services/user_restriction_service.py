from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.settings import AppSetting
from app.models.user import User


USER_RESTRICTIONS_KEY = "user_restrictions"
DEFAULT_RESTRICTED_ACTIONS = ["BUY", "DEPOSIT", "WITHDRAW", "ACTIVE_GAMES"]
ALLOWED_ACTIONS = {"BUY", "DEPOSIT", "WITHDRAW", "ACTIVE_GAMES", "ALL"}


def _now() -> datetime:
    return datetime.utcnow().replace(tzinfo=None)


def _to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip().replace("Z", "+00:00")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_str_dt(value: Any) -> str | None:
    dt = _to_dt(value)
    return dt.isoformat(sep=" ", timespec="seconds") if dt else None


def _setting_get_json(db: Session, key: str) -> object | None:
    row = db.get(AppSetting, str(key))
    return getattr(row, "v_json", None) if row else None


def _load_restrictions(db: Session) -> dict[str, Any]:
    raw = _setting_get_json(db, USER_RESTRICTIONS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def normalize_restriction_actions(actions: Any) -> list[str]:
    raw_items = actions if isinstance(actions, list) else []
    out: list[str] = []
    for raw in raw_items:
        token = str(raw or "").strip().upper()
        if not token or token not in ALLOWED_ACTIONS:
            continue
        if token == "ALL":
            return ["ALL"]
        if token not in out:
            out.append(token)
    return out or list(DEFAULT_RESTRICTED_ACTIONS)


def restriction_state_from_record(record: dict[str, Any] | None) -> dict[str, Any]:
    rec = record or {}
    until_dt = _to_dt(rec.get("until"))
    expired = bool(until_dt and until_dt < _now())
    active = bool(rec.get("active", False) and not expired)
    return {
        "active": active,
        "expired": expired,
        "reason": rec.get("reason"),
        "until": _to_str_dt(rec.get("until")),
        "actions": normalize_restriction_actions(rec.get("actions")),
        "set_at": _to_str_dt(rec.get("set_at")),
        "set_by_user_id": rec.get("set_by_user_id"),
        "set_by_scope": rec.get("set_by_scope"),
        "lifted_at": _to_str_dt(rec.get("lifted_at")),
        "lifted_by_user_id": rec.get("lifted_by_user_id"),
        "lift_reason": rec.get("lift_reason"),
    }


def restriction_state_for_tg_user_id(db: Session, tg_user_id: int) -> dict[str, Any]:
    restrictions = _load_restrictions(db)
    raw = restrictions.get(str(int(tg_user_id)))
    state = restriction_state_from_record(raw if isinstance(raw, dict) else None)
    state["tg_user_id"] = int(tg_user_id)
    return state


def is_restricted_for_action(db: Session, tg_user_id: int, action: str) -> bool:
    state = restriction_state_for_tg_user_id(db, tg_user_id)
    if not bool(state.get("active")):
        return False
    actions = [str(x).upper() for x in (state.get("actions") or [])]
    target = str(action or "").strip().upper()
    return "ALL" in actions or target in actions


def require_not_restricted(db: Session, tg_user_id: int, action: str) -> None:
    state = restriction_state_for_tg_user_id(db, tg_user_id)
    if not bool(state.get("active")):
        return
    actions = [str(x).upper() for x in (state.get("actions") or [])]
    target = str(action or "").strip().upper()
    if "ALL" not in actions and target not in actions:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "USER_RESTRICTED",
            "message": "حساب شما توسط مدیریت محدود شده است. برای پیگیری با پشتیبانی تماس بگیرید.",
            "action": target,
            "reason": state.get("reason"),
            "until": state.get("until"),
        },
    )


def require_user_id_not_restricted(db: Session, user_id: int, action: str) -> None:
    user = db.get(User, int(user_id))
    if user is None:
        return
    require_not_restricted(db, int(user.tg_user_id), action)
