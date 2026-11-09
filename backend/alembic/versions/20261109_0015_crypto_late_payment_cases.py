"""Add non-settling queue for unmatched historical crypto transfers (#30).

Revision ID: 20261109_0015
Revises: 20261109_0014

No backfill, wallet writes, invoice status changes, or address activation.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0015"
down_revision = "20261109_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_late_payment_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("network", sa.String(length=8), nullable=False),
        sa.Column("asset", sa.String(length=12), nullable=False),
        sa.Column("tx_hash", sa.String(length=160), nullable=False),
        sa.Column("destination_masked", sa.String(length=40), nullable=False),
        sa.Column("amount_crypto", sa.Numeric(36, 18), nullable=False),
        sa.Column("occurred_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("confirmed_on_chain", sa.Boolean(), nullable=False),
        sa.Column("classification", sa.String(length=64), nullable=False),
        sa.Column("timing", sa.String(length=40), nullable=False),
        sa.Column("candidate_invoice_ids", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("network", "tx_hash", name="uq_crypto_late_case_network_hash"),
    )
    op.create_index("ix_crypto_late_case_state_created",
                    "crypto_late_payment_cases", ["state", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_crypto_late_case_state_created",
                  table_name="crypto_late_payment_cases")
    op.drop_table("crypto_late_payment_cases")
