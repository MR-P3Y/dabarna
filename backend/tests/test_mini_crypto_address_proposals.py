"""Security contract for staged wallet address proposals (SQLite, no production)."""
import hashlib
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, Base
from app.models.settings import AppSetting
from app.routers import mini_router as mini
from app.services.crypto_address_change import validate_crypto_destination


def tron_address(seed: int) -> str:
    raw = bytes([0x41]) + bytes([seed]) * 20
    data = raw + hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(data, "big")
    out = ""
    while number:
        number, n = divmod(number, 58)
        out = alphabet[n] + out
    return out


class CryptoAddressProposalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        AppSetting.__table__.create(self.engine)
        self.old = tron_address(1)
        self.new = tron_address(2)
        self.app = FastAPI()
        self.app.include_router(mini.router)

        def session_dependency():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = session_dependency
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=101, tg_user_id=9101, roles=["SUPER_ADMIN"]
        )
        self.owner = patch.object(mini, "RBAC_OWNER_USER_ID", None)
        self.options = patch.object(
            mini.CryptoDepositService, "configured_options",
            return_value=[{"network": "TRON", "address": self.old, "asset": "USDT"}],
        )
        self.audit = patch.object(mini.AdminAuditService, "record")
        self.limiter = patch.object(mini, "enforce_write_rate_limit")
        self.owner.start()
        self.options.start()
        self.audit.start()
        self.limiter.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.audit.stop()
        self.limiter.stop()
        self.options.stop()
        self.owner.stop()
        self.engine.dispose()

    def request(self, address=None, expected=None):
        return self.client.post(
            "/mini-api/admin/super/crypto-address-proposals",
            json={
                "network": "TRON",
                "address": address or self.new,
                "expected_current_address": expected or self.old,
                "confirmation": "REQUEST_ADDRESS_CHANGE",
            },
        )

    def test_valid_checksum(self):
        self.assertEqual(validate_crypto_destination("TRON", self.new), self.new)
        with self.assertRaises(ValueError):
            validate_crypto_destination("TRON", self.new[:-1] + "0")
        self.assertEqual(validate_crypto_destination("TON", "0:" + "a" * 64), "0:" + "a" * 64)

    def test_proposal_is_pending_and_never_changes_active_settings(self):
        response = self.request()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["activation_supported"])
        self.assertEqual(response.json()["status"], "PENDING_REVIEW")
        with Session(self.engine) as db:
            row = db.get(AppSetting, "crypto_address_change_proposal:TRON")
            self.assertEqual(row.v_json["address"], self.new)
        self.assertEqual(mini.CryptoDepositService.configured_options()[0]["address"], self.old)
        pending = self.client.get("/mini-api/admin/super/crypto-address-proposals")
        self.assertEqual(pending.status_code, 200)
        self.assertEqual(len(pending.json()["items"]), 1)

    def test_duplicate_proposal_refused(self):
        self.assertEqual(self.request().status_code, 201)
        self.assertEqual(self.request().status_code, 409)

    def test_stale_current_address_refused(self):
        self.assertEqual(self.request(expected=self.new).status_code, 409)

    def test_invalid_checksum_refused(self):
        self.assertEqual(self.request(address="T" + "0" * 33).status_code, 422)

    def test_non_superadmin_denied(self):
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=202, tg_user_id=9202, roles=["ADMIN"]
        )
        self.assertEqual(self.request().status_code, 403)
        self.assertEqual(
            self.client.get("/mini-api/admin/super/crypto-address-proposals").status_code, 403
        )


if __name__ == "__main__":
    unittest.main()
