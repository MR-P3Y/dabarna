"""Atomic-destination prototype unit tests; sqlite exercises serial semantics ONLY.

MySQL concurrency/load tests remain mandatory before any finance release.
"""
from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.settings import AppSetting
from app.services.crypto_destination_state import (
    lock_destination_state, rotate_locked, seed_destination_state, state_key,
    rotation_enabled,
)


def make_tron(seed: int) -> str:
    raw = bytes([0x41]) + bytes([seed]) * 20
    full = raw + hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    alpha = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(full, "big")
    out = ""
    while n:
        n, digit = divmod(n, 58)
        out = alpha[digit] + out
    return out


class AtomicWalletVersionPrototype(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        AppSetting.__table__.create(self.engine)
        self.old, self.new, self.third = make_tron(1), make_tron(2), make_tron(3)
        self.gate = patch("app.services.crypto_destination_state.rotation_enabled", return_value=True)
        self.gate.start()

    def tearDown(self):
        self.gate.stop()
        self.engine.dispose()

    def test_seed_lock_and_versioned_update(self):
        with Session(self.engine) as db:
            state = seed_destination_state(db, network="TRON", address=self.old)
            self.assertEqual(state["version"], 1)
            db.commit()
        with Session(self.engine) as db:
            self.assertEqual(lock_destination_state(db, "TRON")["address"], self.old)
            after = rotate_locked(db, network="TRON", expected_version=1, expected_address=self.old, new_address=self.new)
            self.assertEqual(after["version"], 2)
            db.commit()
        with Session(self.engine) as db:
            self.assertEqual(lock_destination_state(db, "TRON")["address"], self.new)
            self.assertEqual(lock_destination_state(db, "TRON")["version"], 2)

    def test_invalid_version_never_passes_read_lock(self):
        for invalid in (True, 0, -1, "1"):
            with self.subTest(version=invalid), Session(self.engine) as db:
                row = db.get(AppSetting, state_key("TRON"))
                if row is None:
                    row = AppSetting(k=state_key("TRON"))
                row.v_json = {"network": "TRON", "address": self.old, "version": invalid}
                db.add(row); db.commit()
                with self.assertRaises(HTTPException) as caught:
                    lock_destination_state(db, "TRON")
                self.assertEqual(caught.exception.status_code, 409)

    def test_stale_update_rejected_and_does_not_overwrite(self):
        with Session(self.engine) as db:
            seed_destination_state(db, network="TRON", address=self.old)
            db.commit()
        with Session(self.engine) as db:
            rotate_locked(db, network="TRON", expected_version=1, expected_address=self.old, new_address=self.new)
            db.commit()
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as context:
                rotate_locked(db, network="TRON", expected_version=1, expected_address=self.old, new_address=self.third)
            self.assertEqual(context.exception.status_code, 409)
            self.assertEqual(lock_destination_state(db, "TRON")["address"], self.new)

    def test_revert_is_a_new_version_not_history_rewrite(self):
        with Session(self.engine) as db:
            seed_destination_state(db, network="TRON", address=self.old)
            db.commit()
        with Session(self.engine) as db:
            rotate_locked(db, network="TRON", expected_version=1, expected_address=self.old, new_address=self.new)
            db.commit()
        with Session(self.engine) as db:
            back = rotate_locked(db, network="TRON", expected_version=2, expected_address=self.new, new_address=self.old)
            self.assertEqual(back["version"], 3)
            db.commit()

    def test_missing_version_row_fails_closed(self):
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException) as context:
                lock_destination_state(db, "TRON")
            self.assertEqual(context.exception.status_code, 503)

    def test_gate_ignores_any_database_other_than_disposable_mysql(self):
        self.gate.stop()
        try:
            with patch.dict("os.environ", {
                "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "I_ACK_DISPOSABLE_DB_ONLY",
                "DATABASE_URL": "mysql+pymysql://root:pass@production-host/davarna",
            }):
                self.assertFalse(rotation_enabled())
            with patch.dict("os.environ", {
                "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL": "I_ACK_DISPOSABLE_DB_ONLY",
                "DATABASE_URL": "mysql+pymysql://tester:test@davarna-wallet-mysql/davarna_wallet_rotation_test",
            }):
                self.assertTrue(rotation_enabled())
        finally:
            self.gate.start()


if __name__ == "__main__":
    unittest.main()
