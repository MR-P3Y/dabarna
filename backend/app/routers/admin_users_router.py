from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity, AdminScope, require_admin_any
from app.core.config import DEFAULT_TG_GROUP_ID, TELEGRAM_BOT_TOKEN
from app.core.db import get_db
from app.models.finance import DepositRequest, WithdrawRequest
from app.models.game import Game, GamePurchase
from app.models.rbac import Role, UserRole
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.services.admin_audit_service import AdminAuditService
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

USER_RESTRICTIONS_KEY = "user_restrictions"
WALLET_ADJUST_LOG_KEY = "wallet_adjust_logs"
WALLET_ADJUST_LOG_LIMIT = 2000
ALLOWED_ACTIONS = {"BUY", "DEPOSIT", "WITHDRAW", "ACTIVE_GAMES", "ALL"}
WIN_REASONS = {"PRIZE_COL", "PRIZE_ROW"}


class RestrictIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    minutes: int | None = Field(default=None, ge=1, le=43200)
    until: str | None = None
    actions: list[str] | None = None


class UnrestrictIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class WalletAdjustIn(BaseModel):
    amount: int = Field(ne=0)
    reason: str = Field(min_length=3, max_length=300)
    idempotency_key: str | None = Field(default=None, max_length=120)
    notify_user: bool = True


class NotifyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    parse_mode: str | None = Field(default="HTML", max_length=20)
    disable_notification: bool = True


class ComposeIn(BaseModel):
    kind: Literal["deposit_reject", "withdraw_reject", "wallet_adjust", "restriction", "generic"]
    reason: str | None = Field(default=None, max_length=500)
    amount: int | None = None
    ref_id: int | None = None


def _setting_get_json(db: Session, key: str) -> object | None:
    row = db.get(AppSetting, str(key))
    return getattr(row, "v_json", None) if row else None


def _setting_set_json(db: Session, key: str, value: object) -> None:
    row = db.get(AppSetting, str(key))
    if row is None:
        row = AppSetting(k=str(key), v_json=value)
    else:
        row.v_json = value
    db.add(row)


def _now() -> datetime:
    return datetime.utcnow().replace(tzinfo=None)


def _to_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        s = str(v).strip().replace("Z", "+00:00")
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_str_dt(v: Any) -> str | None:
    dt = _to_dt(v)
    return dt.isoformat(sep=" ", timespec="seconds") if dt else None


def _max_dt(values: list[Any]) -> datetime | None:
    out: datetime | None = None
    for v in values:
        dt = _to_dt(v)
        if dt is None:
            continue
        if out is None or dt > out:
            out = dt
    return out


def _display_name(user: User) -> str:
    first = str(user.first_name or "").strip()
    last = str(user.last_name or "").strip()
    if first or last:
        return (first + " " + last).strip()
    username = str(user.username or "").strip()
    return f"@{username}" if username else f"user:{int(user.tg_user_id)}"


def _user_basic(user: User) -> dict[str, Any]:
    return {
        "user_id": int(user.id),
        "tg_user_id": int(user.tg_user_id),
        "username": str(user.username) if user.username else None,
        "first_name": str(user.first_name) if user.first_name else None,
        "last_name": str(user.last_name) if user.last_name else None,
        "display_name": _display_name(user),
        "created_at": _to_str_dt(user.created_at),
    }


def _get_user_by_tg_or_404(db: Session, tg_user_id: int) -> User:
    user = db.execute(select(User).where(User.tg_user_id == int(tg_user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return user


def _roles_for_user(db: Session, user_id: int) -> list[str]:
    rows = db.execute(
        select(Role.name)
        .select_from(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == int(user_id))
    ).scalars().all()
    return sorted({str(x) for x in rows if x})


def _ensure_manage_target(admin: AdminIdentity, target_roles: list[str]) -> None:
    if "SUPER_ADMIN" in target_roles and admin.scope != AdminScope.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="cannot manage super admin")
    if "ADMIN" in target_roles and admin.scope != AdminScope.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="cannot manage admin user")


def _load_restrictions(db: Session) -> dict[str, Any]:
    raw = _setting_get_json(db, USER_RESTRICTIONS_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _restriction_state(record: dict[str, Any] | None) -> dict[str, Any]:
    rec = record or {}
    until_dt = _to_dt(rec.get("until"))
    expired = bool(until_dt and until_dt < _now())
    active = bool(rec.get("active", False) and not expired)
    return {
        "active": active,
        "expired": expired,
        "reason": rec.get("reason"),
        "until": _to_str_dt(rec.get("until")),
        "actions": [str(x) for x in (rec.get("actions") or [])],
        "set_at": _to_str_dt(rec.get("set_at")),
        "set_by_user_id": rec.get("set_by_user_id"),
        "set_by_scope": rec.get("set_by_scope"),
        "lifted_at": _to_str_dt(rec.get("lifted_at")),
        "lifted_by_user_id": rec.get("lifted_by_user_id"),
        "lift_reason": rec.get("lift_reason"),
    }


def _normalize_actions(actions: list[str] | None) -> list[str]:
    if not actions:
        return ["BUY", "DEPOSIT", "WITHDRAW", "ACTIVE_GAMES"]
    out: list[str] = []
    for raw in actions:
        token = str(raw or "").strip().upper()
        if not token:
            continue
        if token not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=400, detail=f"invalid action: {token}")
        if token == "ALL":
            return ["ALL"]
        if token not in out:
            out.append(token)
    return out or ["BUY", "DEPOSIT", "WITHDRAW", "ACTIVE_GAMES"]


def _parse_until(until: str | None, minutes: int | None) -> datetime | None:
    if minutes is not None:
        return _now() + timedelta(minutes=int(minutes))
    if not until:
        return None
    s = str(until).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid until datetime")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _membership_state(tg_user_id: int) -> dict[str, Any]:
    if DEFAULT_TG_GROUP_ID is None:
        return {"required_group_id": None, "status": "UNKNOWN", "telegram_status": None, "is_member": None}
    if not TELEGRAM_BOT_TOKEN:
        return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "UNKNOWN", "telegram_status": None, "is_member": None}

    query = url_parse.urlencode({"chat_id": int(DEFAULT_TG_GROUP_ID), "user_id": int(tg_user_id)})
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatMember?{query}"
    try:
        with url_request.urlopen(url, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "UNKNOWN", "telegram_status": None, "is_member": None}

    if not bool(body.get("ok", False)):
        return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "UNKNOWN", "telegram_status": None, "is_member": None}

    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    tg_status = str(result.get("status") or "").strip().lower()
    if tg_status in {"member", "administrator", "creator"}:
        return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "MEMBER", "telegram_status": tg_status, "is_member": True}
    if tg_status == "restricted":
        return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "RESTRICTED", "telegram_status": tg_status, "is_member": True}
    if tg_status in {"left", "kicked"}:
        return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "NOT_MEMBER", "telegram_status": tg_status, "is_member": False}
    return {"required_group_id": int(DEFAULT_TG_GROUP_ID), "status": "UNKNOWN", "telegram_status": tg_status or None, "is_member": None}


def _telegram_send_private_message(*, tg_user_id: int, text: str, parse_mode: str = "HTML", disable_notification: bool = True) -> dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "telegram bot token not configured"}

    payload = {
        "chat_id": int(tg_user_id),
        "text": str(text),
        "parse_mode": str(parse_mode or "HTML"),
        "disable_web_page_preview": True,
        "disable_notification": bool(disable_notification),
    }
    req = url_request.Request(
        url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (url_error.HTTPError, url_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"telegram send failed: {exc.__class__.__name__}"}
    except Exception:
        return {"ok": False, "error": "telegram send failed"}

    if not bool(body.get("ok", False)):
        return {"ok": False, "error": str(body.get("description") or "telegram send failed")}
    result = body.get("result") if isinstance(body.get("result"), dict) else {}
    return {"ok": True, "message_id": result.get("message_id")}


def _wallet_adjust_log_items(db: Session) -> list[dict[str, Any]]:
    raw = _setting_get_json(db, WALLET_ADJUST_LOG_KEY)
    if not isinstance(raw, list):
        return []
    return [dict(x) for x in raw if isinstance(x, dict)]


def _append_wallet_adjust_log(db: Session, entry: dict[str, Any]) -> None:
    logs = _wallet_adjust_log_items(db)
    logs.append(dict(entry))
    if len(logs) > WALLET_ADJUST_LOG_LIMIT:
        logs = logs[-WALLET_ADJUST_LOG_LIMIT:]
    _setting_set_json(db, WALLET_ADJUST_LOG_KEY, logs)


def _adjust_logs_for_user(db: Session, *, tg_user_id: int, limit: int) -> list[dict[str, Any]]:
    target = int(tg_user_id)
    logs = [x for x in _wallet_adjust_log_items(db) if int(x.get("target_tg_user_id") or -1) == target]
    logs.sort(key=lambda x: _to_dt(x.get("at")) or datetime.min, reverse=True)
    return logs[: int(limit)]


def _reason_label(reason: str) -> str:
    mapping = {
        "DEPOSIT_MANUAL": "واریز دستی",
        "DEPOSIT_GATEWAY": "واریز درگاه",
        "BUY_CARDS": "خرید کارت",
        "PRIZE_COL": "جایزه برد ستونی",
        "PRIZE_ROW": "جایزه برد سطری",
        "WITHDRAW": "برداشت",
        "ADJUST": "اصلاح کیف پول",
    }
    return mapping.get(str(reason), str(reason))


def _compose_message_text(*, user: User, kind: str, reason: str | None = None, amount: int | None = None, ref_id: int | None = None) -> str:
    display = _display_name(user)
    why = str(reason or "بدون توضیح")
    if kind == "deposit_reject":
        return f"کاربر گرامی {display}،\nدرخواست واریز شما با شماره #{int(ref_id or 0)} رد شد.\nعلت: {why}"
    if kind == "withdraw_reject":
        return f"کاربر گرامی {display}،\nدرخواست برداشت شما با شماره #{int(ref_id or 0)} رد شد.\nعلت: {why}"
    if kind == "wallet_adjust":
        sign = "+" if int(amount or 0) > 0 else ""
        return f"کاربر گرامی {display}،\nموجودی کیف پول شما {sign}{int(amount or 0):,} تومان اصلاح شد.\nعلت: {why}"
    if kind == "restriction":
        return f"کاربر گرامی {display}،\nدسترسی شما به صورت موقت محدود شد.\nعلت: {why}"
    return f"کاربر گرامی {display}،\n{why}"

@router.get("/search")
def admin_user_search(
    tg_user_id: int | None = Query(default=None),
    username: str | None = Query(default=None),
    game_id: int | None = Query(default=None),
    deposit_id: int | None = Query(default=None),
    withdraw_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    _: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    if all(v is None for v in [tg_user_id, username, game_id, deposit_id, withdraw_id]):
        raise HTTPException(status_code=400, detail="at least one search filter is required")

    matched: dict[int, set[str]] = {}

    def _add(user_id: int | None, by: str) -> None:
        if user_id is None:
            return
        uid = int(user_id)
        if uid <= 0:
            return
        matched.setdefault(uid, set()).add(by)

    if tg_user_id is not None:
        uid = db.execute(select(User.id).where(User.tg_user_id == int(tg_user_id))).scalar_one_or_none()
        _add(uid, "tg_user_id")

    if username:
        q = str(username).strip().lstrip("@").lower()
        if q:
            like = f"%{q}%"
            rows = db.execute(
                select(User.id)
                .where(
                    or_(
                        func.lower(func.coalesce(User.username, "")).like(like),
                        func.lower(func.coalesce(User.first_name, "")).like(like),
                        func.lower(func.coalesce(User.last_name, "")).like(like),
                    )
                )
                .limit(500)
            ).scalars().all()
            for uid in rows:
                _add(uid, "username")

    if game_id is not None:
        rows = db.execute(
            select(GamePurchase.user_id)
            .where(GamePurchase.game_id == int(game_id))
            .group_by(GamePurchase.user_id)
        ).scalars().all()
        for uid in rows:
            _add(uid, "game_id")

    if deposit_id is not None:
        uid = db.execute(select(DepositRequest.user_id).where(DepositRequest.id == int(deposit_id))).scalar_one_or_none()
        _add(uid, "deposit_id")

    if withdraw_id is not None:
        uid = db.execute(select(WithdrawRequest.user_id).where(WithdrawRequest.id == int(withdraw_id))).scalar_one_or_none()
        _add(uid, "withdraw_id")

    ordered_ids = sorted(matched.keys(), reverse=True)
    users = db.execute(select(User).where(User.id.in_(ordered_ids))).scalars().all() if ordered_ids else []
    user_by_id = {int(u.id): u for u in users}

    items: list[dict[str, Any]] = []
    for uid in ordered_ids[: int(limit)]:
        user = user_by_id.get(uid)
        if not user:
            continue
        items.append(
            {
                **_user_basic(user),
                "roles": _roles_for_user(db, int(user.id)),
                "matched_by": sorted(matched.get(uid, set())),
            }
        )

    return {"total": len(items), "items": items}


@router.get("/{tg_user_id}/profile")
def admin_user_profile(
    tg_user_id: int,
    _: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    roles = _roles_for_user(db, int(user.id))
    wallet = db.execute(select(Wallet).where(Wallet.user_id == int(user.id))).scalar_one_or_none()
    wallet_balance = int(wallet.balance) if wallet else 0

    restrictions = _load_restrictions(db)
    raw_restriction = restrictions.get(str(int(user.tg_user_id)))
    restriction = _restriction_state(raw_restriction if isinstance(raw_restriction, dict) else None)

    games_participated = int(
        db.execute(
            select(func.count(func.distinct(GamePurchase.game_id))).where(GamePurchase.user_id == int(user.id))
        ).scalar_one()
        or 0
    )
    cards_purchased = int(
        db.execute(
            select(func.coalesce(func.sum(GamePurchase.qty), 0)).where(GamePurchase.user_id == int(user.id))
        ).scalar_one()
        or 0
    )
    total_buy_amount = int(
        db.execute(
            select(func.coalesce(func.sum(GamePurchase.total_price), 0)).where(GamePurchase.user_id == int(user.id))
        ).scalar_one()
        or 0
    )

    wins_col_count = 0
    wins_row_count = 0
    wins_col_amount = 0
    wins_row_amount = 0
    last_win_at: datetime | None = None
    last_wallet_tx_at: datetime | None = None

    if wallet:
        win_rows = db.execute(
            select(
                WalletTx.reason,
                func.count(WalletTx.id),
                func.coalesce(func.sum(WalletTx.amount), 0),
                func.max(WalletTx.created_at),
            )
            .where(
                WalletTx.wallet_id == int(wallet.id),
                WalletTx.reason.in_(list(WIN_REASONS)),
            )
            .group_by(WalletTx.reason)
        ).all()
        for reason, cnt, amount_sum, max_at in win_rows:
            if str(reason) == "PRIZE_COL":
                wins_col_count = int(cnt or 0)
                wins_col_amount = int(amount_sum or 0)
            elif str(reason) == "PRIZE_ROW":
                wins_row_count = int(cnt or 0)
                wins_row_amount = int(amount_sum or 0)
            dt = _to_dt(max_at)
            if dt and (last_win_at is None or dt > last_win_at):
                last_win_at = dt

        last_wallet_tx_at = _to_dt(
            db.execute(select(func.max(WalletTx.created_at)).where(WalletTx.wallet_id == int(wallet.id))).scalar_one_or_none()
        )

    deposit_count = int(
        db.execute(select(func.count(DepositRequest.id)).where(DepositRequest.user_id == int(user.id))).scalar_one() or 0
    )
    withdraw_count = int(
        db.execute(select(func.count(WithdrawRequest.id)).where(WithdrawRequest.user_id == int(user.id))).scalar_one() or 0
    )
    pending_withdraw_count = int(
        db.execute(
            select(func.count(WithdrawRequest.id)).where(
                WithdrawRequest.user_id == int(user.id),
                WithdrawRequest.status == "PENDING",
            )
        ).scalar_one()
        or 0
    )

    last_deposit_at = _to_dt(
        db.execute(select(func.max(DepositRequest.created_at)).where(DepositRequest.user_id == int(user.id))).scalar_one_or_none()
    )
    last_withdraw_at = _to_dt(
        db.execute(select(func.max(WithdrawRequest.created_at)).where(WithdrawRequest.user_id == int(user.id))).scalar_one_or_none()
    )
    last_purchase_at = _to_dt(
        db.execute(select(func.max(GamePurchase.created_at)).where(GamePurchase.user_id == int(user.id))).scalar_one_or_none()
    )
    last_activity = _max_dt([user.created_at, last_wallet_tx_at, last_deposit_at, last_withdraw_at, last_purchase_at])

    return {
        "user": _user_basic(user),
        "roles": roles,
        "membership": _membership_state(int(user.tg_user_id)),
        "wallet": {"balance": wallet_balance, "last_tx_at": _to_str_dt(last_wallet_tx_at)},
        "restriction": restriction,
        "stats": {
            "games_participated": games_participated,
            "cards_purchased": cards_purchased,
            "total_buy_amount": total_buy_amount,
            "wins_col_count": wins_col_count,
            "wins_row_count": wins_row_count,
            "wins_total_count": wins_col_count + wins_row_count,
            "wins_col_amount": wins_col_amount,
            "wins_row_amount": wins_row_amount,
            "wins_total_amount": wins_col_amount + wins_row_amount,
            "last_win_at": _to_str_dt(last_win_at),
            "deposit_count": deposit_count,
            "withdraw_count": withdraw_count,
            "pending_withdraw_count": pending_withdraw_count,
            "last_activity_at": _to_str_dt(last_activity),
        },
    }

@router.get("/{tg_user_id}/financial-history")
def admin_user_financial_history(
    tg_user_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    _: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    wallet = db.execute(select(Wallet).where(Wallet.user_id == int(user.id))).scalar_one_or_none()

    tx_rows = []
    if wallet:
        tx_rows = db.execute(
            select(WalletTx)
            .where(WalletTx.wallet_id == int(wallet.id))
            .order_by(WalletTx.id.desc())
            .limit(int(limit))
        ).scalars().all()

    deposit_rows = db.execute(
        select(DepositRequest)
        .where(DepositRequest.user_id == int(user.id))
        .order_by(DepositRequest.id.desc())
        .limit(int(limit))
    ).scalars().all()

    withdraw_rows = db.execute(
        select(WithdrawRequest)
        .where(WithdrawRequest.user_id == int(user.id))
        .order_by(WithdrawRequest.id.desc())
        .limit(int(limit))
    ).scalars().all()

    adjust_logs = _adjust_logs_for_user(db, tg_user_id=int(tg_user_id), limit=int(limit))
    adjust_by_tx_id: dict[int, dict[str, Any]] = {}
    for item in adjust_logs:
        try:
            tx_id = int(item.get("tx_id"))
        except Exception:
            continue
        if tx_id > 0:
            adjust_by_tx_id[tx_id] = item

    tx_items: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    for tx in tx_rows:
        item = {
            "id": int(tx.id),
            "direction": str(tx.direction),
            "amount": int(tx.amount),
            "reason": str(tx.reason),
            "reason_label": _reason_label(str(tx.reason)),
            "ref_type": str(tx.ref_type) if tx.ref_type else None,
            "ref_id": int(tx.ref_id) if tx.ref_id is not None else None,
            "idempotency_key": str(tx.idempotency_key),
            "created_at": _to_str_dt(tx.created_at),
            "adjust_meta": adjust_by_tx_id.get(int(tx.id)) if str(tx.reason) == "ADJUST" else None,
        }
        tx_items.append(item)
        timeline.append({"entry_type": "wallet_tx", "created_at": item["created_at"], "payload": item})

    deposit_items: list[dict[str, Any]] = []
    for row in deposit_rows:
        item = {
            "id": int(row.id),
            "amount": int(row.amount),
            "status": str(row.status),
            "wallet_tx_id": int(row.wallet_tx_id) if row.wallet_tx_id is not None else None,
            "reviewed_by": int(row.reviewed_by) if row.reviewed_by is not None else None,
            "reviewed_at": _to_str_dt(row.reviewed_at),
            "created_at": _to_str_dt(row.created_at),
        }
        deposit_items.append(item)
        timeline.append({"entry_type": "deposit_request", "created_at": item["created_at"], "payload": item})

    withdraw_items: list[dict[str, Any]] = []
    for row in withdraw_rows:
        item = {
            "id": int(row.id),
            "amount": int(row.amount),
            "status": str(row.status),
            "wallet_tx_id": int(row.wallet_tx_id) if row.wallet_tx_id is not None else None,
            "reviewed_by": int(row.reviewed_by) if row.reviewed_by is not None else None,
            "reviewed_at": _to_str_dt(row.reviewed_at),
            "paid_tracking": str(row.paid_tracking) if row.paid_tracking else None,
            "created_at": _to_str_dt(row.created_at),
        }
        withdraw_items.append(item)
        timeline.append({"entry_type": "withdraw_request", "created_at": item["created_at"], "payload": item})

    timeline.sort(key=lambda x: _to_dt(x.get("created_at")) or datetime.min, reverse=True)
    timeline = timeline[: int(limit)]

    return {
        "user": _user_basic(user),
        "wallet_balance": int(wallet.balance) if wallet else 0,
        "wallet_transactions": tx_items,
        "deposit_requests": deposit_items,
        "withdraw_requests": withdraw_items,
        "wallet_adjust_logs": adjust_logs,
        "timeline": timeline,
    }


@router.get("/{tg_user_id}/games-history")
def admin_user_games_history(
    tg_user_id: int,
    limit: int = Query(default=30, ge=1, le=200),
    _: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    wallet = db.execute(select(Wallet).where(Wallet.user_id == int(user.id))).scalar_one_or_none()

    purchase_rows = db.execute(
        select(
            GamePurchase.game_id.label("game_id"),
            func.coalesce(func.sum(GamePurchase.qty), 0).label("cards_qty"),
            func.coalesce(func.sum(GamePurchase.total_price), 0).label("total_spent"),
            func.max(GamePurchase.created_at).label("last_buy_at"),
        )
        .where(GamePurchase.user_id == int(user.id))
        .group_by(GamePurchase.game_id)
        .order_by(func.max(GamePurchase.created_at).desc(), GamePurchase.game_id.desc())
        .limit(int(limit))
    ).mappings().all()

    game_ids = [int(x["game_id"]) for x in purchase_rows]
    games = db.execute(select(Game).where(Game.id.in_(game_ids))).scalars().all() if game_ids else []
    game_by_id = {int(g.id): g for g in games}

    win_by_game: dict[int, dict[str, Any]] = {}
    if wallet and game_ids:
        win_rows = db.execute(
            select(WalletTx.ref_id, WalletTx.reason, WalletTx.amount, WalletTx.created_at)
            .where(
                WalletTx.wallet_id == int(wallet.id),
                WalletTx.ref_type == "GAME",
                WalletTx.ref_id.in_(game_ids),
                WalletTx.reason.in_(list(WIN_REASONS)),
            )
            .order_by(WalletTx.id.desc())
        ).all()
        for ref_id, reason, amount, created_at in win_rows:
            try:
                gid = int(ref_id)
            except Exception:
                continue
            if gid <= 0:
                continue
            bucket = win_by_game.setdefault(gid, {
                "wins_col_count": 0,
                "wins_row_count": 0,
                "wins_col_amount": 0,
                "wins_row_amount": 0,
                "last_win_at": None,
            })
            if str(reason) == "PRIZE_COL":
                bucket["wins_col_count"] = int(bucket["wins_col_count"]) + 1
                bucket["wins_col_amount"] = int(bucket["wins_col_amount"]) + int(amount or 0)
            elif str(reason) == "PRIZE_ROW":
                bucket["wins_row_count"] = int(bucket["wins_row_count"]) + 1
                bucket["wins_row_amount"] = int(bucket["wins_row_amount"]) + int(amount or 0)
            dt = _to_dt(created_at)
            if dt and (bucket["last_win_at"] is None or dt > _to_dt(bucket["last_win_at"])):
                bucket["last_win_at"] = _to_str_dt(dt)

    total_win_amount = 0
    total_win_count = 0
    last_win_at = None
    if wallet:
        total_win_amount = int(
            db.execute(select(func.coalesce(func.sum(WalletTx.amount), 0)).where(
                WalletTx.wallet_id == int(wallet.id),
                WalletTx.reason.in_(list(WIN_REASONS)),
            )).scalar_one() or 0
        )
        total_win_count = int(
            db.execute(select(func.count(WalletTx.id)).where(
                WalletTx.wallet_id == int(wallet.id),
                WalletTx.reason.in_(list(WIN_REASONS)),
            )).scalar_one() or 0
        )
        last_win_at = _to_str_dt(
            db.execute(select(func.max(WalletTx.created_at)).where(
                WalletTx.wallet_id == int(wallet.id),
                WalletTx.reason.in_(list(WIN_REASONS)),
            )).scalar_one_or_none()
        )

    items: list[dict[str, Any]] = []
    total_cards = 0
    total_spent = 0
    for row in purchase_rows:
        gid = int(row["game_id"])
        g = game_by_id.get(gid)
        win = win_by_game.get(gid, {})
        cards_qty = int(row["cards_qty"] or 0)
        spent = int(row["total_spent"] or 0)
        total_cards += cards_qty
        total_spent += spent
        items.append({
            "game_id": gid,
            "game_status": str(g.status) if g else None,
            "game_topic_id": int(g.tg_topic_id) if (g and g.tg_topic_id is not None) else None,
            "card_price": int(g.card_price) if g else None,
            "row_prize_amount": int(g.row_prize_amount) if g else None,
            "col_prize_amount": int(g.col_prize_amount) if g else None,
            "cards_qty": cards_qty,
            "total_spent": spent,
            "last_buy_at": _to_str_dt(row["last_buy_at"]),
            "win": {
                "wins_col_count": int(win.get("wins_col_count", 0)),
                "wins_row_count": int(win.get("wins_row_count", 0)),
                "wins_total_count": int(win.get("wins_col_count", 0)) + int(win.get("wins_row_count", 0)),
                "wins_col_amount": int(win.get("wins_col_amount", 0)),
                "wins_row_amount": int(win.get("wins_row_amount", 0)),
                "wins_total_amount": int(win.get("wins_col_amount", 0)) + int(win.get("wins_row_amount", 0)),
                "last_win_at": win.get("last_win_at"),
            },
        })

    return {
        "user": _user_basic(user),
        "summary": {
            "games_participated": len(items),
            "cards_purchased": total_cards,
            "total_spent": total_spent,
            "total_win_count": total_win_count,
            "total_win_amount": total_win_amount,
            "last_win_at": last_win_at,
        },
        "items": items,
    }

@router.post("/{tg_user_id}/restrict")
def admin_user_restrict(
    tg_user_id: int,
    payload: RestrictIn,
    request: Request,
    admin: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    roles = _roles_for_user(db, int(user.id))
    _ensure_manage_target(admin, roles)

    until_dt = _parse_until(payload.until, payload.minutes)
    if until_dt and until_dt <= _now():
        raise HTTPException(status_code=400, detail="until must be in the future")

    restrictions = _load_restrictions(db)
    key = str(int(user.tg_user_id))
    current = restrictions.get(key) if isinstance(restrictions.get(key), dict) else {}
    current = dict(current or {})
    previous_state = _restriction_state(current)
    current.update({
        "active": True,
        "reason": str(payload.reason).strip(),
        "actions": _normalize_actions(payload.actions),
        "until": _to_str_dt(until_dt),
        "set_at": _to_str_dt(_now()),
        "set_by_user_id": int(admin.user_id) if admin.user_id is not None else None,
        "set_by_scope": str(admin.scope.value if hasattr(admin.scope, "value") else admin.scope),
        "lifted_at": None,
        "lifted_by_user_id": None,
        "lift_reason": None,
    })
    restrictions[key] = current
    _setting_set_json(db, USER_RESTRICTIONS_KEY, restrictions)
    new_state = _restriction_state(current)
    AdminAuditService.record(
        db,
        admin=admin,
        action="user.restrict",
        target_type="user",
        target_id=int(user.id),
        request=request,
        details={
            "user_id": int(user.id),
            "tg_user_id": int(user.tg_user_id),
            "roles": roles,
            "previous_active": bool(previous_state.get("active")),
            "new_active": bool(new_state.get("active")),
            "reason": str(payload.reason).strip(),
            "actions": new_state.get("actions"),
            "until": new_state.get("until"),
        },
    )
    db.commit()

    return {"ok": True, "user": _user_basic(user), "roles": roles, "restriction": _restriction_state(current)}


@router.post("/{tg_user_id}/unrestrict")
def admin_user_unrestrict(
    tg_user_id: int,
    payload: UnrestrictIn,
    request: Request,
    admin: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    roles = _roles_for_user(db, int(user.id))
    _ensure_manage_target(admin, roles)

    restrictions = _load_restrictions(db)
    key = str(int(user.tg_user_id))
    current = restrictions.get(key) if isinstance(restrictions.get(key), dict) else {}
    current = dict(current or {})
    previous_state = _restriction_state(current)
    current.update({
        "active": False,
        "lifted_at": _to_str_dt(_now()),
        "lifted_by_user_id": int(admin.user_id) if admin.user_id is not None else None,
        "lift_reason": str(payload.reason or "").strip() or None,
    })
    restrictions[key] = current
    _setting_set_json(db, USER_RESTRICTIONS_KEY, restrictions)
    new_state = _restriction_state(current)
    AdminAuditService.record(
        db,
        admin=admin,
        action="user.unrestrict",
        target_type="user",
        target_id=int(user.id),
        request=request,
        details={
            "user_id": int(user.id),
            "tg_user_id": int(user.tg_user_id),
            "roles": roles,
            "previous_active": bool(previous_state.get("active")),
            "new_active": bool(new_state.get("active")),
            "reason": str(payload.reason or "").strip() or None,
            "lifted_at": new_state.get("lifted_at"),
        },
    )
    db.commit()

    return {"ok": True, "user": _user_basic(user), "roles": roles, "restriction": _restriction_state(current)}


@router.post("/{tg_user_id}/wallet-adjust")
def admin_user_wallet_adjust(
    tg_user_id: int,
    payload: WalletAdjustIn,
    request: Request,
    admin: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    roles = _roles_for_user(db, int(user.id))
    _ensure_manage_target(admin, roles)

    wallet = WalletService.get_or_create_wallet(db, int(user.id))
    before_balance = int(wallet.balance)
    amount = int(payload.amount)

    idem = str(payload.idempotency_key or "").strip()
    if not idem:
        idem = f"admin-adjust:{int(user.id)}:{uuid4().hex}"

    try:
        if amount > 0:
            tx = WalletService.credit(
                db=db,
                user_id=int(user.id),
                amount=amount,
                reason="ADJUST",
                idempotency_key=idem,
                ref_type="ADMIN_ADJUST",
                ref_id=int(admin.user_id) if admin.user_id is not None else None,
            )
        else:
            tx = WalletService.debit(
                db=db,
                user_id=int(user.id),
                amount=abs(amount),
                reason="ADJUST",
                idempotency_key=idem,
                ref_type="ADMIN_ADJUST",
                ref_id=int(admin.user_id) if admin.user_id is not None else None,
            )
    except HTTPException:
        db.rollback()
        raise

    wallet_after = WalletService.get_or_create_wallet(db, int(user.id))
    after_balance = int(wallet_after.balance)

    log_entry = {
        "at": _to_str_dt(_now()),
        "target_user_id": int(user.id),
        "target_tg_user_id": int(user.tg_user_id),
        "admin_user_id": int(admin.user_id) if admin.user_id is not None else None,
        "admin_scope": str(admin.scope.value if hasattr(admin.scope, "value") else admin.scope),
        "tx_id": int(tx.id),
        "amount": int(amount),
        "reason": str(payload.reason).strip(),
        "before_balance": before_balance,
        "after_balance": after_balance,
        "idempotency_key": idem,
    }
    _append_wallet_adjust_log(db, log_entry)

    notify_result = {"ok": False, "skipped": True}
    if bool(payload.notify_user):
        txt = _compose_message_text(
            user=user,
            kind="wallet_adjust",
            reason=str(payload.reason).strip(),
            amount=int(amount),
            ref_id=int(tx.id),
        )
        notify_result = _telegram_send_private_message(
            tg_user_id=int(user.tg_user_id),
            text=txt,
            parse_mode="HTML",
            disable_notification=False,
        )

    AdminAuditService.record(
        db,
        admin=admin,
        action="wallet.adjust",
        target_type="user",
        target_id=int(user.id),
        request=request,
        details={
            "user_id": int(user.id),
            "tg_user_id": int(user.tg_user_id),
            "wallet_tx_id": int(tx.id),
            "amount": int(amount),
            "direction": "CREDIT" if amount > 0 else "DEBIT",
            "reason": str(payload.reason).strip(),
            "before_balance": before_balance,
            "after_balance": after_balance,
            "idempotency_key": idem,
            "notify_user": bool(payload.notify_user),
            "notify_ok": bool(notify_result.get("ok", False)),
        },
    )
    db.commit()
    return {
        "ok": True,
        "user": _user_basic(user),
        "tx_id": int(tx.id),
        "wallet_before": before_balance,
        "wallet_after": after_balance,
        "adjust_amount": int(amount),
        "reason": str(payload.reason).strip(),
        "idempotency_key": idem,
        "notify": notify_result,
    }


@router.post("/{tg_user_id}/notify")
def admin_user_notify(
    tg_user_id: int,
    payload: NotifyIn,
    _: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    result = _telegram_send_private_message(
        tg_user_id=int(user.tg_user_id),
        text=str(payload.text),
        parse_mode=str(payload.parse_mode or "HTML"),
        disable_notification=bool(payload.disable_notification),
    )
    if not bool(result.get("ok", False)):
        raise HTTPException(status_code=502, detail=str(result.get("error") or "telegram send failed"))
    return {"ok": True, "user": _user_basic(user), "message_id": result.get("message_id")}


@router.post("/{tg_user_id}/compose-message")
def admin_user_compose_message(
    tg_user_id: int,
    payload: ComposeIn,
    _: AdminIdentity = Depends(require_admin_any),
    db: Session = Depends(get_db),
):
    user = _get_user_by_tg_or_404(db, int(tg_user_id))
    text = _compose_message_text(
        user=user,
        kind=str(payload.kind),
        reason=payload.reason,
        amount=payload.amount,
        ref_id=payload.ref_id,
    )
    return {
        "ok": True,
        "kind": payload.kind,
        "text": text,
        "preview": {
            "target_tg_user_id": int(user.tg_user_id),
            "display_name": _display_name(user),
        },
    }
