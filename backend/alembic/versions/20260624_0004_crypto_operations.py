"""Add crypto operational alert and variance fields.

Revision ID: 20260624_0004
Revises: 20260624_0003
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260624_0004"
down_revision = "20260624_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crypto_deposit_requests",
        sa.Column(
            "payment_variance",
            sa.Enum("EXACT", "UNDERPAID", "OVERPAID", name="crypto_payment_variance"),
            nullable=True,
        ),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("variance_amount_crypto", sa.Numeric(precision=36, scale=18), nullable=True),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("pending_alert_notified_at", sa.TIMESTAMP(), nullable=True),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("variance_alert_notified_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index(
        "ix_crypto_deposit_pending_alert",
        "crypto_deposit_requests",
        ["status", "pending_alert_notified_at", "created_at"],
    )
    op.create_index(
        "ix_crypto_deposit_variance_alert",
        "crypto_deposit_requests",
        ["payment_variance", "variance_alert_notified_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crypto_deposit_variance_alert", table_name="crypto_deposit_requests")
    op.drop_index("ix_crypto_deposit_pending_alert", table_name="crypto_deposit_requests")
    op.drop_column("crypto_deposit_requests", "variance_alert_notified_at")
    op.drop_column("crypto_deposit_requests", "pending_alert_notified_at")
    op.drop_column("crypto_deposit_requests", "variance_amount_crypto")
    op.drop_column("crypto_deposit_requests", "payment_variance")
