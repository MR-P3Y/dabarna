"""HTTP-level regression checks for disabled payment methods.

These tests use dependency overrides and mocks only. They do not contact Redis,
MySQL, Telegram, or any production service.
"""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.admin_guard import AdminIdentity, AdminScope, get_admin_identity, require_admin_any
from app.core.db import get_db
from app.core.mini_security import get_mini_user_id
from app.core.user_guard import get_current_user_id
from app.routers import bot_router, finance_router, mini_router, settings_router
from app.services.crypto_deposit_service import CRYPTO_RUNTIME_SETTING_KEY


class PaymentVisibilityRuntimeHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = Mock()
        self.db.get.return_value = SimpleNamespace(v_json=False)
        app = FastAPI()
        app.include_router(bot_router.router)
        app.include_router(finance_router.router)
        app.include_router(mini_router.router)
        app.include_router(settings_router.router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[bot_router.get_bot_user] = lambda: SimpleNamespace(
            id=123, tg_user_id=555123
        )
        app.dependency_overrides[get_current_user_id] = lambda: 123
        app.dependency_overrides[get_mini_user_id] = lambda: 123
        admin_identity = lambda: AdminIdentity(
            scope=AdminScope.ADMIN, token="test-only", user_id=123
        )
        app.dependency_overrides[require_admin_any] = admin_identity
        app.dependency_overrides[get_admin_identity] = admin_identity
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_bot_both_destination_routes_hide_disabled_bank_cards(self) -> None:
        with (
            patch("app.routers.bot_router.require_not_restricted"),
            patch(
                "app.routers.bot_router._deposit_destination_pool",
                side_effect=AssertionError("disabled method must not reveal cards"),
            ),
        ):
            for path in ("/bot/deposit-destinations", "/bot/deposit-destination"):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 503, response.text)
        self.db.commit.assert_not_called()

    def test_mini_destinations_are_empty_when_bank_disabled(self) -> None:
        with (
            patch("app.routers.mini_router.require_user_id_not_restricted"),
            patch(
                "app.routers.mini_router._deposit_destination_pool",
                side_effect=AssertionError("disabled method must not reveal cards"),
            ),
        ):
            response = self.client.get("/mini-api/deposit-destinations")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    def test_mini_one_shot_receipt_fails_before_parsing_body(self) -> None:
        with patch("app.routers.mini_router.require_user_id_not_restricted"):
            response = self.client.post("/mini-api/deposits/with-receipt", data={})
        self.assertEqual(response.status_code, 503, response.text)
        self.db.commit.assert_not_called()

    def test_legacy_finance_deposit_rejects_disabled_flag(self) -> None:
        with patch(
            "app.routers.finance_router.FinanceService.create_deposit_request"
        ) as create:
            response = self.client.post("/finance/deposits", json={"amount": 50000})
            self.assertEqual(response.status_code, 503, response.text)
            create.assert_not_called()
        self.db.commit.assert_not_called()

    def test_generic_admin_settings_cannot_modify_payment_flags(self) -> None:
        for key in ("bank_deposit_enabled", CRYPTO_RUNTIME_SETTING_KEY):
            with self.subTest(key=key):
                response = self.client.put(
                    f"/admin/settings/{key}", json={"v_json": True}
                )
                self.assertEqual(response.status_code, 403, response.text)
        self.db.commit.assert_not_called()

    def test_non_superadmin_cannot_toggle_bot_payment_settings(self) -> None:
        for path in ("/bot/admin/bank-deposit-settings", "/bot/admin/crypto-settings"):
            with self.subTest(path=path):
                response = self.client.put(path, json={"enabled": False})
                self.assertEqual(response.status_code, 403, response.text)
        self.db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
