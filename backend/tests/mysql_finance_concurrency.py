"""Opt-in concurrent MySQL wallet/purchase smoke tests. NEVER run on production.

Requires DAVARNA_FINANCE_TEST_DB=davarna_tambola_v2_test_20261104 and
/run/secrets/davarna_env mounted read-only. Creates committed test-only records
in the isolated database so multiple MySQL connections can see them; removes
only its own records in the unittest cleanup. If cleanup fails, the test fails.
"""
from __future__ import annotations

import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

TEST_DB = "davarna_tambola_v2_test_20261104"
if os.environ.get("DAVARNA_FINANCE_TEST_DB") != TEST_DB:
    raise unittest.SkipTest("isolated MySQL test requires explicit opt-in")

from dotenv import dotenv_values
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

secret_file = Path("/run/secrets/davarna_env")
if not secret_file.is_file():
    raise RuntimeError("missing read-only test credential mount")

source = dotenv_values(secret_file).get("DATABASE_URL")
if not source:
    raise RuntimeError("DATABASE_URL missing from mounted configuration")
url = make_url(source)
if url.get_backend_name() != "mysql":
    raise RuntimeError("expected MySQL connection credentials")
url = url.set(host="davarna-mysql", port=3306, database=TEST_DB)
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["GAME_AUTOPILOT_RUNTIME_ENABLED"] = "false"

from app.models.game import Game, GameCard, GamePurchase
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.services.game_service import GameService
from app.services.wallet_service import WalletService


class MySQLFinanceConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(url, pool_pre_ping=True, pool_size=6, max_overflow=2)
        with cls.engine.connect() as conn:
            name = conn.execute(text("SELECT DATABASE()")).scalar_one()
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if name != TEST_DB or revision != "20261104_0011":
                cls.engine.dispose()
                raise RuntimeError("SAFETY STOP: unexpected DB or migration version")
        print(f"Concurrent tests enabled only for {TEST_DB} ({revision})")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()

    def setUp(self):
        self.tag = "fc" + uuid4().hex[:22]
        self.game_id = None
        self.user_ids = []
        self.wallet_ids = []
        with Session(self.engine) as db:
            # The numeric Telegram IDs are intentionally synthetic; they will
            # never send Telegram messages or authenticate as real users.
            first = User(
                tg_user_id=7000000000000 + secrets.randbelow(10**10),
                username=self.tag + "a", first_name="finance-concurrency-a",
            )
            second = User(
                tg_user_id=7100000000000 + secrets.randbelow(10**10),
                username=self.tag + "b", first_name="finance-concurrency-b",
            )
            db.add_all((first, second))
            db.flush()
            self.alice_id = int(first.id)
            self.bob_id = int(second.id)
            self.user_ids = [self.alice_id, self.bob_id]
            wallets = [
                Wallet(user_id=self.alice_id, balance=100000),
                Wallet(user_id=self.bob_id, balance=100000),
            ]
            db.add_all(wallets)
            db.flush()
            self.wallet_ids = [int(w.id) for w in wallets]
            game = Game(
                tg_group_id=-100999888777,
                tg_topic_id=6,
                admin_user_id=self.alice_id,
                card_price=5000,
                commission_rate=Decimal("0.1000"),
                game_level="LOW",
                card_layout_version=2,
                game_rule="LINE",
                execution_source="ADMIN",
                draw_mode="MANUAL",
                status="LOBBY",
            )
            db.add(game)
            db.flush()
            self.game_id = int(game.id)
            db.commit()
        # Register cleanup before running any test assertions. On every test
        # failure, cleanup runs and removes only these known synthetic IDs.
        self.addCleanup(self._remove_synthetic_records)

    def _remove_synthetic_records(self):
        if self.game_id is None:
            return
        gid = self.game_id
        a, b = self.user_ids
        wa, wb = self.wallet_ids
        try:
            with Session(self.engine) as db:
                with db.begin():
                    # FK-safe removal order, scoped to our synthetic game/users.
                    for query, params in (
                        ("DELETE FROM game_events WHERE game_id=:gid", {"gid": gid}),
                        ("DELETE FROM game_called_numbers WHERE game_id=:gid", {"gid": gid}),
                        ("DELETE FROM game_auto_draws WHERE game_id=:gid", {"gid": gid}),
                        ("DELETE FROM game_cards WHERE game_id=:gid", {"gid": gid}),
                        ("DELETE FROM game_purchases WHERE game_id=:gid", {"gid": gid}),
                        ("DELETE FROM wallet_txs WHERE wallet_id IN (:wa,:wb)", {"wa": wa, "wb": wb}),
                        ("DELETE FROM wallets WHERE id IN (:wa,:wb)", {"wa": wa, "wb": wb}),
                        ("DELETE FROM games WHERE id=:gid", {"gid": gid}),
                        ("DELETE FROM users WHERE id IN (:a,:b)", {"a": a, "b": b}),
                    ):
                        db.execute(text(query), params)
                remaining = db.execute(
                    text("SELECT COUNT(*) FROM users WHERE id IN (:a,:b)"), {"a": a, "b": b}
                ).scalar_one()
                if int(remaining):
                    raise AssertionError("synthetic users remain after cleanup")
        except Exception:
            print(
                f"CLEANUP FAILED — only isolated DB {TEST_DB}; "
                f"synthetic game_id={gid}, user_ids={self.user_ids}, wallet_ids={self.wallet_ids}"
            )
            raise

    def _purchase_worker(self, barrier: Barrier, key: str, qty: int):
        with Session(self.engine, expire_on_commit=False) as db:
            barrier.wait(timeout=15)
            try:
                purchase, cards, pool = GameService.buy_cards(
                    db=db, game_id=self.game_id,
                    user_id=self.alice_id, qty=qty,
                    idempotency_key=key,
                )
                db.commit()
                return ("ok", int(purchase.id), tuple(int(c.id) for c in cards), int(pool))
            except HTTPException as exc:
                db.rollback()
                return ("http", int(exc.status_code), str(exc.detail))

    def _run_purchases(self, requests):
        barrier = Barrier(len(requests))
        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            futures = [
                executor.submit(self._purchase_worker, barrier, key, qty)
                for key, qty in requests
            ]
            return [future.result(timeout=30) for future in futures]

    def _snapshot(self):
        with Session(self.engine) as db:
            wallet_balance = int(db.execute(
                select(Wallet.balance).where(Wallet.user_id == self.alice_id)
            ).scalar_one())
            game = db.get(Game, self.game_id)
            purchases = int(db.execute(
                select(func.count()).select_from(GamePurchase)
                .where(GamePurchase.game_id == self.game_id)
            ).scalar_one())
            cards = int(db.execute(
                select(func.count()).select_from(GameCard)
                .where(GameCard.game_id == self.game_id)
            ).scalar_one())
            debits = int(db.execute(
                select(func.count()).select_from(WalletTx)
                .where(WalletTx.wallet_id == self.wallet_ids[0],
                       WalletTx.reason == "BUY_CARDS")
            ).scalar_one())
            events = int(db.execute(text(
                "SELECT COUNT(*) FROM game_events "
                "WHERE game_id=:gid AND kind='CARDS_PURCHASED'"
            ), {"gid": self.game_id}).scalar_one())
            return (wallet_balance, int(game.sold_amount),
                    int(game.commission_amount), int(game.prize_pool),
                    purchases, cards, debits, events)

    def test_four_simultaneous_same_key_debit_once(self):
        results = self._run_purchases([("same-key", 1)] * 4)
        self.assertTrue(all(r[0] == "ok" for r in results), results)
        self.assertEqual(len({r[1] for r in results}), 1, results)
        self.assertEqual(len({r[2] for r in results}), 1, results)
        self.assertEqual(
            self._snapshot(),
            (95000, 5000, 500, 4500, 1, 1, 1, 1),
        )

    def test_four_simultaneous_distinct_keys_all_count_once(self):
        requests = [(f"separate-{i}", 1) for i in range(4)]
        results = self._run_purchases(requests)
        self.assertTrue(all(r[0] == "ok" for r in results), results)
        self.assertEqual(len({r[1] for r in results}), 4, results)
        self.assertEqual(
            self._snapshot(),
            (80000, 20000, 2000, 18000, 4, 4, 4, 4),
        )

    def test_simultaneous_conflicting_quantities_reject_second(self):
        results = self._run_purchases([("conflict-key", 1), ("conflict-key", 2)])
        successes = [r for r in results if r[0] == "ok"]
        rejected = [r for r in results if r[0] == "http"]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(rejected), 1, results)
        self.assertEqual(rejected[0][1], 409, results)
        quantity = len(successes[0][2])
        total = 5000 * quantity
        self.assertEqual(
            self._snapshot(),
            (100000 - total, total, 500 * quantity,
             4500 * quantity, 1, quantity, 1, 1),
        )

    def test_simultaneous_wallet_credit_same_key_once(self):
        barrier = Barrier(4)

        def credit_worker():
            with Session(self.engine) as db:
                barrier.wait(timeout=15)
                tx = WalletService.credit(
                    db=db,
                    user_id=self.alice_id,
                    amount=2500,
                    reason="ADJUST",
                    idempotency_key="concurrent-credit",
                    ref_type="ADMIN_ADJUST",
                    ref_id=self.bob_id,
                )
                db.commit()
                return int(tx.id)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(credit_worker) for _ in range(4)]
            ids = [f.result(timeout=30) for f in futures]
        self.assertEqual(len(set(ids)), 1)
        with Session(self.engine) as db:
            balance = db.execute(
                select(Wallet.balance).where(Wallet.user_id == self.alice_id)
            ).scalar_one()
            count = db.execute(
                select(func.count()).select_from(WalletTx)
                .where(
                    WalletTx.wallet_id == self.wallet_ids[0],
                    WalletTx.idempotency_key == "concurrent-credit",
                )
            ).scalar_one()
        self.assertEqual((int(balance), int(count)), (102500, 1))


if __name__ == "__main__":
    unittest.main()
