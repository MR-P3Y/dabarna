from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.wallet import Wallet, WalletTx


class WalletService:
    @staticmethod
    def get_or_create_wallet(db: Session, user_id: int) -> Wallet:
        w = db.execute(
            select(Wallet).where(Wallet.user_id == int(user_id))
        ).scalar_one_or_none()
        if w:
            return w
        w = Wallet(user_id=int(user_id), balance=0)
        db.add(w)
        db.flush()
        return w

    @staticmethod
    def get_wallet(db: Session, user_id: int) -> Wallet:
        """Fetch wallet by user_id. Raises 404 if not found."""
        w = db.execute(
            select(Wallet).where(Wallet.user_id == int(user_id))
        ).scalar_one_or_none()
        if not w:
            raise HTTPException(status_code=404, detail="wallet not found")
        return w

    @staticmethod
    def list_txs(db: Session, user_id: int, limit: int = 50) -> list[WalletTx]:
        """Fetch transaction list for a user wallet."""
        w = WalletService.get_wallet(db, user_id)
        rows = db.execute(
            select(WalletTx)
            .where(WalletTx.wallet_id == w.id)
            .order_by(WalletTx.id.desc())
            .limit(limit)
        ).scalars().all()
        return rows

    @staticmethod
    def credit(
        db: Session,
        user_id: int,
        amount: int,
        reason: str,
        idempotency_key: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> WalletTx:
        amount = int(amount)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="amount must be > 0")

        user_id = int(user_id)
        idempotency_key = str(idempotency_key)
        reason = str(reason)

        wallet = db.execute(
            select(Wallet).where(Wallet.user_id == user_id).with_for_update()
        ).scalar_one_or_none()

        if not wallet:
            wallet = Wallet(user_id=user_id, balance=0)
            db.add(wallet)
            db.flush()

        existing = db.execute(
            select(WalletTx).where(
                WalletTx.wallet_id == wallet.id,
                WalletTx.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        tx = WalletTx(
            wallet_id=int(wallet.id),
            direction="CREDIT",
            amount=amount,
            reason=reason,
            ref_type=ref_type,
            ref_id=int(ref_id) if ref_id is not None else None,
            idempotency_key=idempotency_key,
        )
        db.add(tx)

        wallet.balance = int(wallet.balance) + amount
        db.flush()
        return tx

    @staticmethod
    def debit(
        db: Session,
        user_id: int,
        amount: int,
        reason: str,
        idempotency_key: str,
        ref_type: str | None = None,
        ref_id: int | None = None,
    ) -> WalletTx:
        amount = int(amount)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="amount must be > 0")

        user_id = int(user_id)
        idempotency_key = str(idempotency_key)
        reason = str(reason)

        wallet = db.execute(
            select(Wallet).where(Wallet.user_id == user_id).with_for_update()
        ).scalar_one_or_none()

        # سیاست پیشنهادی: wallet را در debit نساز. خطای تمیز بده.
        if not wallet:
            raise HTTPException(status_code=404, detail="wallet not found")

        existing = db.execute(
            select(WalletTx).where(
                WalletTx.wallet_id == wallet.id,
                WalletTx.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        if int(wallet.balance) < amount:
            raise HTTPException(status_code=400, detail="insufficient balance")

        tx = WalletTx(
            wallet_id=int(wallet.id),
            direction="DEBIT",
            amount=amount,
            reason=reason,
            ref_type=ref_type,
            ref_id=int(ref_id) if ref_id is not None else None,
            idempotency_key=idempotency_key,
        )
        db.add(tx)

        wallet.balance = int(wallet.balance) - amount
        # sanity guard (عملاً نباید رخ دهد چون بالا چک کردیم)
        if int(wallet.balance) < 0:
            raise HTTPException(status_code=500, detail="wallet balance became negative")

        db.flush()
        return tx
