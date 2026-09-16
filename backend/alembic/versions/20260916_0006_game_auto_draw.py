"""Add persisted automatic number drawing controls.

Revision ID: 20260916_0006
Revises: 20260625_0005
Create Date: 2026-09-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_0006"
down_revision = "20260625_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_auto_draws",
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="STOPPED", nullable=False),
        sa.Column("interval_seconds", sa.Integer(), server_default="10", nullable=False),
        sa.Column("sequence_json", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_draw_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("started_by", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("paused_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("stopped_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("game_id"),
    )
    op.create_index("ix_game_auto_draws_next_draw_at", "game_auto_draws", ["next_draw_at"])
    op.create_index("ix_game_auto_draws_status_due", "game_auto_draws", ["status", "next_draw_at"])


def downgrade() -> None:
    op.drop_index("ix_game_auto_draws_status_due", table_name="game_auto_draws")
    op.drop_index("ix_game_auto_draws_next_draw_at", table_name="game_auto_draws")
    op.drop_table("game_auto_draws")
