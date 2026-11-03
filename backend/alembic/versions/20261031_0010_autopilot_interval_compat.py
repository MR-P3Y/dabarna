"""align autopilot draw interval with locked auto-draw intervals

Revision ID: 20261031_0010
Revises: 20261031_0009
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0010"
down_revision = "20261031_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE game_autopilot_configs
            SET draw_interval_seconds = 15
            WHERE level = 'HIGH'
              AND draw_interval_seconds = 12
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE game_autopilot_configs
            SET draw_interval_seconds = 12
            WHERE level = 'HIGH'
              AND draw_interval_seconds = 15
            """
        )
    )
