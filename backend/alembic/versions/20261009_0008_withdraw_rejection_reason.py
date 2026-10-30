from alembic import op
import sqlalchemy as sa


revision = "20261009_0008"
down_revision = "20260916_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "withdraw_requests",
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("withdraw_requests", "rejection_reason")
