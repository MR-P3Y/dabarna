"""Single-use, time-limited operator confirmation for a proposed crypto destination.

A confirmation is not a crypto address activation and has no effect on payments.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CryptoDestinationChallenge(Base):
    __tablename__ = "crypto_destination_challenges"
    __table_args__ = (
        Index("ix_crypto_challenge_draft_expiry", "draft_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("crypto_destination_versions.id"), nullable=False
    )
    actor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    secret_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
