from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.core.admin_guard import AdminIdentity, get_admin_identity
from app.core.db import get_db
from app.core.user_guard import get_current_user_id
from app.models.crypto import CryptoDepositRequest
from app.schemas.crypto import (
    CryptoAdminRejectIn,
    CryptoDepositCreateIn,
    CryptoDepositListOut,
    CryptoDepositOut,
    CryptoOptionsOut,
    CryptoTxClaimIn,
    crypto_deposit_dict,
)
from app.services.admin_audit_service import AdminAuditService
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_worker import CryptoDepositWorker

router = APIRouter(prefix="/crypto", tags=["crypto"])


def _to_out(row: CryptoDepositRequest) -> CryptoDepositOut:
    return CryptoDepositOut(**crypto_deposit_dict(row))


@router.get("/options", response_model=CryptoOptionsOut)
def crypto_options(
    current_user_id: int = Depends(get_current_user_id),
):
    _ = current_user_id
    options = CryptoDepositService.enabled_options()
    return CryptoOptionsOut(
        enabled=bool(cfg.CRYPTO_PAYMENTS_ENABLED and options),
        min_toman_amount=int(cfg.CRYPTO_MIN_TOMAN_AMOUNT),
        max_toman_amount=int(cfg.CRYPTO_MAX_TOMAN_AMOUNT),
        invoice_expire_minutes=int(cfg.CRYPTO_INVOICE_EXPIRE_MINUTES),
        options=options,
    )


@router.post("/deposits", response_model=CryptoDepositOut)
def create_crypto_deposit(
    payload: CryptoDepositCreateIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    try:
        invoice = CryptoDepositService.create_invoice(
            db,
            user_id=int(current_user_id),
            amount_toman=int(payload.amount_toman),
            network=payload.network,
        )
        db.commit()
        db.refresh(invoice)
        return _to_out(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="صدور فاکتور ارز دیجیتال ناموفق بود.")


@router.get("/deposits/me", response_model=CryptoDepositListOut)
def list_my_crypto_deposits(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    total = db.execute(
        select(func.count(CryptoDepositRequest.id)).where(
            CryptoDepositRequest.user_id == int(current_user_id)
        )
    ).scalar_one()
    rows = CryptoDepositService.list_owned(
        db,
        user_id=int(current_user_id),
        limit=int(limit),
        offset=int(offset),
    )
    return CryptoDepositListOut(
        total=int(total or 0),
        limit=int(limit),
        offset=int(offset),
        items=[_to_out(row) for row in rows],
    )


@router.get("/deposits/{invoice_id}", response_model=CryptoDepositOut)
def get_crypto_deposit(
    invoice_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    return _to_out(
        CryptoDepositService.get_owned(
            db,
            invoice_id=int(invoice_id),
            user_id=int(current_user_id),
        )
    )


@router.post("/deposits/{invoice_id}/tx-hash", response_model=CryptoDepositOut)
def claim_crypto_tx_hash(
    invoice_id: int,
    payload: CryptoTxClaimIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    try:
        invoice = CryptoDepositService.claim_tx_hash(
            db,
            invoice_id=int(invoice_id),
            user_id=int(current_user_id),
            tx_hash=payload.tx_hash,
        )
        db.commit()
        db.refresh(invoice)
        return _to_out(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="ثبت هش تراکنش ناموفق بود.")


@router.get("/admin/deposits", response_model=CryptoDepositListOut)
def admin_list_crypto_deposits(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    _ = admin
    query = select(CryptoDepositRequest)
    count_query = select(func.count(CryptoDepositRequest.id))
    if status:
        normalized = status.strip().upper()
        query = query.where(CryptoDepositRequest.status == normalized)
        count_query = count_query.where(CryptoDepositRequest.status == normalized)
    total = db.execute(count_query).scalar_one()
    rows = db.execute(
        query.order_by(CryptoDepositRequest.id.desc()).offset(int(offset)).limit(int(limit))
    ).scalars().all()
    return CryptoDepositListOut(
        total=int(total or 0),
        limit=int(limit),
        offset=int(offset),
        items=[_to_out(row) for row in rows],
    )


@router.post("/admin/deposits/{invoice_id}/approve", response_model=CryptoDepositOut)
def admin_approve_crypto_deposit(
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
                "network": str(invoice.network),
                "asset": str(invoice.asset),
                "amount_toman": int(invoice.amount_toman),
                "amount_crypto": crypto_deposit_dict(invoice)["amount_crypto"],
                "tx_hash": invoice.tx_hash,
                "wallet_tx_id": int(tx.id),
            },
        )
        db.commit()
        db.refresh(invoice)
        return _to_out(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="تایید واریز ارز دیجیتال ناموفق بود.")


@router.post("/admin/deposits/{invoice_id}/reject", response_model=CryptoDepositOut)
def admin_reject_crypto_deposit(
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
        db.refresh(invoice)
        return _to_out(invoice)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="رد واریز ارز دیجیتال ناموفق بود.")


@router.post("/admin/scan")
def admin_scan_crypto_deposits(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    stats = CryptoDepositWorker.run_once()
    AdminAuditService.record(
        db,
        admin=admin,
        action="crypto.deposit.scan",
        target_type="crypto_deposit_request",
        request=request,
        details=stats,
    )
    db.commit()
    return {"ok": True, **stats}
