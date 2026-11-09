"""Create non-operational versioned crypto destinations for #30.

Revision ID: 20261109_0013
Revises: 20261108_0012

No backfill, address activation, invoice edits or wallet/ledger writes.
Activation is intentionally not implemented in this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261109_0013"
down_revision = "20261108_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crypto_destination_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("network", sa.String(length=8), nullable=False),
        sa.Column("asset", sa.String(length=12), nullable=False),
        sa.Column("address", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("activated_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("activated_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("retired_at", sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint("network", "asset", "version", name="uq_crypto_dest_network_asset_version"),
        sa.UniqueConstraint("operation_id", name="uq_crypto_dest_operation"),
    )
    op.create_index(
        "ix_crypto_dest_network_state",
        "crypto_destination_versions",
        ["network", "asset", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_crypto_dest_network_state", table_name="crypto_destination_versions")
    op.drop_table("crypto_destination_versions")
