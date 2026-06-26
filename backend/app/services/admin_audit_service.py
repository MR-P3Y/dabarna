from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity
from app.models.admin_audit import AdminAuditLog


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
        client_ip = None
        request_method = None
        request_path = None
        if request is not None:
            client_ip = request.headers.get("CF-Connecting-IP")
            if not client_ip and request.client:
                client_ip = request.client.host
            request_method = request.method
            request_path = str(request.url.path)
        row = AdminAuditLog(
            actor_user_id=int(user_id),
            actor_scope="USER",
            action=action,
            target_type=target_type,
            target_id=target_id,
            client_ip=client_ip,
            request_method=request_method,
            request_path=request_path,
            details_json=details,
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
        client_ip = None
        request_method = None
        request_path = None

        if request is not None:
            client_ip = request.headers.get("CF-Connecting-IP")
            if not client_ip and request.client:
                client_ip = request.client.host
            request_method = request.method
            request_path = str(request.url.path)

        row = AdminAuditLog(
            actor_user_id=admin.user_id,
            actor_scope=str(admin.scope.value if hasattr(admin.scope, "value") else admin.scope),
            action=action,
            target_type=target_type,
            target_id=target_id,
            client_ip=client_ip,
            request_method=request_method,
            request_path=request_path,
            details_json=details,
        )
        db.add(row)
        db.flush()
        return row
