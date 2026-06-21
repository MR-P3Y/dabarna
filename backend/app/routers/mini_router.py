from __future__ import annotations

import json
import os
import base64
import hashlib
import logging
from html import escape as html_escape
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity, AdminScope
from app.core.config import (
    ADMIN_TG_USER_IDS,
    ADMIN_TOKEN_MAP,
    ADMIN_TOKEN_ROLE_MAP,
    DEFAULT_TG_GROUP_ID,
    DEPOSIT_ACCOUNT_NUMBER,
    DEPOSIT_BANK_NAME,
    DEPOSIT_CARD_NUMBER,
    DEPOSIT_DESTINATIONS,
    DEPOSIT_IBAN,
    DEPOSIT_OWNER_NAME,
    RECEIPTS_DIR,
    RBAC_OWNER_USER_ID,
    SUPER_ADMIN_TG_USER_IDS,
    TELEGRAM_INITDATA_HEADER,
    USER_FORUM_CHAT_ID,
    USER_TOPIC_GAME_HIGH_ID,
    USER_TOPIC_GAME_LOW_ID,
    USER_TOPIC_GAME_MEDIUM_ID,
)
from app.core.db import get_db
from app.core.mini_security import (
    enforce_events_rate_limit,
    enforce_write_rate_limit,
    exchange_init_data_for_session,
    get_mini_user_id,
)
from app.models.finance import DepositRequest, WithdrawRequest
from app.models.game import Game, GameCard
from app.models.game_event import GameEvent
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.rbac import Role, UserRole
from app.schemas.mini import (
    MiniAuthExchangeIn,
    MiniAuthExchangeOut,
    MiniBuyIn,
    MiniBuyOut,
    MiniCardOut,
    MiniDepositCreateIn,
    MiniDepositReceiptIn,
    MiniDepositDestinationListOut,
    MiniDepositDestinationOut,
    MiniDepositListOut,
    MiniDepositOut,
    MiniDashboardInsightsOut,
    MiniEventOut,
    MiniGameItemOut,
    MiniGameListOut,
    MiniGameSnapshotOut,
    MiniLatestWinOut,
    MiniNearestToWinOut,
    MiniRecentGameStatOut,
    MiniTrustStatsOut,
    MiniUserCardItemOut,
    MiniUserCardListOut,
    MiniWalletOut,
    MiniWalletTxOut,
    MiniWithdrawCreateIn,
    MiniWithdrawListOut,
    MiniWithdrawOut,
)
from app.services.finance_service import FinanceService
from app.services.game_event_service import GameEventService
from app.services.game_service import GameService
from app.services.wallet_service import WalletService
from app.routers import admin_users_router

router = APIRouter(prefix="/mini-api", tags=["mini"])
log = logging.getLogger("mini.router")

DEPOSIT_DESTINATIONS_SETTING_KEY = "deposit_destinations"
DEPOSIT_REQUEST_DESTINATION_KEY_PREFIX = "deposit_request_destination:"
WITHDRAW_REQUEST_SOURCE_KEY_PREFIX = "withdraw_request_source:"
WITHDRAW_PAID_PROOF_KEY_PREFIX = "withdraw_paid_proof:"
GAME_LIVE_LINK_KEY_PREFIX = "game_live_link:"


def _clean_numeric(value: object) -> str:
    return str(value or "").strip().replace(" ", "").replace("-", "")


def _default_destination_title(bank_name: str, card_number: str, idx: int) -> str:
    bn = str(bank_name or "").strip()
    card = _clean_numeric(card_number)
    tail = card[-4:] if len(card) >= 4 else str(idx + 1)
    if bn:
        return f"{bn} ({tail})"
    return f"کارت {idx + 1} ({tail})"


def _setting_get_json(db: Session, key: str) -> object | None:
    row = db.get(AppSetting, str(key))
    if not row:
        return None
    return getattr(row, "v_json", None)


def _setting_set_json(db: Session, key: str, value: object) -> None:
    row = db.get(AppSetting, str(key))
    if not row:
        row = AppSetting(k=str(key), v_json=value)
        db.add(row)
        return
    row.v_json = value
    db.add(row)


def _normalize_destination_payload(
    payload: dict[str, object],
    *,
    idx: int,
    fallback_id: str | None = None,
) -> dict[str, object]:
    card_number = _clean_numeric(payload.get("card_number"))
    if not card_number or (not card_number.isdigit()) or len(card_number) < 16 or len(card_number) > 19:
        raise HTTPException(status_code=400, detail="شماره کارت مقصد نامعتبر است.")

    dest_id = str(payload.get("id") or "").strip()
    if not dest_id:
        dest_id = str(fallback_id or f"dst_{idx + 1}").strip()
    if len(dest_id) > 64:
        raise HTTPException(status_code=400, detail="شناسه کارت مقصد بیش از حد مجاز است.")

    title = str(payload.get("title") or "").strip()
    bank_name = str(payload.get("bank_name") or "").strip()
    if not title:
        title = _default_destination_title(bank_name=bank_name, card_number=card_number, idx=idx)

    return {
        "id": dest_id,
        "title": title,
        "account_name": str(payload.get("account_name") or "").strip(),
        "bank_name": bank_name,
        "iban": str(payload.get("iban") or "").strip().upper(),
        "card_number": card_number,
        "account_number": _clean_numeric(payload.get("account_number")),
        "is_active": bool(payload.get("is_active", True)),
    }


def _normalize_destination_list(items: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    used_ids: set[str] = set()
    for idx, item in enumerate(items):
        try:
            normalized = _normalize_destination_payload(item, idx=idx)
        except HTTPException:
            continue
        base_id = str(normalized["id"])
        if base_id in used_ids:
            suffix = 2
            cand = f"{base_id}_{suffix}"
            while cand in used_ids:
                suffix += 1
                cand = f"{base_id}_{suffix}"
            normalized["id"] = cand
        used_ids.add(str(normalized["id"]))
        out.append(normalized)
    return out


def _load_destinations_from_settings(db: Session) -> list[dict[str, object]]:
    raw = _setting_get_json(db, DEPOSIT_DESTINATIONS_SETTING_KEY)
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, object]] = []
    for item in raw:
        if isinstance(item, dict):
            parsed.append({str(k): v for k, v in item.items()})
    return _normalize_destination_list(parsed)


def _fallback_destinations_from_env() -> list[dict[str, object]]:
    pool = list(DEPOSIT_DESTINATIONS or [])
    if not pool:
        single = {
            "account_name": str(DEPOSIT_OWNER_NAME or "").strip(),
            "bank_name": str(DEPOSIT_BANK_NAME or "").strip(),
            "iban": str(DEPOSIT_IBAN or "").strip(),
            "card_number": str(DEPOSIT_CARD_NUMBER or "").strip(),
            "account_number": str(DEPOSIT_ACCOUNT_NUMBER or "").strip(),
        }
        if single.get("card_number"):
            pool = [single]

    out: list[dict[str, object]] = []
    for idx, item in enumerate(pool):
        raw = dict(item)
        raw.setdefault("id", f"env_{idx + 1}")
        raw.setdefault("title", _default_destination_title(str(raw.get("bank_name") or ""), str(raw.get("card_number") or ""), idx))
        raw.setdefault("is_active", True)
        try:
            out.append(_normalize_destination_payload(raw, idx=idx))
        except HTTPException:
            continue
    return out


def _deposit_destination_pool(db: Session, *, include_inactive: bool = False) -> list[dict[str, object]]:
    pool = _load_destinations_from_settings(db)
    if not pool:
        pool = _fallback_destinations_from_env()
    if include_inactive:
        return list(pool)
    return [it for it in pool if bool(it.get("is_active", True))]


def _find_destination_by_id(destinations: list[dict[str, object]], destination_id: str | None) -> dict[str, object] | None:
    needle = str(destination_id or "").strip()
    if not needle:
        return None
    for item in destinations:
        if str(item.get("id") or "").strip() == needle:
            return item
    return None


def _request_destination_setting_key(request_id: int) -> str:
    return f"{DEPOSIT_REQUEST_DESTINATION_KEY_PREFIX}{int(request_id)}"


def _withdraw_source_setting_key(request_id: int) -> str:
    return f"{WITHDRAW_REQUEST_SOURCE_KEY_PREFIX}{int(request_id)}"


def _withdraw_paid_proof_setting_key(request_id: int) -> str:
    return f"{WITHDRAW_PAID_PROOF_KEY_PREFIX}{int(request_id)}"


def _game_live_link_setting_key(game_id: int) -> str:
    return f"{GAME_LIVE_LINK_KEY_PREFIX}{int(game_id)}"


def _read_game_live_link(db: Session, *, game_id: int) -> tuple[str | None, str | None]:
    raw = _setting_get_json(db, _game_live_link_setting_key(int(game_id)))
    if not isinstance(raw, dict):
        return None, None

    url = str(raw.get("url") or "").strip()
    if not url:
        return None, None

    updated_at_raw = raw.get("updated_at")
    updated_at = str(updated_at_raw).strip() if updated_at_raw is not None else None
    if updated_at == "":
        updated_at = None
    return url, updated_at


def _save_request_destination(db: Session, *, request_id: int, destination: dict[str, object]) -> None:
    payload = {
        "destination_id": str(destination.get("id") or "").strip(),
        "snapshot": destination,
    }
    _setting_set_json(db, _request_destination_setting_key(request_id), payload)


def _read_request_destination(db: Session, *, request_id: int) -> tuple[str | None, str | None]:
    raw = _setting_get_json(db, _request_destination_setting_key(request_id))
    if not isinstance(raw, dict):
        return None, None
    destination_id = str(raw.get("destination_id") or "").strip() or None
    snap = raw.get("snapshot")
    if not isinstance(snap, dict):
        return destination_id, None
    title = str(snap.get("title") or "").strip() or None
    return destination_id, title


def _to_game_out(g: Game) -> MiniGameItemOut:
    return MiniGameItemOut(
        id=int(g.id),
        tg_group_id=int(g.tg_group_id),
        tg_topic_id=int(g.tg_topic_id) if g.tg_topic_id is not None else None,
        status=str(g.status),
        card_price=int(g.card_price),
        sold_amount=int(g.sold_amount),
        prize_pool=int(g.prize_pool),
        col_prize_amount=int(g.col_prize_amount),
        row_prize_amount=int(g.row_prize_amount),
        created_at=str(g.created_at) if g.created_at else None,
    )


def _parse_status_filter(raw: str | None) -> list[str]:
    text = str(raw or "LOBBY|RUNNING|ENDED").strip().upper().replace(",", "|")
    allowed = {"LOBBY", "RUNNING", "ENDED"}
    out: list[str] = []
    for item in [p.strip() for p in text.split("|") if p.strip()]:
        if item not in allowed:
            raise HTTPException(status_code=400, detail=f"وضعیت نامعتبر است: {item}")
        if item not in out:
            out.append(item)
    return out or ["LOBBY", "RUNNING", "ENDED"]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        cleaned = str(value).strip().replace(",", "")
        if cleaned == "":
            return int(default)
        return int(float(cleaned))
    except Exception:
        return int(default)


def _safe_user_count(values: Any) -> int:
    if not isinstance(values, list):
        return 0
    out: set[int] = set()
    for v in values:
        n = _safe_int(v, 0)
        if n > 0:
            out.add(int(n))
    return len(out)


def _numbers_from_json(raw: Any) -> list[int]:
    if isinstance(raw, list):
        return [int(x) for x in raw]
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                return [int(x) for x in loaded]
        except Exception:
            return []
    return []


def _winner_ids_from_payload_state(raw_state: Any, key: str) -> list[int]:
    if not isinstance(raw_state, dict):
        return []
    item = raw_state.get(key)
    if not isinstance(item, dict):
        return []
    vals = item.get("winner_user_ids")
    if isinstance(vals, list):
        return [int(x) for x in vals if str(x).strip()]
    return []


def _guess_win_pattern(row_winners: set[int], col_winners: set[int]) -> str:
    if row_winners and col_winners:
        return "برد سطری(تمام) + برد ستونی(تورنا)"
    if row_winners:
        return "برد سطری(تمام)"
    if col_winners:
        return "برد ستونی(تورنا)"
    return "نامشخص"


def _user_alias(user: User | None) -> str:
    if user is None:
        return "کاربر"
    username = str(user.username or "").strip()
    if username:
        return f"@{username}"
    first_name = str(user.first_name or "").strip()
    if first_name:
        return first_name
    return f"کاربر {int(user.tg_user_id)}"


ADMIN_ROLE_NAMES: tuple[str, str] = ("ADMIN", "SUPER_ADMIN")


class MiniAdminIdentity:
    def __init__(self, *, user_id: int, tg_user_id: int | None, roles: list[str]):
        self.user_id = int(user_id)
        self.tg_user_id = int(tg_user_id) if tg_user_id is not None else None
        self.roles = sorted({str(r).upper() for r in roles if str(r).strip()})
        self.is_super_admin = "SUPER_ADMIN" in self.roles
        self.is_admin = self.is_super_admin or ("ADMIN" in self.roles)
        self.scope = "SUPER_ADMIN" if self.is_super_admin else ("ADMIN" if self.is_admin else "USER")


class MiniAdminMeOut(BaseModel):
    user_id: int
    tg_user_id: int | None = None
    scope: str
    roles: list[str]
    is_admin: bool
    is_super_admin: bool


class MiniAdminActionIn(BaseModel):
    idempotency_key: str = Field(min_length=6)


class MiniAdminCallIn(BaseModel):
    number: int = Field(ge=1, le=99)
    idempotency_key: str = Field(min_length=6)


class MiniAdminCreateGameIn(BaseModel):
    card_price: int = Field(gt=0, le=1_000_000_000)
    tg_group_id: int | None = Field(default=None)
    tg_topic_id: int | None = Field(default=None)
    source_game_id: int | None = Field(default=None, gt=0)
    idempotency_key: str = Field(min_length=6)


class MiniAdminCreateTopicOut(BaseModel):
    key: str
    title: str
    topic_id: int


class MiniAdminCreateOptionsOut(BaseModel):
    group_id: int | None = None
    topics: list[MiniAdminCreateTopicOut]
    enforce_topic: bool


class MiniAdminCloseLobbyIn(BaseModel):
    cancel_reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=6)


class MiniAdminLiveLinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=512)


class MiniAdminDepositApproveIn(BaseModel):
    idempotency_key: str = Field(min_length=6)


class MiniAdminWithdrawApproveIn(BaseModel):
    idempotency_key: str = Field(min_length=6)


class MiniAdminWithdrawPaidIn(BaseModel):
    paid_tracking: str = Field(min_length=2, max_length=128)


class MiniAdminWithdrawProofIn(BaseModel):
    proof_text: str | None = Field(default=None, max_length=1000)
    filename: str | None = Field(default=None, max_length=255)
    content_type: str | None = Field(default=None, max_length=100)
    data_base64: str | None = None


class MiniAdminWithdrawRejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class MiniSuperGrantIn(BaseModel):
    tg_user_id: int = Field(gt=0)
    role: Literal["ADMIN", "SUPER_ADMIN"] = "ADMIN"


class MiniSuperRevokeIn(BaseModel):
    tg_user_id: int = Field(gt=0)
    role: Literal["ADMIN", "SUPER_ADMIN", "ALL"] = "ALL"


def _normalize_live_url(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="live_url is required")
    if s.startswith("t.me/") or s.startswith("telegram.me/") or s.startswith("www."):
        s = f"https://{s}"
    if not (s.startswith("http://") or s.startswith("https://")):
        raise HTTPException(status_code=400, detail="invalid live_url")
    if len(s) > 512:
        raise HTTPException(status_code=400, detail="live_url is too long")
    p = urlparse(s)
    if p.scheme not in {"http", "https"} or not p.netloc:
        raise HTTPException(status_code=400, detail="invalid live_url")
    return s


def _mini_role_names_for_user(db: Session, user_id: int) -> list[str]:
    rows = db.execute(
        select(Role.name)
        .select_from(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == int(user_id))
    ).scalars().all()
    return [str(r).upper() for r in rows if str(r).strip()]


def _mini_config_roles_for_user(user_id: int, tg_user_id: int | None = None) -> list[str]:
    roles: set[str] = set()
    uid = int(user_id)

    if RBAC_OWNER_USER_ID is not None and uid == int(RBAC_OWNER_USER_ID):
        roles.add("SUPER_ADMIN")
        roles.add("ADMIN")

    if tg_user_id is not None:
        tgid = int(tg_user_id)
        if tgid in (SUPER_ADMIN_TG_USER_IDS or set()):
            roles.add("SUPER_ADMIN")
            roles.add("ADMIN")
        if tgid in (ADMIN_TG_USER_IDS or set()):
            roles.add("ADMIN")

    for token, mapped_uid in (ADMIN_TOKEN_MAP or {}).items():
        try:
            mid = int(mapped_uid)
        except Exception:
            continue
        if mid != uid:
            continue
        role = str((ADMIN_TOKEN_ROLE_MAP or {}).get(str(token), "ADMIN")).strip().upper()
        if role == "SUPER_ADMIN":
            roles.add("SUPER_ADMIN")
            roles.add("ADMIN")
        else:
            roles.add("ADMIN")

    return sorted(roles)


def _mini_admin_identity_for_user(db: Session, user_id: int) -> MiniAdminIdentity:
    tg_user_id = db.execute(
        select(User.tg_user_id).where(User.id == int(user_id))
    ).scalar_one_or_none()
    roles = set(_mini_role_names_for_user(db, int(user_id)))
    roles.update(
        _mini_config_roles_for_user(
            int(user_id),
            int(tg_user_id) if tg_user_id is not None else None,
        )
    )
    identity = MiniAdminIdentity(
        user_id=int(user_id),
        tg_user_id=int(tg_user_id) if tg_user_id is not None else None,
        roles=sorted(roles),
    )
    if not identity.is_admin:
        raise HTTPException(status_code=403, detail="forbidden")
    return identity


def get_mini_admin_identity(
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
) -> MiniAdminIdentity:
    return _mini_admin_identity_for_user(db, int(user_id))


def get_mini_super_admin_identity(
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
) -> MiniAdminIdentity:
    if not ident.is_super_admin:
        raise HTTPException(status_code=403, detail="super admin required")
    if RBAC_OWNER_USER_ID is not None and int(ident.user_id) != int(RBAC_OWNER_USER_ID):
        raise HTTPException(status_code=403, detail="super admin owner required")
    return ident


def _mini_to_admin_identity(ident: MiniAdminIdentity) -> AdminIdentity:
    scope = AdminScope.SUPER_ADMIN if bool(ident.is_super_admin) else AdminScope.ADMIN
    return AdminIdentity(scope=scope, token="MINI", user_id=int(ident.user_id))


def _mini_get_game_or_404(db: Session, game_id: int) -> Game:
    game = db.execute(select(Game).where(Game.id == int(game_id))).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="game not found")
    return game


def _mini_require_game_manage_access(db: Session, game_id: int, ident: MiniAdminIdentity) -> Game:
    game = _mini_get_game_or_404(db, int(game_id))
    if ident.is_super_admin:
        return game
    if int(game.admin_user_id) != int(ident.user_id):
        raise HTTPException(status_code=403, detail="only game admin can manage this game")
    return game


def _mini_default_group_id() -> int | None:
    if USER_FORUM_CHAT_ID is not None:
        return int(USER_FORUM_CHAT_ID)
    if DEFAULT_TG_GROUP_ID is not None:
        return int(DEFAULT_TG_GROUP_ID)
    return None


def _mini_configured_game_topics() -> list[tuple[str, str, int]]:
    raw: list[tuple[str, str, int | None]] = [
        ("game_low", "\U0001F3AF \u0628\u0627\u0632\u06cc \u06f1 (\u0645\u0628\u0644\u063a \u067e\u0627\u06cc\u06cc\u0646)", USER_TOPIC_GAME_LOW_ID),
        ("game_medium", "\U0001F3AF \u0628\u0627\u0632\u06cc \u06f2 (\u0645\u0628\u0644\u063a \u0645\u062a\u0648\u0633\u0637)", USER_TOPIC_GAME_MEDIUM_ID),
        ("game_high", "\U0001F3AF \u0628\u0627\u0632\u06cc \u06f3 (\u0645\u0628\u0644\u063a \u0628\u0627\u0644\u0627)", USER_TOPIC_GAME_HIGH_ID),
    ]
    out: list[tuple[str, str, int]] = []
    seen: set[int] = set()
    for key, title, topic_id in raw:
        if topic_id is None:
            continue
        tid = int(topic_id)
        if tid <= 0 or tid in seen:
            continue
        seen.add(tid)
        out.append((key, title, tid))
    return out


def _mini_game_topic_title(topic_id: int | None) -> str:
    if topic_id is None:
        return "\u062f\u0633\u062a\u0647 \u0639\u0645\u0648\u0645\u06cc"
    tid = int(topic_id)
    for _key, title, configured_topic_id in _mini_configured_game_topics():
        if int(configured_topic_id) == tid:
            return str(title)
    return f"\u062a\u0627\u067e\u06cc\u06a9 {tid}"


def _mini_parse_optional_topic_id(raw: str | None) -> int | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("+"):
        text = text[1:]
    if not text.isdigit():
        return None
    value = int(text)
    if value <= 0:
        return None
    return value


def _mini_send_topic_message(
    *,
    chat_id: int,
    topic_id: int | None,
    text: str,
    parse_mode: str = "HTML",
) -> bool:
    bot_token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        return False
    if int(chat_id) == 0:
        return False

    payload: dict[str, Any] = {
        "chat_id": int(chat_id),
        "text": str(text),
        "parse_mode": str(parse_mode),
        "disable_web_page_preview": True,
        "disable_notification": False,
    }
    if topic_id is not None and int(topic_id) > 0:
        payload["message_thread_id"] = int(topic_id)

    req = urllib_request.Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            body_raw = resp.read().decode("utf-8", errors="replace")
        body = json.loads(body_raw)
        return bool(body.get("ok", False))
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    except Exception:
        return False


def _mini_parse_env_int(name: str) -> int | None:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _mini_fmt_toman(amount: object) -> str:
    try:
        return f"{int(amount or 0):,} ?????"
    except Exception:
        return "0 ?????"


def _mini_user_title(user: User | None, *, user_id: int) -> str:
    if user is None:
        return f"????? #{int(user_id)}"
    username = str(getattr(user, "username", "") or "").strip()
    tg_user_id = getattr(user, "tg_user_id", None)
    if username:
        return f"@{html_escape(username)}"
    if tg_user_id is not None:
        return f"TG <code>{int(tg_user_id)}</code>"
    return f"????? #{int(user_id)}"


def _mini_mask_card(value: object) -> str:
    raw = _clean_numeric(value)
    if len(raw) < 8:
        return html_escape(raw or "-")
    return html_escape(f"{raw[:4]} **** **** {raw[-4:]}")


def _mini_send_admin_topic_notice(*, topic_env: str, text: str) -> bool:
    chat_id = _mini_parse_env_int("ADMIN_FORUM_CHAT_ID")
    topic_id = _mini_parse_env_int(topic_env)
    if chat_id is None or topic_id is None:
        log.warning("mini admin topic notice skipped: missing %s or ADMIN_FORUM_CHAT_ID", topic_env)
        return False

    sent = _mini_send_topic_message(chat_id=int(chat_id), topic_id=int(topic_id), text=str(text), parse_mode="HTML")
    if not sent:
        log.warning("mini admin topic notice failed: topic_env=%s chat_id=%s topic_id=%s", topic_env, chat_id, topic_id)
    return bool(sent)


def _mini_notify_admin_deposit_pending(*, db: Session, dr: DepositRequest) -> bool:
    user = db.get(User, int(dr.user_id))
    destination_id, destination_title = _read_request_destination(db, request_id=int(dr.id))
    dest_line = html_escape(str(destination_title or destination_id or "-"))

    text = (
        "?? <b>??????? ????? ???? ?? Mini App</b>\n"
        "#????? #????_?? #???????_????\n"
        f"?? ????? ???????: <b>{int(dr.id)}</b>\n"
        f"?? ?????: {_mini_user_title(user, user_id=int(dr.user_id))}\n"
        f"?? ????: <b>{_mini_fmt_toman(dr.amount)}</b>\n"
        f"?? ????: <b>{dest_line}</b>\n"
        f"?? ????: <b>{'????? ???' if bool(dr.receipt_path or dr.receipt_file_id) else '?????'}</b>\n"
        f"?? ?????: <b>{html_escape(str(dr.status))}</b>\n\n"
        "???? ?????? ??? ?????? ????????? ?? Mini App ?? ??? ??."
    )
    return _mini_send_admin_topic_notice(topic_env="ADMIN_TOPIC_DEPOSIT_ID", text=text)


def _mini_notify_admin_withdraw_pending(*, db: Session, wr: WithdrawRequest) -> bool:
    user = db.get(User, int(wr.user_id))
    wallet_balance_raw = db.execute(
        select(Wallet.balance).where(Wallet.user_id == int(wr.user_id))
    ).scalar_one_or_none()
    wallet_balance = int(wallet_balance_raw or 0)

    text = (
        "?? <b>??????? ?????? ???? ?? Mini App</b>\n"
        "#?????? #????_?? #???????_????\n"
        f"?? ????? ??????: <b>{int(wr.id)}</b>\n"
        f"?? ?????: {_mini_user_title(user, user_id=int(wr.user_id))}\n"
        f"?? ????: <b>{_mini_fmt_toman(wr.amount)}</b>\n"
        f"?? ?????? ??? ???: <b>{_mini_fmt_toman(wallet_balance)}</b>\n"
        f"?? ??? ???? ????: <b>{html_escape(str(wr.full_name or '-'))}</b>\n"
        f"?? ????: <code>{_mini_mask_card(wr.card_number)}</code>\n"
        f"?? ???: <code>{html_escape(str(wr.iban or '-'))}</code>\n"
        f"?? ?????: <b>{html_escape(str(wr.status))}</b>\n\n"
        "???? ?????? ??? ?????? ????????? ?? Mini App ?? ??? ??."
    )
    return _mini_send_admin_topic_notice(topic_env="ADMIN_TOPIC_WITHDRAW_ID", text=text)


def _mini_send_game_created_notice(*, game: Game) -> bool:
    group_id = int(getattr(game, "tg_group_id", 0) or 0)
    if group_id == 0:
        return False

    game_topic_id = int(game.tg_topic_id) if getattr(game, "tg_topic_id", None) is not None else None
    game_topic_title = _mini_game_topic_title(game_topic_id)
    text = (
        "\U0001F4E3 <b>\u0628\u0627\u0632\u06cc \u062c\u062f\u06cc\u062f \u0622\u0645\u0627\u062f\u0647 \u062e\u0631\u06cc\u062f</b>\n"
        "#\u0627\u0637\u0644\u0627\u0639\u06cc\u0647 #\u0628\u0627\u0632\u06cc_\u062c\u062f\u06cc\u062f\n"
        f"\U0001F3AE \u0628\u0627\u0632\u06cc: <b>#{int(game.id)}</b>\n"
        f"\U0001F9F5 \u062f\u0633\u062a\u0647 \u0628\u0627\u0632\u06cc: <b>{game_topic_title}</b>\n"
        f"\U0001F4B3 \u0642\u06CC\u0645\u062A \u0647\u0631 \u06A9\u0627\u0631\u062A: <b>{int(game.card_price):,}</b> \u062A\u0648\u0645\u0627\u0646\n"
        "\U0001F6D2 \u062E\u0631\u06CC\u062F \u06A9\u0627\u0631\u062A \u0628\u0631\u0627\u06CC \u0627\u06CC\u0646 \u0628\u0627\u0632\u06CC \u0628\u0627\u0632 \u0627\u0633\u062A."
    )

    sent_any = False
    sent_keys: set[tuple[int, int | None]] = set()
    targets: list[tuple[int, int | None]] = []
    targets.append((group_id, game_topic_id))

    announce_topic_id = _mini_parse_optional_topic_id(os.getenv("USER_TOPIC_ANNOUNCE_ID"))
    if announce_topic_id is not None:
        targets.append((group_id, announce_topic_id))

    for chat_id, topic_id in targets:
        key = (int(chat_id), int(topic_id) if topic_id is not None else None)
        if key in sent_keys:
            continue
        sent_keys.add(key)
        if _mini_send_topic_message(chat_id=int(chat_id), topic_id=topic_id, text=text):
            sent_any = True

    if not sent_any:
        log.warning(
            "mini game created announcement not sent (game_id=%s, group_id=%s, topic_id=%s)",
            int(game.id),
            group_id,
            game_topic_id,
        )
    return bool(sent_any)


def _mini_latest_lobby_closed_payload(db: Session, *, game_id: int) -> dict[str, Any]:
    ev = (
        db.execute(
            select(GameEvent)
            .where(
                GameEvent.game_id == int(game_id),
                GameEvent.kind == "GAME_LOBBY_CLOSED",
            )
            .order_by(GameEvent.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if ev is None or not isinstance(ev.payload_json, dict):
        return {}
    payload = dict(ev.payload_json)
    return payload if isinstance(payload, dict) else {}


def _mini_notify_lobby_cancel_refunds(
    db: Session,
    *,
    game_id: int,
    cancel_reason: str,
) -> dict[str, int]:
    marker_key = f"mini_lobby_refund_notice_sent:{int(game_id)}"
    marker = _setting_get_json(db, marker_key)
    if isinstance(marker, dict) and bool(marker.get("sent")):
        return {
            "notified_ok": int(marker.get("notified_ok", 0) or 0),
            "notify_failed": int(marker.get("notify_failed", 0) or 0),
            "no_tg_count": int(marker.get("no_tg_count", 0) or 0),
            "refund_total": int(marker.get("refund_total", 0) or 0),
            "refund_users_count": int(marker.get("refund_users_count", 0) or 0),
        }

    payload = _mini_latest_lobby_closed_payload(db, game_id=int(game_id))
    refunds_raw = payload.get("refunds")
    refunds = refunds_raw if isinstance(refunds_raw, list) else []

    reason_text = str(cancel_reason or "").strip() or str(payload.get("cancel_reason") or "").strip()
    reason_html = html_escape(reason_text) if reason_text else "بدون توضیح"

    notified_ok = 0
    notify_failed = 0
    no_tg_count = 0
    refund_total = 0
    refund_users_count = 0

    for item in refunds:
        if not isinstance(item, dict):
            continue
        amount = int(item.get("amount") or 0)
        purchase_count = int(item.get("purchase_count") or 0)
        if amount <= 0 and purchase_count <= 0:
            continue

        refund_users_count += 1
        refund_total += max(0, int(amount))

        tg_user_id = int(item.get("tg_user_id") or 0)
        if tg_user_id <= 0:
            no_tg_count += 1
            continue

        text = (
            "\U0001F7E6 <b>\u067e\u06cc\u0645\u0648\u0646 \u062f\u0648\u0631\u0646\u0627 | \u06a9\u0646\u0633\u0644 \u0628\u0627\u0632\u06cc</b>\n\n"
            f"\U0001F3AE \u0628\u0627\u0632\u06cc: <b>#{int(game_id)}</b>\n"
            f"\U0001F4DD \u0639\u0644\u062a \u06a9\u0646\u0633\u0644: <b>{reason_html}</b>\n"
            f"\U0001F0CF \u062a\u0639\u062f\u0627\u062f \u06a9\u0627\u0631\u062a \u0634\u0645\u0627: <b>{int(purchase_count)}</b>\n"
            f"\U0001F4B0 \u0645\u0628\u0644\u063a \u0628\u0631\u06af\u0634\u062a\u06cc \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644: <b>{int(amount):,}</b> \u062a\u0648\u0645\u0627\u0646\n\n"
            "\u2705 \u0645\u0628\u0644\u063a \u0628\u0647 \u06a9\u06cc\u0641 \u067e\u0648\u0644 \u0634\u0645\u0627 \u0628\u0631\u06af\u0634\u062a \u062f\u0627\u062f\u0647 \u0634\u062f."
        )

        delivered = False
        for _ in range(3):
            if _mini_send_topic_message(chat_id=int(tg_user_id), topic_id=None, text=text):
                delivered = True
                break

        if delivered:
            notified_ok += 1
        else:
            notify_failed += 1

    _setting_set_json(
        db,
        marker_key,
        {
            "sent": True,
            "sent_at": datetime.utcnow().isoformat(timespec="seconds"),
            "notified_ok": int(notified_ok),
            "notify_failed": int(notify_failed),
            "no_tg_count": int(no_tg_count),
            "refund_total": int(refund_total),
            "refund_users_count": int(refund_users_count),
        },
    )

    return {
        "notified_ok": int(notified_ok),
        "notify_failed": int(notify_failed),
        "no_tg_count": int(no_tg_count),
        "refund_total": int(refund_total),
        "refund_users_count": int(refund_users_count),
    }


def _mini_mark_created_event_notice_sent(db: Session, *, game_id: int, sent: bool) -> None:
    if not sent:
        return
    ev = (
        db.execute(
            select(GameEvent)
            .where(
                GameEvent.game_id == int(game_id),
                GameEvent.kind == "GAME_CREATED",
            )
            .order_by(GameEvent.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if ev is None:
        return

    payload = ev.payload_json if isinstance(ev.payload_json, dict) else {}
    payload = dict(payload)
    payload["mini_created_notice_sent"] = True
    payload["mini_created_notice_source"] = "mini_api"
    ev.payload_json = payload
    db.add(ev)


def _mini_find_active_game(
    db: Session,
    *,
    tg_group_id: int,
    tg_topic_id: int | None,
) -> Game | None:
    q = (
        select(Game)
        .where(
            Game.tg_group_id == int(tg_group_id),
            Game.status.in_(["LOBBY", "RUNNING"]),
        )
        .order_by(Game.id.desc())
        .limit(1)
    )
    if tg_topic_id is None:
        q = q.where(Game.tg_topic_id.is_(None))
    else:
        q = q.where(Game.tg_topic_id == int(tg_topic_id))
    return db.execute(q).scalar_one_or_none()


def _mini_role_id_map(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Role.name, Role.id).where(Role.name.in_(ADMIN_ROLE_NAMES))
    ).all()
    out = {str(name): int(role_id) for name, role_id in rows}
    for needed in ADMIN_ROLE_NAMES:
        if needed not in out:
            raise HTTPException(status_code=500, detail=f"role '{needed}' is not seeded")
    return out


def _mini_super_admin_count(db: Session, role_ids: dict[str, int]) -> int:
    rows = db.execute(
        select(UserRole.user_id).where(UserRole.role_id == int(role_ids["SUPER_ADMIN"]))
    ).scalars().all()
    return len({int(uid) for uid in rows})


def _mini_get_or_create_user_by_tg(db: Session, tg_user_id: int) -> User:
    user = db.execute(
        select(User).where(User.tg_user_id == int(tg_user_id))
    ).scalar_one_or_none()
    if user:
        return user
    user = User(tg_user_id=int(tg_user_id))
    db.add(user)
    db.flush()
    return user


def _mini_admin_account_items(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            User.id,
            User.tg_user_id,
            User.username,
            User.first_name,
            User.last_name,
            Role.name,
        )
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name.in_(ADMIN_ROLE_NAMES))
        .order_by(User.id.asc(), Role.name.asc())
    ).all()
    grouped: dict[int, dict[str, Any]] = {}
    for user_id, tg_user_id, username, first_name, last_name, role_name in rows:
        uid = int(user_id)
        rec = grouped.get(uid)
        if rec is None:
            rec = {
                "user_id": uid,
                "tg_user_id": int(tg_user_id) if tg_user_id is not None else None,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "roles": set(),
            }
            grouped[uid] = rec
        rec["roles"].add(str(role_name))

    items = []
    for rec in grouped.values():
        items.append(
            {
                "user_id": int(rec["user_id"]),
                "tg_user_id": int(rec["tg_user_id"]) if rec["tg_user_id"] is not None else None,
                "username": rec["username"],
                "first_name": rec["first_name"],
                "last_name": rec["last_name"],
                "roles": sorted(rec["roles"]),
            }
        )
    return items


@router.post("/auth/exchange", response_model=MiniAuthExchangeOut)
def exchange_auth(
    payload: MiniAuthExchangeIn,
    db: Session = Depends(get_db),
    x_tg_init_data: str | None = Header(default=None, alias=TELEGRAM_INITDATA_HEADER),
):
    init_data = str(payload.init_data or x_tg_init_data or "").strip()
    result = exchange_init_data_for_session(init_data, db)
    db.commit()
    return MiniAuthExchangeOut(**result)


@router.get("/games", response_model=MiniGameListOut)
def list_games(
    status: str | None = Query(default="LOBBY|RUNNING"),
    tg_group_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    _ = user_id
    statuses = _parse_status_filter(status)
    where = [Game.status.in_(statuses)]
    if tg_group_id is not None:
        where.append(Game.tg_group_id == int(tg_group_id))

    total = db.execute(
        select(func.count()).select_from(Game).where(*where)
    ).scalar_one()

    rows = (
        db.execute(
            select(Game)
            .where(*where)
            .order_by(Game.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        .scalars()
        .all()
    )
    items = [_to_game_out(g) for g in rows]
    return MiniGameListOut(total=int(total or 0), limit=int(limit), offset=int(offset), items=items)


@router.get("/dashboard/insights", response_model=MiniDashboardInsightsOut)
def dashboard_insights(
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    now_local = datetime.now()
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    win_recent_since = now_local - timedelta(hours=24)

    hot_threshold_cards = 10

    active_hot = (
        db.execute(
            select(Game)
            .where(Game.status.in_(["LOBBY", "RUNNING"]))
            .order_by(Game.sold_amount.desc(), Game.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    hot_game_id: int | None = None
    if active_hot and int(active_hot.card_price or 0) > 0:
        sold_cards = int(active_hot.sold_amount) // int(active_hot.card_price)
        if sold_cards >= int(hot_threshold_cards):
            hot_game_id = int(active_hot.id)

    recent_rows = (
        db.execute(
            select(Game)
            .where(Game.status == "ENDED")
            .order_by(Game.id.desc())
            .limit(5)
        )
        .scalars()
        .all()
    )

    recent_games: list[MiniRecentGameStatOut] = []
    for g in recent_rows:
        payout_state = g.payout_state_json if isinstance(g.payout_state_json, dict) else {}
        row_winner_ids = set(_winner_ids_from_payload_state(payout_state, "row"))
        col_winner_ids = set(_winner_ids_from_payload_state(payout_state, "col"))
        all_winners = set(row_winner_ids)
        all_winners.update(col_winner_ids)

        row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
        col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}

        row_prize_total = int(getattr(g, "row_prize_amount", 0) or 0)
        col_prize_total = int(getattr(g, "col_prize_amount", 0) or 0)
        row_payout_total = int(_safe_int(row_info.get("amount_total", 0), 0))
        col_payout_total = int(_safe_int(col_info.get("amount_total", 0), 0))
        if row_prize_total <= 0 and row_payout_total > 0:
            row_prize_total = row_payout_total
        if col_prize_total <= 0 and col_payout_total > 0:
            col_prize_total = col_payout_total

        sold_cards = 0
        if int(g.card_price or 0) > 0:
            sold_cards = int(g.sold_amount) // int(g.card_price)

        row_winners_count = len(row_winner_ids)
        if row_winners_count <= 0:
            row_winners_count = _safe_user_count(row_info.get("winner_user_ids"))
        if row_winners_count <= 0 and row_prize_total > 0:
            row_winners_count = 1

        col_winners_count = len(col_winner_ids)
        if col_winners_count <= 0:
            col_winners_count = _safe_user_count(col_info.get("winner_user_ids"))
        if col_winners_count <= 0 and col_prize_total > 0:
            col_winners_count = 1

        row_winner_amount = int(row_prize_total // row_winners_count) if row_winners_count > 0 else 0
        col_winner_amount = int(col_prize_total // col_winners_count) if col_winners_count > 0 else 0

        recent_games.append(
            MiniRecentGameStatOut(
                game_id=int(g.id),
                card_price=int(g.card_price or 0),
                sold_cards=int(sold_cards),
                sold_amount=int(g.sold_amount or 0),
                commission_amount=int(g.commission_amount or 0),
                prize_pool=int(g.prize_pool),
                winners_count=int(len(all_winners)),
                col_prize_total=int(col_prize_total),
                row_prize_total=int(row_prize_total),
                col_winners_count=int(col_winners_count),
                row_winners_count=int(row_winners_count),
                col_winner_amount=int(col_winner_amount),
                row_winner_amount=int(row_winner_amount),
                win_pattern=_guess_win_pattern(row_winner_ids, col_winner_ids),
            )
        )

    prize_filters = [
        WalletTx.direction == "CREDIT",
        WalletTx.reason.in_(["PRIZE_COL", "PRIZE_ROW"]),
        WalletTx.created_at >= day_start,
    ]

    total_paid_today = db.execute(
        select(func.coalesce(func.sum(WalletTx.amount), 0))
        .select_from(WalletTx)
        .join(Wallet, Wallet.id == WalletTx.wallet_id)
        .where(*prize_filters)
    ).scalar_one()

    winners_today = db.execute(
        select(func.count(func.distinct(Wallet.user_id)))
        .select_from(WalletTx)
        .join(Wallet, Wallet.id == WalletTx.wallet_id)
        .where(*prize_filters)
    ).scalar_one()

    latest_win_row = db.execute(
        select(WalletTx, User)
        .join(Wallet, Wallet.id == WalletTx.wallet_id)
        .join(User, User.id == Wallet.user_id)
        .where(
            WalletTx.direction == "CREDIT",
            WalletTx.reason.in_(["PRIZE_COL", "PRIZE_ROW"]),
        )
        .order_by(WalletTx.id.desc())
        .limit(1)
    ).first()

    latest_win: MiniLatestWinOut | None = None
    if latest_win_row:
        tx, user = latest_win_row
        latest_win = MiniLatestWinOut(
            user_alias=_user_alias(user),
            amount=int(tx.amount),
            game_id=int(tx.ref_id) if tx.ref_id is not None else None,
            at=str(tx.created_at) if tx.created_at else None,
        )

    in_game_count = db.execute(
        select(func.count())
        .select_from(GameCard)
        .join(Game, Game.id == GameCard.game_id)
        .where(
            GameCard.user_id == int(user_id),
            Game.status.in_(["LOBBY", "RUNNING"]),
        )
    ).scalar_one()

    recent_winner_count = db.execute(
        select(func.count())
        .select_from(WalletTx)
        .join(Wallet, Wallet.id == WalletTx.wallet_id)
        .where(
            Wallet.user_id == int(user_id),
            WalletTx.direction == "CREDIT",
            WalletTx.reason.in_(["PRIZE_COL", "PRIZE_ROW"]),
            WalletTx.created_at >= win_recent_since,
        )
    ).scalar_one()

    return MiniDashboardInsightsOut(
        hot_game_id=hot_game_id,
        hot_threshold_cards=int(hot_threshold_cards),
        in_game=bool(int(in_game_count or 0) > 0),
        recent_winner=bool(int(recent_winner_count or 0) > 0),
        recent_games=recent_games,
        trust=MiniTrustStatsOut(
            total_paid_today=int(total_paid_today or 0),
            winners_today=int(winners_today or 0),
            latest_win=latest_win,
        ),
    )


@router.get("/me/cards", response_model=MiniUserCardListOut)
def list_my_cards(
    game_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    where = [GameCard.user_id == int(user_id)]
    if game_id is not None:
        where.append(GameCard.game_id == int(game_id))

    total = db.execute(
        select(func.count()).select_from(GameCard).where(*where)
    ).scalar_one()

    rows = db.execute(
        select(GameCard, Game)
        .join(Game, Game.id == GameCard.game_id)
        .where(*where)
        .order_by(GameCard.id.desc())
        .limit(int(limit))
        .offset(int(offset))
    ).all()

    items: list[MiniUserCardItemOut] = []
    for card, game in rows:
        items.append(
            MiniUserCardItemOut(
                game_id=int(card.game_id),
                card_id=int(card.id),
                fingerprint=str(card.fingerprint),
                numbers=_numbers_from_json(card.numbers_json),
                game_status=str(game.status),
                card_price=int(game.card_price),
                created_at=str(card.created_at) if card.created_at else None,
            )
        )

    return MiniUserCardListOut(
        total=int(total or 0),
        limit=int(limit),
        offset=int(offset),
        items=items,
    )


@router.get("/games/{game_id}/snapshot", response_model=MiniGameSnapshotOut)
def game_snapshot(
    game_id: int,
    events_limit: int = Query(default=20, ge=1, le=100),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    game = db.execute(select(Game).where(Game.id == int(game_id))).scalar_one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="بازی موردنظر پیدا نشد.")

    state = GameService.get_state(db, game_id=int(game_id), last_n=50)
    live_link_url, live_link_updated_at = _read_game_live_link(db, game_id=int(game_id))
    cards = GameService.get_user_cards(db, game_id=int(game_id), user_id=int(user_id))
    my_cards = [
        MiniCardOut(
            card_id=int(c["card_id"]),
            fingerprint=str(c["fingerprint"]),
            numbers=[int(x) for x in c["numbers"]],
        )
        for c in cards
    ]

    all_cards_rows = db.execute(
        select(GameCard.id, GameCard.user_id, GameCard.numbers_json).where(GameCard.game_id == int(game_id))
    ).all()
    players: set[int] = set()
    called_numbers = [int(x) for x in (state.get("called_numbers") or [])]
    called_set = set(called_numbers)
    nearest_card: dict[str, int | None] = {
        "card_id": None,
        "user_id": None,
        "called_count": 0,
        "total_numbers": 0,
        "percent": 0,
        "missing": 0,
    }

    best_missing: int | None = None
    for card_id, card_user_id, numbers_json in all_cards_rows:
        players.add(int(card_user_id))
        numbers = _numbers_from_json(numbers_json)
        total = len(numbers)
        if total <= 0:
            continue
        called_count = sum(1 for n in numbers if int(n) in called_set)
        missing = max(0, total - called_count)
        percent = int(round((called_count / total) * 100))
        if best_missing is None or missing < best_missing or (
            missing == best_missing and percent > int(nearest_card["percent"] or 0)
        ):
            best_missing = missing
            nearest_card = {
                "card_id": int(card_id),
                "user_id": int(card_user_id),
                "called_count": int(called_count),
                "total_numbers": int(total),
                "percent": int(percent),
                "missing": int(missing),
            }

    winner_user_ids = set(int(x) for x in (state.get("row_winner_user_ids") or []))
    winner_user_ids.update(int(x) for x in (state.get("col_winner_user_ids") or []))
    players_count = int(len(players))
    winners_count = int(len(winner_user_ids))
    remaining_players = max(0, players_count - winners_count)
    max_number = int(GameService._get_setting(db, GameService.KEY_MAX_NUMBER, 99))
    max_number = max(1, max_number)
    called_progress_pct = int(round((len(called_numbers) / max_number) * 100)) if called_numbers else 0

    state = dict(state)
    state.update(
        {
            "players_count": players_count,
            "sold_cards_count": int(len(all_cards_rows)),
            "my_cards_count": int(len(my_cards)),
            "winners_count": winners_count,
            "remaining_players_estimate": int(remaining_players),
            "called_count": int(len(called_numbers)),
            "called_progress_pct": int(min(100, max(0, called_progress_pct))),
            "nearest_to_win": MiniNearestToWinOut(**nearest_card).model_dump(),
            "live_link_url": live_link_url,
            "live_link_updated_at": live_link_updated_at,
        }
    )

    last_event_id = db.execute(
        select(func.coalesce(func.max(GameEvent.id), 0)).where(GameEvent.game_id == int(game_id))
    ).scalar_one()

    ev_rows = (
        db.execute(
            select(GameEvent)
            .where(GameEvent.game_id == int(game_id))
            .order_by(GameEvent.id.desc())
            .limit(int(events_limit))
        )
        .scalars()
        .all()
    )

    recent_events = [
        MiniEventOut(
            id=int(e.id),
            game_id=int(e.game_id),
            kind=str(e.kind),
            payload=e.payload_json if isinstance(e.payload_json, dict) else None,
            created_at=str(e.created_at),
        )
        for e in reversed(ev_rows)
    ]

    return MiniGameSnapshotOut(
        game=_to_game_out(game),
        state=state,
        my_cards=my_cards,
        last_event_id=int(last_event_id or 0),
        recent_events=recent_events,
    )


@router.get("/games/{game_id}/events", response_model=list[MiniEventOut])
def list_game_events(
    game_id: int,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    enforce_events_rate_limit(int(user_id))
    rows = GameEventService.list_events(db, game_id=int(game_id), after_id=int(after_id), limit=int(limit))
    return [
        MiniEventOut(
            id=int(r.id),
            game_id=int(r.game_id),
            kind=str(r.kind),
            payload=r.payload_json if isinstance(r.payload_json, dict) else None,
            created_at=str(r.created_at),
        )
        for r in rows
    ]


@router.post("/games/{game_id}/buy", response_model=MiniBuyOut)
def buy_cards(
    game_id: int,
    payload: MiniBuyIn,
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(user_id))
    purchase, _cards, prize_pool = GameService.buy_cards(
        db=db,
        game_id=int(game_id),
        user_id=int(user_id),
        qty=int(payload.qty),
        idempotency_key=str(payload.idempotency_key),
    )
    db.commit()
    return MiniBuyOut(
        game_id=int(game_id),
        purchase_id=int(purchase.id),
        qty=int(purchase.qty),
        total_price=int(purchase.total_price),
        wallet_tx_id=int(purchase.wallet_tx_id),
        prize_pool=int(prize_pool),
    )


@router.get("/me/wallet", response_model=MiniWalletOut)
def my_wallet(
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    wallet = WalletService.get_or_create_wallet(db, int(user_id))
    db.flush()
    return MiniWalletOut(
        user_id=int(user_id),
        balance=int(wallet.balance),
        updated_at=str(wallet.updated_at) if wallet.updated_at else None,
    )


@router.get("/me/wallet/txs", response_model=list[MiniWalletTxOut])
def my_wallet_txs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    wallet = db.execute(select(Wallet).where(Wallet.user_id == int(user_id))).scalar_one_or_none()
    if not wallet:
        return []

    rows = (
        db.execute(
            select(WalletTx)
            .where(WalletTx.wallet_id == int(wallet.id))
            .order_by(WalletTx.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        .scalars()
        .all()
    )
    return [
        MiniWalletTxOut(
            id=int(tx.id),
            direction=str(tx.direction),
            amount=int(tx.amount),
            reason=str(tx.reason),
            ref_type=str(tx.ref_type) if tx.ref_type else None,
            ref_id=int(tx.ref_id) if tx.ref_id is not None else None,
            created_at=str(tx.created_at),
        )
        for tx in rows
    ]


@router.get("/deposit-destinations", response_model=MiniDepositDestinationListOut)
def list_deposit_destinations(
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    _ = user_id
    pool = _deposit_destination_pool(db, include_inactive=False)
    items = [
        MiniDepositDestinationOut(
            id=str(it.get("id") or ""),
            title=str(it.get("title") or ""),
            account_name=str(it.get("account_name") or ""),
            bank_name=str(it.get("bank_name") or ""),
            iban=str(it.get("iban") or ""),
            card_number=str(it.get("card_number") or ""),
            account_number=str(it.get("account_number") or ""),
            is_active=bool(it.get("is_active", True)),
        )
        for it in pool
    ]
    return MiniDepositDestinationListOut(
        total=len(items),
        items=items,
        instructions="یکی از حساب‌های فعال را انتخاب کن و سپس درخواست واریز را ثبت کن.",
    )


@router.post("/deposits", response_model=MiniDepositOut)
def create_deposit(
    payload: MiniDepositCreateIn,
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(user_id))
    pool = _deposit_destination_pool(db, include_inactive=False)
    selected = _find_destination_by_id(pool, payload.destination_id)
    if payload.destination_id and selected is None:
        raise HTTPException(status_code=400, detail="کارت مقصد انتخابی معتبر نیست.")
    if selected is None and pool:
        selected = pool[0]

    dr = FinanceService.create_deposit_request(db, int(user_id), int(payload.amount))
    if selected is not None:
        _save_request_destination(db, request_id=int(dr.id), destination=selected)
    db.commit()

    destination_id, destination_title = _read_request_destination(db, request_id=int(dr.id))
    return MiniDepositOut(
        id=int(dr.id),
        amount=int(dr.amount),
        status=str(dr.status),
        receipt_uploaded=bool(dr.receipt_path),
        destination_id=destination_id,
        destination_title=destination_title,
        created_at=str(dr.created_at) if dr.created_at else None,
    )


@router.get("/me/deposits", response_model=MiniDepositListOut)
def list_my_deposits(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    where = [DepositRequest.user_id == int(user_id)]
    total = db.execute(select(func.count()).select_from(DepositRequest).where(*where)).scalar_one()
    rows = (
        db.execute(
            select(DepositRequest)
            .where(*where)
            .order_by(DepositRequest.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        .scalars()
        .all()
    )
    items = [
        MiniDepositOut(
            id=int(dr.id),
            amount=int(dr.amount),
            status=str(dr.status),
            receipt_uploaded=bool(dr.receipt_path),
            destination_id=_read_request_destination(db, request_id=int(dr.id))[0],
            destination_title=_read_request_destination(db, request_id=int(dr.id))[1],
            created_at=str(dr.created_at) if dr.created_at else None,
        )
        for dr in rows
    ]
    return MiniDepositListOut(total=int(total or 0), limit=int(limit), offset=int(offset), items=items)


@router.post("/deposits/{deposit_id}/receipt", response_model=MiniDepositOut)
def upload_deposit_receipt(
    deposit_id: int,
    payload: MiniDepositReceiptIn,
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(user_id))

    dr = db.execute(
        select(DepositRequest).where(
            DepositRequest.id == int(deposit_id),
            DepositRequest.user_id == int(user_id),
        )
    ).scalar_one_or_none()
    if not dr:
        raise HTTPException(status_code=404, detail="درخواست واریز پیدا نشد.")
    if str(dr.status) not in {"AWAITING_RECEIPT", "PENDING_REVIEW"}:
        raise HTTPException(status_code=400, detail="وضعیت درخواست واریز معتبر نیست.")

    content_type = str(payload.content_type or "").lower()
    if not (content_type.startswith("image/") or content_type == "application/pdf"):
        raise HTTPException(status_code=400, detail="نوع فایل رسید معتبر نیست.")

    original_name = str(payload.filename or "").strip()
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
        if content_type == "application/pdf":
            ext = ".pdf"
        elif content_type == "image/png":
            ext = ".png"
        elif content_type == "image/webp":
            ext = ".webp"
        else:
            ext = ".jpg"

    raw_b64 = str(payload.data_base64 or "").strip()
    if not raw_b64:
        raise HTTPException(status_code=400, detail="فایل رسید خالی است.")
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="فرمت فایل رسید نامعتبر است.") from exc
    if not blob:
        raise HTTPException(status_code=400, detail="فایل رسید خالی است.")
    if len(blob) > 6 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="حجم فایل رسید بیش از حد مجاز است.")

    receipt_dir = Path(RECEIPTS_DIR)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    dest = receipt_dir / f"mini_{int(deposit_id)}_{uuid4().hex}{ext}"

    with dest.open("wb") as out:
        out.write(blob)

    dr.receipt_path = str(dest.resolve())
    dr.receipt_file_id = None
    dr.status = "PENDING_REVIEW"
    db.flush()
    db.commit()
    _mini_notify_admin_deposit_pending(db=db, dr=dr)

    return MiniDepositOut(
        id=int(dr.id),
        amount=int(dr.amount),
        status=str(dr.status),
        receipt_uploaded=True,
        destination_id=_read_request_destination(db, request_id=int(dr.id))[0],
        destination_title=_read_request_destination(db, request_id=int(dr.id))[1],
        created_at=str(dr.created_at) if dr.created_at else None,
    )


@router.post("/withdraws", response_model=MiniWithdrawOut)
def create_withdraw(
    payload: MiniWithdrawCreateIn,
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(user_id))
    body = payload.model_dump()
    body["user_id"] = int(user_id)
    wr = FinanceService.create_withdraw_request(db, body)
    _setting_set_json(
        db,
        _withdraw_source_setting_key(int(wr.id)),
        {"source": "mini"},
    )
    db.commit()
    _mini_notify_admin_withdraw_pending(db=db, wr=wr)

    return MiniWithdrawOut(
        id=int(wr.id),
        amount=int(wr.amount),
        status=str(wr.status),
        created_at=str(wr.created_at) if wr.created_at else None,
    )


@router.get("/me/withdraws", response_model=MiniWithdrawListOut)
def list_my_withdraws(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: int = Depends(get_mini_user_id),
    db: Session = Depends(get_db),
):
    where = [WithdrawRequest.user_id == int(user_id)]
    total = db.execute(select(func.count()).select_from(WithdrawRequest).where(*where)).scalar_one()
    rows = (
        db.execute(
            select(WithdrawRequest)
            .where(*where)
            .order_by(WithdrawRequest.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        .scalars()
        .all()
    )
    items = [
        MiniWithdrawOut(
            id=int(wr.id),
            amount=int(wr.amount),
            status=str(wr.status),
            created_at=str(wr.created_at) if wr.created_at else None,
        )
        for wr in rows
    ]
    return MiniWithdrawListOut(total=int(total or 0), limit=int(limit), offset=int(offset), items=items)


# ==================== MINI ADMIN ====================

@router.get("/admin/me", response_model=MiniAdminMeOut)
def mini_admin_me(
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
):
    return MiniAdminMeOut(
        user_id=int(ident.user_id),
        tg_user_id=int(ident.tg_user_id) if ident.tg_user_id is not None else None,
        scope=str(ident.scope),
        roles=list(ident.roles),
        is_admin=bool(ident.is_admin),
        is_super_admin=bool(ident.is_super_admin),
    )


@router.get("/admin/users/search")
def mini_admin_users_search(
    tg_user_id: int | None = Query(default=None),
    username: str | None = Query(default=None),
    game_id: int | None = Query(default=None),
    deposit_id: int | None = Query(default=None),
    withdraw_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    return admin_users_router.admin_user_search(
        tg_user_id=tg_user_id,
        username=username,
        game_id=game_id,
        deposit_id=deposit_id,
        withdraw_id=withdraw_id,
        limit=int(limit),
        _=_mini_to_admin_identity(ident),
        db=db,
    )


@router.get("/admin/users/{tg_user_id}/profile")
def mini_admin_user_profile(
    tg_user_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    return admin_users_router.admin_user_profile(
        tg_user_id=int(tg_user_id),
        _=_mini_to_admin_identity(ident),
        db=db,
    )


@router.get("/admin/users/{tg_user_id}/financial-history")
def mini_admin_user_financial_history(
    tg_user_id: int,
    limit: int = Query(default=30, ge=1, le=200),
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    return admin_users_router.admin_user_financial_history(
        tg_user_id=int(tg_user_id),
        limit=int(limit),
        _=_mini_to_admin_identity(ident),
        db=db,
    )


@router.get("/admin/users/{tg_user_id}/games-history")
def mini_admin_user_games_history(
    tg_user_id: int,
    limit: int = Query(default=30, ge=1, le=200),
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    return admin_users_router.admin_user_games_history(
        tg_user_id=int(tg_user_id),
        limit=int(limit),
        _=_mini_to_admin_identity(ident),
        db=db,
    )


@router.post("/admin/users/{tg_user_id}/restrict")
def mini_admin_user_restrict(
    tg_user_id: int,
    payload: admin_users_router.RestrictIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(ident.user_id))
    return admin_users_router.admin_user_restrict(
        tg_user_id=int(tg_user_id),
        payload=payload,
        admin=_mini_to_admin_identity(ident),
        db=db,
    )


@router.post("/admin/users/{tg_user_id}/unrestrict")
def mini_admin_user_unrestrict(
    tg_user_id: int,
    payload: admin_users_router.UnrestrictIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(ident.user_id))
    return admin_users_router.admin_user_unrestrict(
        tg_user_id=int(tg_user_id),
        payload=payload,
        admin=_mini_to_admin_identity(ident),
        db=db,
    )


@router.post("/admin/users/{tg_user_id}/wallet-adjust")
def mini_admin_user_wallet_adjust(
    tg_user_id: int,
    payload: admin_users_router.WalletAdjustIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(ident.user_id))
    return admin_users_router.admin_user_wallet_adjust(
        tg_user_id=int(tg_user_id),
        payload=payload,
        admin=_mini_to_admin_identity(ident),
        db=db,
    )


@router.post("/admin/users/{tg_user_id}/notify")
def mini_admin_user_notify(
    tg_user_id: int,
    payload: admin_users_router.NotifyIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(ident.user_id))
    return admin_users_router.admin_user_notify(
        tg_user_id=int(tg_user_id),
        payload=payload,
        _=_mini_to_admin_identity(ident),
        db=db,
    )


@router.post("/admin/users/{tg_user_id}/compose-message")
def mini_admin_user_compose_message(
    tg_user_id: int,
    payload: admin_users_router.ComposeIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    return admin_users_router.admin_user_compose_message(
        tg_user_id=int(tg_user_id),
        payload=payload,
        _=_mini_to_admin_identity(ident),
        db=db,
    )


@router.get("/admin/games/create-options", response_model=MiniAdminCreateOptionsOut)
def mini_admin_create_options(
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
):
    _ = ident
    topics = [
        MiniAdminCreateTopicOut(key=key, title=title, topic_id=int(topic_id))
        for key, title, topic_id in _mini_configured_game_topics()
    ]
    return MiniAdminCreateOptionsOut(
        group_id=_mini_default_group_id(),
        topics=topics,
        enforce_topic=bool(topics),
    )


@router.get("/admin/games")
def mini_admin_games(
    status: str | None = Query(default="LOBBY|RUNNING"),
    tg_group_id: int | None = Query(default=None),
    limit: int = Query(default=40, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    statuses = _parse_status_filter(status)
    where = [Game.status.in_(statuses)]
    if tg_group_id is not None:
        where.append(Game.tg_group_id == int(tg_group_id))
    if not ident.is_super_admin:
        where.append(Game.admin_user_id == int(ident.user_id))

    total = db.execute(
        select(func.count()).select_from(Game).where(*where)
    ).scalar_one()
    rows = (
        db.execute(
            select(Game)
            .where(*where)
            .order_by(Game.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        .scalars()
        .all()
    )
    items: list[dict[str, Any]] = []
    for g in rows:
        url, updated_at = _read_game_live_link(db, game_id=int(g.id))
        item = _to_game_out(g).model_dump()
        item["admin_user_id"] = int(g.admin_user_id)
        item["can_manage"] = bool(ident.is_super_admin or int(g.admin_user_id) == int(ident.user_id))
        item["live_link_url"] = url
        item["live_link_updated_at"] = updated_at
        items.append(item)

    return {
        "total": int(total or 0),
        "limit": int(limit),
        "offset": int(offset),
        "items": items,
    }


@router.post("/admin/games/create")
def mini_admin_create_game(
    payload: MiniAdminCreateGameIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    idem_key = str(payload.idempotency_key or "").strip()
    if len(idem_key) < 6:
        raise HTTPException(status_code=400, detail="کلید یکتای عملیات نامعتبر است.")

    # app_settings.k is intentionally short in production; keep this idempotency key below the DB column limit.
    idem_digest = hashlib.sha256(idem_key.encode("utf-8")).hexdigest()[:40]
    idem_setting_key = f"mini_acg:{idem_digest}"
    existing = _setting_get_json(db, idem_setting_key)
    if isinstance(existing, dict):
        game_id_raw = existing.get("game_id")
        try:
            game_id = int(game_id_raw)
        except Exception:
            game_id = 0
        if game_id > 0:
            g = db.execute(select(Game).where(Game.id == game_id)).scalar_one_or_none()
            if g is not None:
                return {
                    "ok": True,
                    "game": _to_game_out(g),
                    "idempotent": True,
                    "reused_active": bool(existing.get("reused_active", False)),
                    "requested_card_price": int(payload.card_price),
                }

    source_game = None
    if payload.source_game_id is not None:
        source_game = _mini_require_game_manage_access(db, int(payload.source_game_id), ident)

    tg_group_id = payload.tg_group_id
    if tg_group_id is None and source_game is not None:
        tg_group_id = int(source_game.tg_group_id)
    if tg_group_id is None:
        tg_group_id = _mini_default_group_id()
    if tg_group_id is None:
        raise HTTPException(
            status_code=400,
            detail="شناسه گروه بازی مشخص نیست. مقدار USER_FORUM_CHAT_ID یا DEFAULT_TG_GROUP_ID را تنظیم کنید.",
        )
    # Telegram supergroup/chat IDs are usually negative; only zero is invalid.
    if int(tg_group_id) == 0:
        raise HTTPException(status_code=400, detail="شناسه گروه بازی نامعتبر است.")

    tg_topic_id = payload.tg_topic_id
    if tg_topic_id is None and source_game is not None and source_game.tg_topic_id is not None:
        tg_topic_id = int(source_game.tg_topic_id)
    if tg_topic_id is not None and int(tg_topic_id) <= 0:
        raise HTTPException(status_code=400, detail="شناسه تاپیک نامعتبر است.")

    configured_topics = _mini_configured_game_topics()
    allowed_topic_ids = {int(topic_id) for _, _, topic_id in configured_topics}
    if source_game is None and allowed_topic_ids:
        if tg_topic_id is None:
            raise HTTPException(status_code=400, detail="ابتدا یکی از تاپیک‌های بازی را انتخاب کنید.")
        if int(tg_topic_id) not in allowed_topic_ids:
            raise HTTPException(status_code=400, detail="این تاپیک در تنظیمات ربات برای بازی تعریف نشده است.")

    card_price = int(payload.card_price)
    if card_price <= 0:
        raise HTTPException(status_code=400, detail="مبلغ کارت باید بیشتر از صفر باشد.")

    active = _mini_find_active_game(
        db,
        tg_group_id=int(tg_group_id),
        tg_topic_id=int(tg_topic_id) if tg_topic_id is not None else None,
    )
    if active is not None:
        _setting_set_json(
            db,
            idem_setting_key,
            {"game_id": int(active.id), "created_by": int(ident.user_id), "reused_active": True},
        )
        db.commit()
        return {
            "ok": True,
            "game": _to_game_out(active),
            "idempotent": False,
            "reused_active": True,
            "requested_card_price": int(card_price),
        }

    g = GameService.create_game(
        db=db,
        admin_user_id=int(ident.user_id),
        tg_group_id=int(tg_group_id),
        tg_topic_id=int(tg_topic_id) if tg_topic_id is not None else None,
        card_price=int(card_price),
    )
    db.flush()
    _setting_set_json(
        db,
        idem_setting_key,
        {"game_id": int(g.id), "created_by": int(ident.user_id), "reused_active": False},
    )
    db.commit()
    db.refresh(g)
    notice_sent = False
    try:
        notice_sent = _mini_send_game_created_notice(game=g)
    except Exception:
        log.exception("failed to send mini game-created announcement for game_id=%s", int(g.id))
    try:
        _mini_mark_created_event_notice_sent(db, game_id=int(g.id), sent=bool(notice_sent))
        if notice_sent:
            db.commit()
    except Exception:
        log.exception("failed to mark mini game-created notice flag for game_id=%s", int(g.id))
    return {
        "ok": True,
        "game": _to_game_out(g),
        "idempotent": False,
        "reused_active": False,
        "requested_card_price": int(card_price),
    }


@router.post("/admin/games/{game_id}/start")
def mini_admin_start_game(
    game_id: int,
    payload: MiniAdminActionIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    game = GameService.start_game(
        db=db,
        game_id=int(game_id),
        admin_user_id=int(ident.user_id),
        idempotency_key=str(payload.idempotency_key),
    )
    db.commit()
    db.refresh(game)
    return {"ok": True, "game": _to_game_out(game)}


@router.post("/admin/games/{game_id}/call")
def mini_admin_call_number(
    game_id: int,
    payload: MiniAdminCallIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    out = GameService.call_number(
        db=db,
        game_id=int(game_id),
        number=int(payload.number),
        admin_user_id=int(ident.user_id),
        idempotency_key=str(payload.idempotency_key),
    )
    db.commit()
    return {"ok": True, "result": out}


@router.post("/admin/games/{game_id}/undo-last-call")
def mini_admin_undo_call(
    game_id: int,
    payload: MiniAdminActionIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    out = GameService.undo_last_call(
        db=db,
        game_id=int(game_id),
        admin_user_id=int(ident.user_id),
        idempotency_key=str(payload.idempotency_key),
    )
    db.commit()
    return {"ok": True, "result": out}


@router.post("/admin/games/{game_id}/close-lobby")
def mini_admin_close_lobby(
    game_id: int,
    payload: MiniAdminCloseLobbyIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    cancel_reason = str(payload.cancel_reason or "").strip()
    game = GameService.close_lobby_game(
        db=db,
        game_id=int(game_id),
        admin_user_id=int(ident.user_id),
        idempotency_key=str(payload.idempotency_key),
        cancel_reason=cancel_reason,
    )
    notify_stats = {
        "notified_ok": 0,
        "notify_failed": 0,
        "no_tg_count": 0,
        "refund_total": 0,
        "refund_users_count": 0,
    }
    try:
        notify_stats = _mini_notify_lobby_cancel_refunds(
            db,
            game_id=int(game_id),
            cancel_reason=cancel_reason,
        )
    except Exception:
        log.exception("failed to notify users for lobby-close refunds game_id=%s", int(game_id))

    db.commit()
    db.refresh(game)
    return {"ok": True, "game": _to_game_out(game), "refund_notify": notify_stats}


@router.get("/admin/games/{game_id}/live-link")
def mini_admin_get_live_link(
    game_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    url, updated_at = _read_game_live_link(db, game_id=int(game_id))
    participants_count = db.execute(
        select(func.count(func.distinct(GameCard.user_id))).where(GameCard.game_id == int(game_id))
    ).scalar_one()
    return {
        "game_id": int(game_id),
        "url": url,
        "updated_at": updated_at,
        "participants_count": int(participants_count or 0),
    }


@router.put("/admin/games/{game_id}/live-link")
def mini_admin_set_live_link(
    game_id: int,
    payload: MiniAdminLiveLinkIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    url = _normalize_live_url(payload.url)
    now = datetime.utcnow().isoformat(timespec="seconds")
    _setting_set_json(
        db,
        _game_live_link_setting_key(int(game_id)),
        {
            "url": url,
            "updated_by": int(ident.user_id),
            "updated_at": now,
        },
    )
    db.commit()
    return {"ok": True, "game_id": int(game_id), "url": url, "updated_at": now}


@router.post("/admin/games/{game_id}/live-link/send")
def mini_admin_send_live_link(
    game_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = _mini_require_game_manage_access(db, int(game_id), ident)
    url, updated_at = _read_game_live_link(db, game_id=int(game_id))
    if not url:
        raise HTTPException(status_code=400, detail="live_url is required")

    rows = db.execute(
        select(
            User.id,
            User.tg_user_id,
            func.count(GameCard.id).label("cards_count"),
        )
        .select_from(GameCard)
        .join(User, User.id == GameCard.user_id)
        .where(GameCard.game_id == int(game_id))
        .group_by(User.id, User.tg_user_id)
    ).all()

    participants_count = len(rows)
    notified_ok = 0
    notify_failed = 0
    no_tg_count = 0
    failed_tg_ids: list[int] = []

    safe_url = html_escape(str(url), quote=True)
    for row in rows:
        tg_user_id = int(row.tg_user_id or 0)
        cards_count = int(row.cards_count or 0)
        if tg_user_id <= 0:
            no_tg_count += 1
            continue

        text = (
            "🎥 <b>لینک پخش زنده بازی آماده است</b>\n\n"
            f"🎮 بازی: <b>#{int(game_id)}</b>\n"
            f"🃏 تعداد کارت‌های شما در این بازی: <b>{cards_count}</b>\n\n"
            "برای مشاهده پخش زنده روی لینک زیر بزنید:\n"
            f'<a href="{safe_url}">مشاهده پخش زنده بازی #{int(game_id)}</a>\n\n'
            "این لینک فقط برای بازیکنانی ارسال شده که در همین بازی کارت خریداری کرده‌اند."
        )

        delivered = False
        for _ in range(3):
            if _mini_send_topic_message(chat_id=tg_user_id, topic_id=None, text=text):
                delivered = True
                break

        if delivered:
            notified_ok += 1
        else:
            notify_failed += 1
            if len(failed_tg_ids) < 10:
                failed_tg_ids.append(tg_user_id)

    return {
        "ok": True,
        "game_id": int(game_id),
        "url": str(url),
        "updated_at": updated_at,
        "participants_count": int(participants_count),
        "notified_ok": int(notified_ok),
        "notify_failed": int(notify_failed),
        "no_tg_count": int(no_tg_count),
        "failed_tg_ids": failed_tg_ids,
    }


@router.delete("/admin/games/{game_id}/live-link")
def mini_admin_clear_live_link(
    game_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _mini_require_game_manage_access(db, int(game_id), ident)
    now = datetime.utcnow().isoformat(timespec="seconds")
    _setting_set_json(
        db,
        _game_live_link_setting_key(int(game_id)),
        {
            "url": "",
            "updated_by": int(ident.user_id),
            "updated_at": now,
        },
    )
    db.commit()
    return {"ok": True, "game_id": int(game_id), "url": None, "updated_at": now}


@router.get("/admin/deposits")
def mini_admin_list_deposits(
    status: str | None = Query(default="PENDING_REVIEW"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    query = (
        select(DepositRequest, User)
        .join(User, User.id == DepositRequest.user_id)
        .order_by(DepositRequest.id.desc())
    )
    if status:
        s = str(status).strip().upper()
        if s != "ALL":
            query = query.where(DepositRequest.status == s)

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()
    rows = db.execute(query.limit(int(limit)).offset(int(offset))).all()

    items: list[dict[str, Any]] = []
    for dr, user in rows:
        destination_id, destination_title = _read_request_destination(db, request_id=int(dr.id))
        items.append(
            {
                "id": int(dr.id),
                "user_id": int(dr.user_id),
                "tg_user_id": int(user.tg_user_id) if user and user.tg_user_id is not None else None,
                "tg_username": str(user.username) if user and user.username else None,
                "amount": int(dr.amount),
                "status": str(dr.status),
                "receipt_uploaded": bool(dr.receipt_path or dr.receipt_file_id),
                "receipt_url": f"/mini-api/admin/deposits/{int(dr.id)}/receipt",
                "destination_id": destination_id,
                "destination_title": destination_title,
                "created_at": str(dr.created_at) if dr.created_at else None,
            }
        )

    return {"total": int(total or 0), "limit": int(limit), "offset": int(offset), "items": items}


@router.get("/admin/deposits/{deposit_id}/receipt")
def mini_admin_get_deposit_receipt(
    deposit_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    dr = db.execute(
        select(DepositRequest).where(DepositRequest.id == int(deposit_id))
    ).scalar_one_or_none()
    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")
    p = Path(str(dr.receipt_path or "")).expanduser()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="receipt file not found")
    return FileResponse(str(p.resolve()))


@router.post("/admin/deposits/{deposit_id}/approve")
def mini_admin_approve_deposit(
    deposit_id: int,
    payload: MiniAdminDepositApproveIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    dr, tx = FinanceService.approve_deposit(
        db=db,
        deposit_id=int(deposit_id),
        admin_user_id=int(ident.user_id),
        idempotency_key=str(payload.idempotency_key),
    )
    db.commit()
    return {"ok": True, "deposit_id": int(dr.id), "status": str(dr.status), "wallet_tx_id": int(tx.id)}


@router.post("/admin/deposits/{deposit_id}/reject")
def mini_admin_reject_deposit(
    deposit_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    dr = FinanceService.reject_deposit(
        db=db,
        deposit_id=int(deposit_id),
        admin_user_id=int(ident.user_id),
    )
    db.commit()
    return {"ok": True, "deposit_id": int(dr.id), "status": str(dr.status)}


@router.get("/admin/withdraws")
def mini_admin_list_withdraws(
    status: str | None = Query(default="PENDING|APPROVED"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    query = (
        select(WithdrawRequest, User)
        .join(User, User.id == WithdrawRequest.user_id)
        .order_by(WithdrawRequest.id.desc())
    )

    raw = str(status or "").strip().upper().replace(",", "|")
    if raw and raw != "ALL":
        allowed = {"PENDING", "APPROVED", "PAID", "REJECTED"}
        selected = [x.strip() for x in raw.split("|") if x.strip()]
        for s in selected:
            if s not in allowed:
                raise HTTPException(status_code=400, detail=f"invalid withdraw status: {s}")
        if selected:
            query = query.where(WithdrawRequest.status.in_(selected))

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()
    rows = db.execute(query.limit(int(limit)).offset(int(offset))).all()

    items: list[dict[str, Any]] = []
    for wr, user in rows:
        items.append(
            {
                "id": int(wr.id),
                "user_id": int(wr.user_id),
                "tg_user_id": int(user.tg_user_id) if user and user.tg_user_id is not None else None,
                "tg_username": str(user.username) if user and user.username else None,
                "amount": int(wr.amount),
                "status": str(wr.status),
                "full_name": str(wr.full_name),
                "card_number": str(wr.card_number),
                "iban": str(wr.iban or ""),
                "account_number": str(wr.account_number or ""),
                "paid_tracking": str(wr.paid_tracking or ""),
                "created_at": str(wr.created_at) if wr.created_at else None,
            }
        )

    return {"total": int(total or 0), "limit": int(limit), "offset": int(offset), "items": items}


@router.get("/admin/withdraws/{withdraw_id}/wallet-status")
def mini_admin_withdraw_wallet_status(
    withdraw_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    wr = db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == int(withdraw_id))
    ).scalar_one_or_none()
    if not wr:
        raise HTTPException(status_code=404, detail="withdraw_request not found")

    user = db.get(User, int(wr.user_id))
    wallet_balance_raw = db.execute(
        select(Wallet.balance).where(Wallet.user_id == int(wr.user_id))
    ).scalar_one_or_none()
    wallet_balance = int(wallet_balance_raw or 0)

    pending_total_raw = db.execute(
        select(func.coalesce(func.sum(WithdrawRequest.amount), 0)).where(
            WithdrawRequest.user_id == int(wr.user_id),
            WithdrawRequest.status == "PENDING",
        )
    ).scalar_one()
    pending_total = int(pending_total_raw or 0)

    pending_other_raw = db.execute(
        select(func.coalesce(func.sum(WithdrawRequest.amount), 0)).where(
            WithdrawRequest.user_id == int(wr.user_id),
            WithdrawRequest.status == "PENDING",
            WithdrawRequest.id != int(wr.id),
        )
    ).scalar_one()
    pending_other = int(pending_other_raw or 0)

    request_amount = int(wr.amount or 0)
    available_for_this = max(0, int(wallet_balance) - int(pending_other))
    can_approve = str(wr.status).upper() == "PENDING" and available_for_this >= request_amount

    return {
        "ok": True,
        "withdraw_id": int(wr.id),
        "user_id": int(wr.user_id),
        "tg_user_id": int(user.tg_user_id) if user and user.tg_user_id is not None else None,
        "tg_username": str(user.username) if user and user.username else None,
        "status": str(wr.status),
        "request_amount": int(request_amount),
        "wallet_balance": int(wallet_balance),
        "pending_total": int(pending_total),
        "pending_other": int(pending_other),
        "available_for_this": int(available_for_this),
        "can_approve": bool(can_approve),
    }


@router.post("/admin/withdraws/{withdraw_id}/approve")
def mini_admin_approve_withdraw(
    withdraw_id: int,
    payload: MiniAdminWithdrawApproveIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    wr, tx = FinanceService.approve_withdraw(
        db=db,
        withdraw_id=int(withdraw_id),
        admin_user_id=int(ident.user_id),
        idempotency_key=str(payload.idempotency_key),
    )
    db.commit()
    return {"ok": True, "withdraw_id": int(wr.id), "status": str(wr.status), "wallet_tx_id": int(tx.id)}


@router.post("/admin/withdraws/{withdraw_id}/proof")
def mini_admin_save_withdraw_proof(
    withdraw_id: int,
    payload: MiniAdminWithdrawProofIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    enforce_write_rate_limit(int(ident.user_id))
    wr = db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == int(withdraw_id))
    ).scalar_one_or_none()
    if not wr:
        raise HTTPException(status_code=404, detail="withdraw_request not found")
    if str(wr.status) not in {"APPROVED", "PAID"}:
        raise HTTPException(status_code=400, detail="withdraw_request not approved")

    proof_text = str(payload.proof_text or "").strip()
    filename = str(payload.filename or "").strip()
    content_type = str(payload.content_type or "").strip().lower()
    raw_b64 = str(payload.data_base64 or "").strip()

    if not proof_text and not raw_b64:
        raise HTTPException(status_code=400, detail="withdraw proof is required")

    image_path: str | None = None
    image_filename: str | None = None
    image_content_type: str | None = None

    if raw_b64:
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="withdraw proof image type is invalid")

        original_name = filename or "withdraw-proof.jpg"
        ext = os.path.splitext(original_name)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            if content_type == "image/png":
                ext = ".png"
            elif content_type == "image/webp":
                ext = ".webp"
            else:
                ext = ".jpg"

        try:
            blob = base64.b64decode(raw_b64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="withdraw proof image is invalid") from exc
        if not blob:
            raise HTTPException(status_code=400, detail="withdraw proof image is empty")
        if len(blob) > 6 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="withdraw proof image is too large")

        proof_dir = Path(RECEIPTS_DIR)
        proof_dir.mkdir(parents=True, exist_ok=True)
        dest = proof_dir / f"withdraw_paid_{int(withdraw_id)}_{uuid4().hex}{ext}"
        with dest.open("wb") as out:
            out.write(blob)

        image_path = str(dest.resolve())
        image_filename = original_name
        image_content_type = content_type

    existing = _setting_get_json(db, _withdraw_paid_proof_setting_key(int(withdraw_id)))
    if not isinstance(existing, dict):
        existing = {}

    proof = {
        "proof_text": proof_text,
        "image_path": image_path or existing.get("image_path"),
        "image_filename": image_filename or existing.get("image_filename"),
        "image_content_type": image_content_type or existing.get("image_content_type"),
        "updated_at": datetime.utcnow().isoformat(),
        "updated_by": int(ident.user_id),
    }
    _setting_set_json(db, _withdraw_paid_proof_setting_key(int(withdraw_id)), proof)
    db.commit()

    return {
        "ok": True,
        "withdraw_id": int(withdraw_id),
        "proof_text": str(proof.get("proof_text") or ""),
        "image_uploaded": bool(proof.get("image_path")),
        "image_url": f"/mini-api/admin/withdraws/{int(withdraw_id)}/proof/file" if proof.get("image_path") else None,
    }


@router.get("/admin/withdraws/{withdraw_id}/proof")
def mini_admin_get_withdraw_proof(
    withdraw_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    wr = db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == int(withdraw_id))
    ).scalar_one_or_none()
    if not wr:
        raise HTTPException(status_code=404, detail="withdraw_request not found")

    proof = _setting_get_json(db, _withdraw_paid_proof_setting_key(int(withdraw_id)))
    if not isinstance(proof, dict):
        proof = {}

    return {
        "ok": True,
        "withdraw_id": int(withdraw_id),
        "status": str(wr.status),
        "paid_tracking": str(wr.paid_tracking or ""),
        "proof_text": str(proof.get("proof_text") or ""),
        "image_uploaded": bool(proof.get("image_path")),
        "image_url": f"/mini-api/admin/withdraws/{int(withdraw_id)}/proof/file" if proof.get("image_path") else None,
        "updated_at": proof.get("updated_at"),
    }


@router.get("/admin/withdraws/{withdraw_id}/proof/file")
def mini_admin_get_withdraw_proof_file(
    withdraw_id: int,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    proof = _setting_get_json(db, _withdraw_paid_proof_setting_key(int(withdraw_id)))
    if not isinstance(proof, dict):
        raise HTTPException(status_code=404, detail="withdraw proof not found")
    p = Path(str(proof.get("image_path") or "")).expanduser()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="withdraw proof file not found")
    return FileResponse(str(p.resolve()))




def _mini_multipart_field(name: str, value: str, boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        f"{value}\r\n"
    ).encode("utf-8")


def _mini_multipart_file(
    *,
    field_name: str,
    filename: str,
    content_type: str,
    data: bytes,
    boundary: str,
) -> bytes:
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    return head + data + b"\r\n"


def _mini_image_content_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


def _mini_send_photo_message(
    *,
    chat_id: int,
    photo_path: str,
    caption: str,
    parse_mode: str = "HTML",
) -> bool:
    bot_token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token or int(chat_id or 0) <= 0:
        return False

    p = Path(str(photo_path or "")).expanduser()
    if not p.exists() or not p.is_file():
        return False

    try:
        data = p.read_bytes()
    except Exception:
        return False
    if not data:
        return False

    boundary = f"----davarna{uuid4().hex}"
    filename = p.name or "withdraw-proof.jpg"
    parts: list[bytes] = [
        _mini_multipart_field("chat_id", str(int(chat_id)), boundary),
        _mini_multipart_field("caption", str(caption), boundary),
        _mini_multipart_field("parse_mode", str(parse_mode), boundary),
        _mini_multipart_field("disable_notification", "false", boundary),
        _mini_multipart_file(
            field_name="photo",
            filename=filename,
            content_type=_mini_image_content_type(p),
            data=data,
            boundary=boundary,
        ),
        f"--{boundary}--\r\n".encode("utf-8"),
    ]

    req = urllib_request.Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=20) as resp:
            body_raw = resp.read().decode("utf-8", errors="replace")
        body = json.loads(body_raw)
        return bool(body.get("ok", False))
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    except Exception:
        return False


def _mini_send_plain_user_message(*, chat_id: int, text: str) -> bool:
    # Reuse existing backend Telegram sender if available.
    try:
        return bool(_mini_send_topic_message(chat_id=int(chat_id), topic_id=None, text=str(text)))
    except TypeError:
        try:
            return bool(_mini_send_topic_message(chat_id=int(chat_id), text=str(text)))
        except Exception:
            return False
    except Exception:
        return False


def _mini_withdraw_paid_user_message(
    *,
    withdraw_id: int,
    amount: int,
    paid_tracking: str,
    proof_text: str,
    has_image: bool,
) -> str:
    tracking_text = html_escape(str(paid_tracking or "").strip() or "-")
    proof_text_clean = html_escape(str(proof_text or "").strip())
    proof_line = f"\n🧾 متن رسید: <b>{proof_text_clean}</b>" if proof_text_clean else ""
    image_line = "\n🖼 تصویر فیش پرداخت پیوست شد." if has_image else ""
    return (
        "🟦 <b>دورنای پیمون | برداشت پرداخت شد</b>\n\n"
        f"🧾 شماره برداشت: <b>{int(withdraw_id)}</b>\n"
        f"💵 مبلغ: <b>{int(amount):,}</b> تومان\n"
        f"🔖 پیگیری پرداخت: <code>{tracking_text}</code>"
        f"{proof_line}"
        f"{image_line}\n\n"
        "✅ پرداخت برداشت شما توسط ادمین ثبت شد."
    )


def _mini_notify_withdraw_paid_to_user(
    db: Session,
    *,
    wr: WithdrawRequest,
    paid_tracking: str,
) -> dict[str, Any]:
    user = db.execute(select(User).where(User.id == int(wr.user_id))).scalar_one_or_none()
    tg_user_id = int(getattr(user, "tg_user_id", 0) or 0) if user is not None else 0
    if tg_user_id <= 0:
        return {"sent": False, "reason": "user_has_no_tg_user_id"}

    proof = _setting_get_json(db, _withdraw_paid_proof_setting_key(int(wr.id)))
    if not isinstance(proof, dict):
        proof = {}

    proof_text = str(proof.get("proof_text") or "").strip()
    image_path = str(proof.get("image_path") or "").strip()
    has_image = bool(image_path)
    text = _mini_withdraw_paid_user_message(
        withdraw_id=int(wr.id),
        amount=int(wr.amount),
        paid_tracking=str(paid_tracking or wr.paid_tracking or ""),
        proof_text=proof_text,
        has_image=has_image,
    )

    sent = False
    sent_kind = "text"

    if has_image:
        sent = _mini_send_photo_message(
            chat_id=int(tg_user_id),
            photo_path=image_path,
            caption=text,
        )
        sent_kind = "photo"
        if not sent:
            fallback_text = text + "\n\n⚠️ تصویر فیش در سیستم ثبت شد، اما ارسال تصویر به تلگرام ناموفق بود."
            sent = _mini_send_plain_user_message(chat_id=int(tg_user_id), text=fallback_text)
            sent_kind = "text_fallback"

    if not has_image:
        sent = _mini_send_plain_user_message(chat_id=int(tg_user_id), text=text)
        sent_kind = "text"

    return {
        "sent": bool(sent),
        "kind": sent_kind,
        "tg_user_id": int(tg_user_id),
        "has_image": bool(has_image),
    }


@router.post("/admin/withdraws/{withdraw_id}/paid")
def mini_admin_paid_withdraw(
    withdraw_id: int,
    payload: MiniAdminWithdrawPaidIn,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    wr = FinanceService.mark_withdraw_paid(
        db=db,
        withdraw_id=int(withdraw_id),
        admin_user_id=int(ident.user_id),
        paid_tracking=str(payload.paid_tracking),
    )
    db.flush()

    notify_result = _mini_notify_withdraw_paid_to_user(
        db,
        wr=wr,
        paid_tracking=str(payload.paid_tracking),
    )

    db.commit()
    return {
        "ok": True,
        "withdraw_id": int(wr.id),
        "status": str(wr.status),
        "paid_tracking": str(wr.paid_tracking or ""),
        "user_notify": notify_result,
    }

@router.post("/admin/withdraws/{withdraw_id}/reject")
def mini_admin_reject_withdraw(
    withdraw_id: int,
    payload: MiniAdminWithdrawRejectIn | None = None,
    ident: MiniAdminIdentity = Depends(get_mini_admin_identity),
    db: Session = Depends(get_db),
):
    wr = FinanceService.reject_withdraw(
        db=db,
        withdraw_id=int(withdraw_id),
        admin_user_id=int(ident.user_id),
        reason=str((payload.reason if payload else "") or "").strip() or None,
    )
    db.commit()
    return {"ok": True, "withdraw_id": int(wr.id), "status": str(wr.status)}


@router.get("/admin/super/admins")
def mini_super_admin_list(
    ident: MiniAdminIdentity = Depends(get_mini_super_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    items = _mini_admin_account_items(db)
    return {"total": len(items), "items": items}


@router.post("/admin/super/admins/grant")
def mini_super_admin_grant(
    payload: MiniSuperGrantIn,
    ident: MiniAdminIdentity = Depends(get_mini_super_admin_identity),
    db: Session = Depends(get_db),
):
    _ = ident
    role_ids = _mini_role_id_map(db)
    role_id = int(role_ids[str(payload.role)])
    user = _mini_get_or_create_user_by_tg(db, int(payload.tg_user_id))
    exists = db.execute(
        select(UserRole)
        .where(UserRole.user_id == int(user.id))
        .where(UserRole.role_id == int(role_id))
    ).scalar_one_or_none()
    if exists is None:
        db.add(UserRole(user_id=int(user.id), role_id=int(role_id)))
        db.flush()
    db.commit()
    items = _mini_admin_account_items(db)
    item = next((x for x in items if int(x.get("tg_user_id") or 0) == int(payload.tg_user_id)), None)
    return {"ok": True, "item": item}


@router.post("/admin/super/admins/revoke")
def mini_super_admin_revoke(
    payload: MiniSuperRevokeIn,
    ident: MiniAdminIdentity = Depends(get_mini_super_admin_identity),
    db: Session = Depends(get_db),
):
    role_ids = _mini_role_id_map(db)
    user = db.execute(
        select(User).where(User.tg_user_id == int(payload.tg_user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if payload.role == "ALL":
        target_role_ids = [int(role_ids["ADMIN"]), int(role_ids["SUPER_ADMIN"])]
    else:
        target_role_ids = [int(role_ids[str(payload.role)])]

    user_role_rows = db.execute(
        select(UserRole.role_id)
        .where(UserRole.user_id == int(user.id))
        .where(UserRole.role_id.in_(target_role_ids))
    ).scalars().all()
    role_set = {int(x) for x in user_role_rows}
    if not role_set:
        return {"ok": True, "removed": 0, "user_id": int(user.id), "tg_user_id": int(user.tg_user_id)}

    removing_super = int(role_ids["SUPER_ADMIN"]) in role_set
    if removing_super:
        if int(ident.user_id) == int(user.id):
            raise HTTPException(status_code=409, detail="cannot revoke your own super admin role")
        if _mini_super_admin_count(db, role_ids) <= 1:
            raise HTTPException(status_code=409, detail="cannot revoke last super admin")

    res = db.execute(
        delete(UserRole)
        .where(UserRole.user_id == int(user.id))
        .where(UserRole.role_id.in_(list(role_set)))
    )
    db.commit()
    return {
        "ok": True,
        "removed": int(res.rowcount or 0),
        "user_id": int(user.id),
        "tg_user_id": int(user.tg_user_id),
    }
