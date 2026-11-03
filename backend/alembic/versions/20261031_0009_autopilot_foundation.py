"""add autopilot foundation

Revision ID: 20261031_0009
Revises: 20261009_0008
Create Date: 2026-10-31
"""

from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision = "20261031_0009"
down_revision = "20261009_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("game_level", sa.String(length=16), nullable=True))
    op.add_column(
        "games",
        sa.Column("execution_source", sa.String(length=16), nullable=False, server_default="ADMIN"),
    )
    op.add_column("games", sa.Column("scheduled_start_at", sa.TIMESTAMP(), nullable=True))
    op.create_index("idx_games_level_status", "games", ["game_level", "status"], unique=False)

    op.create_table(
        "game_autopilot_configs",
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduler_mode", sa.String(length=16), nullable=False, server_default="MANUAL"),
        sa.Column("start_mode", sa.String(length=16), nullable=False, server_default="MANUAL"),
        sa.Column("draw_mode", sa.String(length=16), nullable=False, server_default="MANUAL"),
        sa.Column("card_price", sa.BigInteger(), nullable=True),
        sa.Column("commission_rate", sa.DECIMAL(precision=5, scale=4), nullable=False, server_default="0.1000"),
        sa.Column("announce_before_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("countdown_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("repeat_interval_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("draw_interval_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("min_unique_players", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("level"),
    )

    configs = sa.table(
        "game_autopilot_configs",
        sa.column("level", sa.String()),
        sa.column("enabled", sa.Integer()),
        sa.column("scheduler_mode", sa.String()),
        sa.column("start_mode", sa.String()),
        sa.column("draw_mode", sa.String()),
        sa.column("card_price", sa.BigInteger()),
        sa.column("commission_rate", sa.DECIMAL(5, 4)),
        sa.column("announce_before_seconds", sa.Integer()),
        sa.column("countdown_seconds", sa.Integer()),
        sa.column("repeat_interval_seconds", sa.Integer()),
        sa.column("draw_interval_seconds", sa.Integer()),
        sa.column("cooldown_seconds", sa.Integer()),
        sa.column("min_unique_players", sa.Integer()),
    )
    op.bulk_insert(
        configs,
        [
            {
                "level": "LOW",
                "enabled": 0,
                "scheduler_mode": "MANUAL",
                "start_mode": "MANUAL",
                "draw_mode": "MANUAL",
                "card_price": None,
                "commission_rate": Decimal("0.1000"),
                "announce_before_seconds": 300,
                "countdown_seconds": 30,
                "repeat_interval_seconds": 480,
                "draw_interval_seconds": 8,
                "cooldown_seconds": 60,
                "min_unique_players": 2,
            },
            {
                "level": "MEDIUM",
                "enabled": 0,
                "scheduler_mode": "MANUAL",
                "start_mode": "MANUAL",
                "draw_mode": "MANUAL",
                "card_price": None,
                "commission_rate": Decimal("0.1000"),
                "announce_before_seconds": 300,
                "countdown_seconds": 30,
                "repeat_interval_seconds": 900,
                "draw_interval_seconds": 10,
                "cooldown_seconds": 60,
                "min_unique_players": 2,
            },
            {
                "level": "HIGH",
                "enabled": 0,
                "scheduler_mode": "MANUAL",
                "start_mode": "MANUAL",
                "draw_mode": "MANUAL",
                "card_price": None,
                "commission_rate": Decimal("0.1000"),
                "announce_before_seconds": 300,
                "countdown_seconds": 30,
                "repeat_interval_seconds": 1800,
                "draw_interval_seconds": 12,
                "cooldown_seconds": 60,
                "min_unique_players": 2,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("game_autopilot_configs")
    op.drop_index("idx_games_level_status", table_name="games")
    op.drop_column("games", "scheduled_start_at")
    op.drop_column("games", "execution_source")
    op.drop_column("games", "game_level")
