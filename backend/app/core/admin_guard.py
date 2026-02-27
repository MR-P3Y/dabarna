from enum import Enum
from typing import Optional
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import (
    ADMIN_AUTH_ENABLED,
    ADMIN_AUTH_HEADER,
    ADMIN_TOKEN_MAP,
    SUPER_ADMIN_TOKENS,
    ADMIN_TOKENS,
    ADMIN_TOKEN_ROLE_MAP,
    BOT_SERVICE_TOKEN,
    BOT_SERVICE_USER_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_INITDATA_MAX_AGE_SECONDS,
    TELEGRAM_INITDATA_HEADER,
)
from app.core.db import get_db
from app.models.rbac import Role, UserRole
from app.services.user_service import UserService
from app.utils.tg_webapp import verify_init_data_with_age, TelegramInitDataError

FORBIDDEN_DETAIL = "forbidden"

class AdminScope(str, Enum):
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"

class AdminIdentity:
    def __init__(self, scope: AdminScope, token: str, user_id: Optional[int] = None):
        self.scope = scope
        self.token = token
        self.user_id = user_id

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


def _check_admin_token(token: str) -> Optional[AdminIdentity]:
    """Check if token is a valid admin token. Returns AdminIdentity or None."""
    if not token or not token.strip():
        return None

    token = token.strip()

    # Check if it's BOT_SERVICE_TOKEN (special case for bot)
    if BOT_SERVICE_TOKEN and token == BOT_SERVICE_TOKEN:
        return AdminIdentity(scope=AdminScope.ADMIN, token=token, user_id=BOT_SERVICE_USER_ID)

    # Check if it's in ADMIN_TOKEN_MAP
    if token not in ADMIN_TOKEN_MAP:
        return None

    user_id = ADMIN_TOKEN_MAP[token]

    # Determine scope from ADMIN_TOKEN_ROLE_MAP
    role = ADMIN_TOKEN_ROLE_MAP.get(token, "ADMIN")
    scope = AdminScope.SUPER_ADMIN if role == "SUPER_ADMIN" else AdminScope.ADMIN

    return AdminIdentity(scope=scope, token=token, user_id=user_id)


def require_admin_any(
    x_tg_init_data: Optional[str] = Header(default=None, alias=TELEGRAM_INITDATA_HEADER),
    x_admin_token: Optional[str] = Header(default=None, alias=ADMIN_AUTH_HEADER),
    db: Session = Depends(get_db),
) -> AdminIdentity:
    if not ADMIN_AUTH_ENABLED:
        # در حالت غیرفعال: اجازه بده (ولی با scope admin)
        return AdminIdentity(scope=AdminScope.ADMIN, token="DISABLED", user_id=None)

    # ابتدا X-Admin-Token را بررسی کن
    if x_admin_token:
        admin_identity = _check_admin_token(x_admin_token)
        if admin_identity:
            return admin_identity

    # سپس Telegram initData را استفاده کن
    if not x_tg_init_data:
        raise HTTPException(status_code=401, detail="missing authorization")

    init_data = x_tg_init_data.strip()
    user_id = _load_tg_user(init_data, db)

    role_names = db.execute(
        select(Role.name)
        .select_from(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    ).scalars().all()

    if "SUPER_ADMIN" in role_names:
        return AdminIdentity(scope=AdminScope.SUPER_ADMIN, token="TG", user_id=user_id)
    if "ADMIN" in role_names:
        return AdminIdentity(scope=AdminScope.ADMIN, token="TG", user_id=user_id)

    raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)


def get_admin_identity(
    x_tg_init_data: Optional[str] = Header(default=None, alias=TELEGRAM_INITDATA_HEADER),
    x_admin_token: Optional[str] = Header(default=None, alias=ADMIN_AUTH_HEADER),
    db: Session = Depends(get_db),
) -> AdminIdentity:
    """Compatibility wrapper for older imports that expect `get_admin_identity`.

    Routers still import `get_admin_identity` in several places; delegate to
    `require_admin_any` for the actual logic.
    """
    return require_admin_any(
        x_tg_init_data=x_tg_init_data,
        x_admin_token=x_admin_token,
        db=db,
    )
