"""Introduce versioned card layouts and explicit game winning rules.

Revision ID: 20261104_0011
Revises: 20261031_0010

Important: All existing and newly created games remain LEGACY/1 until
the application explicitly opts into V2 after the API/UI rollout.
Autopilot level names are retained as DB keys for compatibility.
"""

from alembic import op
import sqlalchemy as sa


revision = "20261104_0011"
down_revision = "20261031_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column("card_layout_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "games",
        sa.Column("game_rule", sa.String(length=16), nullable=False, server_default="LEGACY"),
    )
    op.add_column(
        "game_autopilot_configs",
        sa.Column("game_rule", sa.String(length=16), nullable=False, server_default="LINE"),
    )

    # These mappings describe FUTURE lanes; the worker still runs legacy
    # mechanics until the explicitly gated V2 application rollout.
    op.get_bind().execute(
        sa.text(
            """
            UPDATE game_autopilot_configs
            SET game_rule = CASE
                WHEN level = 'HIGH' THEN 'FULL_CARD'
                ELSE 'LINE'
            END
            WHERE level IN ('LOW', 'MEDIUM', 'HIGH')
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    v2_games = int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM games WHERE card_layout_version = 2")
        ).scalar_one()
        or 0
    )
    if v2_games:
        raise RuntimeError(
            "Cannot downgrade Tambola V2 while V2 games exist; preserve their 27-cell cards and rule metadata."
        )

    op.drop_column("game_autopilot_configs", "game_rule")
    op.drop_column("games", "game_rule")
    op.drop_column("games", "card_layout_version")
