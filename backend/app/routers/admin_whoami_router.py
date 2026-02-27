from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.admin_guard import get_admin_identity, AdminIdentity, AdminScope

router = APIRouter(prefix="/admin", tags=["admin-auth"])


class AdminWhoamiOut(BaseModel):
    ok: bool = True
    is_admin: bool
    role: str
    admin_user_id: int
    token_hint: str | None = None


@router.get("/whoami", response_model=AdminWhoamiOut)
def admin_whoami(identity: AdminIdentity = Depends(get_admin_identity)):
    # اگر این dependency رد شود، 401/403 را خودش می‌دهد.
    return AdminWhoamiOut(
        is_admin=True,
        role=identity.scope.value if isinstance(identity.scope, AdminScope) else str(identity.scope),
        admin_user_id=identity.user_id,
        token_hint=identity.token[:4] + "…" + identity.token[-4:] if identity.token else None,
    )
