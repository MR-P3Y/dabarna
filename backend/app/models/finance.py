from sqlalchemy import BigInteger, TIMESTAMP, text, ForeignKey, Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

DepositStatus = Enum("AWAITING_RECEIPT","PENDING_REVIEW","APPROVED","REJECTED", name="deposit_status")
GatewayPayStatus = Enum("CREATED","REDIRECTED","VERIFIED","FAILED", name="gateway_pay_status")
WithdrawStatus = Enum("PENDING","APPROVED","PAID","REJECTED", name="withdraw_status")

class DepositRequest(Base):
    __tablename__ = "deposit_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(DepositStatus, nullable=False)

    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)

    wallet_tx_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallet_txs.id"), nullable=True)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

class GatewayPayment(Base):
    __tablename__ = "gateway_payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)

    gateway: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(GatewayPayStatus, nullable=False)
    wallet_tx_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallet_txs.id"), nullable=True)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

class WithdrawRequest(Base):
    __tablename__ = "withdraw_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)

    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    iban: Mapped[str] = mapped_column(String(34), nullable=False)
    card_number: Mapped[str] = mapped_column(String(32), nullable=False)
    account_number: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(WithdrawStatus, nullable=False)

    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(TIMESTAMP, nullable=True)

    paid_tracking: Mapped[str | None] = mapped_column(String(128), nullable=True)
    wallet_tx_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallet_txs.id"), nullable=True)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
