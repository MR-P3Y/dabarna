"""Super-admin crypto destination planning (#30).

DRAFT / CANCELLED ONLY. Never changes .env addresses, active scanner
configuration, open invoices or wallet balances. Calling routes must enforce
get_mini_super_admin_identity; auditing shares the same DB transaction.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto import CryptoDepositRequest
from app.models.crypto_destination_version import CryptoDestinationVersion
from app.services.crypto_address_rotation_validation import (
    InvalidDepositAddress, masked_address, validate_deposit_address,
)
from app.services.crypto_deposit_service import OPEN_STATUSES


_ASSET = {"TRON": "USDT", "TON": "TON"}


def _current_address(network: str) -> str:
    if network == "TRON":
        return str(cfg.CRYPTO_TRON_USDT_ADDRESS or "")
    if network == "TON":
        return str(cfg.CRYPTO_TON_ADDRESS or "")
    raise HTTPException(status_code=400, detail="شبکه ارز دیجیتال پشتیبانی نمی‌شود.")


def _normalize(network: str, address: str) -> str:
    try:
        return validate_deposit_address(network, address)
    except InvalidDepositAddress as exc:
        raise HTTPException(status_code=400, detail="آدرس شبکه انتخاب‌شده نامعتبر است.") from exc


def _same_destination(network: str, old: str, new: str) -> bool:
    from app.services.crypto_address_rotation_validation import same_deposit_destination

    return same_deposit_destination(network, old, new)


def _latest(db: Session, *, network: str, asset: str, lock: bool = False):
    stmt = select(CryptoDestinationVersion).where(
        CryptoDestinationVersion.network == network,
        CryptoDestinationVersion.asset == asset,
    ).order_by(CryptoDestinationVersion.version.desc()).limit(1)
    if lock:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


class CryptoDestinationDraftService:
    @staticmethod
    def preview(
        db: Session, *, network: str, address: str, expected_version: int,
    ) -> dict[str, Any]:
        asset = _ASSET.get(network)
        if not asset:
            raise HTTPException(status_code=400, detail="شبکه نامعتبر است.")
        proposed = _normalize(network, address)
        current_raw = _current_address(network)
        if not current_raw:
            raise HTTPException(status_code=409, detail="آدرس فعلی شبکه روی سرور تنظیم نشده است.")
        try:
            current = validate_deposit_address(network, current_raw)
        except InvalidDepositAddress as exc:
            raise HTTPException(status_code=409, detail="آدرس فعلی سرور نیازمند بررسی دستی است.") from exc
        if _same_destination(network, current, proposed):
            raise HTTPException(status_code=409, detail="آدرس جدید با حساب مقصد فعلی یکسان است.")

        latest = _latest(db, network=network, asset=asset)
        current_version = int(latest.version) if latest else 0
        if current_version != int(expected_version):
            raise HTTPException(status_code=409, detail="نسخه آدرس تغییر کرده است؛ اطلاعات را تازه کنید.")
        if latest is not None and latest.state == "DRAFT":
            raise HTTPException(status_code=409, detail="برای این شبکه پیش‌نویس باز وجود دارد.")

        rows = db.execute(
            select(CryptoDepositRequest.destination_address).where(
                CryptoDepositRequest.network == network,
                CryptoDepositRequest.status.in_(OPEN_STATUSES),
            ).distinct()
        ).scalars().all()
        invoice_count = int(db.execute(
            select(func.count()).select_from(CryptoDepositRequest).where(
                CryptoDepositRequest.network == network,
                CryptoDepositRequest.status.in_(OPEN_STATUSES),
            )
        ).scalar_one())
        retained = []
        for item in rows:
            raw = str(item)
            # A malformed historical destination blocks further planning.
            try:
                old = validate_deposit_address(network, raw)
            except InvalidDepositAddress as exc:
                raise HTTPException(status_code=409, detail="یک فاکتور باز آدرس مقصد نامعتبر دارد.") from exc
            retained.append(masked_address(old))
        return {
            "network": network,
            "asset": asset,
            "current_address": current,
            "new_address": proposed,
            "current_masked": masked_address(current),
            "new_masked": masked_address(proposed),
            "expected_version": current_version,
            "proposed_version": current_version + 1,
            "open_invoice_count": invoice_count,
            "open_destination_masks": sorted(set(retained)),
            "can_activate": False,
            "blocked_by": "ACTIVATION_NOT_IMPLEMENTED",
        }

    @staticmethod
    def create_draft(
        db: Session, *, network: str, address: str, reason: str,
        expected_version: int, operation_id: str, actor_id: int,
    ) -> tuple[CryptoDestinationVersion, bool, dict[str, Any]]:
        existing = db.execute(select(CryptoDestinationVersion).where(
            CryptoDestinationVersion.operation_id == operation_id,
        )).scalar_one_or_none()
        if existing:
            canonical = _normalize(network, address)
            if (
                int(existing.requested_by) == int(actor_id)
                and existing.network == network
                and existing.address == canonical
                and existing.reason == reason
                and int(existing.version) == int(expected_version) + 1
            ):
                return existing, True, {"network": network, "asset": _ASSET.get(network)}
            raise HTTPException(status_code=409, detail="شناسه عملیات پیش‌تر برای درخواست متفاوت استفاده شده است.")

        preview = CryptoDestinationDraftService.preview(
            db, network=network, address=address, expected_version=expected_version,
        )
        row = CryptoDestinationVersion(
            network=network,
            asset=preview["asset"],
            address=preview["new_address"],
            previous_address=preview["current_address"],
            version=int(preview["proposed_version"]),
            state="DRAFT",
            requested_by=int(actor_id),
            reason=reason,
            operation_id=operation_id,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="درخواست هم‌زمان یا تکراری شناسایی شد؛ دوباره بررسی کنید.") from exc
        except OperationalError as exc:
            # InnoDB concurrent gap locks can deadlock (1213) or time out (1205).
            # Surface a safe conflict instead of retrying the financial write.
            db.rollback()
            code = getattr(getattr(exc, "orig", None), "args", (None,))[0]
            if code in (1205, 1213):
                raise HTTPException(status_code=409, detail="تغییر هم‌زمان ثبت شد؛ وضعیت را تازه کنید.") from exc
            raise
        return row, False, preview

    @staticmethod
    def cancel_draft(
        db: Session, *, draft_id: int,
    ) -> tuple[CryptoDestinationVersion, bool]:
        row = db.execute(select(CryptoDestinationVersion).where(
            CryptoDestinationVersion.id == int(draft_id)
        ).with_for_update()).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="پیش‌نویس پیدا نشد.")
        if row.state == "CANCELLED":
            return row, True
        if row.state != "DRAFT":
            raise HTTPException(status_code=409, detail="این نسخه دیگر قابل لغو نیست.")
        row.state = "CANCELLED"
        db.flush()
        return row, False

    @staticmethod
    def versions(db: Session, *, network: str) -> list[dict[str, Any]]:
        asset = _ASSET.get(network)
        if not asset:
            raise HTTPException(status_code=400, detail="شبکه نامعتبر است.")
        rows = db.execute(
            select(CryptoDestinationVersion)
            .where(CryptoDestinationVersion.network == network,
                   CryptoDestinationVersion.asset == asset)
            .order_by(CryptoDestinationVersion.version.desc())
            .limit(50)
        ).scalars().all()
        return [
            {
                "id": int(row.id), "network": network, "asset": asset,
                "version": int(row.version), "state": row.state,
                "address_masked": masked_address(row.address),
                "requested_by": int(row.requested_by),
                "activated_by": int(row.activated_by) if row.activated_by else None,
                "created_at": str(row.created_at),
                "operation_id": row.operation_id,
            }
            for row in rows
        ]
