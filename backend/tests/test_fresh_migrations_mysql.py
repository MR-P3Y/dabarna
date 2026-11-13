"""Opt-in real migration regression. Requires a NEW disposable MySQL schema."""
import os
import subprocess
import sys
import unittest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

if os.getenv("DAVARNA_FRESH_MIGRATION_TEST") != "I_ACK_DISPOSABLE_DB":
    raise unittest.SkipTest("disposable migration database required")
url = make_url(os.environ["DATABASE_URL"])
if url.host != "davarna-mysql" or url.database != "davarna_fresh_release_regression":
    raise RuntimeError("unexpected migration test destination")


class FreshMigrationTests(unittest.TestCase):
    def test_fresh_upgrade_and_repeat_preserve_records(self):
        engine = create_engine(url)
        self.addCleanup(engine.dispose)
        self.assertEqual(inspect(engine).get_table_names(), [])
        def upgrade():
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        upgrade()
        with engine.begin() as conn:
            self.assertEqual(conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "20261113_0013")
            conn.execute(text("INSERT INTO users (id,tg_user_id,first_name) VALUES (9001,9001,'fixture')"))
            conn.execute(text("INSERT INTO wallets (user_id,balance) VALUES (9001,12345)"))
            before = conn.execute(text("SELECT level,enabled,start_mode,game_rule FROM game_autopilot_configs ORDER BY level")).all()
        upgrade()
        with engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT balance FROM wallets WHERE user_id=9001")).scalar_one(),12345)
            self.assertEqual(conn.execute(text("SELECT level,enabled,start_mode,game_rule FROM game_autopilot_configs ORDER BY level")).all(),before)
            self.assertEqual(len(conn.execute(text("SHOW TRIGGERS")).all()), 5)
        cols={c["name"] for c in inspect(engine).get_columns("games")}
        self.assertTrue({"draw_mode","game_rule","card_layout_version","scheduled_start_at","autopilot_ready_at"} <= cols)
