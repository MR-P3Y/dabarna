from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.routers.admin_reports_router import games_sales_summary


class AdminReportsCryptoTests(unittest.TestCase):
    def test_successful_crypto_deposits_are_counted_by_credit_time(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE games (
                      id INTEGER PRIMARY KEY,
                      tg_group_id INTEGER,
                      tg_topic_id INTEGER,
                      commission_rate NUMERIC,
                      created_at DATETIME
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE game_purchases (
                      game_id INTEGER,
                      qty INTEGER,
                      total_price INTEGER,
                      created_at DATETIME
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE game_events (
                      game_id INTEGER,
                      kind TEXT,
                      payload_json JSON,
                      created_at DATETIME
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE crypto_deposit_requests (
                      network TEXT,
                      amount_toman INTEGER,
                      status TEXT,
                      credited_at DATETIME
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO crypto_deposit_requests
                      (network, amount_toman, status, credited_at)
                    VALUES
                      ('TRON', 500000, 'CREDITED', '2026-06-24 12:00:00'),
                      ('TON', 700000, 'REJECTED', '2026-06-24 13:00:00'),
                      ('TON', 900000, 'CREDITED', '2026-06-23 12:00:00')
                    """
                )
            )

        with Session(engine) as db:
            out = games_sales_summary(
                ident=SimpleNamespace(),
                db=db,
                from_at="2026-06-24 00:00:00",
                to_at="2026-06-24 23:59:59",
                tg_group_id=None,
                tg_topic_id=None,
            )
        engine.dispose()

        self.assertTrue(out["crypto_deposits_included"])
        self.assertEqual(out["crypto_deposits_count"], 1)
        self.assertEqual(out["crypto_deposits_total"], 500_000)
        self.assertEqual(out["crypto_tron_deposits_count"], 1)
        self.assertEqual(out["crypto_tron_deposits_total"], 500_000)
        self.assertEqual(out["crypto_ton_deposits_count"], 0)
        self.assertEqual(out["crypto_ton_deposits_total"], 0)


if __name__ == "__main__":
    unittest.main()
