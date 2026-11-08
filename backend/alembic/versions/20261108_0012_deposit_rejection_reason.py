"""Persist a reason for bank deposit rejections by Mini App finance admins.

Revision ID: 20261108_0012
Revises: 20261104_0011

Nullable to preserve all historic deposit requests and bot compatibility.
No data correction, wallet/ledger change or status backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261108_0012"
down_revision = "20261104_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deposit_requests",
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deposit_requests", "rejection_reason")
