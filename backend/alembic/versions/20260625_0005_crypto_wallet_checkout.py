"""Add direct wallet checkout and active crypto invoice fields.

Revision ID: 20260625_0005
Revises: 20260624_0004
Create Date: 2026-06-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_0005"
down_revision = "20260624_0004"
branch_labels = None
depends_on = None


OLD_STATUSES = (
    "WAITING_PAYMENT",
    "CONFIRMING",
    "CREDITED",
    "EXPIRED",
    "NEEDS_REVIEW",
    "REJECTED",
)
NEW_STATUSES = OLD_STATUSES + ("CANCELLED",)


def _mysql_status_sql(values: tuple[str, ...]) -> str:
    enum_values = ",".join(f"'{value}'" for value in values)
    return (
        "ALTER TABLE crypto_deposit_requests "
        f"MODIFY COLUMN status ENUM({enum_values}) NOT NULL"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(_mysql_status_sql(NEW_STATUSES))

    op.add_column("crypto_deposit_requests", sa.Column("active_user_id", sa.BigInteger(), nullable=True))
    op.add_column("crypto_deposit_requests", sa.Column("rate_fetched_at", sa.TIMESTAMP(), nullable=True))
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("estimated_network_fee", sa.Numeric(precision=36, scale=18), nullable=True),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("estimated_network_fee_asset", sa.String(length=12), nullable=True),
    )
    op.add_column("crypto_deposit_requests", sa.Column("wallet_provider", sa.String(length=32), nullable=True))
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("wallet_account_address", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("confirmation_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("required_confirmations", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "crypto_deposit_requests",
        sa.Column("payment_requested_at", sa.TIMESTAMP(), nullable=True),
    )
    op.add_column("crypto_deposit_requests", sa.Column("cancelled_at", sa.TIMESTAMP(), nullable=True))

    if bind.dialect.name == "mysql":
        op.execute(
            """
            UPDATE crypto_deposit_requests c
            JOIN (
                SELECT user_id, MAX(id) AS keep_id
                FROM crypto_deposit_requests
                WHERE status IN ('WAITING_PAYMENT', 'CONFIRMING')
                GROUP BY user_id
                HAVING COUNT(*) > 1
            ) d ON d.user_id = c.user_id
            SET c.status='EXPIRED',
                c.failure_reason='فاکتور قدیمی با نسخه جدید جایگزین شد.',
                c.updated_at=CURRENT_TIMESTAMP
            WHERE c.status IN ('WAITING_PAYMENT', 'CONFIRMING')
              AND c.id <> d.keep_id
            """
        )
    op.execute(
        """
        UPDATE crypto_deposit_requests
        SET active_user_id=user_id
        WHERE status IN ('WAITING_PAYMENT', 'CONFIRMING')
        """
    )
    op.create_unique_constraint(
        "uq_crypto_deposit_active_user",
        "crypto_deposit_requests",
        ["active_user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_crypto_deposit_active_user",
        "crypto_deposit_requests",
        type_="unique",
    )
    op.drop_column("crypto_deposit_requests", "cancelled_at")
    op.drop_column("crypto_deposit_requests", "payment_requested_at")
    op.drop_column("crypto_deposit_requests", "required_confirmations")
    op.drop_column("crypto_deposit_requests", "confirmation_count")
    op.drop_column("crypto_deposit_requests", "wallet_account_address")
    op.drop_column("crypto_deposit_requests", "wallet_provider")
    op.drop_column("crypto_deposit_requests", "estimated_network_fee_asset")
    op.drop_column("crypto_deposit_requests", "estimated_network_fee")
    op.drop_column("crypto_deposit_requests", "rate_fetched_at")
    op.drop_column("crypto_deposit_requests", "active_user_id")
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            "UPDATE crypto_deposit_requests SET status='REJECTED' "
            "WHERE status='CANCELLED'"
        )
        op.execute(_mysql_status_sql(OLD_STATUSES))
