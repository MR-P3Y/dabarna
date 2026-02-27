from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import unquote

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import (
    MINI_INITDATA_REPLAY_TTL_SEC,
    MINI_RATE_LIMIT_EVENTS_PER_SEC,
    MINI_RATE_LIMIT_WRITE_PER_MIN,
    MINI_SESSION_SECRET,
    MINI_SESSION_TTL_SEC,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_INITDATA_HEADER,
    TELEGRAM_INITDATA_MAX_AGE_SECONDS,
)
from app.core.db import get_db
from app.core.redis_client import get_redis
from app.services.user_service import UserService
from app.utils.tg_webapp import TelegramInitDataError, verify_init_data_with_age

log = logging.getLogger("mini.security")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + pad).encode("ascii"))


def _token_sign(payload_b64: str) -> str:
    sig = hmac.new(
        MINI_SESSION_SECRET.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(sig)


def issue_session_token(user_id: int, ttl_sec: int | None = None) -> tuple[str, int]:
    now = int(time.time())
    ttl = max(60, int(ttl_sec or MINI_SESSION_TTL_SEC))
    exp = now + ttl
    payload = {"uid": int(user_id), "iat": now, "exp": exp}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig_b64 = _token_sign(payload_b64)
    return f"{payload_b64}.{sig_b64}", exp


def verify_session_token(token: str) -> int:
    if not token or "." not in token:
        raise HTTPException(status_code=401, detail="توکن نشست نامعتبر است.")

    parts = token.strip().split(".")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="توکن نشست نامعتبر است.")

    payload_b64, sig_b64 = parts
    expected = _token_sign(payload_b64)
    if not hmac.compare_digest(expected, sig_b64):
        raise HTTPException(status_code=401, detail="امضای نشست نامعتبر است.")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=401, detail="محتوای نشست نامعتبر است.")

    uid = payload.get("uid")
    exp = payload.get("exp")
    if not isinstance(uid, int) or uid <= 0:
        raise HTTPException(status_code=401, detail="کاربر نشست نامعتبر است.")
    if not isinstance(exp, int):
        raise HTTPException(status_code=401, detail="زمان انقضای نشست نامعتبر است.")
    if int(time.time()) > int(exp):
        raise HTTPException(status_code=401, detail="نشست کاربری منقضی شده است.")
    return int(uid)


def _parse_bearer(authorization: str | None) -> str | None:
    raw = str(authorization or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    return token or None


def _init_data_candidates(init_data: str) -> list[str]:
    cleaned = str(init_data or "").strip()
    if not cleaned:
        return []
    out = [cleaned]
    try:
        decoded = unquote(cleaned).strip()
        if decoded and decoded != cleaned and "hash=" in decoded:
            out.append(decoded)
    except Exception:
        pass
    return out


def _verify_init_data_candidates(init_data: str):
    candidates = _init_data_candidates(init_data)
    if not candidates:
        raise HTTPException(status_code=400, detail="داده احراز هویت تلگرام الزامی است.")

    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="توکن ربات تلگرام روی سرور تنظیم نشده است.")

    last_exc: TelegramInitDataError | None = None
    for candidate in candidates:
        try:
            parsed = verify_init_data_with_age(
                init_data=candidate,
                bot_token=TELEGRAM_BOT_TOKEN,
                max_age_seconds=TELEGRAM_INITDATA_MAX_AGE_SECONDS,
            )
            return candidate, parsed
        except TelegramInitDataError as exc:
            last_exc = exc

    reason_raw = str(last_exc or "invalid init data").strip().lower()
    reason_map = {
        "missing init_data": "داده احراز هویت تلگرام ارسال نشده است.",
        "missing hash": "امضای امنیتی تلگرام ناقص است.",
        "invalid hash": "امضای امنیتی تلگرام نامعتبر است. مینی‌اپ را فقط از منوی رسمی ربات باز کنید.",
        "invalid user json": "اطلاعات کاربر تلگرام نامعتبر است.",
        "invalid auth_date": "زمان احراز هویت تلگرام نامعتبر است.",
        "auth_date missing": "زمان احراز هویت تلگرام ارسال نشده است.",
        "auth_date too old": "زمان احراز هویت منقضی شده است. مینی‌اپ را مجددا از منوی ربات باز کنید.",
        "invalid init data": "داده احراز هویت تلگرام نامعتبر است.",
    }
    reason = reason_map.get(reason_raw, "داده احراز هویت تلگرام نامعتبر است.")
    log.warning("telegram init_data rejected: reason=%s", reason)
    raise HTTPException(status_code=401, detail=reason)


def _user_from_init_data(init_data: str, db: Session) -> tuple[int, str]:
    normalized_init_data, parsed = _verify_init_data_candidates(init_data)

    user = parsed.user or {}
    tg_user_id = user.get("id")
    if not isinstance(tg_user_id, int):
        raise HTTPException(status_code=401, detail="شناسه کاربر تلگرام نامعتبر است.")

    u = UserService.upsert(
        db,
        tg_user_id=tg_user_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
    )
    return int(u.id), normalized_init_data


def consume_init_data_nonce(init_data: str) -> bool:
    digest = hashlib.sha256(init_data.encode("utf-8")).hexdigest()
    key = f"mini:initdata:{digest}"
    try:
        r = get_redis()
        return bool(r.set(key, "1", nx=True, ex=max(30, int(MINI_INITDATA_REPLAY_TTL_SEC))))
    except Exception as exc:
        # Fail-open on Redis outage to avoid full auth outage.
        log.warning("replay guard unavailable: %s", exc)
        return True


def enforce_rate_limit(
    *,
    scope: str,
    user_id: int,
    limit: int,
    window_sec: int,
) -> None:
    if limit <= 0 or window_sec <= 0:
        return
    slot = int(time.time() // int(window_sec))
    key = f"mini:rl:{scope}:{int(user_id)}:{slot}"
    try:
        r = get_redis()
        count = int(r.incr(key))
        if count == 1:
            r.expire(key, int(window_sec) + 3)
    except Exception as exc:
        log.warning("rate-limit store unavailable: %s", exc)
        return

    if count > int(limit):
        raise HTTPException(status_code=429, detail="تعداد درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید.")


def enforce_events_rate_limit(user_id: int) -> None:
    enforce_rate_limit(
        scope="events",
        user_id=int(user_id),
        limit=int(MINI_RATE_LIMIT_EVENTS_PER_SEC),
        window_sec=1,
    )


def enforce_write_rate_limit(user_id: int) -> None:
    enforce_rate_limit(
        scope="write",
        user_id=int(user_id),
        limit=int(MINI_RATE_LIMIT_WRITE_PER_MIN),
        window_sec=60,
    )


def get_mini_user_id(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tg_init_data: str | None = Header(default=None, alias=TELEGRAM_INITDATA_HEADER),
    db: Session = Depends(get_db),
) -> int:
    bearer = _parse_bearer(authorization)
    if bearer:
        return verify_session_token(bearer)

    if x_tg_init_data:
        user_id, _ = _user_from_init_data(x_tg_init_data.strip(), db)
        return int(user_id)

    raise HTTPException(status_code=401, detail="احراز هویت انجام نشد.")


def exchange_init_data_for_session(init_data: str, db: Session) -> dict[str, Any]:
    cleaned = str(init_data or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="داده احراز هویت تلگرام الزامی است.")

    user_id, normalized_init_data = _user_from_init_data(cleaned, db)

    if not consume_init_data_nonce(normalized_init_data):
        raise HTTPException(status_code=409, detail="این نشست قبلاً استفاده شده است. مینی‌اپ را دوباره از منوی ربات باز کنید.")

    token, exp = issue_session_token(user_id)

    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": int(exp),
        "expires_in": max(0, int(exp - int(time.time()))),
        "user_id": int(user_id),
    }
