"""Stable display numbers, independent of all financial and callback IDs.

Run with writers stopped. Each DDL step is independently resumable on MySQL.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa

revision = "20261115_0014"
down_revision = "20261113_0013"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    specs = [
        ("games", "display_code", sa.String(32), "uq_games_display_code", ["display_code"]),
        ("game_cards", "display_serial", sa.Integer, "uq_game_card_serial", ["game_id", "display_serial"]),
    ]
    for table, name, kind, index, keys in specs:
        inspector = sa.inspect(conn)
        if name not in {col["name"] for col in inspector.get_columns(table)}:
            op.add_column(table, sa.Column(name, kind, nullable=True))
        if index not in {i["name"] for i in sa.inspect(conn).get_indexes(table)}:
            op.create_index(index, table, keys, unique=True)

    # UNIX_TIMESTAMP reads the instant of a MySQL TIMESTAMP irrespective of session TZ.
    days = {}
    zone = ZoneInfo("Asia/Tehran")
    games = conn.execute(sa.text(
        "SELECT id,UNIX_TIMESTAMP(created_at),display_code FROM games ORDER BY id"
    )).all()
    for gid, epoch, existing in games:
        day = datetime.fromtimestamp(int(epoch), timezone.utc).astimezone(zone).strftime("%Y%m%d")
        serial = days[day] = days.get(day, 0) + 1
        code = f"G-{day}-{serial:03d}"
        if existing is None:
            conn.execute(sa.text("UPDATE games SET display_code=:code WHERE id=:id"), dict(code=code, id=gid))
        elif existing != code:
            raise RuntimeError("Display code already assigned differently")
    conn.execute(sa.text("""
        UPDATE game_cards c JOIN (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY id) AS serial
            FROM game_cards
        ) numbered ON numbered.id=c.id SET c.display_serial=numbered.serial
        WHERE c.display_serial IS NULL
    """))
    day = max(days, default="")
    if not conn.execute(sa.text("SELECT k FROM app_settings WHERE k='game_display_sequence'")).first():
        conn.execute(sa.text("""INSERT INTO app_settings(k,v_json)
            VALUES ('game_display_sequence',JSON_OBJECT('day',:day,'serial',:serial))"""),
            {"day":day, "serial":days.get(day, 0)})


def downgrade():
    # Assigned public references may already have been sent in Telegram.
    # Rolling back the application can retain this additive schema.
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM games WHERE display_code IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Keep published display numbers during application rollback")
    for table, index, name in (("game_cards","uq_game_card_serial","display_serial"),
                               ("games","uq_games_display_code","display_code")):
        op.drop_index(index, table_name=table)
        op.drop_column(table, name)
    conn.execute(sa.text("DELETE FROM app_settings WHERE k='game_display_sequence'"))
