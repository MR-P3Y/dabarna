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
        self.assertEqual(events[-1], ("invoice_read", 2))
        self.assertEqual(events[1], ("rotation_committed", 2))

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
