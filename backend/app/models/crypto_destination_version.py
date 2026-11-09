"""Non-operational crypto destination version records for staged rotation (#30)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CryptoDestinationVersion(Base):
    __tablename__ = "crypto_destination_versions"
    __table_args__ = (
        UniqueConstraint("network", "asset", "version", name="uq_crypto_dest_network_asset_version"),
        UniqueConstraint("operation_id", name="uq_crypto_dest_operation"),
        Index("ix_crypto_dest_network_state", "network", "asset", "state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    network: Mapped[str] = mapped_column(String(8), nullable=False)
    asset: Mapped[str] = mapped_column(String(12), nullable=False)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_address: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    activated_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), nullable=False,
    )
    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
