"""Opt-in financial smoke tests against the *isolated* Davarna MySQL database.

Run only with DAVARNA_FINANCE_TEST_DB=davarna_tambola_v2_test_20261104.
Never connects to the production database. Every test uses a connection-level
transaction that is rolled back, while session commits use SAVEPOINTs.
"""
from __future__ import annotations

import itertools
import os
import secrets
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

TEST_DB = "davarna_tambola_v2_test_20261104"

if os.environ.get("DAVARNA_FINANCE_TEST_DB") != TEST_DB:
    raise unittest.SkipTest("explicit isolated MySQL opt-in required")

from dotenv import dotenv_values
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

secret_file = Path("/run/secrets/davarna_env")
if not secret_file.is_file():
    raise RuntimeError("read-only isolated test credentials mount is missing")
raw_url = dotenv_values(secret_file).get("DATABASE_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL missing in mounted environment file")
source_url = make_url(raw_url)
if source_url.get_backend_name() != "mysql":
    raise RuntimeError("expected MySQL connection credentials")
# Unconditionally replace BOTH the database and host. Do not trust any
# database/host from the deployment environment for test writes.
test_url = source_url.set(host="davarna-mysql", port=3306, database=TEST_DB)
os.environ["DATABASE_URL"] = test_url.render_as_string(hide_password=False)
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["GAME_AUTOPILOT_RUNTIME_ENABLED"] = "false"

from app.models.game import Game, GameCalledNumber, GameCard, GamePurchase
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.services.game_service import GameService


class MySQLFinanceSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(test_url, pool_pre_ping=True)
        with cls.engine.connect() as connection:
            dbname = connection.execute(text("SELECT DATABASE()")).scalar_one()
            if dbname != TEST_DB:
                raise RuntimeError("SAFETY STOP: connected to unexpected database")
            ver = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if ver != "20261104_0011":
                raise RuntimeError("SAFETY STOP: unexpected database migration version")
        print(f"Connected to isolated DB: {TEST_DB}; migration: {ver}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.outer_tx = self.connection.begin()
        # Business operations can commit between requests, but such commits
        # only release savepoints. The encompassing test transaction never
        # commits and is unconditionally rolled back in tearDown.
        self.db = Session(
            bind=self.connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        self.addCleanup(self._cleanup)
        self._make_fixtures()

    def _cleanup(self):
        try:
            self.db.close()
        finally:
            try:
                if self.outer_tx.is_active:
                    self.outer_tx.rollback()
            finally:
                self.connection.close()

    def _make_fixtures(self, *, rule="LINE"):
        nonce = secrets.randbelow(10**11)
        self.alice = User(tg_user_id=8000000000000 + nonce, first_name="finance-smoke-a")
        self.bob = User(tg_user_id=9000000000000 + nonce, first_name="finance-smoke-b")
        self.db.add_all([self.alice, self.bob])
        self.db.flush()
        self.db.add_all([
            Wallet(user_id=self.alice.id, balance=100000),
            Wallet(user_id=self.bob.id, balance=100000),
        ])
        self.game = Game(
            tg_group_id=-100999888777,
            tg_topic_id=6,
            admin_user_id=self.alice.id,
            card_price=5000,
            commission_rate=Decimal("0.1000"),
            game_level="LOW",
            card_layout_version=2,
            game_rule=rule,
            draw_mode="MANUAL",
            status="LOBBY",
        )
        self.db.add(self.game)
        self.db.commit()

    def _buy(self, user, key):
        purchase, cards, pool = GameService.buy_cards(
            self.db,
            game_id=int(self.game.id),
            user_id=int(user.id),
            qty=1,
            idempotency_key=key,
        )
        self.db.commit()
        return purchase, cards, pool

    def _balance(self, user):
        return int(self.db.execute(
            select(Wallet.balance).where(Wallet.user_id == user.id)
        ).scalar_one())

    def _count(self, model, *filters):
        query = select(func.count()).select_from(model)
        if filters:
            query = query.where(*filters)
        return int(self.db.execute(query).scalar_one())

    def _start(self):
        GameService.start_game(
            self.db,
            game_id=int(self.game.id),
            admin_user_id=int(self.alice.id),
            idempotency_key="smoke-start",
            can_manage_any=True,
        )
        self.db.commit()
        self.assertEqual(self.game.status, "RUNNING")
        self.assertEqual(self.game.prize_pool, 9000)

    def _call(self, number):
        self.db.add(GameCalledNumber(
            game_id=int(self.game.id),
            number=int(number),
            called_by=int(self.alice.id),
        ))
        self.db.flush()
        GameService._check_and_payout(self.db, self.game, int(number))
        self.db.commit()

    def test_buy_replay_and_refund_with_real_mysql_events(self):
        first, alice_cards, pool = self._buy(self.alice, "smoke-buy-alice")
        self.assertEqual(pool, 4500)
        second, bob_cards, pool = self._buy(self.bob, "smoke-buy-bob")
        self.assertEqual(pool, 9000)
        self.assertEqual(len(alice_cards), 1)
        self.assertEqual(len(bob_cards), 1)
        self.assertEqual(len(alice_cards[0].numbers_json), 27)
        self.assertEqual(len([n for n in alice_cards[0].numbers_json if n]), 15)

        repeated, replay_cards, _ = self._buy(self.alice, "smoke-buy-alice")
        self.assertEqual(first.id, repeated.id)
        self.assertEqual(alice_cards[0].id, replay_cards[0].id)
        with self.assertRaises(HTTPException) as cm:
            GameService.buy_cards(
                self.db, game_id=int(self.game.id),
                user_id=int(self.alice.id), qty=2,
                idempotency_key="smoke-buy-alice",
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.db.rollback()

        self.assertEqual(self._balance(self.alice), 95000)
        self.assertEqual(self._balance(self.bob), 95000)
        self.assertEqual(self._count(GamePurchase, GamePurchase.game_id == self.game.id), 2)
        self.assertEqual(self._count(GameCard, GameCard.game_id == self.game.id), 2)
        self.assertEqual(self._count(WalletTx, WalletTx.reason == "BUY_CARDS",
                                     WalletTx.ref_id == self.game.id), 2)
        events = self.db.execute(text(
            "SELECT COUNT(*) FROM game_events "
            "WHERE game_id=:game_id AND kind='CARDS_PURCHASED'"
        ), {"game_id": self.game.id}).scalar_one()
        self.assertEqual(int(events), 2, "MySQL purchase event recording failed")

        GameService.close_lobby_game(
            self.db, game_id=int(self.game.id),
            admin_user_id=int(self.alice.id),
            idempotency_key="smoke-close",
            can_manage_any=True,
        )
        self.db.commit()
        self.assertEqual(self._balance(self.alice), 100000)
        self.assertEqual(self._balance(self.bob), 100000)
        self.assertEqual(self.game.status, "ENDED")
        GameService.close_lobby_game(
            self.db, game_id=int(self.game.id),
            admin_user_id=int(self.alice.id),
            idempotency_key="smoke-close-repeated",
            can_manage_any=True,
        )
        self.db.commit()
        self.assertEqual(self._balance(self.alice), 100000)
        self.assertEqual(self._balance(self.bob), 100000)
        self.assertEqual(self._count(WalletTx, WalletTx.reason == "ADJUST",
                                     WalletTx.ref_id == self.game.id), 2)

    def test_line_tourna_then_final_exact_once(self):
        _, alice_cards, _ = self._buy(self.alice, "line-alice")
        _, bob_cards, _ = self._buy(self.bob, "line-bob")
        self._start()
        a = alice_cards[0]
        b = bob_cards[0]
        chosen = None
        for offset in (0, 9, 18):
            row = [int(n) for n in a.numbers_json[offset:offset + 9] if n]
            if GameService._winner_cards([b], set(row), "ROW",
                                         layout_version=2, game_rule="LINE"):
                continue
            for triple in itertools.combinations(row, 3):
                if not GameService._winner_cards(
                    [b], set(triple), "COL",
                    layout_version=2, game_rule="LINE"
                ):
                    chosen = (row, triple)
                    break
            if chosen:
                break
        self.assertIsNotNone(chosen, "no uncontested row; rerun generated-card test")
        row, triple = chosen
        for number in triple:
            self._call(number)
        self.assertEqual(self._balance(self.alice), 98000)  # 95,000 + 3,000
        self.assertEqual(self.game.col_paid, 1)
        GameService._check_and_payout(self.db, self.game, int(triple[-1]))
        self.db.commit()
        self.assertEqual(self._balance(self.alice), 98000)

        for number in row:
            if number not in triple:
                self._call(number)
        self.assertEqual(self._balance(self.alice), 104000)  # + 6,000
        self.assertEqual(self.game.status, "ENDED")
        GameService._check_and_payout(self.db, self.game, int(row[-1]))
        self.db.commit()
        self.assertEqual(self._balance(self.alice), 104000)
        self.assertEqual(self._count(WalletTx, WalletTx.reason == "PRIZE_COL",
                                     WalletTx.ref_id == self.game.id), 1)
        self.assertEqual(self._count(WalletTx, WalletTx.reason == "PRIZE_ROW",
                                     WalletTx.ref_id == self.game.id), 1)

    def test_full_card_pays_only_after_fifteen(self):
        self.game.game_rule = "FULL_CARD"
        self.db.commit()
        _, alice_cards, _ = self._buy(self.alice, "full-alice")
        self._buy(self.bob, "full-bob")
        self._start()
        self.assertEqual(self.game.col_prize_amount, 0)
        self.assertEqual(self.game.row_prize_amount, 9000)
        numbers = [int(n) for n in alice_cards[0].numbers_json if n]
        for number in numbers[:-1]:
            self._call(number)
        self.assertEqual(self._balance(self.alice), 95000)
        self.assertEqual(self._count(WalletTx, WalletTx.reason == "PRIZE_COL",
                                     WalletTx.ref_id == self.game.id), 0)
        self._call(numbers[-1])
        self.assertEqual(self._balance(self.alice), 104000)
        self.assertEqual(self.game.status, "ENDED")
        self.assertEqual(self._count(WalletTx, WalletTx.reason == "PRIZE_ROW",
                                     WalletTx.ref_id == self.game.id), 1)


    def test_v2_snapshot_nearest_progress_with_full_ninety_calls(self):
        """The V2 preview must count 15 numbers, never 27 cells or just 50 calls."""
        from app.routers.mini_router import game_snapshot

        _, cards, _ = self._buy(self.alice, "snapshot-alice")
        actual = [int(n) for n in cards[0].numbers_json if n > 0]
        rest = [n for n in range(1, 91) if n not in set(actual)]
        self.assertEqual(len(actual) + len(rest), 90)
        self.db.add_all([
            GameCalledNumber(
                game_id=int(self.game.id),
                number=number,
                called_by=int(self.alice.id),
            )
            for number in actual + rest
        ])
        self.db.flush()
        with patch("app.routers.mini_router._read_game_live_link", return_value=(None, None)):
            snapshot = game_snapshot(
                game_id=int(self.game.id),
                events_limit=5,
                user_id=int(self.alice.id),
                db=self.db,
            )
        st = snapshot.state
        nearest = st["nearest_to_win"]
        self.assertEqual(st["called_count"], 90)
        self.assertEqual(len(st["called_numbers"]), 90)
        self.assertEqual(nearest["total_numbers"], 15)
        self.assertEqual(nearest["called_count"], 15)
        self.assertEqual(nearest["missing"], 0)
        self.assertEqual(nearest["percent"], 100)

    def test_bot_admin_report_responds_with_v2_metadata(self):
        """Regression guard: game report's raw SQL must include V2 fields."""
        from app.routers.bot_router import get_bot_admin_game_report

        with patch("app.routers.bot_router._require_game_admin_access"):
            report = get_bot_admin_game_report(
                game_id=int(self.game.id),
                events_limit=5,
                db=self.db,
                admin=object(),
            )
        self.assertEqual(report.game.card_layout_version, 2)
        self.assertEqual(report.game.game_rule, "LINE")
        self.assertEqual(report.game.commission_rate, 0.1)


if __name__ == "__main__":
    unittest.main()
