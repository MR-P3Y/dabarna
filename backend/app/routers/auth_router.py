from __future__ import annotations

import os
import time
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import AUTH_DEBUG_ENABLED
from app.services.user_service import UserService
from app.utils.tg_webapp import verify_init_data, TelegramInitDataError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/telegram", tags=["auth"])


class VerifyTelegramIn(BaseModel):
    init_data: str


class VerifyTelegramOut(BaseModel):
    ok: bool = True
    user_id: int
    tg_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class DebugInitDataIn(BaseModel):
    init_data: str


class DebugInitDataOut(BaseModel):
    ok: bool = True
    has_init_data: bool
    init_data_length: int
    has_user: bool
    user_id: int | None
    has_hash: bool
    hash_valid: bool | None
    error: str | None


@router.post("/_debug/verify-init-data", response_model=DebugInitDataOut)
def debug_verify_init_data(payload: DebugInitDataIn):
    """Debug endpoint to verify initData structure and hash without creating user."""
    if not AUTH_DEBUG_ENABLED:
        raise HTTPException(status_code=404, detail="not found")

    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    init_data = (payload.init_data or "").strip()

    result = DebugInitDataOut(
        ok=False,
        has_init_data=bool(init_data),
        init_data_length=len(init_data),
        has_user=False,
        user_id=None,
        has_hash=False,
        hash_valid=None,
        error=None,
    )

    if not init_data:
        result.error = "init_data is empty"
        return result

    if not bot_token:
        result.error = "TELEGRAM_BOT_TOKEN not configured on server"
        return result

    try:
        from app.utils.tg_webapp import parse_init_data
        parsed = parse_init_data(init_data)

        result.has_user = parsed.user is not None
        if parsed.user:
            result.user_id = parsed.user.get("id")

        result.has_hash = "hash" in parsed.data

        # Try to verify
        try:
            verify_init_data(init_data, bot_token=bot_token)
            result.hash_valid = True
            result.ok = True
        except TelegramInitDataError as e:
            result.hash_valid = False
            result.error = f"Hash verification failed: {str(e)}"

    except Exception as e:
        result.error = f"Parse error: {str(e)}"

    return result


@router.post("/verify", response_model=VerifyTelegramOut)
def verify_telegram(payload: VerifyTelegramIn, db: Session = Depends(get_db)):
    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not bot_token:
        # Fail-closed for prod: if server is not configured, don't allow login
        logger.warning("TELEGRAM_BOT_TOKEN not configured")
        raise HTTPException(status_code=503, detail="تأیید تلگرام بر روی سرور تنظیم نشده است")

    max_age = int(os.getenv("TELEGRAM_INITDATA_MAX_AGE_SECONDS", "86400") or "86400")
    init_data = (payload.init_data or "").strip()

    logger.info(f"Verify request: init_data length={len(init_data)}")

    # Parse and verify init_data with detailed error messages
    try:
        from app.utils.tg_webapp import parse_init_data
        parsed = parse_init_data(init_data)
        logger.info(f"Parsed: user={parsed.user is not None}, auth_date={parsed.auth_date}")
    except TelegramInitDataError as e:
        error_msg = str(e)
        logger.warning(f"Parse error: {error_msg}")
        raise HTTPException(status_code=401, detail=f"داده تلگرام نامعتبر: {error_msg}")
    except Exception as e:
        logger.error(f"Unexpected parse error: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="خطا در پردازش داده تلگرام")

    # Verify signature
    try:
        parsed = verify_init_data(init_data, bot_token=bot_token)
        logger.info("Hash verification passed")
    except TelegramInitDataError as e:
        error_msg = str(e)
        logger.warning(f"Hash verification failed: {error_msg}")
        raise HTTPException(status_code=401, detail=f"تأیید امضا شکست: {error_msg}")
    except Exception as e:
        logger.error(f"Unexpected verification error: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail="خطا در تأیید امضا")

    # Validate auth_date exists and is recent
    if parsed.auth_date is None:
        logger.warning("auth_date is missing")
        raise HTTPException(status_code=401, detail="داده تلگرام نامعتبر: auth_date موجود نیست")

    now = int(time.time())
    age = now - parsed.auth_date
    if max_age > 0 and age > max_age:
        logger.warning(f"auth_date too old: age={age}s, max={max_age}s")
        raise HTTPException(status_code=401, detail=f"داده تلگرام منقضی است (سن: {age}s)")

    # Extract user data
    user = parsed.user or {}
    tg_user_id = user.get("id")
    if not isinstance(tg_user_id, int):
        logger.warning(f"Invalid tg_user_id: {tg_user_id}")
        raise HTTPException(status_code=401, detail="داده تلگرام نامعتبر: شناسۀ کاربر موجود نیست")

    username = user.get("username")
    first_name = user.get("first_name")
    last_name = user.get("last_name")

    logger.info(f"Valid telegram user: id={tg_user_id}, username={username}")

    # Upsert user to database
    try:
        u = UserService.upsert(
            db,
            tg_user_id=tg_user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        db.commit()
        logger.info(f"Upserted user: id={u.id}")
    except Exception as e:
        logger.error(f"Error upserting user {tg_user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطا در ایجاد یا به‌روزرسانی کاربر")

    return VerifyTelegramOut(
        user_id=int(u.id),
        tg_user_id=int(u.tg_user_id),
        username=u.username,
        first_name=u.first_name,
        last_name=u.last_name,
    )
