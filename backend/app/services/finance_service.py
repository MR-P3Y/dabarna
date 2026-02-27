from sqlalchemy import select, func
from sqlalchemy.orm import Session
from fastapi import HTTPException
import uuid
import re
from datetime import datetime, timedelta

from app.models.finance import DepositRequest, WithdrawRequest, GatewayPayment
from app.models.wallet import Wallet
from app.services.wallet_service import WalletService

WITHDRAW_IDEMPOTENCY_WINDOW_MINUTES = 10


def _clean_numeric(value: str | int | None) -> str:
    return str(value or "").strip().replace(" ", "").replace("-", "")

class FinanceService:
    @staticmethod
    def create_deposit_request(db: Session, user_id: int, amount: int) -> DepositRequest:
        if int(amount or 0) <= 0:
            raise HTTPException(status_code=400, detail="مبلغ واریز باید بیشتر از صفر باشد.")

        dr = DepositRequest(user_id=user_id, amount=amount, status="AWAITING_RECEIPT")
        db.add(dr)
        db.flush()
        return dr

    @staticmethod
    def upload_receipt(db: Session, deposit_id: int, receipt_file_id: str) -> DepositRequest:
        dr = db.get(DepositRequest, deposit_id)
        if not dr:
            raise HTTPException(status_code=404, detail="درخواست واریز پیدا نشد.")
        if dr.status not in ("AWAITING_RECEIPT", "PENDING_REVIEW"):
            raise HTTPException(status_code=400, detail="وضعیت درخواست واریز معتبر نیست.")
        dr.receipt_file_id = receipt_file_id
        dr.status = "PENDING_REVIEW"
        db.flush()
        return dr

    @staticmethod
    def approve_deposit(db: Session, deposit_id: int, admin_user_id: int, idempotency_key: str):
        dr = db.execute(
            select(DepositRequest).where(DepositRequest.id == deposit_id).with_for_update()
        ).scalar_one_or_none()
        if not dr:
            raise HTTPException(status_code=404, detail="درخواست واریز پیدا نشد.")
        if dr.status != "PENDING_REVIEW":
            raise HTTPException(status_code=400, detail="درخواست واریز هنوز آماده بررسی نهایی نیست.")

        # credit wallet (idempotent)
        tx = WalletService.credit(
            db=db,
            user_id=dr.user_id,
            amount=dr.amount,
            reason="DEPOSIT_MANUAL",
            idempotency_key=idempotency_key,
            ref_type="DEPOSIT",
            ref_id=dr.id,
        )

        dr.status = "APPROVED"
        dr.reviewed_by = admin_user_id
        dr.wallet_tx_id = tx.id
        db.flush()
        return dr, tx

    @staticmethod
    def reject_deposit(db: Session, deposit_id: int, admin_user_id: int):
        dr = db.execute(
            select(DepositRequest).where(DepositRequest.id == deposit_id).with_for_update()
        ).scalar_one_or_none()
        if not dr:
            raise HTTPException(status_code=404, detail="درخواست واریز پیدا نشد.")
        if dr.status not in ("PENDING_REVIEW", "AWAITING_RECEIPT"):
            raise HTTPException(status_code=400, detail="وضعیت درخواست واریز معتبر نیست.")
        dr.status = "REJECTED"
        dr.reviewed_by = admin_user_id
        db.flush()
        return dr

    @staticmethod
    def create_withdraw_request(db: Session, payload: dict) -> WithdrawRequest:
        user_id = int(payload.get("user_id") or 0)
        if user_id <= 0:
            raise HTTPException(status_code=400, detail="شناسه کاربر نامعتبر است.")

        try:
            amount = int(payload.get("amount") or 0)
        except Exception:
            amount = 0
        if amount <= 0:
            raise HTTPException(status_code=400, detail="مبلغ برداشت باید بیشتر از صفر باشد.")

        full_name = str(payload.get("full_name") or "").strip()
        if len(full_name) < 3:
            raise HTTPException(status_code=400, detail="نام و نام خانوادگی معتبر نیست.")

        iban = str(payload.get("iban") or "").strip().upper().replace(" ", "")
        if iban and (not re.fullmatch(r"IR\d{24}", iban)):
            raise HTTPException(status_code=400, detail="شماره شبا نامعتبر است.")

        card_number = _clean_numeric(payload.get("card_number"))
        if not re.fullmatch(r"\d{16}", card_number):
            raise HTTPException(status_code=400, detail="شماره کارت نامعتبر است.")

        account_number = _clean_numeric(payload.get("account_number"))
        if account_number and (not re.fullmatch(r"\d{6,20}", account_number)):
            raise HTTPException(status_code=400, detail="شماره حساب نامعتبر است.")

        # Soft idempotency without DB migration:
        # if same PENDING request exists in a recent window, return it.
        idem_key = str(payload.get("idempotency_key") or "").strip()
        if idem_key:
            since = datetime.utcnow() - timedelta(minutes=WITHDRAW_IDEMPOTENCY_WINDOW_MINUTES)
            existing = db.execute(
                select(WithdrawRequest)
                .where(
                    WithdrawRequest.user_id == user_id,
                    WithdrawRequest.amount == amount,
                    WithdrawRequest.full_name == full_name,
                    WithdrawRequest.iban == iban,
                    WithdrawRequest.card_number == card_number,
                    WithdrawRequest.account_number == account_number,
                    WithdrawRequest.status == "PENDING",
                    WithdrawRequest.created_at >= since,
                )
                .order_by(WithdrawRequest.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if existing:
                return existing

        wallet_balance_raw = db.execute(
            select(Wallet.balance).where(Wallet.user_id == user_id).with_for_update()
        ).scalar_one_or_none()
        wallet_balance = int(wallet_balance_raw or 0)

        reserved_pending_raw = db.execute(
            select(func.coalesce(func.sum(WithdrawRequest.amount), 0))
            .where(
                WithdrawRequest.user_id == user_id,
                WithdrawRequest.status == "PENDING",
            )
        ).scalar_one()
        reserved_pending = int(reserved_pending_raw or 0)
        available_balance = max(0, wallet_balance - reserved_pending)
        if amount > available_balance:
            raise HTTPException(status_code=400, detail="موجودی قابل برداشت کافی نیست.")

        wr = WithdrawRequest(
            user_id=user_id,
            amount=amount,
            full_name=full_name,
            iban=iban,
            card_number=card_number,
            account_number=account_number,
            status="PENDING",
        )
        db.add(wr)
        db.flush()
        return wr

    @staticmethod
    def approve_withdraw(db: Session, withdraw_id: int, admin_user_id: int, idempotency_key: str):
        wr = db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        ).scalar_one_or_none()
        if not wr:
            raise HTTPException(status_code=404, detail="درخواست برداشت پیدا نشد.")
        if wr.status != "PENDING":
            raise HTTPException(status_code=400, detail="این درخواست برداشت در وضعیت در انتظار نیست.")

        tx = WalletService.debit(
            db=db,
            user_id=wr.user_id,
            amount=wr.amount,
            reason="WITHDRAW",
            idempotency_key=idempotency_key,
            ref_type="WITHDRAW",
            ref_id=wr.id,
        )

        wr.status = "APPROVED"
        wr.reviewed_by = admin_user_id
        wr.reviewed_at = datetime.utcnow()
        wr.wallet_tx_id = tx.id
        db.flush()
        return wr, tx

    @staticmethod
    def mark_withdraw_paid(db: Session, withdraw_id: int, admin_user_id: int, paid_tracking: str):
        wr = db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        ).scalar_one_or_none()
        if not wr:
            raise HTTPException(status_code=404, detail="درخواست برداشت پیدا نشد.")
        if wr.status != "APPROVED":
            raise HTTPException(status_code=400, detail="این درخواست برداشت هنوز تایید نشده است.")

        wr.status = "PAID"
        wr.paid_tracking = paid_tracking
        wr.reviewed_by = admin_user_id
        wr.reviewed_at = datetime.utcnow()
        db.flush()
        return wr

    @staticmethod
    def reject_withdraw(db: Session, withdraw_id: int, admin_user_id: int, reason: str | None = None):
        _ = reason
        wr = db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        ).scalar_one_or_none()
        if not wr:
            raise HTTPException(status_code=404, detail="درخواست برداشت پیدا نشد.")
        if wr.status != "PENDING":
            raise HTTPException(status_code=400, detail="این درخواست برداشت در وضعیت در انتظار نیست.")

        wr.status = "REJECTED"
        wr.reviewed_by = admin_user_id
        wr.reviewed_at = datetime.utcnow()
        db.flush()
        return wr

    # ========== Gateway Payment Methods ==========
    @staticmethod
    def initiate_gateway_payment(
        db: Session,
        user_id: int,
        amount: int,
        gateway: str,  # "zarinpal", "stripe", etc
        callback_url: str,
    ) -> GatewayPayment:
        """
        Create a GatewayPayment record and return payment initiation data.
        Status: CREATED
        """
        if int(amount or 0) <= 0:
            raise HTTPException(status_code=400, detail="مبلغ پرداخت باید بیشتر از صفر باشد.")

        if gateway not in ("zarinpal", "stripe", "paddlepay"):
            raise HTTPException(status_code=400, detail="درگاه پرداخت نامعتبر است.")

        # Generate unique authority/ref_id for this payment
        authority = str(uuid.uuid4())
        ref_id = str(uuid.uuid4())

        gp = GatewayPayment(
            user_id=user_id,
            amount=amount,
            gateway=gateway,
            authority=authority,
            ref_id=ref_id,
            status="CREATED",
        )
        db.add(gp)
        db.flush()
        return gp

    @staticmethod
    def verify_gateway_payment(
        db: Session,
        authority: str,
        ref_id: str,
    ) -> tuple[GatewayPayment, object]:
        """
        Verify gateway payment and credit wallet if successful.
        Updates status to VERIFIED and creates wallet transaction.
        Returns (GatewayPayment, WalletTx)
        """
        gp = db.execute(
            select(GatewayPayment).where(
                GatewayPayment.authority == authority,
                GatewayPayment.ref_id == ref_id,
            ).with_for_update()
        ).scalar_one_or_none()

        if not gp:
            raise HTTPException(status_code=404, detail="پرداخت موردنظر پیدا نشد.")

        if gp.status != "CREATED":
            raise HTTPException(status_code=400, detail=f"وضعیت پرداخت قبلاً «{gp.status}» شده است.")

        # Update status to VERIFIED
        gp.status = "VERIFIED"

        # Credit wallet (idempotent using authority as idempotency key)
        tx = WalletService.credit(
            db=db,
            user_id=gp.user_id,
            amount=gp.amount,
            reason="DEPOSIT_GATEWAY",
            idempotency_key=f"gateway_{gp.authority}",
            ref_type="GATEWAY_PAYMENT",
            ref_id=gp.id,
        )

        gp.wallet_tx_id = tx.id
        db.flush()
        return gp, tx

    @staticmethod
    def fail_gateway_payment(
        db: Session,
        authority: str,
        ref_id: str,
    ) -> GatewayPayment:
        """
        Mark a gateway payment as failed.
        """
        gp = db.execute(
            select(GatewayPayment).where(
                GatewayPayment.authority == authority,
                GatewayPayment.ref_id == ref_id,
            ).with_for_update()
        ).scalar_one_or_none()

        if not gp:
            raise HTTPException(status_code=404, detail="پرداخت موردنظر پیدا نشد.")

        gp.status = "FAILED"
        db.flush()
        return gp

    @staticmethod
    def get_gateway_payment(db: Session, gp_id: int) -> GatewayPayment:
        """Get a gateway payment by ID"""
        gp = db.get(GatewayPayment, gp_id)
        if not gp:
            raise HTTPException(status_code=404, detail="پرداخت موردنظر پیدا نشد.")
        return gp

    @staticmethod
    def list_user_gateway_payments(db: Session, user_id: int, limit: int = 50) -> list[GatewayPayment]:
        """List gateway payments for a user"""
        payments = db.execute(
            select(GatewayPayment)
            .where(GatewayPayment.user_id == user_id)
            .order_by(GatewayPayment.id.desc())
            .limit(limit)
        ).scalars().all()
        return payments
