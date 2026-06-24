from sqlalchemy import BigInteger, TIMESTAMP, text, ForeignKey, Enum, String, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base

WalletTxDirection = Enum("CREDIT", "DEBIT", name="wallet_tx_direction")
WalletTxReason = Enum(
    "DEPOSIT_MANUAL",
    "DEPOSIT_GATEWAY",
    "DEPOSIT_CRYPTO",
    "BUY_CARDS",
    "PRIZE_COL",
    "PRIZE_ROW",
    "WITHDRAW",
    "ADJUST",
    name="wallet_tx_reason",
)

class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    updated_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"), nullable=False
    )

    user = relationship("User", back_populates="wallet")
    txs = relationship("WalletTx", back_populates="wallet")

class WalletTx(Base):
    __tablename__ = "wallet_txs"
    __table_args__ = (
        UniqueConstraint("wallet_id", "idempotency_key", name="uq_wallet_idem"),
        Index("idx_wallet_created", "wallet_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("wallets.id"), nullable=False)

    direction: Mapped[str] = mapped_column(WalletTxDirection, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(WalletTxReason, nullable=False)

    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)

    created_at: Mapped[str] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    wallet = relationship("Wallet", back_populates="txs")
