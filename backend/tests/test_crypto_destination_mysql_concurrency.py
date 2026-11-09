"""MySQL-only concurrency regression. Never run against Production.

Requires dedicated host davarna-wallet-mysql and schema davarna_wallet_rotation_test.
Run only after disposable database provisioning with no shared Docker volumes.
"""
from __future__ import annotations

import os
import hashlib
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

if os.getenv("DAVARNA_WALLET_MYSQL_CONCURRENCY") != "I_ACK_DISPOSABLE_DB":
    raise unittest.SkipTest("disposable MySQL opt-in required")
URL = os.getenv("DATABASE_URL", "")
parsed = make_url(URL)
if not (parsed.get_backend_name() == "mysql" and parsed.host == "davarna-wallet-mysql"
        and parsed.database == "davarna_wallet_rotation_test"):
    raise unittest.SkipTest("refusing non-disposable database")

from app.models.settings import AppSetting
from app.services.crypto_destination_state import (
    lock_destination_state, rotate_locked, seed_destination_state,
)
from app.core import config as cfg


class _AtomicWalletMySQLConcurrency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(URL, pool_pre_ping=True, pool_size=3)
        with cls.engine.begin() as con:
            actual = con.execute(text("SELECT DATABASE()")).scalar()
            if actual != "davarna_wallet_rotation_test":
                raise AssertionError("unsafe database target")
        AppSetting.__table__.create(cls.engine, checkfirst=True)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def test_invoice_reader_blocks_behind_rotation_lock(self):
        # We use a mock address validator because this test is about SQL
        # transaction locking, not wallet address encoding.
        from app.services import crypto_destination_state as state
        gate = patch.object(state, "rotation_enabled", return_value=True)
        valid = patch.object(state, "validate_crypto_destination", side_effect=lambda n, a: a)
        gate.start()
        valid.start()
        self.addCleanup(gate.stop)
        self.addCleanup(valid.stop)
        with self.engine.begin() as con:
            con.execute(text("DELETE FROM app_settings WHERE k = 'crypto_destination_v1:TRON'"))
        with Session(self.engine) as db:
            seed_destination_state(db, network="TRON", address="OLD")
            db.commit()

        held = threading.Event()
        attempting = threading.Event()
        release = threading.Event()
        events = []

        def rotate():
            with Session(self.engine) as db:
                new = rotate_locked(db, network="TRON", expected_version=1,
                                    expected_address="OLD", new_address="NEW")
                events.append(("rotated_uncommitted", new["version"]))
                held.set()
                if not release.wait(8):
                    raise AssertionError("lock coordination timed out")
                db.commit()
                events.append(("rotation_committed", new["version"]))

        def invoice_read():
            if not held.wait(8):
                raise AssertionError("rotation lock not acquired")
            attempting.set()
            with Session(self.engine) as db:
                version = lock_destination_state(db, "TRON")
                events.append(("invoice_read", version["version"]))
                db.commit()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(rotate)
            self.assertTrue(held.wait(8))
            b = pool.submit(invoice_read)
            self.assertTrue(attempting.wait(8), "invoice reader never attempted lock")
            time.sleep(0.35)
            self.assertNotIn("invoice_read", [row[0] for row in events],
                             "invoice must wait for the rotation commit")
            release.set()
            a.result(timeout=12)
            b.result(timeout=12)
        # Both commits and reads are proven by their observed values, not by
        # post-commit Python list append order: once db.commit() returns, the
        # waiting reader may acquire the lock before the writer appends its log.
        self.assertEqual(len(events), 3, events)
        self.assertEqual(events[0], ("rotated_uncommitted", 2))
        self.assertCountEqual(
            events[1:],
            [("rotation_committed", 2), ("invoice_read", 2)],
        )

    def test_concurrent_invoice_snapshot_is_consistent_and_rollback_restores_old_destination(self):
        """Persistent invoice snapshots are serialized against rotation commit."""
        from app.services import crypto_destination_state as state
        # Dedicated disposable schema only; table has no Production equivalent.
        with self.engine.begin() as con:
            con.execute(text(
                "CREATE TABLE IF NOT EXISTS wallet_rotation_invoice_snapshots "
                "(id BIGINT PRIMARY KEY AUTO_INCREMENT, address VARCHAR(128) NOT NULL, "
                "version INTEGER NOT NULL) ENGINE=InnoDB"
            ))
            con.execute(text("DELETE FROM wallet_rotation_invoice_snapshots"))
            con.execute(text("DELETE FROM app_settings WHERE k = 'crypto_destination_v1:TRON'"))

        with patch.object(state, "rotation_enabled", return_value=True), patch.object(
            state, "validate_crypto_destination", side_effect=lambda n, a: a,
        ):
            with Session(self.engine) as db:
                seed_destination_state(db, network="TRON", address="OLD")
                db.commit()

            got_lock = threading.Event()
            release_lock = threading.Event()
            reader_attempting = threading.Event()
            order = []

            def issue_first():
                with Session(self.engine) as db:
                    snapshot = lock_destination_state(db, "TRON")
                    db.execute(
                        text("INSERT INTO wallet_rotation_invoice_snapshots(address, version) "
                             "VALUES (:address, :version)"),
                        snapshot,
                    )
                    got_lock.set()
                    if not release_lock.wait(8):
                        raise AssertionError("first invoice lock timed out")
                    db.commit()
                    order.append(("invoice_first", snapshot["address"]))

            def rotate_after_first():
                if not got_lock.wait(8):
                    raise AssertionError("first invoice not started")
                reader_attempting.set()
                with Session(self.engine) as db:
                    result = rotate_locked(db, network="TRON", expected_version=1,
                                           expected_address="OLD", new_address="NEW")
                    db.commit()
                    order.append(("rotation", result["address"]))

            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(issue_first)
                self.assertTrue(got_lock.wait(8))
                rotator = pool.submit(rotate_after_first)
                self.assertTrue(reader_attempting.wait(8))
                time.sleep(0.35)
                self.assertFalse(order, "rotation must not commit ahead of invoice")
                release_lock.set()
                first.result(timeout=12)
                rotator.result(timeout=12)

            with Session(self.engine) as db:
                after = lock_destination_state(db, "TRON")
                db.execute(
                    text("INSERT INTO wallet_rotation_invoice_snapshots(address, version) "
                         "VALUES (:address, :version)"),
                    after,
                )
                db.commit()

            with self.engine.begin() as con:
                saved = con.execute(text(
                    "SELECT address, version FROM wallet_rotation_invoice_snapshots ORDER BY id"
                )).all()
            self.assertEqual([tuple(row) for row in saved], [("OLD", 1), ("NEW", 2)])
            self.assertEqual(order, [("invoice_first", "OLD"), ("rotation", "NEW")])

            # A rollback is a NEW version, and cannot rewrite existing snapshots.
            with Session(self.engine) as db:
                back = rotate_locked(db, network="TRON", expected_version=2,
                                     expected_address="NEW", new_address="OLD")
                db.commit()
            self.assertEqual(back["version"], 3)
            with self.engine.begin() as con:
                saved_after = con.execute(text(
                    "SELECT address, version FROM wallet_rotation_invoice_snapshots ORDER BY id"
                )).all()
            self.assertEqual([tuple(row) for row in saved_after], [("OLD", 1), ("NEW", 2)])

    def test_real_ledger_replay_does_not_double_credit_after_restart(self):
        """Same hash, same user: two sessions must yield one wallet ledger row."""
        from app.core.db import Base
        from app.models.user import User
        from app.models.wallet import Wallet, WalletTx
        from app.services.wallet_service import WalletService
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, Wallet.__table__, WalletTx.__table__],
            checkfirst=True,
        )
        with self.engine.begin() as con:
            # MySQL test DB is guaranteed isolated by module-level allowlist.
            # Avoid deleting users: other tests can leave their FK'd invoices.
            con.execute(text("DELETE FROM wallet_txs"))
            con.execute(text("DELETE FROM wallets"))
        with Session(self.engine) as db:
            db.add(User(tg_user_id=991223344))
            db.flush()
            uid = db.execute(
                text("SELECT id FROM users WHERE tg_user_id=991223344")
            ).scalar_one()
            db.commit()
        idem = "crypto:TRON:" + "a" * 64
        with Session(self.engine) as db:
            tx = WalletService.credit(
                db, user_id=uid, amount=125000, reason="DEPOSIT_CRYPTO",
                idempotency_key=idem, ref_type="CRYPTO_DEPOSIT", ref_id=724,
            )
            self.assertEqual(tx.amount, 125000)
            db.commit()
        # A new SQLAlchemy session emulates worker restart/replayed scan.
        with Session(self.engine) as db:
            replay = WalletService.credit(
                db, user_id=uid, amount=125000, reason="DEPOSIT_CRYPTO",
                idempotency_key=idem, ref_type="CRYPTO_DEPOSIT", ref_id=724,
            )
            db.commit()
            self.assertEqual(replay.amount, 125000)
        with self.engine.begin() as con:
            balance = con.execute(text(
                "SELECT balance FROM wallets WHERE user_id=:uid"
            ), {"uid": uid}).scalar_one()
            count = con.execute(text(
                "SELECT COUNT(*) FROM wallet_txs WHERE idempotency_key=:key"
            ), {"key": idem}).scalar_one()
        self.assertEqual(balance, 125000)
        self.assertEqual(count, 1)

    def test_real_invoice_create_with_rotation_uses_committed_address(self):
        """Call real CryptoDepositService.create_invoice, persist actual model."""
        from datetime import datetime, timezone
        from decimal import Decimal
        from types import SimpleNamespace
        from app.core.db import Base
        from app.models.user import User
        from app.models.wallet import Wallet, WalletTx
        from app.models.crypto import CryptoDepositRequest
        from app.services import crypto_destination_state as state
        from app.services import crypto_deposit_service as deposit
        from app.services.crypto_deposit_service import CryptoDepositService

        alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        def tron_addr(seed):
            payload = bytes([0x41]) + bytes([seed])*20
            raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            number = int.from_bytes(raw, "big")
            chars = ""
            while number:
                number, mod = divmod(number, 58)
                chars = alphabet[mod] + chars
            return chars

        old, new = tron_addr(7), tron_addr(8)
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, Wallet.__table__, WalletTx.__table__,
                    CryptoDepositRequest.__table__],
            checkfirst=True,
        )
        with self.engine.begin() as con:
            con.execute(text("DELETE FROM crypto_deposit_requests"))
            con.execute(text("DELETE FROM wallet_txs"))
            con.execute(text("DELETE FROM wallets"))
            con.execute(text("DELETE FROM users"))
            con.execute(text("DELETE FROM app_settings WHERE k = 'crypto_destination_v1:TRON'"))
        with Session(self.engine) as db:
            db.add_all([
                User(id=501, tg_user_id=9900501),
                User(id=502, tg_user_id=9900502),
            ])
            db.commit()

        quote = SimpleNamespace(
            rate_toman=Decimal("100000"),
            provider="disposable-test",
            is_stale=False,
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        spec = {"network": "TRON", "asset": "USDT", "address": old, "decimals": 6}
        preflight = {"healthy": True, "quote": quote}
        started = threading.Event()
        release = threading.Event()
        invoice_attempt = threading.Event()
        # No pricing API or chain API is called: only actual MySQL models and
        # real create_invoice code are used in this test.
        with (
            patch.object(state, "rotation_enabled", return_value=True),
            patch.object(deposit, "rotation_enabled", return_value=True),
            patch.object(deposit.cfg, "CRYPTO_PAYMENTS_ENABLED", True),
            patch.object(deposit.cfg, "CRYPTO_MIN_TOMAN_AMOUNT", 1),
            patch.object(deposit.cfg, "CRYPTO_MAX_TOMAN_AMOUNT", 10000000),
            patch.object(deposit.cfg, "CRYPTO_RATE_BUFFER_PERCENT", Decimal("0")),
            patch.object(CryptoDepositService, "runtime_enabled", return_value=True),
            patch.object(CryptoDepositService, "configured_options", return_value=[spec]),
            patch.object(deposit.CryptoPreflightService, "check", return_value=preflight),
        ):
            with Session(self.engine) as db:
                seed_destination_state(db, network="TRON", address=old)
                db.commit()

            def writer():
                with Session(self.engine) as db:
                    rotate_locked(db, network="TRON", expected_version=1,
                                  expected_address=old, new_address=new)
                    started.set()
                    if not release.wait(8):
                        raise AssertionError("rotation release timeout")
                    db.commit()

            def invoice_after_rotation():
                if not started.wait(8):
                    raise AssertionError("rotation did not start")
                invoice_attempt.set()
                with Session(self.engine) as db:
                    invoice = CryptoDepositService.create_invoice(
                        db, user_id=501, amount_toman=200000, network="TRON"
                    )
                    db.commit()
                    return invoice.id

            with ThreadPoolExecutor(max_workers=2) as pool:
                rotator = pool.submit(writer)
                self.assertTrue(started.wait(8))
                incoming = pool.submit(invoice_after_rotation)
                self.assertTrue(invoice_attempt.wait(8))
                time.sleep(0.35)
                self.assertFalse(incoming.done(), "real invoice issue must wait for rotation")
                release.set()
                rotator.result(timeout=12)
                issued_id = incoming.result(timeout=12)

            with Session(self.engine) as db:
                first = db.get(CryptoDepositRequest, issued_id)
                self.assertEqual(first.destination_address, new)
                self.assertEqual(first.status, "WAITING_PAYMENT")
                self.assertEqual(first.user_id, 501)
                back = rotate_locked(db, network="TRON", expected_version=2,
                                     expected_address=new, new_address=old)
                self.assertEqual(back["version"], 3)
                db.commit()

            with Session(self.engine) as db:
                second = CryptoDepositService.create_invoice(
                    db, user_id=502, amount_toman=300000, network="TRON"
                )
                db.commit()
                self.assertEqual(second.destination_address, old)
                self.assertEqual(db.get(CryptoDepositRequest, issued_id).destination_address, new)

    def test_stale_activation_refused_after_other_commit(self):
        from app.services import crypto_destination_state as state
        with patch.object(state, "rotation_enabled", return_value=True), patch.object(
            state, "validate_crypto_destination", side_effect=lambda n, a: a,
        ):
            with self.engine.begin() as con:
                con.execute(text("DELETE FROM app_settings WHERE k = 'crypto_destination_v1:TRON'"))
            with Session(self.engine) as db:
                seed_destination_state(db, network="TRON", address="OLD")
                db.commit()
            with Session(self.engine) as db:
                rotate_locked(db, network="TRON", expected_version=1,
                              expected_address="OLD", new_address="NEW")
                db.commit()
            with Session(self.engine) as db:
                with self.assertRaises(HTTPException) as error:
                    rotate_locked(db, network="TRON", expected_version=1,
                                  expected_address="OLD", new_address="WRONG")
                self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
