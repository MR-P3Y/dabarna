"""Opt-in MySQL Autopilot end-to-end test in the *named test DB only*.

Never run against a production schema. Uses an outer database transaction
that is rolled back at the end of every test. Inner application commits
release SAVEPOINTs, not the test's outer transaction.

Requires:
  DAVARNA_AUTOPILOT_E2E_DB=davarna_tambola_v2_test_20261104
  /run/secrets/davarna_env with DATABASE_URL for connection credentials.
The source host/database are ALWAYS replaced with davarna-mysql / TEST_DB.
No Telegram, Redis or live game worker is contacted.
"""
from __future__ import annotations

import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

TEST_DB = "davarna_tambola_v2_test_20261104"
if os.environ.get("DAVARNA_AUTOPILOT_E2E_DB") != TEST_DB:
    raise unittest.SkipTest("explicit isolated Autopilot test database opt-in required")

from dotenv import dotenv_values
from sqlalchemy import and_, create_engine, func, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

secret_file = Path("/run/secrets/davarna_env")
if not secret_file.is_file():
    raise RuntimeError("read-only database credentials mount required")
raw_url = dotenv_values(secret_file).get("DATABASE_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL unavailable in private credentials mount")
source_url = make_url(raw_url)
if source_url.get_backend_name() != "mysql":
    raise RuntimeError("SAFETY STOP: expected MySQL")
test_url = source_url.set(host="davarna-mysql", port=3306, database=TEST_DB)
if test_url.database != TEST_DB or test_url.host != "davarna-mysql":
    raise RuntimeError("SAFETY STOP: test database or host mismatch")
os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["GAME_AUTOPILOT_RUNTIME_ENABLED"] = "false"
# The test container is read-only; receipts must go to its writable tmpfs.
os.environ["RECEIPTS_DIR"] = "/tmp/receipts"

from app.core import config as cfg
from app.models.game import Game, GameAutoDraw, GameCalledNumber
from app.models.game_autopilot import GameAutopilotConfig
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.services.game_autopilot_worker import GameAutopilotWorker
from app.services.game_auto_draw_worker import GameAutoDrawWorker
from app.services.game_service import GameService


class MySQLAutopilotEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(test_url, pool_pre_ping=True)
        with cls.engine.connect() as db:
            actual_db = db.execute(text("SELECT DATABASE()")).scalar_one()
            if actual_db != TEST_DB:
                raise RuntimeError("SAFETY STOP: wrong database selected")
            version = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if version != "20261104_0011":
                raise RuntimeError(f"SAFETY STOP: wrong test schema migration {version}")
        print(f"ISOLATED MYSQL ONLY: {TEST_DB}, migration {version}")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.conn = self.engine.connect()
        self.outer = self.conn.begin()
        # All worker sessions use this *same* test-only outer DB transaction.
        self.Factory = sessionmaker(
            bind=self.conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        self.db = self.Factory()
        self.addCleanup(self.cleanup)

        nonce = secrets.randbelow(10**10)
        self.group_id = -(1007000000000 + nonce)
        self.alice = User(tg_user_id=7000000000000 + nonce, first_name="autopilot-test-a")
        self.bob = User(tg_user_id=8000000000000 + nonce, first_name="autopilot-test-b")
        self.db.add_all([self.alice, self.bob])
        self.db.flush()
        self.db.add_all([
            Wallet(user_id=int(self.alice.id), balance=100_000),
            Wallet(user_id=int(self.bob.id), balance=100_000),
        ])
        row = self.db.get(GameAutopilotConfig, "LOW")
        if row is None:
            raise RuntimeError("isolated test DB is missing LOW Autopilot config")
        row.enabled = 1
        row.scheduler_mode = "AUTO"
        row.start_mode = "AUTO"
        row.draw_mode = "AUTO"
        row.game_rule = "LINE"
        row.card_price = 5_000
        row.commission_rate = Decimal("0.1000")
        row.min_unique_players = 2
        row.countdown_seconds = 30
        row.draw_interval_seconds = 8
        row.cooldown_seconds = 30
        row.repeat_interval_seconds = 120
        # The persistent *test* schema can contain stale active LOW games from
        # earlier test sessions. GameService.create_game intentionally enforces
        # one active game per level globally (not just per Telegram group).
        # Temporarily mask these rows inside this test's OUTER transaction.
        # No schema changes, deletions, wallet operations, or committed writes.
        preexisting_low = self.db.execute(
            select(Game).where(
                or_(
                    Game.game_level == "LOW",
                    and_(
                        Game.game_level.is_(None),
                        Game.tg_topic_id == 6,
                    ),
                ),
                Game.status.in_(("LOBBY", "RUNNING")),
            ).with_for_update()
        ).scalars().all()
        if len(preexisting_low) > 20:
            raise RuntimeError(
                "SAFETY STOP: too many preexisting active LOW games in isolated test DB"
            )
        for previous in preexisting_low:
            previous.status = "ENDED"
            previous.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if preexisting_low:
            print(
                f"Isolated test DB: temporarily masking {len(preexisting_low)}"
                " preexisting LOW games (outer transaction rolls back all changes)"
            )

        # Other lanes may already have test settings; disable them inside
        # the same outer test transaction.
        for name in ("MEDIUM", "HIGH"):
            other = self.db.get(GameAutopilotConfig, name)
            if other is not None:
                other.enabled = 0
        self.db.commit()

    def cleanup(self):
        try:
            self.db.close()
        finally:
            try:
                if self.outer.is_active:
                    self.outer.rollback()
            finally:
                self.conn.close()

    def tick(self, when):
        # Redis lock is mocked, but the Autopilot runs its actual SQL service.
        with (
            patch("app.services.game_autopilot_worker.SessionLocal", self.Factory),
            patch("app.services.game_autopilot_worker.RedisLock") as lock,
            patch("app.services.game_autopilot_worker._utcnow_naive", return_value=when),
        ):
            lock.return_value.acquire.return_value = True
            stats = GameAutopilotWorker.run_once()
            self.assertEqual(stats["failed"], 0, stats)
            return stats["levels"]["LOW"]

    def check_wallet(self, user_id):
        self.db.expire_all()
        return int(self.db.execute(select(Wallet.balance).where(Wallet.user_id == user_id)).scalar_one())

    def financial_snapshot(self, game_id):
        self.db.expire_all()
        txs = self.db.execute(
            select(WalletTx).where(
                WalletTx.ref_type == "GAME",
                WalletTx.ref_id == int(game_id),
            )
        ).scalars().all()
        return {
            "buy": sum(int(tx.amount) for tx in txs if tx.reason == "BUY_CARDS" and tx.direction == "DEBIT"),
            "prizes": sum(int(tx.amount) for tx in txs if tx.reason in {"PRIZE_ROW", "PRIZE_COL"} and tx.direction == "CREDIT"),
            "prize_count": sum(1 for tx in txs if tx.reason in {"PRIZE_ROW", "PRIZE_COL"} and tx.direction == "CREDIT"),
            "idempotency_unique": len({(int(tx.wallet_id), str(tx.idempotency_key)) for tx in txs}) == len(txs),
        }

    def test_two_player_autopilot_draw_payout_and_next_round(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with (
            patch.object(cfg, "GAME_TAMBOLA_V2_ENABLED", True),
            patch.object(cfg, "GAME_AUTO_DRAW_ENABLED", True),
            patch.object(cfg, "GAME_AUTOPILOT_RUNTIME_ENABLED", True),
            patch.object(cfg, "USER_FORUM_CHAT_ID", self.group_id),
            patch.object(cfg, "GAME_AUTOPILOT_SYSTEM_USER_ID", int(self.alice.id)),
            patch(
                "app.services.game_autopilot_worker.GameAutopilotConfigService.topic_id_for_level",
                return_value=6,
            ),
        ):
            self.assertEqual(self.tick(now), "created")
            self.db.expire_all()
            game = self.db.execute(
                select(Game).where(
                    Game.tg_group_id == self.group_id,
                    Game.execution_source == "SYSTEM",
                )
            ).scalar_one()
            game_id = int(game.id)
            self.assertEqual(str(game.game_rule), "LINE")
            self.assertEqual(int(game.card_layout_version), 2)
            control = self.db.get(GameAutoDraw, game_id)
            self.assertEqual(str(control.status), "ARMED")
            self.assertEqual(len(control.sequence_json), 90)
            self.assertEqual(len(set(control.sequence_json)), 90)
            self.assertIsNotNone(control.sequence_commitment)

            GameService.buy_cards(
                self.db, game_id, int(self.alice.id), 1,
                idempotency_key="e2e-buy-alice",
            )
            self.db.commit()
            self.assertEqual(self.tick(now + timedelta(seconds=1)), "waiting_players")
            self.db.expire_all()
            self.assertEqual(str(self.db.get(Game, game_id).status), "LOBBY")

            GameService.buy_cards(
                self.db, game_id, int(self.bob.id), 1,
                idempotency_key="e2e-buy-bob",
            )
            self.db.commit()
            self.assertEqual(self.tick(now + timedelta(seconds=2)), "countdown_armed")
            self.assertEqual(self.tick(now + timedelta(seconds=20)), "countdown_wait")
            self.assertEqual(self.tick(now + timedelta(seconds=34)), "started")

            self.db.expire_all()
            game = self.db.get(Game, game_id)
            self.assertEqual(str(game.status), "RUNNING")
            self.assertIsNotNone(game.draw_mode_locked_at)
            control = self.db.get(GameAutoDraw, game_id)
            self.assertEqual(str(control.status), "RUNNING")
            self.assertEqual(int(game.prize_pool), 9000)
            self.assertEqual(int(game.commission_amount), 1000)
            self.assertEqual(self.financial_snapshot(game_id)["buy"], 10_000)

            # The actual SQL MySQL trigger and real GameService.call_number
            # execute; only Redis lock/cache and external clock are mocked.
            with (
                patch("app.services.game_auto_draw_worker.SessionLocal", self.Factory),
                patch("app.services.game_service.RedisLock") as lock,
                patch("app.services.game_service.idem_get", return_value=None),
                patch("app.services.game_service.idem_set"),
            ):
                lock.return_value.acquire.return_value = True
                for _ in range(90):
                    self.assertTrue(GameAutoDrawWorker._draw_game(game_id))
                    self.db.expire_all()
                    if str(self.db.get(Game, game_id).status) == "ENDED":
                        break
                else:
                    self.fail("90 AUTO numbers were drawn without finishing game")
                self.assertFalse(GameAutoDrawWorker._draw_game(game_id))

            self.db.expire_all()
            game = self.db.get(Game, game_id)
            control = self.db.get(GameAutoDraw, game_id)
            self.assertEqual(str(game.status), "ENDED")
            self.assertEqual(str(control.status), "STOPPED")
            called = self.db.execute(
                select(func.count(GameCalledNumber.id)).where(GameCalledNumber.game_id == game_id)
            ).scalar_one()
            self.assertEqual(int(control.cursor), int(called))
            snapshot = self.financial_snapshot(game_id)
            self.assertEqual(snapshot["buy"], 10000)
            self.assertEqual(snapshot["prizes"], 9000)
            self.assertTrue(snapshot["idempotency_unique"])
            self.assertGreater(snapshot["prize_count"], 0)
            self.assertEqual(
                self.check_wallet(int(self.alice.id)) + self.check_wallet(int(self.bob.id)),
                200000 - 10000 + 9000,
            )
            # Avoid false positive with all credits in only one wallet.
            payout_before = self.financial_snapshot(game_id)
            with (
                patch("app.services.game_auto_draw_worker.SessionLocal", self.Factory),
                patch("app.services.game_service.RedisLock") as lock,
            ):
                lock.return_value.acquire.return_value = True
                self.assertFalse(GameAutoDrawWorker._draw_game(game_id))
            self.assertEqual(payout_before, self.financial_snapshot(game_id))

            ended = self.db.get(Game, game_id).ended_at
            self.assertIsNotNone(ended)
            self.assertEqual(self.tick(ended + timedelta(seconds=60)), "cooldown")
            self.assertEqual(self.tick(ended + timedelta(seconds=130)), "created")
            self.db.expire_all()
            active = self.db.execute(
                select(Game).where(
                    Game.tg_group_id == self.group_id,
                    Game.execution_source == "SYSTEM",
                    Game.status.in_(["LOBBY", "RUNNING"]),
                )
            ).scalars().all()
            self.assertEqual(len(active), 1)
            self.assertNotEqual(int(active[0].id), game_id)
            self.assertEqual(str(active[0].status), "LOBBY")
            self.assertEqual(self.financial_snapshot(game_id)["prizes"], 9000)
            print("PASS: isolated MySQL Autopilot start/draw/winner/payout/repeat; all changes rollback")


if __name__ == "__main__":
    unittest.main()
