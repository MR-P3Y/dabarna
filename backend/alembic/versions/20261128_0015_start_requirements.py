"""Configurable Autopilot readiness thresholds."""
import sqlalchemy as sa
from alembic import op

revision = "20261128_0015"
down_revision = "20261115_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("game_autopilot_configs", sa.Column("start_requirement", sa.String(16), nullable=False, server_default="PLAYERS"))
    op.add_column("game_autopilot_configs", sa.Column("min_cards_sold", sa.Integer(), nullable=False, server_default="2"))


def downgrade():
    op.drop_column("game_autopilot_configs", "min_cards_sold")
    op.drop_column("game_autopilot_configs", "start_requirement")
