"""Add crypto deposit invoices and wallet transaction reason.

Revision ID: 20260624_0003
Revises: 20260623_0002
Create Date: 2026-06-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260624_0003"
down_revision = "20260623_0002"
branch_labels = None
depends_on = None


WALLET_REASONS_WITH_CRYPTO = (
    "DEPOSIT_MANUAL",
    "DEPOSIT_GATEWAY",
    "DEPOSIT_CRYPTO",
    "BUY_CARDS",
    "PRIZE_COL",
    "PRIZE_ROW",
    "WITHDRAW",
    "ADJUST",
)

WALLET_REASONS_WITHOUT_CRYPTO = tuple(
    value for value in WALLET_REASONS_WITH_CRYPTO if value != "DEPOSIT_CRYPTO"
)


def _mysql_wallet_reason_sql(values: tuple[str, ...]) -> str:
    enum_values = ",".join(f"'{value}'" for value in values)
    return f"ALTER TABLE wallet_txs MODIFY COLUMN reason ENUM({enum_values}) NOT NULL"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(_mysql_wallet_reason_sql(WALLET_REASONS_WITH_CRYPTO))

    op.create_table(
        "crypto_deposit_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("network", sa.Enum("TRON", "TON", name="crypto_network"), nullable=False),
        sa.Column("asset", sa.Enum("USDT", "TON", name="crypto_asset"), nullable=False),
        sa.Column("amount_toman", sa.BigInteger(), nullable=False),
        sa.Column("rate_toman_per_asset", sa.Numeric(precision=28, scale=8), nullable=False),
        sa.Column("amount_crypto", sa.Numeric(precision=36, scale=18), nullable=False),
        sa.Column("paid_amount_crypto", sa.Numeric(precision=36, scale=18), nullable=True),
        sa.Column("rate_provider", sa.String(length=32), nullable=False),
        sa.Column("destination_address", sa.String(length=128), nullable=False),
        sa.Column("memo", sa.String(length=64), nullable=True),
        sa.Column("tx_hash", sa.String(length=160), nullable=True),
        sa.Column("sender_address", sa.String(length=160), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "WAITING_PAYMENT",
                "CONFIRMING",
                "CREDITED",
                "EXPIRED",
                "NEEDS_REVIEW",
                "REJECTED",
                name="crypto_deposit_status",
            ),
            nullable=False,
        ),
        sa.Column("wallet_tx_id", sa.BigInteger(), nullable=True),
        sa.Column("failure_reason", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("confirmed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("credited_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("last_checked_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("admin_notified_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("user_notified_at", sa.TIMESTAMP(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_tx_id"], ["wallet_txs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_crypto_deposit_public_id"),
        sa.UniqueConstraint("network", "tx_hash", name="uq_crypto_deposit_network_tx"),
    )
    op.create_index(
        "ix_crypto_deposit_user_created",
        "crypto_deposit_requests",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_crypto_deposit_status_expires",
        "crypto_deposit_requests",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_crypto_deposit_match",
        "crypto_deposit_requests",
        ["network", "asset", "amount_crypto", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_crypto_deposit_match", table_name="crypto_deposit_requests")
    op.drop_index("ix_crypto_deposit_status_expires", table_name="crypto_deposit_requests")
    op.drop_index("ix_crypto_deposit_user_created", table_name="crypto_deposit_requests")
    op.drop_table("crypto_deposit_requests")

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            "UPDATE wallet_txs SET reason='DEPOSIT_GATEWAY' "
            "WHERE reason='DEPOSIT_CRYPTO'"
        )
        op.execute(_mysql_wallet_reason_sql(WALLET_REASONS_WITHOUT_CRYPTO))
