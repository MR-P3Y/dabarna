from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


CryptoNetwork = Enum("TRON", "TON", name="crypto_network")
CryptoAsset = Enum("USDT", "TON", name="crypto_asset")
CryptoDepositStatus = Enum(
    "WAITING_PAYMENT",
    "CONFIRMING",
    "CREDITED",
    "EXPIRED",
    "NEEDS_REVIEW",
    "REJECTED",
    name="crypto_deposit_status",
)


class CryptoDepositRequest(Base):
    __tablename__ = "crypto_deposit_requests"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_crypto_deposit_public_id"),
        UniqueConstraint("network", "tx_hash", name="uq_crypto_deposit_network_tx"),
        Index("ix_crypto_deposit_user_created", "user_id", "created_at"),
        Index("ix_crypto_deposit_status_expires", "status", "expires_at"),
        Index("ix_crypto_deposit_match", "network", "asset", "amount_crypto", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    network: Mapped[str] = mapped_column(CryptoNetwork, nullable=False)
    asset: Mapped[str] = mapped_column(CryptoAsset, nullable=False)
    amount_toman: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_toman_per_asset: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    amount_crypto: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    paid_amount_crypto: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    rate_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_address: Mapped[str] = mapped_column(String(128), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sender_address: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(CryptoDepositStatus, nullable=False)
    wallet_tx_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("wallet_txs.id"), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    detected_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    credited_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    admin_notified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    user_notified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
