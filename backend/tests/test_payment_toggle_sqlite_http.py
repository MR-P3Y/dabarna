"""Integration tests for payment toggles with a disposable SQLite database.

Only app_settings is created in memory. External providers, rate limits, bank
destinations, and admin identity sources are stubbed. No production DB, Redis,
Telegram, chain API, file upload, or network request is used.
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config as cfg
from app.core.admin_guard import AdminIdentity, AdminScope, get_admin_identity
from app.core.db import get_db
from app.core.mini_security import get_mini_user_id
from app.models.settings import AppSetting
from app.routers import bot_router, mini_router
from app.services.crypto_deposit_service import (
    CRYPTO_RUNTIME_SETTING_KEY,
    CryptoDepositService,
)


OWNER_ID = 9913001
DESTINATION = {
    "id": "test-dst-1",
    "title": "Test bank (4444)",
    "account_name": "Test only",
    "bank_name": "Test bank",
    "iban": "",
    "card_number": "1111222233334444",
    "account_number": "",
    "is_active": True,
}
CRYPTO_NETWORK = {
    "network": "TRON",
    "asset": "USDT",
    "address": "test-address-no-funds",
    "decimals": 6,
}


class PaymentToggleSqliteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        AppSetting.__table__.create(self.engine)
        self.addCleanup(self.engine.dispose)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=OWNER_ID, tg_user_id=4400001,
            roles=["SUPER_ADMIN", "ADMIN"],
        )
        self.bot_admin = AdminIdentity(
            scope=AdminScope.SUPER_ADMIN,
            token="test-only",
            user_id=OWNER_ID,
        )

        self.app = FastAPI()
        self.app.include_router(bot_router.router)
        self.app.include_router(mini_router.router)

        def isolated_db():
            with self.session_factory() as session:
                yield session

        self.app.dependency_overrides[get_db] = isolated_db
        self.app.dependency_overrides[bot_router.get_bot_user] = lambda: SimpleNamespace(
            id=100, tg_user_id=4400001, username="test_only"
        )
        self.app.dependency_overrides[get_mini_user_id] = lambda: OWNER_ID
        self.app.dependency_overrides[get_admin_identity] = lambda: self.bot_admin
        # Keep the actual superadmin gate, overriding only how the user's roles
        # are obtained from Telegram/RBAC so no real accounts are touched.
        self.app.dependency_overrides[mini_router.get_mini_admin_identity] = (
            lambda: self.mini_admin
        )

        patchers = [
            patch.object(bot_router, "RBAC_OWNER_USER_ID", OWNER_ID),
            patch.object(mini_router, "RBAC_OWNER_USER_ID", OWNER_ID),
            patch.object(cfg, "CRYPTO_PAYMENTS_ENABLED", True),
            patch.object(
                CryptoDepositService,
                "configured_options",
                return_value=[dict(CRYPTO_NETWORK)],
            ),
            patch.object(
                bot_router, "_deposit_destination_pool",
                return_value=[dict(DESTINATION)],
            ),
            patch.object(
                mini_router, "_deposit_destination_pool",
                return_value=[dict(DESTINATION)],
            ),
            patch.object(mini_router.AdminAuditService, "record"),
            patch.object(mini_router, "require_user_id_not_restricted"),
            patch.object(mini_router, "enforce_write_rate_limit"),
            patch.object(bot_router, "require_not_restricted"),
            patch.object(
                mini_router.CryptoPreflightService,
                "check",
                return_value={
                    "healthy": True, "quote": None, "reason": None,
                    "checked_at": None, "estimated_network_fee": None,
                },
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def stored(self, key: str):
        with self.session_factory() as db:
            row = db.get(AppSetting, key)
            return None if row is None else row.v_json

    def assert_http(self, method: str, path: str, code: int, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, code, response.text)
        return response.json()

    def test_bank_toggle_mini_to_bot_and_back(self):
        self.assertTrue(
            self.assert_http("GET", "/bot/admin/bank-deposit-settings", 200)[
                "runtime_enabled"
            ]
        )

        status = self.assert_http(
            "PUT", "/mini-api/admin/super/bank-deposit-settings",
            200, json={"enabled": False},
        )
        self.assertFalse(status["runtime_enabled"])
        self.assertIs(self.stored("bank_deposit_enabled"), False)
        self.assertFalse(
            self.assert_http("GET", "/bot/admin/bank-deposit-settings", 200)[
                "runtime_enabled"
            ]
        )
        for path in ("/bot/deposit-destinations", "/bot/deposit-destination"):
            self.assert_http("GET", path, 503)

        visible = self.assert_http("GET", "/mini-api/deposit-destinations", 200)
        self.assertEqual(visible["items"], [])
        self.assert_http(
            "POST", "/bot/deposit-requests", 503, json={"amount": 50000}
        )
        self.assert_http(
            "POST", "/mini-api/deposits", 503,
            json={"amount": 50000, "destination_id": "test-dst-1"},
        )

        restored = self.assert_http(
            "PUT", "/bot/admin/bank-deposit-settings",
            200, json={"enabled": True},
        )
        self.assertTrue(restored["runtime_enabled"])
        self.assertIs(self.stored("bank_deposit_enabled"), True)
        self.assertEqual(
            self.assert_http("GET", "/mini-api/deposit-destinations", 200)["total"],
            1,
        )
        self.assertEqual(
            self.assert_http("GET", "/bot/deposit-destinations", 200)["total"],
            1,
        )

    def test_crypto_toggle_bot_to_mini_and_back(self):
        enabled = self.assert_http(
            "PUT", "/bot/admin/crypto-settings",
            200, json={"enabled": True},
        )
        self.assertTrue(enabled["runtime_enabled"])
        self.assertIs(self.stored(CRYPTO_RUNTIME_SETTING_KEY), True)
        self.assertTrue(
            self.assert_http("GET", "/mini-api/admin/super/crypto-settings", 200)[
                "runtime_enabled"
            ]
        )
        self.assertTrue(
            self.assert_http("GET", "/bot/crypto/options", 200)["enabled"]
        )
        self.assertTrue(
            self.assert_http("GET", "/mini-api/crypto/options", 200)["enabled"]
        )

        disabled = self.assert_http(
            "PUT", "/mini-api/admin/super/crypto-settings",
            200, json={"enabled": False},
        )
        self.assertFalse(disabled["runtime_enabled"])
        self.assertIs(self.stored(CRYPTO_RUNTIME_SETTING_KEY), False)
        for path in ("/bot/crypto/options", "/mini-api/crypto/options"):
            data = self.assert_http("GET", path, 200)
            self.assertFalse(data["enabled"])
            self.assertEqual(data["options"], [])

        for path in ("/bot/crypto/deposits", "/mini-api/crypto/deposits"):
            self.assert_http(
                "POST", path, 503,
                json={"amount_toman": 50000, "network": "TRON"},
            )

    def test_switching_one_method_does_not_switch_the_other(self):
        self.assert_http(
            "PUT", "/bot/admin/crypto-settings",
            200, json={"enabled": True},
        )
        self.assert_http(
            "PUT", "/mini-api/admin/super/bank-deposit-settings",
            200, json={"enabled": False},
        )
        self.assertIs(self.stored("bank_deposit_enabled"), False)
        self.assertIs(self.stored(CRYPTO_RUNTIME_SETTING_KEY), True)
        self.assertFalse(
            self.assert_http("GET", "/bot/admin/bank-deposit-settings", 200)[
                "runtime_enabled"
            ]
        )
        self.assertTrue(
            self.assert_http("GET", "/mini-api/admin/super/crypto-settings", 200)[
                "runtime_enabled"
            ]
        )

    def test_regular_admin_cannot_change_payment_switches(self):
        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=OWNER_ID, tg_user_id=4400001, roles=["ADMIN"],
        )
        self.bot_admin = AdminIdentity(
            scope=AdminScope.ADMIN, token="test-only", user_id=OWNER_ID,
        )
        for path in (
            "/bot/admin/bank-deposit-settings",
            "/bot/admin/crypto-settings",
            "/mini-api/admin/super/bank-deposit-settings",
            "/mini-api/admin/super/crypto-settings",
        ):
            with self.subTest(path=path):
                self.assert_http(
                    "PUT", path, 403, json={"enabled": False}
                )
        self.assertIsNone(self.stored("bank_deposit_enabled"))
        self.assertIsNone(self.stored(CRYPTO_RUNTIME_SETTING_KEY))

    def test_superadmin_who_is_not_owner_cannot_change_switches(self):
        self.mini_admin = mini_router.MiniAdminIdentity(
            user_id=OWNER_ID + 1, tg_user_id=4400002, roles=["SUPER_ADMIN"],
        )
        self.bot_admin = AdminIdentity(
            scope=AdminScope.SUPER_ADMIN,
            token="test-only",
            user_id=OWNER_ID + 1,
        )
        for path in (
            "/bot/admin/bank-deposit-settings",
            "/bot/admin/crypto-settings",
            "/mini-api/admin/super/bank-deposit-settings",
            "/mini-api/admin/super/crypto-settings",
        ):
            with self.subTest(path=path):
                self.assert_http("PUT", path, 403, json={"enabled": False})
        self.assertIsNone(self.stored("bank_deposit_enabled"))
        self.assertIsNone(self.stored(CRYPTO_RUNTIME_SETTING_KEY))

    def test_enabling_bank_without_active_destination_fails(self):
        with (
            patch.object(bot_router, "_deposit_destination_pool", return_value=[]),
            patch.object(mini_router, "_deposit_destination_pool", return_value=[]),
        ):
            for path in (
                "/bot/admin/bank-deposit-settings",
                "/mini-api/admin/super/bank-deposit-settings",
            ):
                with self.subTest(path=path):
                    self.assert_http("PUT", path, 409, json={"enabled": True})
        self.assertIsNone(self.stored("bank_deposit_enabled"))

    def test_enabling_crypto_requires_server_flag_and_configured_wallet(self):
        with patch.object(cfg, "CRYPTO_PAYMENTS_ENABLED", False):
            for path in (
                "/bot/admin/crypto-settings",
                "/mini-api/admin/super/crypto-settings",
            ):
                with self.subTest(path=path):
                    self.assert_http("PUT", path, 409, json={"enabled": True})
        with patch.object(CryptoDepositService, "configured_options", return_value=[]):
            for path in (
                "/bot/admin/crypto-settings",
                "/mini-api/admin/super/crypto-settings",
            ):
                with self.subTest(path=path):
                    self.assert_http("PUT", path, 409, json={"enabled": True})
        self.assertIsNone(self.stored(CRYPTO_RUNTIME_SETTING_KEY))


if __name__ == "__main__":
    unittest.main()
