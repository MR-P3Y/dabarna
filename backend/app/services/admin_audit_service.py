from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity
from app.models.admin_audit import AdminAuditLog
from app.models.user import User


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _user_snapshot(db: Session, user_id: int | None, *, prefix: str) -> dict[str, Any]:
    uid = _safe_int(user_id)
    if uid is None or uid <= 0:
        return {}
    out: dict[str, Any] = {f"{prefix}_user_id": uid}
    try:
        user = db.get(User, uid)
    except Exception:
        user = None
    if user is not None:
        out[f"{prefix}_tg_user_id"] = _safe_int(getattr(user, "tg_user_id", None))
        out[f"{prefix}_username"] = getattr(user, "username", None)
        out[f"{prefix}_first_name"] = getattr(user, "first_name", None)
        out[f"{prefix}_last_name"] = getattr(user, "last_name", None)
    return out


def _request_snapshot(request: Request | None) -> dict[str, Any]:
    if request is None:
        return {}
    client_ip = request.headers.get("CF-Connecting-IP")
    if not client_ip and request.client:
        client_ip = request.client.host
    return {
        "client_ip": client_ip,
        "request_method": request.method,
        "request_path": str(request.url.path),
        "user_agent": request.headers.get("User-Agent"),
        "source": "mini_app" if str(request.url.path).startswith("/mini-api/") else "api",
    }


def _merge_details(
    db: Session,
    *,
    details: dict[str, Any] | None,
    actor_user_id: int | None,
    actor_scope: str,
    request: Request | None,
) -> dict[str, Any]:
    out: dict[str, Any] = dict(details or {})
    for k, v in _user_snapshot(db, actor_user_id, prefix="actor").items():
        out.setdefault(k, v)
    out.setdefault("actor_scope", actor_scope)
    for k, v in _request_snapshot(request).items():
        out.setdefault(k, v)

    target_user_id = out.get("target_user_id") or out.get("user_id")
    for k, v in _user_snapshot(db, _safe_int(target_user_id), prefix="target").items():
        out.setdefault(k, v)

    return out


class AdminAuditService:
    @staticmethod
    def record_user(
        db: Session,
        *,
        user_id: int,
        action: str,
        target_type: str,
        target_id: int | None = None,
        details: dict[str, Any] | None = None,
        request: Request | None = None,
    ) -> AdminAuditLog:
        req = _request_snapshot(request)
        row = AdminAuditLog(
            actor_user_id=int(user_id),
            actor_scope="USER",
            action=action,
            target_type=target_type,
            target_id=target_id,
            client_ip=req.get("client_ip"),
            request_method=req.get("request_method"),
            request_path=req.get("request_path"),
            details_json=_merge_details(
                db,
                details=details,
                actor_user_id=int(user_id),
                actor_scope="USER",
                request=request,
            ),
        )
        db.add(row)
        db.flush()
        return row

    @staticmethod
    def record(
        db: Session,
        *,
        admin: AdminIdentity,
        action: str,
        target_type: str,
        target_id: int | None = None,
        details: dict[str, Any] | None = None,
        request: Request | None = None,
    ) -> AdminAuditLog:
        req = _request_snapshot(request)
        actor_scope = str(admin.scope.value if hasattr(admin.scope, "value") else admin.scope)
        row = AdminAuditLog(
            actor_user_id=admin.user_id,
            actor_scope=actor_scope,
            action=action,
            target_type=target_type,
            target_id=target_id,
            client_ip=req.get("client_ip"),
            request_method=req.get("request_method"),
            request_path=req.get("request_path"),
            details_json=_merge_details(
                db,
                details=details,
                actor_user_id=admin.user_id,
                actor_scope=actor_scope,
                request=request,
            ),
        )
        db.add(row)
        db.flush()
        return row
