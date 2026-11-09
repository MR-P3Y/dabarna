"""Snapshot old address and add one-time confirmations (no address activation).

Revision ID: 20261109_0014
Revises: 20261109_0013

Additive schema only. The confirmation record MUST NOT update payment settings,
environment, scanner configuration, invoices or ledgers.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0014"
down_revision = "20261109_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crypto_destination_versions",
        sa.Column("previous_address", sa.String(length=128), nullable=True),
    )
    op.create_table(
        "crypto_destination_challenges",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("draft_id", sa.BigInteger(), sa.ForeignKey("crypto_destination_versions.id"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("secret_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("consumed_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("ix_crypto_challenge_draft_expiry", "crypto_destination_challenges",
                    ["draft_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_crypto_challenge_draft_expiry", table_name="crypto_destination_challenges")
    op.drop_table("crypto_destination_challenges")
    op.drop_column("crypto_destination_versions", "previous_address")
