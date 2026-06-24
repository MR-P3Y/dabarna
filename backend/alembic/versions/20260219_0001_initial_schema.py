"""Initial schema.

Revision ID: 20260219_0001
Revises:
Create Date: 2026-02-19
"""

from __future__ import annotations

from alembic import op

from app.core.db import Base
from app import models  # noqa: F401


revision = "20260219_0001"
down_revision = None
branch_labels = None
depends_on = None

POST_INITIAL_TABLES = {
    "admin_audit_logs",
    "crypto_deposit_requests",
}


def _initial_tables():
    return [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in POST_INITIAL_TABLES
    ]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_initial_tables())


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=list(reversed(_initial_tables())))
