"""MySQL-only concurrency regression. Never run against Production.

Requires dedicated host davarna-wallet-mysql and schema davarna_wallet_rotation_test.
Run only after disposable database provisioning with no shared Docker volumes.
"""
from __future__ import annotations

import os
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
