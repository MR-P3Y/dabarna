"""Persist readiness grace and allow fast draws only for stored FULL_CARD/v2.

Revision ID: 20261113_0013
Revises: 20261108_0012
No wallet, invoice, purchase, settings or existing game status is updated.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261113_0013'
down_revision = '20261108_0012'
branch_labels = None
depends_on = None

OLD = 'NEW.draw_interval_seconds NOT IN (5, 8, 10, 15)'
NEW = "(NEW.draw_interval_seconds NOT IN (5, 8, 10, 15) AND NOT (NEW.game_rule = 'FULL_CARD' AND NEW.card_layout_version = 2 AND NEW.draw_interval_seconds IN (2, 3, 4)))"


def _read_guard(bind, expected):
    body = bind.execute(sa.text("SELECT ACTION_STATEMENT FROM information_schema.TRIGGERS "
        "WHERE TRIGGER_SCHEMA=DATABASE() AND TRIGGER_NAME='trg_games_draw_mode_guard'")).scalar_one_or_none()
    if not isinstance(body, str) or body.count(expected) != 1:
        raise RuntimeError('Unexpected draw-mode trigger; migration refused before schema change')
    return body


def _replace_guard(body):
    op.execute('DROP TRIGGER trg_games_draw_mode_guard')
    op.execute('CREATE TRIGGER trg_games_draw_mode_guard BEFORE UPDATE ON games FOR EACH ROW '+body)


def upgrade():
    bind=op.get_bind()
    body=_read_guard(bind, OLD) if bind.dialect.name=='mysql' else None
    op.add_column('games',sa.Column('autopilot_ready_at',sa.TIMESTAMP(),nullable=True))
    if body is not None:
        _replace_guard(body.replace(OLD, NEW))


def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM games WHERE draw_interval_seconds IN (2,3,4)')).scalar_one():
        raise RuntimeError('Fast-game history exists; destructive compatibility downgrade refused')
    body=_read_guard(bind, NEW) if bind.dialect.name=='mysql' else None
    if body is not None:
        _replace_guard(body.replace(NEW, OLD))
    op.drop_column('games','autopilot_ready_at')
