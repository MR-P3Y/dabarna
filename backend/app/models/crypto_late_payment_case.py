"""Unmatched historical crypto observations: immutable review-only queue entries.

This model deliberately carries no wallet_tx_id and has no paid/approved state.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, JSON, Numeric, String, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CryptoLatePaymentCase(Base):
    __tablename__ = "crypto_late_payment_cases"
    __table_args__ = (
        UniqueConstraint("network", "tx_hash", name="uq_crypto_late_case_network_hash"),
        Index("ix_crypto_late_case_state_created", "state", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    asset: Mapped[str] = mapped_column(String(12), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(160), nullable=False)
    destination_masked: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_crypto: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    confirmed_on_chain: Mapped[bool] = mapped_column(Boolean, nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    timing: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_invoice_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="OPEN")
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )
