from __future__ import annotations

from collections import OrderedDict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity, AdminScope, require_admin_any
from app.core.config import RBAC_OWNER_USER_ID
from app.core.db import get_db
from app.models.rbac import Role, UserRole
from app.models.user import User
from app.services.admin_audit_service import AdminAuditService

router = APIRouter(prefix="/admin/rbac", tags=["admin-rbac"])

ADMIN_ROLE_NAMES = ("ADMIN", "SUPER_ADMIN")


class AdminAccountOut(BaseModel):
    user_id: int
    tg_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    roles: list[str]


class AdminAccountListOut(BaseModel):
    total: int
    items: list[AdminAccountOut]


class GrantAdminIn(BaseModel):
    tg_user_id: int = Field(gt=0)
    role: Literal["ADMIN", "SUPER_ADMIN"] = "ADMIN"


class RevokeAdminIn(BaseModel):
    tg_user_id: int = Field(gt=0)
    role: Literal["ADMIN", "SUPER_ADMIN", "ALL"] = "ALL"


def _require_super_admin(identity: AdminIdentity = Depends(require_admin_any)) -> AdminIdentity:
    if identity.scope != AdminScope.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="super admin required")
    if RBAC_OWNER_USER_ID is None:
        raise HTTPException(status_code=503, detail="rbac owner is not configured")
    if identity.user_id is None or int(identity.user_id) != int(RBAC_OWNER_USER_ID):
        raise HTTPException(status_code=403, detail="super admin owner required")
    return identity


def _role_id_map(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Role.name, Role.id).where(Role.name.in_(ADMIN_ROLE_NAMES))
    ).all()
    out = {str(name): int(role_id) for name, role_id in rows}
    for needed in ADMIN_ROLE_NAMES:
        if needed not in out:
            raise HTTPException(status_code=500, detail=f"role '{needed}' is not seeded")
    return out


def _super_admin_count(db: Session, role_ids: dict[str, int]) -> int:
    rows = db.execute(
        select(UserRole.user_id).where(UserRole.role_id == int(role_ids["SUPER_ADMIN"]))
    ).scalars().all()
    return len({int(uid) for uid in rows})


def _get_or_create_user_by_tg(db: Session, tg_user_id: int) -> User:
    user = db.execute(
        select(User).where(User.tg_user_id == int(tg_user_id))
    ).scalar_one_or_none()
    if user:
        return user
    user = User(tg_user_id=int(tg_user_id))
    db.add(user)
    db.flush()
    return user


def _build_admin_account(db: Session, user_id: int) -> AdminAccountOut:
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
        .where(User.id == int(user_id))
        .where(Role.name.in_(ADMIN_ROLE_NAMES))
        .order_by(Role.name.asc())
    ).all()

    if not rows:
        raise HTTPException(status_code=404, detail="admin account not found")

    first = rows[0]
    roles = sorted({str(r[5]) for r in rows})
    return AdminAccountOut(
        user_id=int(first[0]),
        tg_user_id=int(first[1]),
        username=first[2],
        first_name=first[3],
        last_name=first[4],
        roles=roles,
    )


@router.get("/admins", response_model=AdminAccountListOut)
def list_admin_accounts(
    _: AdminIdentity = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
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

    grouped: "OrderedDict[int, dict]" = OrderedDict()
    for user_id, tg_user_id, username, first_name, last_name, role_name in rows:
        uid = int(user_id)
        rec = grouped.get(uid)
        if rec is None:
            rec = {
                "user_id": uid,
                "tg_user_id": int(tg_user_id),
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "roles": set(),
            }
            grouped[uid] = rec
        rec["roles"].add(str(role_name))

    items = [
        AdminAccountOut(
            user_id=rec["user_id"],
            tg_user_id=rec["tg_user_id"],
            username=rec["username"],
            first_name=rec["first_name"],
            last_name=rec["last_name"],
            roles=sorted(rec["roles"]),
        )
        for rec in grouped.values()
    ]
    return AdminAccountListOut(total=len(items), items=items)


@router.post("/admins/grant", response_model=AdminAccountOut)
def grant_admin_account(
    payload: GrantAdminIn,
    request: Request,
    identity: AdminIdentity = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    role_ids = _role_id_map(db)
    role_id = int(role_ids[payload.role])
    user = _get_or_create_user_by_tg(db, int(payload.tg_user_id))

    existing = db.execute(
        select(UserRole)
        .where(UserRole.user_id == int(user.id))
        .where(UserRole.role_id == role_id)
    ).scalar_one_or_none()
    already_had_role = existing is not None
    if existing is None:
        db.add(UserRole(user_id=int(user.id), role_id=role_id))
        db.flush()
    AdminAuditService.record(
        db,
        admin=identity,
        action="admin.grant",
        target_type="user",
        target_id=int(user.id),
        request=request,
        details={
            "user_id": int(user.id),
            "tg_user_id": int(user.tg_user_id),
            "role": str(payload.role),
            "already_had_role": bool(already_had_role),
        },
    )
    db.commit()
    return _build_admin_account(db, int(user.id))


@router.post("/admins/revoke")
def revoke_admin_account(
    payload: RevokeAdminIn,
    request: Request,
    identity: AdminIdentity = Depends(_require_super_admin),
    db: Session = Depends(get_db),
):
    role_ids = _role_id_map(db)
    user = db.execute(
        select(User).where(User.tg_user_id == int(payload.tg_user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    target_role_ids: list[int]
    if payload.role == "ALL":
        target_role_ids = [int(role_ids["ADMIN"]), int(role_ids["SUPER_ADMIN"])]
    else:
        target_role_ids = [int(role_ids[payload.role])]

    user_role_rows = db.execute(
        select(UserRole.role_id)
        .where(UserRole.user_id == int(user.id))
        .where(UserRole.role_id.in_(target_role_ids))
    ).scalars().all()
    role_set = {int(x) for x in user_role_rows}
    role_names_by_id = {int(v): str(k) for k, v in role_ids.items()}
    removed_roles = [role_names_by_id.get(int(x), str(x)) for x in sorted(role_set)]
    if not role_set:
        AdminAuditService.record(
            db,
            admin=identity,
            action="admin.revoke",
            target_type="user",
            target_id=int(user.id),
            request=request,
            details={
                "user_id": int(user.id),
                "tg_user_id": int(user.tg_user_id),
                "requested_role": str(payload.role),
                "removed": 0,
                "removed_roles": [],
            },
        )
        db.commit()
        return {"ok": True, "removed": 0, "user_id": int(user.id), "tg_user_id": int(user.tg_user_id)}

    removing_super = int(role_ids["SUPER_ADMIN"]) in role_set
    if removing_super:
        if identity.user_id is not None and int(identity.user_id) == int(user.id):
            raise HTTPException(status_code=409, detail="cannot revoke your own super admin role")
        if _super_admin_count(db, role_ids) <= 1:
            raise HTTPException(status_code=409, detail="cannot revoke last super admin")

    delete_result = db.execute(
        delete(UserRole)
        .where(UserRole.user_id == int(user.id))
        .where(UserRole.role_id.in_(list(role_set)))
    )
    AdminAuditService.record(
        db,
        admin=identity,
        action="admin.revoke",
        target_type="user",
        target_id=int(user.id),
        request=request,
        details={
            "user_id": int(user.id),
            "tg_user_id": int(user.tg_user_id),
            "requested_role": str(payload.role),
            "removed": int(delete_result.rowcount or 0),
            "removed_roles": removed_roles,
        },
    )
    db.commit()
    return {
        "ok": True,
        "removed": int(delete_result.rowcount or 0),
        "user_id": int(user.id),
        "tg_user_id": int(user.tg_user_id),
    }
