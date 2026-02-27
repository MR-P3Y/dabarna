from __future__ import annotations

from fastapi import Header, HTTPException, Request, Depends
from typing import Optional
from sqlalchemy.orm import Session

from app.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_INITDATA_MAX_AGE_SECONDS, TELEGRAM_INITDATA_HEADER, ADMIN_TOKEN_MAP, BOT_SERVICE_TOKEN, BOT_SERVICE_USER_ID
from app.core.db import get_db
from app.services.user_service import UserService
from app.utils.tg_webapp import verify_init_data_with_age, TelegramInitDataError


def _parse_int(value: str, *, field: str) -> int:
    try:
        return int(value)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid {field}")


def _read_init_data(x_tg_init_data: Optional[str]) -> str:
    if not x_tg_init_data:
        raise HTTPException(status_code=401, detail="missing telegram init data")
    return x_tg_init_data.strip()


def _load_tg_user(init_data: str, db: Session) -> int:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="telegram bot token not configured")
    try:
        parsed = verify_init_data_with_age(
            init_data=init_data,
            bot_token=TELEGRAM_BOT_TOKEN,
            max_age_seconds=TELEGRAM_INITDATA_MAX_AGE_SECONDS,
        )
    except TelegramInitDataError as e:
        raise HTTPException(status_code=401, detail=f"invalid telegram init data: {str(e)}")

    user = parsed.user or {}
    tg_user_id = user.get("id")
    if not isinstance(tg_user_id, int):
        raise HTTPException(status_code=401, detail="invalid telegram user id")

    u = UserService.upsert(
        db,
        tg_user_id=tg_user_id,
        username=user.get("username"),
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
    )
    return int(u.id)


def require_user_header(x_user_id: Optional[str]) -> int:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="missing user header")
    return _parse_int(x_user_id, field="X-User-Id")


def get_current_user_id(
    x_tg_init_data: Optional[str] = Header(None, alias=TELEGRAM_INITDATA_HEADER),
    x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> int:
    """Dependency to extract current user ID.

    Priority:
    1. X-User-Token (from ADMIN_TOKEN_MAP or BOT_SERVICE_TOKEN)
    2. X-Tg-Init-Data (Telegram WebApp)
    3. X-User-Id (optional, must match one of above if provided)
    """
    # Try X-User-Token first
    if x_user_token:
        x_user_token = x_user_token.strip()

        # Check BOT_SERVICE_TOKEN
        if BOT_SERVICE_TOKEN and x_user_token == BOT_SERVICE_TOKEN:
            uid = BOT_SERVICE_USER_ID
            # Optional: verify X-User-Id matches if provided
            if x_user_id is not None:
                header_uid = _parse_int(x_user_id, field="X-User-Id")
                if header_uid != uid:
                    raise HTTPException(status_code=403, detail="forbidden")
            return uid

        # Check ADMIN_TOKEN_MAP
    # Fall back to Telegram initData
    if not x_tg_init_data:
        raise HTTPException(status_code=401, detail="missing user authorization")

    init_data = x_tg_init_data.strip()
    uid = _load_tg_user(init_data, db)

    # Optional: verify X-User-Id matches if provided
    if x_user_id is not None:
        header_uid = _parse_int(x_user_id, field="X-User-Id")
        if header_uid != uid:
            raise HTTPException(status_code=403, detail="forbidden")

    return uid


def guard_path_user_id(param_name: str = "user_id"):
    """
    Dependency that enforces:
      - Telegram initData header exists
      - equals request.path_params[param_name]
    """
    def _dep(
        request: Request,
        x_tg_init_data: Optional[str] = Header(None, alias=TELEGRAM_INITDATA_HEADER),
        db: Session = Depends(get_db),
    ) -> int:
        uid = _load_tg_user(_read_init_data(x_tg_init_data), db)
        if param_name not in request.path_params:
            raise HTTPException(status_code=500, detail="server misconfigured (missing path param)")
        path_uid = _parse_int(str(request.path_params[param_name]), field=param_name)
        if uid != path_uid:
            raise HTTPException(status_code=403, detail="forbidden")
        return uid

    return _dep


def guard_body_user_id(body_user_id: int):
    """
    Helper for routers: compares Telegram user to body.user_id
    """
    def _dep(
        x_tg_init_data: Optional[str] = Header(None, alias=TELEGRAM_INITDATA_HEADER),
        db: Session = Depends(get_db),
    ) -> int:
        uid = _load_tg_user(_read_init_data(x_tg_init_data), db)
        if uid != int(body_user_id):
            raise HTTPException(status_code=403, detail="forbidden")
        return uid

    return _dep
