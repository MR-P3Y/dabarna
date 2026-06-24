from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request # type: ignore
from sqlalchemy.orm import Session # type: ignore
from sqlalchemy import select, text, func # type: ignore
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from fastapi.responses import FileResponse
import json
import os
import hashlib
from uuid import uuid4
from urllib.parse import urlparse

from app.core.db import get_db
from app.core import config as cfg
from app.core.config import (
    BOT_SERVICE_TOKEN,
    DEPOSIT_CARD_NUMBER,
    DEPOSIT_OWNER_NAME,
    DEPOSIT_BANK_NAME,
    DEPOSIT_IBAN,
    DEPOSIT_ACCOUNT_NUMBER,
    DEPOSIT_DESTINATIONS,
    DEPOSIT_DESTINATION_SALT,
    RBAC_OWNER_USER_ID,
    RECEIPTS_DIR,
)
from app.core.admin_guard import get_admin_identity, AdminIdentity, AdminScope
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.finance import WithdrawRequest, DepositRequest
from app.models.crypto import CryptoDepositRequest
from app.models.game import Game, GameCard, GamePurchase
from app.models.settings import AppSetting
from app.services.user_service import UserService
from app.services.finance_service import FinanceService
from app.services.game_service import GameService
from app.services.telegram_file_service import download_telegram_file
from app.services.admin_audit_service import AdminAuditService
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_health_service import CryptoHealthService
from app.services.crypto_reconciliation_service import CryptoReconciliationService
from app.schemas.crypto import (
    CryptoAdminRejectIn,
    CryptoDepositCreateIn,
    CryptoTxClaimIn,
    crypto_deposit_dict,
)

router = APIRouter(prefix="/bot", tags=["bot"])
_RECEIPT_HASH_CACHE: dict[str, tuple[float, str]] = {}


# ==================== Auth Dependencies ====================

def require_bot_token(x_bot_token: Optional[str] = Header(None)) -> str:
    """Verify X-Bot-Token header"""
    if not x_bot_token:
        raise HTTPException(status_code=401, detail="missing X-Bot-Token header")

    x_bot_token = x_bot_token.strip()
    if not BOT_SERVICE_TOKEN or x_bot_token != BOT_SERVICE_TOKEN:
        raise HTTPException(status_code=403, detail="invalid bot token")

    return x_bot_token


def get_bot_user(
    x_tg_user_id: Optional[str] = Header(None),
    x_tg_username: Optional[str] = Header(None),
    token: str = Depends(require_bot_token),
    db: Session = Depends(get_db),
) -> User:
    """Get or create Telegram user"""
    if not x_tg_user_id:
        raise HTTPException(status_code=400, detail="missing X-Tg-User-Id header")

    try:
        tg_user_id = int(x_tg_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid X-Tg-User-Id format")

    # Get or create user
    user = UserService.upsert(
        db=db,
        tg_user_id=tg_user_id,
        username=x_tg_username.strip() if x_tg_username else None,
    )

    return user


def _parse_bot_game_statuses(status: Optional[str]) -> list[str]:
    """
    Bot-facing statuses:
    - LOBBY
    - ACTIVE (mapped to RUNNING in DB)
    - RUNNING (also accepted)
    - ENDED
    """
    default_status = "LOBBY|ACTIVE"
    raw = (status or default_status).upper().replace(",", "|")
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if not parts:
        parts = ["LOBBY", "ACTIVE"]

    mapping = {
        "LOBBY": "LOBBY",
        "ACTIVE": "RUNNING",
        "RUNNING": "RUNNING",
        "ENDED": "ENDED",
    }
    normalized: list[str] = []
    for p in parts:
        if p not in mapping:
            raise HTTPException(status_code=400, detail=f"invalid status: {p}")
        mapped = mapping[p]
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _parse_admin_game_statuses(status: Optional[str]) -> list[str]:
    if status is None:
        return []

    raw = status.strip().upper().replace(",", "|")
    if not raw:
        return []

    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if not parts:
        return []

    mapping = {
        "LOBBY": "LOBBY",
        "RUNNING": "RUNNING",
        "ACTIVE": "RUNNING",
        "ENDED": "ENDED",
    }

    normalized: list[str] = []
    for p in parts:
        if p not in mapping:
            raise HTTPException(status_code=400, detail=f"invalid status: {p}")
        mapped = mapping[p]
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _as_str_datetime(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat(sep=" ", timespec="seconds")
    return str(v)


def _as_json_dict(v: Any) -> dict[str, Any] | None:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            loaded = json.loads(s)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return None
    return None


def _as_json_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        try:
            loaded = json.loads(s)
            if isinstance(loaded, list):
                return loaded
        except Exception:
            return []
    return []


def _row_paid_from_payload(raw: Any) -> int:
    payload = _as_json_dict(raw)
    if not payload:
        return 0
    try:
        return int(payload.get("row_paid", 0) or 0)
    except Exception:
        return 0


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    out: list[int] = []
    for v in values:
        try:
            out.append(int(v))
        except Exception:
            continue
    return out


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


def _require_admin_user_id(admin: AdminIdentity) -> int:
    if admin.user_id is None:
        raise HTTPException(status_code=403, detail="forbidden")
    return int(admin.user_id)


def _require_super_admin_owner(admin: AdminIdentity) -> int:
    if admin.scope != AdminScope.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="super admin required")
    if RBAC_OWNER_USER_ID is None:
        raise HTTPException(status_code=503, detail="rbac owner is not configured")
    if admin.user_id is None or int(admin.user_id) != int(RBAC_OWNER_USER_ID):
        raise HTTPException(status_code=403, detail="super admin owner required")
    return int(admin.user_id)


def _get_game_or_404(db: Session, game_id: int) -> Game:
    g = db.execute(select(Game).where(Game.id == game_id)).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="game not found")
    return g


def _require_game_admin_access(db: Session, game_id: int, admin: AdminIdentity) -> Game:
    game = _get_game_or_404(db, game_id)
    if admin.scope == AdminScope.SUPER_ADMIN:
        return game
    admin_uid = _require_admin_user_id(admin)
    if int(game.admin_user_id) != int(admin_uid):
        raise HTTPException(status_code=403, detail="only game admin can manage live link")
    return game


def _parse_date_or_datetime(raw: Optional[str], *, end_of_day: bool = False) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            if end_of_day:
                return d.replace(hour=23, minute=59, second=59, microsecond=999999)
            return d
        except Exception:
            raise HTTPException(status_code=400, detail=f"invalid date filter: {raw}")
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    raise HTTPException(status_code=400, detail=f"invalid date filter: {raw}")


def _sha256_file(path: str | None) -> str | None:
    if not path:
        return None
    p = str(path).strip()
    if not p or not os.path.exists(p):
        return None
    try:
        mtime = os.path.getmtime(p)
    except Exception:
        return None

    cached = _RECEIPT_HASH_CACHE.get(p)
    if cached and cached[0] == mtime:
        return cached[1]

    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
    except Exception:
        return None

    digest = h.hexdigest()
    _RECEIPT_HASH_CACHE[p] = (mtime, digest)
    return digest


def _deposit_receipt_duplicate_meta(db: Session, dr: DepositRequest) -> tuple[str | None, list[int]]:
    own_hash = _sha256_file(getattr(dr, "receipt_path", None))
    if not own_hash:
        return None, []

    rows = db.execute(
        select(DepositRequest.id, DepositRequest.receipt_path)
        .where(
            DepositRequest.id != dr.id,
            DepositRequest.receipt_path.is_not(None),
        )
    ).all()

    dup_ids: list[int] = []
    for rid, rpath in rows:
        if _sha256_file(str(rpath) if rpath is not None else None) == own_hash:
            dup_ids.append(int(rid))

    dup_ids.sort(reverse=True)
    return own_hash, dup_ids


DEPOSIT_DESTINATIONS_SETTING_KEY = "deposit_destinations"
DEPOSIT_REQUEST_DESTINATION_KEY_PREFIX = "deposit_request_destination:"
WITHDRAW_REQUEST_SOURCE_KEY_PREFIX = "withdraw_request_source:"
GAME_LIVE_LINK_KEY_PREFIX = "game_live_link:"


def _single_destination_fallback() -> dict[str, str]:
    return {
        "account_name": str(DEPOSIT_OWNER_NAME or "").strip(),
        "bank_name": str(DEPOSIT_BANK_NAME or "").strip(),
        "iban": str(DEPOSIT_IBAN or "").strip(),
        "card_number": str(DEPOSIT_CARD_NUMBER or "").strip(),
        "account_number": str(DEPOSIT_ACCOUNT_NUMBER or "").strip(),
    }


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


def _withdraw_request_source_setting_key(request_id: int) -> str:
    return f"{WITHDRAW_REQUEST_SOURCE_KEY_PREFIX}{int(request_id)}"


def _read_withdraw_request_source(db: Session, request_id: int) -> str | None:
    raw = _setting_get_json(db, _withdraw_request_source_setting_key(int(request_id)))
    if isinstance(raw, dict):
        source = str(raw.get("source") or "").strip().lower()
        return source or None
    if isinstance(raw, str):
        source = str(raw).strip().lower()
        return source or None
    return None


def _normalize_destination_payload(
    payload: dict[str, object],
    *,
    idx: int,
    fallback_id: str | None = None,
) -> dict[str, object]:
    card_number = _clean_numeric(payload.get("card_number"))
    if not card_number or (not card_number.isdigit()) or len(card_number) < 16 or len(card_number) > 19:
        raise HTTPException(status_code=400, detail="invalid destination card_number")

    dest_id = str(payload.get("id") or "").strip()
    if not dest_id:
        dest_id = str(fallback_id or f"dst_{idx + 1}").strip()
    if len(dest_id) > 64:
        raise HTTPException(status_code=400, detail="destination_id is too long")

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
        single = _single_destination_fallback()
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


def _generate_destination_id(existing: set[str]) -> str:
    while True:
        cand = f"dst_{uuid4().hex[:8]}"
        if cand not in existing:
            return cand


def _request_destination_setting_key(request_id: int) -> str:
    return f"{DEPOSIT_REQUEST_DESTINATION_KEY_PREFIX}{int(request_id)}"


def _game_live_link_setting_key(game_id: int) -> str:
    return f"{GAME_LIVE_LINK_KEY_PREFIX}{int(game_id)}"


def _save_request_destination(db: Session, *, request_id: int, destination: dict[str, object]) -> None:
    payload = {
        "destination_id": str(destination.get("id") or "").strip(),
        "snapshot": destination,
    }
    _setting_set_json(db, _request_destination_setting_key(request_id), payload)


def _legacy_pick_destination(
    *,
    request_id: int,
    user_id: int,
    db: Session,
) -> tuple[dict[str, object], int | None, int]:
    pool = _deposit_destination_pool(db, include_inactive=False)
    if not pool:
        raise HTTPException(status_code=503, detail="deposit destination is not configured")
    seed = f"{int(request_id)}:{int(user_id)}:{DEPOSIT_DESTINATION_SALT}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    idx = int(digest[:16], 16) % len(pool)
    return pool[idx], int(idx + 1), int(len(pool))


def _resolve_request_destination(
    *,
    db: Session,
    request_id: int,
    user_id: int,
) -> tuple[dict[str, object], int | None, int]:
    raw = _setting_get_json(db, _request_destination_setting_key(request_id))
    configured_pool = _deposit_destination_pool(db, include_inactive=True)
    configured_count = int(len(configured_pool))
    if isinstance(raw, dict):
        payload = {str(k): v for k, v in raw.items()}
        snap = payload.get("snapshot")
        if isinstance(snap, dict):
            try:
                normalized_snapshot = _normalize_destination_payload(
                    {str(k): v for k, v in snap.items()},
                    idx=0,
                    fallback_id=str(payload.get("destination_id") or ""),
                )
                slot = None
                sid = str(normalized_snapshot.get("id") or "")
                for i, item in enumerate(configured_pool):
                    if str(item.get("id") or "") == sid:
                        slot = int(i + 1)
                        break
                return normalized_snapshot, slot, configured_count
            except HTTPException:
                pass

    return _legacy_pick_destination(request_id=request_id, user_id=user_id, db=db)


def _destination_as_out(item: dict[str, object]) -> "DepositDestinationOut":
    return DepositDestinationOut(
        id=str(item.get("id") or ""),
        title=str(item.get("title") or ""),
        account_name=str(item.get("account_name") or ""),
        bank_name=str(item.get("bank_name") or ""),
        iban=str(item.get("iban") or ""),
        card_number=str(item.get("card_number") or ""),
        account_number=str(item.get("account_number") or ""),
        is_active=bool(item.get("is_active", True)),
    )


# ==================== Schemas ====================

class BotUserOut(BaseModel):
    id: int
    tg_user_id: int
    username: Optional[str] = None

    class Config:
        from_attributes = True


class WalletTxOut(BaseModel):
    id: int
    direction: str
    amount: int
    reason: str
    ref_type: str | None = None
    ref_id: int | None = None
    idempotency_key: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class WalletOut(BaseModel):
    balance: int
    updated_at: str
    transactions: Optional[list[WalletTxOut]] = None

    class Config:
        from_attributes = True


class CreateWithdrawRequestIn(BaseModel):
    amount: int
    full_name: str
    iban: str | None = None
    card_number: str
    account_number: str | None = None
    idempotency_key: str = Field(min_length=6)


class WithdrawRequestOut(BaseModel):
    id: int
    amount: int
    status: str
    created_at: str

    class Config:
        from_attributes = True


class CreateDepositRequestIn(BaseModel):
    amount: int
    destination_id: str | None = None


class DepositDestinationOut(BaseModel):
    id: str = ""
    title: str = ""
    account_name: str
    bank_name: str
    iban: str
    card_number: str
    account_number: str
    is_active: bool = True


class DepositDestinationListOut(BaseModel):
    mode: str = "USER_SELECT"
    total: int
    items: list[DepositDestinationOut]
    instructions: str | None = None


class AdminDepositDestinationIn(BaseModel):
    title: str = Field(min_length=2, max_length=64)
    account_name: str = Field(min_length=2, max_length=96)
    bank_name: str = Field(min_length=2, max_length=64)
    card_number: str = Field(min_length=16, max_length=19)
    iban: str | None = Field(default="", max_length=34)
    account_number: str | None = Field(default="", max_length=32)
    is_active: bool = True


class DepositRequestOut(BaseModel):
    id: int
    amount: int
    status: str
    created_at: str
    destination: DepositDestinationOut | None = None
    destination_slot: int | None = None
    destination_count: int | None = None
    receipt_hash: str | None = None
    duplicate_of_ids: list[int] = Field(default_factory=list)
    is_duplicate_receipt: bool = False

    class Config:
        from_attributes = True


class BotGameOut(BaseModel):
    id: int
    title: str
    status: str
    card_price: int
    tg_group_id: int
    tg_topic_id: int | None = None
    prize_pool: int
    sold_amount: int
    created_at: str

    class Config:
        from_attributes = True


class BotAdminGameOut(BaseModel):
    id: int
    tg_group_id: int
    tg_topic_id: int | None = None
    admin_user_id: int
    status: str
    card_price: int
    sold_amount: int
    commission_amount: int
    prize_pool: int
    prize_locked: int
    col_prize_amount: int
    row_prize_amount: int
    col_paid: int
    row_paid: int
    row_winner_user_id: int | None = None
    created_at: str

    class Config:
        from_attributes = True


class BotAdminGameListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[BotAdminGameOut]


class BotAdminStartIn(BaseModel):
    idempotency_key: str = Field(min_length=6)


class BotAdminCallIn(BaseModel):
    number: int = Field(ge=1)
    idempotency_key: str = Field(min_length=6)


class BotAdminCallOut(BaseModel):
    game_id: int
    number: int
    called_count: int
    col_paid: int
    row_paid: int
    row_winner_user_ids: list[int] | None = None
    row_winner_card_ids: list[int] | None = None


class BotAdminUndoIn(BaseModel):
    idempotency_key: str = Field(min_length=6)


class BotAdminUndoOut(BaseModel):
    game_id: int
    undone_number: int
    called_count: int
    status: str
    col_paid: int
    row_paid: int
    row_winner_user_ids: list[int] | None = None
    row_winner_card_ids: list[int] | None = None


class BotAdminStatusIn(BaseModel):
    status: str
    idempotency_key: str = Field(min_length=6)
    cancel_reason: str | None = Field(default=None, min_length=3, max_length=500)


class BotAdminGameReportGameOut(BaseModel):
    id: int
    tg_group_id: int
    tg_topic_id: int | None = None
    admin_user_id: int
    admin_tg_user_id: int | None = None
    status: str
    card_price: int
    sold_amount: int
    commission_amount: int
    prize_pool: int
    prize_locked: int
    col_prize_amount: int
    row_prize_amount: int
    col_paid: int
    row_paid: int
    col_winner_user_ids: list[int] = Field(default_factory=list)
    col_winner_tg_user_ids: list[int] = Field(default_factory=list)
    col_winner_card_ids: list[int] = Field(default_factory=list)
    row_winner_user_ids: list[int] = Field(default_factory=list)
    row_winner_tg_user_ids: list[int] = Field(default_factory=list)
    row_winner_card_ids: list[int] = Field(default_factory=list)
    payout_state_json: dict[str, Any] | None = None
    row_winner_user_id: int | None = None
    created_at: str


class BotAdminGamePurchaseStatsOut(BaseModel):
    purchases_count: int
    cards_sold: int
    sales_total: int


class BotAdminCalledNumberOut(BaseModel):
    number: int
    called_by: int
    created_at: str


class BotAdminGameEventOut(BaseModel):
    id: int
    kind: str
    idem_key: str | None = None
    actor_user_id: int | None = None
    tg_group_id: int | None = None
    payload_json: dict[str, Any] | None = None
    created_at: str


class BotAdminWinnerCardOut(BaseModel):
    card_id: int
    user_id: int
    tg_user_id: int | None = None
    numbers: list[int] = Field(default_factory=list)


class BotAdminReportOut(BaseModel):
    game: BotAdminGameReportGameOut
    purchases: BotAdminGamePurchaseStatsOut
    called_numbers: list[BotAdminCalledNumberOut]
    events: list[BotAdminGameEventOut]
    winner_cards: list[BotAdminWinnerCardOut] = Field(default_factory=list)


class BotAdminGameLiveLinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=512)


class BotAdminGameLiveLinkOut(BaseModel):
    game_id: int
    url: str | None = None
    updated_by: int | None = None
    updated_at: str | None = None
    participants_count: int = 0


class BotAdminGameParticipantOut(BaseModel):
    user_id: int
    tg_user_id: int | None = None
    tg_username: str | None = None
    cards_count: int
    purchases_count: int
    total_paid: int = 0


class BotPurchaseCardsIn(BaseModel):
    game_id: int
    quantity: int
    idempotency_key: str


class BotPurchaseCardsOut(BaseModel):
    order_id: int
    total_amount: int
    wallet_balance: int
    cards_created: int
    game_id: int
    wallet_tx_id: int

    class Config:
        from_attributes = True


class UploadReceiptIn(BaseModel):
    receipt_file_id: str

class AdminDepositRequestOut(BaseModel):
    id: int
    user_id: int
    tg_user_id: int | None = None
    tg_username: str | None = None
    amount: int
    status: str
    receipt_file_id: Optional[str] = None
    receipt_url: str | None = None
    created_at: str
    destination: DepositDestinationOut | None = None
    destination_slot: int | None = None
    destination_count: int | None = None
    receipt_hash: str | None = None
    duplicate_of_ids: list[int] = Field(default_factory=list)
    is_duplicate_receipt: bool = False


    class Config:
        from_attributes = True


class AdminWithdrawRequestOut(BaseModel):
    id: int
    user_id: int
    tg_user_id: int | None = None
    tg_username: str | None = None
    request_source: str | None = None
    amount: int
    status: str
    full_name: str
    iban: str
    card_number: str
    account_number: str
    paid_tracking: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class ApproveDepositIn(BaseModel):
    idempotency_key: str


class ApproveWithdrawIn(BaseModel):
    idempotency_key: str = Field(min_length=6)


class MarkWithdrawPaidIn(BaseModel):
    paid_tracking: str = Field(min_length=3, max_length=128)


class RejectWithdrawIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class ManualChargeIn(BaseModel):
    telegram_user_id: int
    amount: int
    reason: str = "manual_charge"


def _to_bot_admin_game_out(g: Game) -> BotAdminGameOut:
    return BotAdminGameOut(
        id=int(g.id),
        tg_group_id=int(g.tg_group_id),
        tg_topic_id=int(g.tg_topic_id) if getattr(g, "tg_topic_id", None) is not None else None,
        admin_user_id=int(g.admin_user_id),
        status=str(g.status),
        card_price=int(g.card_price),
        sold_amount=int(g.sold_amount),
        commission_amount=int(g.commission_amount),
        prize_pool=int(g.prize_pool),
        prize_locked=int(g.prize_locked),
        col_prize_amount=int(g.col_prize_amount),
        row_prize_amount=int(g.row_prize_amount),
        col_paid=int(g.col_paid),
        row_paid=int(_row_paid_from_payload(g.payout_state_json)),
        row_winner_user_id=int(g.row_winner_user_id) if g.row_winner_user_id is not None else None,
        created_at=_as_str_datetime(g.created_at),
    )


# ==================== POST /bot/sync-user ====================

@router.post("/sync-user", response_model=BotUserOut)
def sync_user(
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Sync/get Telegram user with bot service token.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID
    - X-Tg-Username: telegram username (optional)

    Returns: User info
    """
    db.commit()
    return user


# ==================== GET /bot/wallet ====================

@router.get("/wallet", response_model=WalletOut)
def get_wallet(
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """
    Get wallet balance and recent transactions.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID

    Query params:
    - limit: max transactions to return (default 50)
    - offset: pagination offset (default 0)

    Returns: Wallet with balance and transactions
    """
    wallet = db.execute(
        select(Wallet).where(Wallet.user_id == user.id)
    ).scalar_one_or_none()

    if not wallet:
        # Create wallet if doesn't exist
        wallet = Wallet(user_id=user.id, balance=0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)

    # Load recent transactions
    txs = db.execute(
        select(WalletTx)
        .where(WalletTx.wallet_id == wallet.id)
        .order_by(WalletTx.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    # Convert transactions to schema
    transactions = [
        WalletTxOut(
            id=tx.id,
            direction=tx.direction,
            amount=tx.amount,
            reason=tx.reason,
            ref_type=str(tx.ref_type) if tx.ref_type else None,
            ref_id=int(tx.ref_id) if tx.ref_id is not None else None,
            idempotency_key=str(tx.idempotency_key) if tx.idempotency_key else None,
            created_at=str(tx.created_at) if tx.created_at else "",
        )
        for tx in txs
    ]

    return WalletOut(
        balance=wallet.balance,
        updated_at=str(wallet.updated_at) if wallet.updated_at else "",
        transactions=transactions,
    )


# ==================== POST /bot/withdraw-requests ====================

@router.post("/withdraw-requests", response_model=WithdrawRequestOut)
def create_withdraw_request(
    payload: CreateWithdrawRequestIn,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Create a new withdraw request.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID

    Body:
    {
        "amount": 10000,
        "full_name": "John Doe",
        "iban": "IR1234567890",
        "card_number": "6370123456789012",
        "account_number": "1234567890"
    }

    Returns: Withdraw request with PENDING status
    """
    try:
        request_payload = payload.model_dump()
        request_payload["user_id"] = int(user.id)
        wr = FinanceService.create_withdraw_request(db, request_payload)
        db.commit()
        db.refresh(wr)

        return WithdrawRequestOut(
            id=wr.id,
            amount=wr.amount,
            status=wr.status,
            created_at=str(wr.created_at) if wr.created_at else "",
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"withdraw create failed: {str(e)}")


# ==================== Crypto deposits ====================


@router.get("/crypto/options")
def bot_crypto_options(
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    _ = user
    status = CryptoDepositService.runtime_status(db)
    return {
        "enabled": bool(status["enabled"]),
        "min_toman_amount": int(cfg.CRYPTO_MIN_TOMAN_AMOUNT),
        "max_toman_amount": int(cfg.CRYPTO_MAX_TOMAN_AMOUNT),
        "invoice_expire_minutes": int(cfg.CRYPTO_INVOICE_EXPIRE_MINUTES),
        "daily_user_max_count": int(cfg.CRYPTO_DAILY_USER_MAX_COUNT),
        "daily_user_max_toman": int(cfg.CRYPTO_DAILY_USER_MAX_TOMAN),
        "options": list(status["options"]) if bool(status["enabled"]) else [],
    }


@router.post("/crypto/deposits")
def bot_create_crypto_deposit(
    payload: CryptoDepositCreateIn,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    try:
        invoice = CryptoDepositService.create_invoice(
            db,
            user_id=int(user.id),
            amount_toman=int(payload.amount_toman),
            network=payload.network,
        )
        db.commit()
        db.refresh(invoice)
        return crypto_deposit_dict(
            invoice,
            tg_user_id=int(user.tg_user_id),
            tg_username=user.username,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="صدور فاکتور ارز دیجیتال ناموفق بود.")


@router.get("/crypto/deposits")
def bot_list_crypto_deposits(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    rows = CryptoDepositService.list_owned(
        db,
        user_id=int(user.id),
        limit=int(limit),
        offset=int(offset),
    )
    return {
        "items": [
            crypto_deposit_dict(
                row,
                tg_user_id=int(user.tg_user_id),
                tg_username=user.username,
            )
            for row in rows
        ]
    }


@router.get("/crypto/deposits/{invoice_id}")
def bot_get_crypto_deposit(
    invoice_id: int,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    invoice = CryptoDepositService.get_owned(
        db,
        invoice_id=int(invoice_id),
        user_id=int(user.id),
    )
    return crypto_deposit_dict(
        invoice,
        tg_user_id=int(user.tg_user_id),
        tg_username=user.username,
    )


@router.post("/crypto/deposits/{invoice_id}/tx-hash")
def bot_claim_crypto_tx_hash(
    invoice_id: int,
    payload: CryptoTxClaimIn,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    try:
        invoice = CryptoDepositService.claim_tx_hash(
            db,
            invoice_id=int(invoice_id),
            user_id=int(user.id),
            tx_hash=payload.tx_hash,
        )
        db.commit()
        db.refresh(invoice)
        return crypto_deposit_dict(
            invoice,
            tg_user_id=int(user.tg_user_id),
            tg_username=user.username,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="ثبت هش تراکنش ناموفق بود.")


@router.get("/admin/crypto-deposits")
def bot_admin_list_crypto_deposits(
    status: str | None = Query(default="NEEDS_REVIEW"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = admin
    query = (
        select(CryptoDepositRequest, User)
        .join(User, User.id == CryptoDepositRequest.user_id)
    )
    if status:
        query = query.where(CryptoDepositRequest.status == str(status).strip().upper())
    rows = db.execute(
        query.order_by(CryptoDepositRequest.id.desc()).offset(int(offset)).limit(int(limit))
    ).all()
    return {
        "items": [
            crypto_deposit_dict(
                invoice,
                tg_user_id=int(user.tg_user_id),
                tg_username=user.username,
            )
            for invoice, user in rows
        ]
    }


@router.get("/admin/crypto-deposits/{invoice_id}")
def bot_admin_get_crypto_deposit(
    invoice_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = admin
    row = db.execute(
        select(CryptoDepositRequest, User)
        .join(User, User.id == CryptoDepositRequest.user_id)
        .where(CryptoDepositRequest.id == int(invoice_id))
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="فاکتور واریز ارز دیجیتال پیدا نشد.")
    invoice, user = row
    return crypto_deposit_dict(
        invoice,
        tg_user_id=int(user.tg_user_id),
        tg_username=user.username,
    )


@router.post("/admin/crypto-deposits/{invoice_id}/approve")
def bot_admin_approve_crypto_deposit(
    invoice_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        invoice, tx = CryptoDepositService.approve_review(db, invoice_id=int(invoice_id))
        invoice.admin_notified_at = datetime.utcnow()
        AdminAuditService.record(
            db,
            admin=admin,
            action="crypto.deposit.approve",
            target_type="crypto_deposit_request",
            target_id=int(invoice.id),
            request=request,
            details={
                "user_id": int(invoice.user_id),
                "amount_toman": int(invoice.amount_toman),
                "tx_hash": invoice.tx_hash,
                "wallet_tx_id": int(tx.id),
            },
        )
        db.commit()
        return crypto_deposit_dict(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="تایید واریز ارز دیجیتال ناموفق بود.")


@router.post("/admin/crypto-deposits/{invoice_id}/reject")
def bot_admin_reject_crypto_deposit(
    invoice_id: int,
    payload: CryptoAdminRejectIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        invoice = CryptoDepositService.reject_review(
            db,
            invoice_id=int(invoice_id),
            reason=payload.reason,
        )
        invoice.admin_notified_at = datetime.utcnow()
        AdminAuditService.record(
            db,
            admin=admin,
            action="crypto.deposit.reject",
            target_type="crypto_deposit_request",
            target_id=int(invoice.id),
            request=request,
            details={
                "user_id": int(invoice.user_id),
                "amount_toman": int(invoice.amount_toman),
                "tx_hash": invoice.tx_hash,
                "reason": invoice.failure_reason,
            },
        )
        db.commit()
        return crypto_deposit_dict(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="رد واریز ارز دیجیتال ناموفق بود.")


@router.get("/crypto/notifications")
def bot_crypto_notifications(
    limit: int = Query(default=30, ge=1, le=100),
    token: str = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    _ = token
    pending_cutoff = datetime.utcnow() - timedelta(minutes=int(cfg.CRYPTO_PENDING_ALERT_MINUTES))
    admin_rows = db.execute(
        select(CryptoDepositRequest, User)
        .join(User, User.id == CryptoDepositRequest.user_id)
        .where(
            CryptoDepositRequest.admin_notified_at.is_(None),
            CryptoDepositRequest.status.in_(("NEEDS_REVIEW", "CREDITED")),
        )
        .order_by(CryptoDepositRequest.id.asc())
        .limit(int(limit))
    ).all()
    user_rows = db.execute(
        select(CryptoDepositRequest, User)
        .join(User, User.id == CryptoDepositRequest.user_id)
        .where(
            CryptoDepositRequest.user_notified_at.is_(None),
            CryptoDepositRequest.status.in_(("CREDITED", "REJECTED")),
        )
        .order_by(CryptoDepositRequest.id.asc())
        .limit(int(limit))
    ).all()
    pending_rows = db.execute(
        select(CryptoDepositRequest, User)
        .join(User, User.id == CryptoDepositRequest.user_id)
        .where(
            CryptoDepositRequest.pending_alert_notified_at.is_(None),
            CryptoDepositRequest.status.in_(("WAITING_PAYMENT", "CONFIRMING")),
            CryptoDepositRequest.created_at <= pending_cutoff,
        )
        .order_by(CryptoDepositRequest.id.asc())
        .limit(int(limit))
    ).all()
    variance_rows = db.execute(
        select(CryptoDepositRequest, User)
        .join(User, User.id == CryptoDepositRequest.user_id)
        .where(
            CryptoDepositRequest.variance_alert_notified_at.is_(None),
            CryptoDepositRequest.payment_variance.in_(("UNDERPAID", "OVERPAID")),
        )
        .order_by(CryptoDepositRequest.id.asc())
        .limit(int(limit))
    ).all()
    return {
        "admin": [
            crypto_deposit_dict(row, tg_user_id=int(user.tg_user_id), tg_username=user.username)
            for row, user in admin_rows
        ],
        "user": [
            crypto_deposit_dict(row, tg_user_id=int(user.tg_user_id), tg_username=user.username)
            for row, user in user_rows
        ],
        "pending": [
            crypto_deposit_dict(row, tg_user_id=int(user.tg_user_id), tg_username=user.username)
            for row, user in pending_rows
        ],
        "variance": [
            crypto_deposit_dict(row, tg_user_id=int(user.tg_user_id), tg_username=user.username)
            for row, user in variance_rows
        ],
    }


@router.post("/crypto/notifications/{invoice_id}/{audience}/ack")
def bot_ack_crypto_notification(
    invoice_id: int,
    audience: str,
    token: str = Depends(require_bot_token),
    db: Session = Depends(get_db),
):
    _ = token
    invoice = db.execute(
        select(CryptoDepositRequest)
        .where(CryptoDepositRequest.id == int(invoice_id))
        .with_for_update()
    ).scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="فاکتور واریز ارز دیجیتال پیدا نشد.")
    normalized = str(audience or "").strip().lower()
    now = datetime.utcnow()
    if normalized == "admin":
        invoice.admin_notified_at = now
    elif normalized == "user":
        invoice.user_notified_at = now
    elif normalized == "pending":
        invoice.pending_alert_notified_at = now
    elif normalized == "variance":
        invoice.variance_alert_notified_at = now
    else:
        raise HTTPException(status_code=400, detail="مخاطب اعلان نامعتبر است.")
    db.commit()
    return {"ok": True, "invoice_id": int(invoice.id), "audience": normalized}


@router.get("/admin/crypto-health")
def bot_admin_crypto_health(
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = admin
    return CryptoHealthService.check()


@router.get("/admin/crypto-reconciliation")
def bot_admin_crypto_reconciliation(
    from_at: str | None = Query(default=None),
    to_at: str | None = Query(default=None),
    admin: AdminIdentity = Depends(get_admin_identity),
    db: Session = Depends(get_db),
):
    _ = admin
    end_at = _parse_date_or_datetime(to_at) if to_at else datetime.utcnow()
    start_at = (
        _parse_date_or_datetime(from_at)
        if from_at
        else end_at - timedelta(hours=int(cfg.CRYPTO_RECONCILIATION_LOOKBACK_HOURS))
    )
    if start_at is None or end_at is None or start_at > end_at:
        raise HTTPException(status_code=400, detail="بازه گزارش تطبیق نامعتبر است.")
    if start_at.tzinfo is not None:
        start_at = start_at.astimezone(timezone.utc).replace(tzinfo=None)
    if end_at.tzinfo is not None:
        end_at = end_at.astimezone(timezone.utc).replace(tzinfo=None)
    return CryptoReconciliationService.run(db, start_at=start_at, end_at=end_at)


# ==================== GET /bot/deposit-destinations ====================

@router.get("/deposit-destinations", response_model=DepositDestinationListOut)
def list_deposit_destinations(
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    pool = _deposit_destination_pool(db, include_inactive=False)
    if not pool:
        raise HTTPException(status_code=503, detail="deposit destination is not configured")

    return DepositDestinationListOut(
        mode="USER_SELECT",
        total=len(pool),
        items=[_destination_as_out(it) for it in pool],
        instructions="یکی از کارت‌های مقصد را انتخاب کن، سپس مبلغ و رسید را ثبت کن.",
    )


# ==================== GET /bot/deposit-destination (compat) ====================

@router.get("/deposit-destination")
def get_deposit_destination(
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    pool = _deposit_destination_pool(db, include_inactive=False)
    if not pool:
        raise HTTPException(status_code=503, detail="deposit destination is not configured")
    preview = pool[0]
    return {
        "mode": "USER_SELECT",
        "pool_size": len(pool),
        "destination": _destination_as_out(preview).model_dump(),
        "items": [_destination_as_out(it).model_dump() for it in pool],
        "instructions": "ابتدا کارت مقصد را انتخاب کن، سپس مبلغ را ثبت کن.",
    }


# ==================== SUPER ADMIN: /bot/admin/deposit-destinations ====================

@router.get("/admin/deposit-destinations", response_model=DepositDestinationListOut)
def admin_list_deposit_destinations(
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_super_admin_owner(admin)
    pool = _deposit_destination_pool(db, include_inactive=True)
    return DepositDestinationListOut(
        mode="ADMIN_MANAGE",
        total=len(pool),
        items=[_destination_as_out(it) for it in pool],
        instructions="مدیریت کارت‌های واریز: افزودن، ویرایش، حذف.",
    )


@router.post("/admin/deposit-destinations", response_model=DepositDestinationListOut)
def admin_add_deposit_destination(
    payload: AdminDepositDestinationIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_super_admin_owner(admin)
    current = _deposit_destination_pool(db, include_inactive=True)
    current_ids = {str(it.get("id") or "").strip() for it in current}
    new_id = _generate_destination_id(current_ids)
    raw_item = payload.model_dump()
    raw_item["id"] = new_id
    normalized = _normalize_destination_payload(raw_item, idx=len(current), fallback_id=new_id)
    current.append(normalized)
    _setting_set_json(db, DEPOSIT_DESTINATIONS_SETTING_KEY, current)
    db.commit()
    final_items = _deposit_destination_pool(db, include_inactive=True)
    return DepositDestinationListOut(
        mode="ADMIN_MANAGE",
        total=len(final_items),
        items=[_destination_as_out(it) for it in final_items],
        instructions="کارت جدید اضافه شد.",
    )


@router.put("/admin/deposit-destinations/{destination_id}", response_model=DepositDestinationListOut)
def admin_update_deposit_destination(
    destination_id: str,
    payload: AdminDepositDestinationIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_super_admin_owner(admin)
    current = _deposit_destination_pool(db, include_inactive=True)
    did = str(destination_id or "").strip()
    if not did:
        raise HTTPException(status_code=400, detail="invalid destination_id")

    idx = -1
    for i, item in enumerate(current):
        if str(item.get("id") or "") == did:
            idx = i
            break
    if idx < 0:
        raise HTTPException(status_code=404, detail="destination not found")

    updated_raw = payload.model_dump()
    updated_raw["id"] = did
    updated = _normalize_destination_payload(updated_raw, idx=idx, fallback_id=did)
    if bool(current[idx].get("is_active", True)) and (not bool(updated.get("is_active", True))):
        active_count = sum(1 for it in current if bool(it.get("is_active", True)))
        if active_count <= 1:
            raise HTTPException(status_code=409, detail="at least one active destination is required")
    current[idx] = updated
    _setting_set_json(db, DEPOSIT_DESTINATIONS_SETTING_KEY, current)
    db.commit()
    final_items = _deposit_destination_pool(db, include_inactive=True)
    return DepositDestinationListOut(
        mode="ADMIN_MANAGE",
        total=len(final_items),
        items=[_destination_as_out(it) for it in final_items],
        instructions="کارت ویرایش شد.",
    )


@router.delete("/admin/deposit-destinations/{destination_id}", response_model=DepositDestinationListOut)
def admin_delete_deposit_destination(
    destination_id: str,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _require_super_admin_owner(admin)
    current = _deposit_destination_pool(db, include_inactive=True)
    did = str(destination_id or "").strip()
    if not did:
        raise HTTPException(status_code=400, detail="invalid destination_id")

    filtered = [it for it in current if str(it.get("id") or "") != did]
    if len(filtered) == len(current):
        raise HTTPException(status_code=404, detail="destination not found")
    if not filtered:
        raise HTTPException(status_code=409, detail="cannot delete last destination")
    _setting_set_json(db, DEPOSIT_DESTINATIONS_SETTING_KEY, filtered)
    db.commit()
    final_items = _deposit_destination_pool(db, include_inactive=True)
    return DepositDestinationListOut(
        mode="ADMIN_MANAGE",
        total=len(final_items),
        items=[_destination_as_out(it) for it in final_items],
        instructions="کارت حذف شد.",
    )


# ==================== POST /bot/deposit-requests (Create) ====================

@router.post("/deposit-requests", response_model=DepositRequestOut)
def create_deposit_request(
    payload: CreateDepositRequestIn,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Create a new deposit request.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID

    Body:
    {
        "amount": 10000
    }

    Returns: Deposit request with AWAITING_RECEIPT status
    """
    # Validate amount
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be positive")
    pool = _deposit_destination_pool(db, include_inactive=False)
    if not pool:
        raise HTTPException(status_code=503, detail="deposit destination is not configured")
    selected: dict[str, object] | None = None
    destination_id = str(payload.destination_id or "").strip()
    if destination_id:
        selected = _find_destination_by_id(pool, destination_id)
        if not selected:
            raise HTTPException(status_code=400, detail="invalid destination_id")
    elif len(pool) == 1:
        selected = pool[0]
    else:
        raise HTTPException(status_code=400, detail="destination_id is required")

    # Create deposit request
    dr = DepositRequest(
        user_id=user.id,
        amount=payload.amount,
        status="AWAITING_RECEIPT",
    )

    db.add(dr)
    db.flush()
    _save_request_destination(db, request_id=int(dr.id), destination=selected)
    db.commit()
    db.refresh(dr)
    destination_slot = None
    for i, item in enumerate(pool):
        if str(item.get("id") or "") == str(selected.get("id") or ""):
            destination_slot = int(i + 1)
            break
    destination_count = int(len(pool))

    return DepositRequestOut(
        id=dr.id,
        amount=dr.amount,
        status=dr.status,
        created_at=str(dr.created_at) if dr.created_at else "",
        destination=_destination_as_out(selected),
        destination_slot=destination_slot,
        destination_count=destination_count,
    )


# ==================== GET /bot/games ====================

@router.get("/games", response_model=list[BotGameOut])
def list_bot_games(
    status: Optional[str] = "LOBBY|ACTIVE",
    tg_group_id: int | None = Query(default=None),
    tg_topic_id: int | None = Query(default=None),
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    List games for bot purchase flow.

    Query params:
    - status: LOBBY|ACTIVE (ACTIVE maps to RUNNING)
    - limit: max rows (default 50)
    - offset: pagination offset (default 0)
    """
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    statuses = _parse_bot_game_statuses(status)
    query = select(Game).where(Game.status.in_(statuses))
    if tg_group_id is not None:
        query = query.where(Game.tg_group_id == int(tg_group_id))
    if tg_topic_id is not None:
        query = query.where(Game.tg_topic_id == int(tg_topic_id))

    rows = db.execute(
        query.order_by(Game.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    out: list[BotGameOut] = []
    for g in rows:
        bot_status = "ACTIVE" if str(g.status) == "RUNNING" else str(g.status)
        out.append(
            BotGameOut(
                id=g.id,
                title=f"Game #{g.id}",
                status=bot_status,
                card_price=g.card_price,
                tg_group_id=g.tg_group_id,
                tg_topic_id=g.tg_topic_id,
                prize_pool=g.prize_pool,
                sold_amount=g.sold_amount,
                created_at=str(g.created_at) if g.created_at else "",
            )
        )
    return out


# ==================== POST /bot/purchase-cards ====================

@router.post("/purchase-cards", response_model=BotPurchaseCardsOut)
def bot_purchase_cards(
    payload: BotPurchaseCardsIn,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Purchase cards atomically (wallet debit + cards creation) with idempotency.

    Body:
    {
      "game_id": 8,
      "quantity": 5,
      "idempotency_key": "BUY:tg_user_id:game_id:nonce"
    }
    """
    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    idem = (payload.idempotency_key or "").strip()
    if not idem:
        raise HTTPException(status_code=400, detail="idempotency_key is required")

    try:
        purchase, cards, _ = GameService.buy_cards(
            db=db,
            game_id=int(payload.game_id),
            user_id=int(user.id),
            qty=int(payload.quantity),
            idempotency_key=idem,
        )

        wallet = db.execute(select(Wallet).where(Wallet.user_id == user.id)).scalar_one_or_none()
        wallet_balance = int(wallet.balance) if wallet else 0

        db.commit()
        return BotPurchaseCardsOut(
            order_id=int(purchase.id),
            total_amount=int(purchase.total_price),
            wallet_balance=wallet_balance,
            cards_created=len(cards),
            game_id=int(payload.game_id),
            wallet_tx_id=int(purchase.wallet_tx_id),
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"purchase failed: {str(e)}")


# ==================== GET /bot/deposit-requests/{id} ====================

@router.get("/deposit-requests/{deposit_id}", response_model=DepositRequestOut)
def get_deposit_request(
    deposit_id: int,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Get a single deposit request for the current bot user.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID
    """
    dr = db.execute(
        select(DepositRequest).where(
            DepositRequest.id == deposit_id,
            DepositRequest.user_id == user.id,
        )
    ).scalar_one_or_none()

    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")

    receipt_hash, duplicate_of_ids = _deposit_receipt_duplicate_meta(db, dr)
    selected_destination, destination_slot, destination_count = _resolve_request_destination(
        db=db,
        request_id=int(dr.id),
        user_id=int(dr.user_id),
    )

    return DepositRequestOut(
        id=dr.id,
        amount=dr.amount,
        status=dr.status,
        created_at=str(dr.created_at) if dr.created_at else "",
        destination=_destination_as_out(selected_destination),
        destination_slot=destination_slot,
        destination_count=destination_count,
        receipt_hash=receipt_hash,
        duplicate_of_ids=duplicate_of_ids,
        is_duplicate_receipt=bool(duplicate_of_ids),
    )


# ==================== POST /bot/deposit-requests/{id}/receipt ====================

@router.post("/deposit-requests/{deposit_id}/receipt", response_model=DepositRequestOut)
def upload_deposit_receipt(
    deposit_id: int,
    payload: UploadReceiptIn,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Upload receipt for deposit request.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID

    Body:
    {
        "receipt_file_id": "telegram_file_id"
    }

    Downloads the file from Telegram and saves to disk.
    Returns: Updated deposit request
    """
    # Get deposit request
    dr = db.execute(
        select(DepositRequest).where(
            DepositRequest.id == deposit_id,
            DepositRequest.user_id == user.id,
        )
    ).scalar_one_or_none()

    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")

    # Check status - only allow receipt upload if awaiting
    if dr.status != "AWAITING_RECEIPT":
        raise HTTPException(status_code=400, detail="deposit_request not awaiting receipt")

    try:
        # Download and save file from Telegram
        saved_path = download_telegram_file(
            file_id=payload.receipt_file_id,
            dest_dir=RECEIPTS_DIR,
            filename_prefix=str(dr.id),
        )

        # Update database
        dr.receipt_file_id = payload.receipt_file_id
        dr.receipt_path = saved_path
        dr.status = "PENDING_REVIEW"

        db.add(dr)
        db.commit()
        db.refresh(dr)
        receipt_hash, duplicate_of_ids = _deposit_receipt_duplicate_meta(db, dr)
        selected_destination, destination_slot, destination_count = _resolve_request_destination(
            db=db,
            request_id=int(dr.id),
            user_id=int(dr.user_id),
        )

        return DepositRequestOut(
            id=dr.id,
            amount=dr.amount,
            status=dr.status,
            created_at=str(dr.created_at) if dr.created_at else "",
            destination=_destination_as_out(selected_destination),
            destination_slot=destination_slot,
            destination_count=destination_count,
            receipt_hash=receipt_hash,
            duplicate_of_ids=duplicate_of_ids,
            is_duplicate_receipt=bool(duplicate_of_ids),
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"receipt upload failed: {str(e)}")


# ==================== GET /bot/my-cards ====================

@router.get("/my-cards")
def get_my_cards(
    game_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_bot_user),
    db: Session = Depends(get_db),
):
    """
    Get user's cards with pagination.

    Headers:
    - X-Bot-Token: service token
    - X-Tg-User-Id: telegram user ID

    Query params:
    - game_id: filter by game (optional)
    - page: page number (1-based, default 1)
    - page_size: cards per page (default 20)

    Returns: List of cards with pagination info
    """
    from app.models.game import GameCard

    # Validate pagination
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")

    # Build query
    query = select(GameCard).where(GameCard.user_id == user.id)

    if game_id:
        query = query.where(GameCard.game_id == game_id)

    # Get total count before pagination
    total_count_result = db.execute(query).scalars().all()
    total_count = len(total_count_result)

    # Apply pagination
    offset = (page - 1) * page_size
    cards = db.execute(
        query.offset(offset).limit(page_size)
    ).scalars().all()

    return {
        "cards": cards if cards else [],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_count,
            "total_pages": (total_count + page_size - 1) // page_size if total_count > 0 else 0,
        }
    }


# ==================== GET /bot/admin/games ====================

@router.get("/admin/games", response_model=BotAdminGameListOut)
def list_bot_admin_games(
    status: str | None = Query(default=None),
    tg_group_id: int | None = Query(default=None),
    tg_topic_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = admin

    normalized_statuses = _parse_admin_game_statuses(status)
    where = ["1=1"]
    params: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}

    if normalized_statuses:
        status_placeholders: list[str] = []
        for idx, s in enumerate(normalized_statuses):
            key = f"status_{idx}"
            status_placeholders.append(f":{key}")
            params[key] = s
        where.append(f"status IN ({', '.join(status_placeholders)})")
    if tg_group_id is not None:
        where.append("tg_group_id = :tg_group_id")
        params["tg_group_id"] = int(tg_group_id)
    if tg_topic_id is not None:
        where.append("tg_topic_id = :tg_topic_id")
        params["tg_topic_id"] = int(tg_topic_id)

    total_row = db.execute(
        text(f"""
            SELECT COUNT(*) AS c
            FROM games
            WHERE {" AND ".join(where)}
        """),
        params,
    ).mappings().one()

    rows = db.execute(
        text(f"""
            SELECT
              id, tg_group_id, tg_topic_id, admin_user_id, status,
              card_price, sold_amount, commission_amount, prize_pool,
              prize_locked, col_prize_amount, row_prize_amount,
              col_paid, payout_state_json, row_winner_user_id,
              created_at
            FROM games
            WHERE {" AND ".join(where)}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    items = [
        BotAdminGameOut(
            id=int(r["id"]),
            tg_group_id=int(r["tg_group_id"]),
            tg_topic_id=int(r["tg_topic_id"]) if r["tg_topic_id"] is not None else None,
            admin_user_id=int(r["admin_user_id"]),
            status=str(r["status"]),
            card_price=int(r["card_price"]),
            sold_amount=int(r["sold_amount"]),
            commission_amount=int(r["commission_amount"]),
            prize_pool=int(r["prize_pool"]),
            prize_locked=int(r["prize_locked"]),
            col_prize_amount=int(r["col_prize_amount"]),
            row_prize_amount=int(r["row_prize_amount"]),
            col_paid=int(r["col_paid"]),
            row_paid=int(_row_paid_from_payload(r.get("payout_state_json"))),
            row_winner_user_id=int(r["row_winner_user_id"]) if r["row_winner_user_id"] is not None else None,
            created_at=_as_str_datetime(r["created_at"]),
        )
        for r in rows
    ]

    return BotAdminGameListOut(
        total=int(total_row["c"] or 0),
        limit=int(limit),
        offset=int(offset),
        items=items,
    )


# ==================== GET /bot/admin/games/{game_id}/report ====================

@router.get("/admin/games/{game_id}/report", response_model=BotAdminReportOut)
def get_bot_admin_game_report(
    game_id: int,
    events_limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = admin

    game = db.execute(
        text("""
            SELECT
              id, tg_group_id, tg_topic_id, admin_user_id, status,
              card_price, sold_amount, commission_amount, prize_pool,
              prize_locked, col_prize_amount, row_prize_amount,
              col_paid, payout_state_json, row_winner_user_id,
              created_at
            FROM games
            WHERE id = :game_id
        """),
        {"game_id": game_id},
    ).mappings().one_or_none()
    if not game:
        raise HTTPException(status_code=404, detail="game not found")

    payout_state = _as_json_dict(game.get("payout_state_json")) or {}
    col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
    row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
    col_winner_user_ids = _as_int_list(col_info.get("winner_user_ids"))
    col_winner_card_ids = _as_int_list(col_info.get("winner_card_ids"))
    row_winner_user_ids = _as_int_list(row_info.get("winner_user_ids"))
    row_winner_card_ids = _as_int_list(row_info.get("winner_card_ids"))

    user_ids = {
        int(game["admin_user_id"]),
        *col_winner_user_ids,
        *row_winner_user_ids,
    }
    tg_map: dict[int, int] = {}
    if user_ids:
        tg_rows = db.execute(
            select(User.id, User.tg_user_id).where(User.id.in_(list(user_ids)))
        ).all()
        tg_map = {int(uid): int(tg_uid) for uid, tg_uid in tg_rows if tg_uid is not None}

    admin_tg_user_id = tg_map.get(int(game["admin_user_id"]))
    col_winner_tg_user_ids = [int(tg_map.get(uid, 0) or 0) for uid in col_winner_user_ids]
    row_winner_tg_user_ids = [int(tg_map.get(uid, 0) or 0) for uid in row_winner_user_ids]
    winner_card_ids = sorted({*col_winner_card_ids, *row_winner_card_ids})

    winner_cards_out: list[BotAdminWinnerCardOut] = []
    if winner_card_ids:
        card_rows = db.execute(
            select(GameCard.id, GameCard.user_id, GameCard.numbers_json).where(
                GameCard.game_id == game_id,
                GameCard.id.in_(winner_card_ids),
            )
        ).all()
        for cid, uid, nums_raw in card_rows:
            nums = []
            for x in _as_json_list(nums_raw):
                try:
                    nums.append(int(x))
                except Exception:
                    continue
            winner_cards_out.append(
                BotAdminWinnerCardOut(
                    card_id=int(cid),
                    user_id=int(uid),
                    tg_user_id=tg_map.get(int(uid)),
                    numbers=nums,
                )
            )
        winner_cards_out.sort(key=lambda x: int(x.card_id))

    purchases = db.execute(
        text("""
            SELECT
              COUNT(*) AS purchases_count,
              COALESCE(SUM(qty),0) AS cards_sold,
              COALESCE(SUM(total_price),0) AS sales_total
            FROM game_purchases
            WHERE game_id = :game_id
        """),
        {"game_id": game_id},
    ).mappings().one()

    called_rows = db.execute(
        text("""
            SELECT number, called_by, created_at
            FROM game_called_numbers
            WHERE game_id = :game_id
            ORDER BY id ASC
        """),
        {"game_id": game_id},
    ).mappings().all()

    event_rows = db.execute(
        text("""
            SELECT id, kind, idem_key, actor_user_id, tg_group_id, payload_json, created_at
            FROM game_events
            WHERE game_id = :game_id
            ORDER BY id DESC
            LIMIT :lim
        """),
        {"game_id": game_id, "lim": events_limit},
    ).mappings().all()

    return BotAdminReportOut(
        game=BotAdminGameReportGameOut(
            id=int(game["id"]),
            tg_group_id=int(game["tg_group_id"]),
            tg_topic_id=int(game["tg_topic_id"]) if game["tg_topic_id"] is not None else None,
            admin_user_id=int(game["admin_user_id"]),
            admin_tg_user_id=admin_tg_user_id,
            status=str(game["status"]),
            card_price=int(game["card_price"]),
            sold_amount=int(game["sold_amount"]),
            commission_amount=int(game["commission_amount"]),
            prize_pool=int(game["prize_pool"]),
            prize_locked=int(game["prize_locked"]),
            col_prize_amount=int(game["col_prize_amount"]),
            row_prize_amount=int(game["row_prize_amount"]),
            col_paid=int(game["col_paid"]),
            row_paid=int(_row_paid_from_payload(game.get("payout_state_json"))),
            col_winner_user_ids=col_winner_user_ids,
            col_winner_tg_user_ids=col_winner_tg_user_ids,
            col_winner_card_ids=col_winner_card_ids,
            row_winner_user_ids=row_winner_user_ids,
            row_winner_tg_user_ids=row_winner_tg_user_ids,
            row_winner_card_ids=row_winner_card_ids,
            payout_state_json=_as_json_dict(game.get("payout_state_json")),
            row_winner_user_id=int(game["row_winner_user_id"]) if game["row_winner_user_id"] is not None else None,
            created_at=_as_str_datetime(game["created_at"]),
        ),
        purchases=BotAdminGamePurchaseStatsOut(
            purchases_count=int(purchases["purchases_count"] or 0),
            cards_sold=int(purchases["cards_sold"] or 0),
            sales_total=int(purchases["sales_total"] or 0),
        ),
        called_numbers=[
            BotAdminCalledNumberOut(
                number=int(c["number"]),
                called_by=int(c["called_by"]),
                created_at=_as_str_datetime(c["created_at"]),
            )
            for c in called_rows
        ],
        events=[
            BotAdminGameEventOut(
                id=int(e["id"]),
                kind=str(e["kind"]),
                idem_key=str(e["idem_key"]) if e["idem_key"] is not None else None,
                actor_user_id=int(e["actor_user_id"]) if e["actor_user_id"] is not None else None,
                tg_group_id=int(e["tg_group_id"]) if e["tg_group_id"] is not None else None,
                payload_json=_as_json_dict(e.get("payload_json")),
                created_at=_as_str_datetime(e["created_at"]),
            )
            for e in event_rows
        ],
        winner_cards=winner_cards_out,
    )


# ==================== GAME LIVE LINK ====================

@router.get("/admin/games/{game_id}/live-link", response_model=BotAdminGameLiveLinkOut)
def get_bot_admin_game_live_link(
    game_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = _require_game_admin_access(db, game_id, admin)
    payload = _setting_get_json(db, _game_live_link_setting_key(game_id))
    payload_dict = payload if isinstance(payload, dict) else {}

    participants_count = db.execute(
        select(func.count(func.distinct(GamePurchase.user_id))).where(GamePurchase.game_id == int(game_id))
    ).scalar_one()

    return BotAdminGameLiveLinkOut(
        game_id=int(game_id),
        url=str(payload_dict.get("url") or "") or None,
        updated_by=int(payload_dict["updated_by"]) if str(payload_dict.get("updated_by") or "").isdigit() else None,
        updated_at=str(payload_dict.get("updated_at") or "") or None,
        participants_count=int(participants_count or 0),
    )


@router.put("/admin/games/{game_id}/live-link", response_model=BotAdminGameLiveLinkOut)
def set_bot_admin_game_live_link(
    game_id: int,
    payload: BotAdminGameLiveLinkIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = _require_game_admin_access(db, game_id, admin)
    url = _normalize_live_url(payload.url)
    now = datetime.utcnow().isoformat(timespec="seconds")
    data = {
        "url": url,
        "updated_by": int(admin.user_id) if admin.user_id is not None else None,
        "updated_at": now,
    }
    _setting_set_json(db, _game_live_link_setting_key(game_id), data)
    db.commit()
    participants_count = db.execute(
        select(func.count(func.distinct(GamePurchase.user_id))).where(GamePurchase.game_id == int(game_id))
    ).scalar_one()
    return BotAdminGameLiveLinkOut(
        game_id=int(game_id),
        url=url,
        updated_by=int(admin.user_id) if admin.user_id is not None else None,
        updated_at=now,
        participants_count=int(participants_count or 0),
    )


@router.delete("/admin/games/{game_id}/live-link", response_model=BotAdminGameLiveLinkOut)
def clear_bot_admin_game_live_link(
    game_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = _require_game_admin_access(db, game_id, admin)
    _setting_set_json(
        db,
        _game_live_link_setting_key(game_id),
        {
            "url": "",
            "updated_by": int(admin.user_id) if admin.user_id is not None else None,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
    )
    db.commit()
    participants_count = db.execute(
        select(func.count(func.distinct(GamePurchase.user_id))).where(GamePurchase.game_id == int(game_id))
    ).scalar_one()
    return BotAdminGameLiveLinkOut(
        game_id=int(game_id),
        url=None,
        updated_by=int(admin.user_id) if admin.user_id is not None else None,
        updated_at=datetime.utcnow().isoformat(timespec="seconds"),
        participants_count=int(participants_count or 0),
    )


@router.get("/admin/games/{game_id}/participants", response_model=list[BotAdminGameParticipantOut])
def list_bot_admin_game_participants(
    game_id: int,
    only_with_tg: bool = Query(default=True),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = _require_game_admin_access(db, game_id, admin)

    query = (
        select(
            User.id,
            User.tg_user_id,
            User.username,
            func.coalesce(func.sum(GamePurchase.qty), 0).label("cards_count"),
            func.count(GamePurchase.id).label("purchases_count"),
            func.coalesce(func.sum(GamePurchase.total_price), 0).label("total_paid"),
        )
        .select_from(User)
        .join(GamePurchase, GamePurchase.user_id == User.id)
        .where(GamePurchase.game_id == int(game_id))
        .group_by(User.id, User.tg_user_id, User.username)
        .order_by(func.coalesce(func.sum(GamePurchase.qty), 0).desc(), User.id.asc())
    )
    if only_with_tg:
        query = query.where(User.tg_user_id.is_not(None))

    rows = db.execute(query).all()
    out: list[BotAdminGameParticipantOut] = []
    for uid, tg_uid, username, cards_count, purchases_count, total_paid in rows:
        out.append(
            BotAdminGameParticipantOut(
                user_id=int(uid),
                tg_user_id=int(tg_uid) if tg_uid is not None else None,
                tg_username=str(username) if username is not None else None,
                cards_count=int(cards_count or 0),
                purchases_count=int(purchases_count or 0),
                total_paid=int(total_paid or 0),
            )
        )
    return out


# ==================== POST /bot/admin/games/{game_id}/ensure-active ====================

@router.post("/admin/games/{game_id}/ensure-active", response_model=BotAdminGameOut)
def ensure_bot_admin_game_active(
    game_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    src_game = _get_game_or_404(db, game_id)

    active_q = (
        select(Game)
        .where(
            Game.tg_group_id == src_game.tg_group_id,
            Game.status.in_(["LOBBY", "RUNNING"]),
        )
    )
    if getattr(src_game, "tg_topic_id", None) is None:
        active_q = active_q.where(Game.tg_topic_id.is_(None))
    else:
        active_q = active_q.where(Game.tg_topic_id == int(src_game.tg_topic_id))

    active = db.execute(
        active_q.order_by(Game.id.desc()).limit(1)
    ).scalar_one_or_none()
    if active:
        return _to_bot_admin_game_out(active)

    admin_uid = _require_admin_user_id(admin)
    try:
        created = GameService.create_game(
            db=db,
            admin_user_id=admin_uid,
            tg_group_id=int(src_game.tg_group_id),
            tg_topic_id=int(src_game.tg_topic_id) if getattr(src_game, "tg_topic_id", None) is not None else None,
            card_price=int(src_game.card_price),
        )
        AdminAuditService.record(
            db,
            admin=admin,
            action="game.create",
            target_type="game",
            target_id=int(created.id),
            request=request,
            details={
                "game_id": int(created.id),
                "source_game_id": int(src_game.id),
                "tg_group_id": int(created.tg_group_id),
                "tg_topic_id": int(created.tg_topic_id) if created.tg_topic_id is not None else None,
                "card_price": int(created.card_price),
                "status": str(created.status),
                "source": "bot.ensure_active",
            },
        )
        db.commit()
        db.refresh(created)
        return _to_bot_admin_game_out(created)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"ensure active failed: {str(e)}")


# ==================== POST /bot/admin/games/{game_id}/start ====================

@router.post("/admin/games/{game_id}/start", response_model=BotAdminGameOut)
def start_bot_admin_game(
    game_id: int,
    payload: BotAdminStartIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    admin_uid = _require_admin_user_id(admin)
    try:
        before = db.execute(select(Game.status).where(Game.id == int(game_id))).scalar_one_or_none()
        game = GameService.start_game(
            db=db,
            game_id=game_id,
            admin_user_id=admin_uid,
            idempotency_key=payload.idempotency_key,
        )
        AdminAuditService.record(
            db,
            admin=admin,
            action="game.start",
            target_type="game",
            target_id=int(game.id),
            request=request,
            details={
                "game_id": int(game.id),
                "status_before": str(before) if before is not None else None,
                "status_after": str(game.status),
                "sold_amount": int(game.sold_amount),
                "prize_pool": int(game.prize_pool),
                "col_prize_amount": int(game.col_prize_amount),
                "row_prize_amount": int(game.row_prize_amount),
                "idempotency_key": str(payload.idempotency_key),
            },
        )
        db.commit()
        db.refresh(game)
        return _to_bot_admin_game_out(game)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"start failed: {str(e)}")


# ==================== POST /bot/admin/games/{game_id}/call ====================

@router.post("/admin/games/{game_id}/call", response_model=BotAdminCallOut)
def call_number_on_bot_admin_game(
    game_id: int,
    payload: BotAdminCallIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    admin_uid = _require_admin_user_id(admin)
    try:
        res = GameService.call_number(
            db=db,
            game_id=game_id,
            number=payload.number,
            admin_user_id=admin_uid,
            idempotency_key=payload.idempotency_key,
        )
        AdminAuditService.record(
            db,
            admin=admin,
            action="game.call",
            target_type="game",
            target_id=int(game_id),
            request=request,
            details={
                "game_id": int(game_id),
                "number": int(payload.number),
                "called_count": int(res.get("called_count") or 0),
                "col_paid": int(res.get("col_paid") or 0),
                "row_paid": int(res.get("row_paid") or 0),
                "row_winner_user_ids": [int(x) for x in (res.get("row_winner_user_ids") or [])],
                "row_winner_card_ids": [int(x) for x in (res.get("row_winner_card_ids") or [])],
                "idempotency_key": str(payload.idempotency_key),
            },
        )
        db.commit()
        return BotAdminCallOut(**res)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"call failed: {str(e)}")


# ==================== POST /bot/admin/games/{game_id}/undo-last-call ====================

@router.post("/admin/games/{game_id}/undo-last-call", response_model=BotAdminUndoOut)
def undo_last_call_on_bot_admin_game(
    game_id: int,
    payload: BotAdminUndoIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    admin_uid = _require_admin_user_id(admin)
    try:
        res = GameService.undo_last_call(
            db=db,
            game_id=game_id,
            admin_user_id=admin_uid,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return BotAdminUndoOut(**res)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"undo failed: {str(e)}")


# ==================== POST /bot/admin/games/{game_id}/status ====================

@router.post("/admin/games/{game_id}/status", response_model=BotAdminGameOut)
def set_bot_admin_game_status(
    game_id: int,
    payload: BotAdminStatusIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    requested = (payload.status or "").strip().upper()
    if requested == "ACTIVE":
        requested = "RUNNING"

    if requested not in {"RUNNING", "ENDED"}:
        raise HTTPException(
            status_code=400,
            detail="status endpoint currently supports only RUNNING or ENDED",
        )

    admin_uid = _require_admin_user_id(admin)
    try:
        if requested == "RUNNING":
            game = GameService.start_game(
                db=db,
                game_id=game_id,
                admin_user_id=admin_uid,
                idempotency_key=payload.idempotency_key,
            )
        else:
            cancel_reason = str(payload.cancel_reason or "").strip()
            if not cancel_reason:
                raise HTTPException(status_code=400, detail="cancel_reason is required when closing lobby")
            game = GameService.close_lobby_game(
                db=db,
                game_id=game_id,
                admin_user_id=admin_uid,
                idempotency_key=payload.idempotency_key,
                cancel_reason=cancel_reason,
            )
        db.commit()
        db.refresh(game)
        return _to_bot_admin_game_out(game)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"status update failed: {str(e)}")


# ==================== GET /bot/admin/deposit-requests ====================

@router.get("/admin/deposit-requests", response_model=list[AdminDepositRequestOut])
def list_admin_deposit_requests(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    created_from: Optional[str] = Query(default=None),
    created_to: Optional[str] = Query(default=None),
    min_amount: Optional[int] = Query(default=None, ge=0),
    max_amount: Optional[int] = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    """
    List all deposit requests (for admin).

    Headers:
    - X-Admin-Token or X-User-Token (admin identity)

    Query params:
    - status: filter by status (AWAITING_RECEIPT, PENDING_REVIEW, APPROVED, REJECTED)
    - limit: max results (default 100)
    - offset: pagination offset (default 0)
    - created_from: inclusive lower bound for created_at (YYYY-MM-DD or ISO datetime)
    - created_to: inclusive upper bound for created_at (YYYY-MM-DD or ISO datetime)
    - min_amount: minimum amount
    - max_amount: maximum amount

    Returns: List of deposit requests
    """
    query = (
        select(DepositRequest, User)
        .join(User, User.id == DepositRequest.user_id)
        .order_by(DepositRequest.id.desc())
    )

    if status:
        query = query.where(DepositRequest.status == status)

    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if min_amount is not None and max_amount is not None and int(min_amount) > int(max_amount):
        raise HTTPException(status_code=400, detail="min_amount cannot be greater than max_amount")

    created_from_dt = _parse_date_or_datetime(created_from, end_of_day=False)
    created_to_dt = _parse_date_or_datetime(created_to, end_of_day=True)
    if created_from_dt and created_to_dt and created_from_dt > created_to_dt:
        raise HTTPException(status_code=400, detail="created_from cannot be greater than created_to")

    if created_from_dt is not None:
        query = query.where(DepositRequest.created_at >= created_from_dt)
    if created_to_dt is not None:
        query = query.where(DepositRequest.created_at <= created_to_dt)
    if min_amount is not None:
        query = query.where(DepositRequest.amount >= int(min_amount))
    if max_amount is not None:
        query = query.where(DepositRequest.amount <= int(max_amount))

    query = query.offset(offset).limit(limit)

    rows = db.execute(query).all()
    out: list[AdminDepositRequestOut] = []
    for dr, user in rows:
        receipt_hash, duplicate_of_ids = _deposit_receipt_duplicate_meta(db, dr)
        selected_destination, destination_slot, destination_count = _resolve_request_destination(
            db=db,
            request_id=int(dr.id),
            user_id=int(dr.user_id),
        )
        out.append(
            AdminDepositRequestOut(
                id=dr.id,
                user_id=dr.user_id,
                tg_user_id=user.tg_user_id if user else None,
                tg_username=user.username if user else None,
                amount=dr.amount,
                status=dr.status,
                receipt_file_id=dr.receipt_file_id,
                receipt_url=f"/bot/admin/deposit-requests/{dr.id}/receipt",
                created_at=str(dr.created_at) if dr.created_at else "",
                destination=_destination_as_out(selected_destination),
                destination_slot=destination_slot,
                destination_count=destination_count,
                receipt_hash=receipt_hash,
                duplicate_of_ids=duplicate_of_ids,
                is_duplicate_receipt=bool(duplicate_of_ids),
            )
        )
    return out


@router.get("/admin/deposit-requests/{deposit_id}", response_model=AdminDepositRequestOut)
def get_admin_deposit_request(
    deposit_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    row = db.execute(
        select(DepositRequest, User)
        .join(User, User.id == DepositRequest.user_id)
        .where(DepositRequest.id == deposit_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="deposit_request not found")

    dr, user = row
    receipt_hash, duplicate_of_ids = _deposit_receipt_duplicate_meta(db, dr)
    selected_destination, destination_slot, destination_count = _resolve_request_destination(
        db=db,
        request_id=int(dr.id),
        user_id=int(dr.user_id),
    )
    return AdminDepositRequestOut(
        id=dr.id,
        user_id=dr.user_id,
        tg_user_id=user.tg_user_id if user else None,
        tg_username=user.username if user else None,
        amount=dr.amount,
        status=dr.status,
        receipt_file_id=dr.receipt_file_id,
        receipt_url=f"/bot/admin/deposit-requests/{dr.id}/receipt",
        created_at=str(dr.created_at) if dr.created_at else "",
        destination=_destination_as_out(selected_destination),
        destination_slot=destination_slot,
        destination_count=destination_count,
        receipt_hash=receipt_hash,
        duplicate_of_ids=duplicate_of_ids,
        is_duplicate_receipt=bool(duplicate_of_ids),
    )


@router.get("/admin/withdraw-requests", response_model=list[AdminWithdrawRequestOut])
def list_admin_withdraw_requests(
    status: Optional[str] = "PENDING",
    limit: int = 100,
    offset: int = 0,
    created_from: Optional[str] = Query(default=None),
    created_to: Optional[str] = Query(default=None),
    min_amount: Optional[int] = Query(default=None, ge=0),
    max_amount: Optional[int] = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    """
    List withdraw requests (for admin) with pagination.

    Headers:
    - X-Admin-Token or X-User-Token (admin identity)

    Query params:
    - status: optional filter (PENDING, APPROVED, PAID, REJECTED)
    - limit: max results (default 100)
    - offset: pagination offset (default 0)
    - created_from: inclusive lower bound for created_at (YYYY-MM-DD or ISO datetime)
    - created_to: inclusive upper bound for created_at (YYYY-MM-DD or ISO datetime)
    - min_amount: minimum amount
    - max_amount: maximum amount
    """
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if min_amount is not None and max_amount is not None and int(min_amount) > int(max_amount):
        raise HTTPException(status_code=400, detail="min_amount cannot be greater than max_amount")

    created_from_dt = _parse_date_or_datetime(created_from, end_of_day=False)
    created_to_dt = _parse_date_or_datetime(created_to, end_of_day=True)
    if created_from_dt and created_to_dt and created_from_dt > created_to_dt:
        raise HTTPException(status_code=400, detail="created_from cannot be greater than created_to")

    query = (
        select(WithdrawRequest, User)
        .join(User, User.id == WithdrawRequest.user_id)
        .order_by(WithdrawRequest.id.desc())
    )
    if status:
        query = query.where(WithdrawRequest.status == status)
    if created_from_dt is not None:
        query = query.where(WithdrawRequest.created_at >= created_from_dt)
    if created_to_dt is not None:
        query = query.where(WithdrawRequest.created_at <= created_to_dt)
    if min_amount is not None:
        query = query.where(WithdrawRequest.amount >= int(min_amount))
    if max_amount is not None:
        query = query.where(WithdrawRequest.amount <= int(max_amount))
    query = query.offset(offset).limit(limit)

    rows = db.execute(query).all()
    return [
        AdminWithdrawRequestOut(
            id=wr.id,
            user_id=wr.user_id,
            tg_user_id=user.tg_user_id if user else None,
            tg_username=user.username if user else None,
            request_source=_read_withdraw_request_source(db, int(wr.id)),
            amount=wr.amount,
            status=wr.status,
            full_name=wr.full_name,
            iban=wr.iban,
            card_number=wr.card_number,
            account_number=wr.account_number,
            paid_tracking=wr.paid_tracking,
            created_at=str(wr.created_at) if wr.created_at else "",
        )
        for wr, user in rows
    ]


@router.get("/admin/withdraw-requests/{withdraw_id}", response_model=AdminWithdrawRequestOut)
def get_admin_withdraw_request(
    withdraw_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    row = db.execute(
        select(WithdrawRequest, User)
        .join(User, User.id == WithdrawRequest.user_id)
        .where(WithdrawRequest.id == withdraw_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="withdraw_request not found")

    wr, user = row
    return AdminWithdrawRequestOut(
        id=wr.id,
        user_id=wr.user_id,
        tg_user_id=user.tg_user_id if user else None,
        tg_username=user.username if user else None,
        request_source=_read_withdraw_request_source(db, int(wr.id)),
        amount=wr.amount,
        status=wr.status,
        full_name=wr.full_name,
        iban=wr.iban,
        card_number=wr.card_number,
        account_number=wr.account_number,
        paid_tracking=wr.paid_tracking,
        created_at=str(wr.created_at) if wr.created_at else "",
    )


@router.post("/admin/withdraw-requests/{withdraw_id}/approve")
def approve_admin_withdraw_request(
    withdraw_id: int,
    payload: ApproveWithdrawIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    admin_uid = _require_admin_user_id(admin)
    try:
        wr, tx = FinanceService.approve_withdraw(
            db=db,
            withdraw_id=withdraw_id,
            admin_user_id=admin_uid,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return {
            "withdraw_id": int(wr.id),
            "status": str(wr.status),
            "wallet_tx_id": int(tx.id),
            "reviewed_by": admin_uid,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"withdraw approve failed: {str(e)}")


@router.post("/admin/withdraw-requests/{withdraw_id}/paid")
def mark_admin_withdraw_paid(
    withdraw_id: int,
    payload: MarkWithdrawPaidIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    admin_uid = _require_admin_user_id(admin)
    try:
        wr = FinanceService.mark_withdraw_paid(
            db=db,
            withdraw_id=withdraw_id,
            admin_user_id=admin_uid,
            paid_tracking=payload.paid_tracking,
        )
        db.commit()
        return {
            "withdraw_id": int(wr.id),
            "status": str(wr.status),
            "paid_tracking": str(wr.paid_tracking or ""),
            "reviewed_by": admin_uid,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"withdraw paid failed: {str(e)}")


@router.post("/admin/withdraw-requests/{withdraw_id}/reject")
def reject_admin_withdraw_request(
    withdraw_id: int,
    payload: RejectWithdrawIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    admin_uid = _require_admin_user_id(admin)
    try:
        wr = FinanceService.reject_withdraw(
            db=db,
            withdraw_id=withdraw_id,
            admin_user_id=admin_uid,
            reason=payload.reason,
        )
        db.commit()
        return {
            "withdraw_id": int(wr.id),
            "status": str(wr.status),
            "reviewed_by": admin_uid,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"withdraw reject failed: {str(e)}")


# ==================== POST /bot/admin/deposit-requests/{id}/approve ====================

@router.post("/admin/deposit-requests/{deposit_id}/approve")
def approve_deposit_request(
    deposit_id: int,
    payload: ApproveDepositIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    """
    Approve a deposit request and credit the wallet.

    Headers:
    - X-Admin-Token or X-User-Token (admin identity)

    Body:
    {
        "idempotency_key": "unique_key_for_safety"
    }

    Returns: Updated deposit request
    """
    # Get deposit request
    dr = db.execute(
        select(DepositRequest).where(DepositRequest.id == deposit_id)
    ).scalar_one_or_none()

    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")

    if dr.status == "APPROVED":
        raise HTTPException(status_code=400, detail="already approved")

    try:
        # Use finance service to approve
        result_dr, tx = FinanceService.approve_deposit(
            db,
            deposit_id,
            admin_user_id=admin.user_id,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()

        return {
            "id": result_dr.id,
            "user_id": result_dr.user_id,
            "amount": result_dr.amount,
            "status": result_dr.status,
            "wallet_tx_id": tx.id,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"approval failed: {str(e)}")


# ==================== POST /bot/admin/deposit-requests/{id}/reject ====================

@router.post("/admin/deposit-requests/{deposit_id}/reject")
def reject_deposit_request(
    deposit_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    """
    Reject a deposit request.

    Headers:
    - X-Admin-Token or X-User-Token (admin identity)

    Returns: Updated deposit request
    """
    # Get deposit request
    dr = db.execute(
        select(DepositRequest).where(DepositRequest.id == deposit_id)
    ).scalar_one_or_none()

    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")

    if dr.status == "REJECTED":
        raise HTTPException(status_code=400, detail="already rejected")

    try:
        result_dr = FinanceService.reject_deposit(
            db,
            deposit_id,
            admin_user_id=admin.user_id,
        )
        db.commit()

        return {
            "id": result_dr.id,
            "user_id": result_dr.user_id,
            "amount": result_dr.amount,
            "status": result_dr.status,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"rejection failed: {str(e)}")


# ==================== POST /bot/admin/manual-charge ====================

@router.post("/admin/manual-charge")
def manual_charge(
    payload: ManualChargeIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    """
    Manually charge a user's wallet (admin only).

    Headers:
    - X-Admin-Token or X-User-Token (admin identity)

    Body:
    {
        "telegram_user_id": 123456789,
        "amount": 10000,
        "reason": "manual_charge"
    }

    Returns: Wallet transaction details
    """
    try:
        # Get user by telegram user ID
        user = db.execute(
            select(User).where(User.tg_user_id == payload.telegram_user_id)
        ).scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="user not found")

        # Get or create wallet
        wallet = db.execute(
            select(Wallet).where(Wallet.user_id == user.id)
        ).scalar_one_or_none()

        if not wallet:
            wallet = Wallet(user_id=user.id, balance=0)
            db.add(wallet)
            db.flush()

        # Create wallet transaction
        tx = WalletTx(
            wallet_id=wallet.id,
            direction="in",
            amount=payload.amount,
            reason=f"admin_charge:{payload.reason}",
        )

        wallet.balance += payload.amount
        db.add(wallet)
        db.add(tx)
        db.commit()
        db.refresh(tx)

        return {
            "transaction_id": tx.id,
            "user_id": user.id,
            "telegram_user_id": user.tg_user_id,
            "amount": payload.amount,
            "new_balance": wallet.balance,
            "reason": payload.reason,
            "created_at": str(tx.created_at) if tx.created_at else "",
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"charge failed: {str(e)}")


@router.get("/admin/deposit-requests/{deposit_id}/receipt")
def admin_get_deposit_receipt(
    deposit_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    dr = db.execute(select(DepositRequest).where(DepositRequest.id == deposit_id)).scalar_one_or_none()
    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")
    if not dr.receipt_path:
        raise HTTPException(status_code=404, detail="receipt not found")

    if not os.path.exists(dr.receipt_path):
        raise HTTPException(status_code=404, detail="receipt file missing on disk")

    # FileResponse خودش content-type رو حدس می‌زنه
    return FileResponse(dr.receipt_path, filename=os.path.basename(dr.receipt_path))
