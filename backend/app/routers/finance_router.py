# app/routers/finance_router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.db import get_db
from app.core.user_guard import get_current_user_id
from app.core.admin_guard import get_admin_identity, AdminIdentity

from app.models.finance import DepositRequest, WithdrawRequest, GatewayPayment
from app.schemas.finance import (
    CreateDepositIn,
    UploadReceiptIn,
    CreateWithdrawIn,
    DepositOut,
    WithdrawOut,
    ApproveDepositIn,
    ApproveWithdrawIn,
    MarkWithdrawPaidIn,
    RejectWithdrawIn,
    InitiateGatewayPaymentIn,
    GatewayPaymentOut,
    VerifyGatewayPaymentIn,
    FailGatewayPaymentIn,
)
from app.services.finance_service import FinanceService
from app.services.gateway_service import GatewayFactory, get_supported_gateways

router = APIRouter(prefix="/finance", tags=["finance"])


def _get_deposit_owned_by_user(db: Session, deposit_id: int, user_id: int) -> DepositRequest:
    dr = db.execute(
        select(DepositRequest).where(DepositRequest.id == deposit_id)
    ).scalar_one_or_none()
    if not dr:
        raise HTTPException(status_code=404, detail="deposit_request not found")
    if dr.user_id != user_id:
        raise HTTPException(status_code=403, detail="forbidden")
    return dr


def _get_gateway_payment_owned_by_user(db: Session, gp_id: int, user_id: int) -> GatewayPayment:
    gp = db.get(GatewayPayment, gp_id)
    if not gp:
        raise HTTPException(status_code=404, detail="gateway_payment not found")
    if gp.user_id != user_id:
        raise HTTPException(status_code=403, detail="forbidden")
    return gp


# ---------- Deposits (user) ----------
@router.post("/deposits", response_model=DepositOut)
def create_deposit(
    data: CreateDepositIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    try:
        # اگر پروژه‌ات از create_deposit_request استفاده می‌کند:
        dr = FinanceService.create_deposit_request(db, current_user_id, data.amount)
        db.commit()
        return DepositOut(
            id=dr.id,
            user_id=dr.user_id,
            amount=dr.amount,
            status=dr.status,
            receipt_file_id=dr.receipt_file_id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        # اینجا عمداً پیام کلی می‌دیم (production)
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/deposits/{deposit_id}/receipt", response_model=DepositOut)
def upload_receipt(
    deposit_id: int,
    data: UploadReceiptIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    # مالکیت را همینجا enforce می‌کنیم
    _ = _get_deposit_owned_by_user(db, deposit_id, current_user_id)

    try:
        dr = FinanceService.upload_receipt(db, deposit_id, data.receipt_file_id)
        db.commit()
        return DepositOut(
            id=dr.id,
            user_id=dr.user_id,
            amount=dr.amount,
            status=dr.status,
            receipt_file_id=dr.receipt_file_id,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


# ---------- Withdraws (user) ----------
@router.post("/withdraws", response_model=WithdrawOut)
def create_withdraw(
    data: CreateWithdrawIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    try:
        payload = data.model_dump()
        payload["user_id"] = current_user_id
        wr = FinanceService.create_withdraw_request(db, payload)
        db.commit()
        return WithdrawOut(
            id=wr.id,
            user_id=wr.user_id,
            amount=wr.amount,
            status=wr.status,
            full_name=wr.full_name,
            iban=wr.iban,
            card_number=wr.card_number,
            account_number=wr.account_number,
            paid_tracking=wr.paid_tracking,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


# ---------- Admin endpoints ----------
@router.get("/admin/deposits/pending", response_model=list[DepositOut])
def list_pending_deposits(
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    rows = db.execute(
        select(DepositRequest)
        .where(DepositRequest.status == "PENDING_REVIEW")
        .order_by(DepositRequest.id.desc())
    ).scalars().all()

    return [
        DepositOut(id=r.id, user_id=r.user_id, amount=r.amount, status=r.status, receipt_file_id=r.receipt_file_id)
        for r in rows
    ]


@router.post("/admin/deposits/{deposit_id}/approve")
def approve_deposit(
    deposit_id: int,
    data: ApproveDepositIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        dr, tx = FinanceService.approve_deposit(
            db,
            deposit_id,
            admin_user_id=admin.user_id,
            idempotency_key=data.idempotency_key,
        )
        db.commit()
        return {"deposit_id": dr.id, "wallet_tx_id": tx.id, "status": dr.status, "reviewed_by": admin.user_id}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/admin/deposits/{deposit_id}/reject")
def reject_deposit(
    deposit_id: int,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        dr = FinanceService.reject_deposit(db, deposit_id, admin_user_id=admin.user_id)
        db.commit()
        return {"deposit_id": dr.id, "status": dr.status, "reviewed_by": admin.user_id}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/admin/withdraws/pending", response_model=list[WithdrawOut])
def list_pending_withdraws(
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    rows = db.execute(
        select(WithdrawRequest)
        .where(WithdrawRequest.status == "PENDING")
        .order_by(WithdrawRequest.id.desc())
    ).scalars().all()

    return [
        WithdrawOut(
            id=r.id,
            user_id=r.user_id,
            amount=r.amount,
            status=r.status,
            full_name=r.full_name,
            iban=r.iban,
            card_number=r.card_number,
            account_number=r.account_number,
            paid_tracking=r.paid_tracking,
        )
        for r in rows
    ]


@router.post("/admin/withdraws/{withdraw_id}/approve")
def approve_withdraw(
    withdraw_id: int,
    data: ApproveWithdrawIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        wr, tx = FinanceService.approve_withdraw(
            db,
            withdraw_id,
            admin_user_id=admin.user_id,
            idempotency_key=data.idempotency_key,
        )
        db.commit()
        return {"withdraw_id": wr.id, "wallet_tx_id": tx.id, "status": wr.status, "reviewed_by": admin.user_id}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/admin/withdraws/{withdraw_id}/reject")
def reject_withdraw(
    withdraw_id: int,
    data: RejectWithdrawIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        wr = FinanceService.reject_withdraw(
            db=db,
            withdraw_id=withdraw_id,
            admin_user_id=admin.user_id,
            reason=data.reason,
        )
        db.commit()
        return {"withdraw_id": wr.id, "status": wr.status, "reviewed_by": admin.user_id}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/admin/withdraws/{withdraw_id}/paid")
def mark_paid(
    withdraw_id: int,
    data: MarkWithdrawPaidIn,
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    try:
        wr = FinanceService.mark_withdraw_paid(
            db,
            withdraw_id,
            admin_user_id=admin.user_id,
            paid_tracking=data.paid_tracking,
        )
        db.commit()
        return {
            "withdraw_id": wr.id,
            "status": wr.status,
            "paid_tracking": wr.paid_tracking,
            "reviewed_by": admin.user_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


# ---------- Gateway Payments (Online Payment) ----------

@router.post("/gateway/initiate", response_model=GatewayPaymentOut)
def initiate_gateway_payment(
    data: InitiateGatewayPaymentIn,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    """
    Initiate an online payment via gateway (ZarinPal, Stripe, PaddlePay)
    Returns gateway payment record with authority and ref_id
    """
    try:
        gp = FinanceService.initiate_gateway_payment(
            db,
            user_id=current_user_id,
            amount=data.amount,
            gateway=data.gateway,
            callback_url=data.callback_url,
        )
        db.commit()
        return GatewayPaymentOut.model_validate(gp)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/gateway/{gp_id}/payment-link")
def get_gateway_payment_link(
    gp_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    """
    Get the payment link/URL for a gateway payment
    User should redirect to the payment_url to complete payment
    """
    try:
        gp = _get_gateway_payment_owned_by_user(db, gp_id, current_user_id)

        if gp.status != "CREATED":
            raise HTTPException(
                status_code=400,
                detail=f"Payment already {gp.status.lower()}"
            )

        # Build payment link using gateway factory
        payment_link = GatewayFactory.build_payment_link(
            gateway=gp.gateway,
            authority=gp.authority,
            amount=gp.amount
        )

        return {
            "payment_id": gp.id,
            "status": gp.status,
            "amount": gp.amount,
            "gateway": gp.gateway,
            **payment_link
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/gateway/{gp_id}", response_model=GatewayPaymentOut)
def get_gateway_payment(
    gp_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    """Get the status of a gateway payment"""
    try:
        gp = _get_gateway_payment_owned_by_user(db, gp_id, current_user_id)
        return GatewayPaymentOut.model_validate(gp)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/gateway/me/payments", response_model=list[GatewayPaymentOut])
def list_my_gateway_payments(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
    limit: int = 50,
):
    """List all gateway payments for current user"""
    try:
        payments = FinanceService.list_user_gateway_payments(db, current_user_id, limit)
        return [GatewayPaymentOut.model_validate(gp) for gp in payments]
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/gateway/supported")
def get_supported_gateways_endpoint():
    """Get list of supported payment gateways"""
    return {
        "supported_gateways": get_supported_gateways(),
        "gateways": {
            "zarinpal": {
                "name": "ZarinPal",
                "description": "Iranian payment gateway - ZarinPal",
                "supported_currencies": ["IRR"]
            },
            "stripe": {
                "name": "Stripe",
                "description": "International payment gateway - Stripe",
                "supported_currencies": ["USD", "EUR", "GBP"]
            },
            "paddlepay": {
                "name": "PaddlePay",
                "description": "Digital payment platform - PaddlePay",
                "supported_currencies": ["USD", "EUR", "GBP"]
            }
        }
    }


@router.post("/gateway/verify", response_model=GatewayPaymentOut)
def verify_gateway_payment(
    data: VerifyGatewayPaymentIn,
    db: Session = Depends(get_db),
):
    """
    Verify gateway payment and credit wallet.
    This endpoint is called by the gateway or frontend after successful payment.
    Status: CREATED → VERIFIED (wallet credited)
    """
    try:
        gp, tx = FinanceService.verify_gateway_payment(
            db,
            authority=data.authority,
            ref_id=data.ref_id,
        )
        db.commit()
        return GatewayPaymentOut.model_validate(gp)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/gateway/webhook/zarinpal")
def zarinpal_webhook(
    data: dict,
    db: Session = Depends(get_db),
):
    """
    ZarinPal webhook callback
    Called by ZarinPal after payment completion
    Expects: authority, ref_id, status (1=success, 0=failed)
    """
    try:
        status = data.get("status", 0)
        authority = data.get("authority", "")
        ref_id = data.get("ref_id", "")

        if not authority or not ref_id:
            raise HTTPException(status_code=400, detail="Missing authority or ref_id")

        if status == 1:
            # Payment successful
            gp, tx = FinanceService.verify_gateway_payment(db, authority, ref_id)
            db.commit()
            return {"result": "verified", "payment_id": gp.id, "status": gp.status}
        else:
            # Payment failed
            gp = FinanceService.fail_gateway_payment(db, authority, ref_id)
            db.commit()
            return {"result": "failed", "payment_id": gp.id, "status": gp.status}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"webhook error: {str(e)}")


@router.post("/gateway/webhook/stripe")
def stripe_webhook(
    data: dict,
    db: Session = Depends(get_db),
):
    """
    Stripe webhook callback
    Called by Stripe after payment completion
    Expects: type (charge.succeeded|charge.failed), data.object.metadata.authority, data.object.metadata.ref_id
    """
    try:
        event_type = data.get("type", "")
        event_data = data.get("data", {}).get("object", {})
        metadata = event_data.get("metadata", {})

        authority = metadata.get("authority", "")
        ref_id = metadata.get("ref_id", "")

        if not authority or not ref_id:
            raise HTTPException(status_code=400, detail="Missing authority or ref_id in metadata")

        if event_type == "charge.succeeded":
            # Payment successful
            gp, tx = FinanceService.verify_gateway_payment(db, authority, ref_id)
            db.commit()
            return {"result": "verified", "payment_id": gp.id}
        elif event_type == "charge.failed":
            # Payment failed
            gp = FinanceService.fail_gateway_payment(db, authority, ref_id)
            db.commit()
            return {"result": "failed", "payment_id": gp.id}
        else:
            return {"result": "ignored", "reason": "event type not handled"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"webhook error: {str(e)}")


@router.post("/gateway/fail", response_model=GatewayPaymentOut)
def fail_gateway_payment(
    data: FailGatewayPaymentIn,
    db: Session = Depends(get_db),
):
    """
    Mark a gateway payment as failed.
    Called when payment fails or user cancels the payment.
    Status: CREATED → FAILED
    """
    try:
        gp = FinanceService.fail_gateway_payment(
            db,
            authority=data.authority,
            ref_id=data.ref_id,
        )
        db.commit()
        return GatewayPaymentOut.model_validate(gp)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/admin/gateway/pending", response_model=list[GatewayPaymentOut])
def list_pending_gateway_payments(
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
):
    """List all pending gateway payments (for monitoring)"""
    try:
        rows = db.execute(
            select(GatewayPayment)
            .where(GatewayPayment.status == "CREATED")
            .order_by(GatewayPayment.id.desc())
        ).scalars().all()
        return [GatewayPaymentOut.model_validate(gp) for gp in rows]
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/admin/gateway/verified", response_model=list[GatewayPaymentOut])
def list_verified_gateway_payments(
    db: Session = Depends(get_db),
    admin: AdminIdentity = Depends(get_admin_identity),
    limit: int = 50,
):
    """List all verified gateway payments (for audit)"""
    try:
        rows = db.execute(
            select(GatewayPayment)
            .where(GatewayPayment.status == "VERIFIED")
            .order_by(GatewayPayment.id.desc())
            .limit(limit)
        ).scalars().all()
        return [GatewayPaymentOut.model_validate(gp) for gp in rows]
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")

