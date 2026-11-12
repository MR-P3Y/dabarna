"""Owner-managed TON/TRON destinations: isolated SQLite HTTP security regression tests.

No production network, API key, invoice, payment, bot polling or database is used.
"""
from __future__ import annotations

import hashlib
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.admin_guard import AdminIdentity, AdminScope, get_admin_identity
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.crypto import CryptoDepositRequest
from app.routers import mini_router as mini
from app.routers import bot_router as bot
from app.services.crypto_deposit_service import CryptoDepositService


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


class OwnerCryptoWalletManagerTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # The invoices table needs users/wallets/wallet_txs for its FKs.
        for model in (User, Wallet, WalletTx, CryptoDepositRequest, AppSetting):
            model.__table__.create(self.engine)
        with Session(self.engine) as db:
            db.add(User(id=1, tg_user_id=123456789))
            db.commit()

        self.app = FastAPI()
        self.app.include_router(mini.router)
        self.app.include_router(bot.router)

        def get_session():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = get_session
        self.app.dependency_overrides[mini.get_mini_admin_identity] = (
            lambda: mini.MiniAdminIdentity(
                user_id=1, tg_user_id=123456789, roles=["SUPER_ADMIN"],
            )
        )
        self.app.dependency_overrides[get_admin_identity] = (
            lambda: AdminIdentity(
                scope=AdminScope.SUPER_ADMIN, token="TEST",
                user_id=1, roles={"SUPER_ADMIN"},
            )
        )
        specs = [
            patch.object(mini, "RBAC_OWNER_USER_ID", 1),
            patch.object(bot, "RBAC_OWNER_USER_ID", 1),
            patch.object(mini, "production_rotation_enabled", return_value=True),
            patch.object(mini, "rotation_enabled", return_value=True),
            patch("app.services.crypto_destination_state.rotation_enabled", return_value=True),
            patch("app.services.crypto_deposit_service.rotation_enabled", return_value=True),
            patch("app.services.crypto_deposit_service.production_rotation_enabled", return_value=True),
            patch.object(CryptoDepositService, "configured_options", return_value=[]),
            patch.object(mini, "enforce_write_rate_limit"),
            patch.object(mini.CryptoChainService, "list_incoming", return_value=[]),
            patch.object(mini.AdminAuditService, "record"),
        ]
        self.patchers = specs
        for p in self.patchers:
            p.start()
        self.client = TestClient(self.app)
        self.first = tron_address(1)
        self.second = tron_address(2)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patchers):
            p.stop()
        self.engine.dispose()

    def add_initial(self):
        return self.client.post(
            "/mini-api/admin/super/crypto-address-initialize-production",
            json={
                "network": "TRON", "address": self.first,
                "confirmation": "ADD_NEW_CRYPTO_DESTINATION_WITH_PAYMENTS_OFF",
            },
        )

    def test_first_add_without_env_and_no_payments(self):
        result = self.add_initial()
        self.assertEqual(result.status_code, 200, result.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(AppSetting, "crypto_payments_runtime_enabled").v_json, False)
            saved = db.get(AppSetting, "crypto_destination_v1:TRON").v_json
            self.assertEqual(saved["address"], self.first)
            self.assertEqual(saved["version"], 1)
            self.assertEqual(CryptoDepositService.runtime_status(db)["options"][0]["address"], self.first)
        self.assertEqual(self.add_initial().status_code, 409, "repeated add must never overwrite")

    def test_bot_proposal_activation_uses_same_database_address(self):
        self.assertEqual(self.add_initial().status_code, 200)
        listing = self.client.get("/bot/admin/crypto-wallets")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["networks"][0]["address"], self.first)

        proposal = self.client.post("/bot/admin/crypto-wallets/propose", json={
            "network": "TRON", "address": self.second,
            "expected_current_address": self.first,
            "confirmation": "REQUEST_ADDRESS_CHANGE",
        })
        self.assertEqual(proposal.status_code, 201, proposal.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(AppSetting, "crypto_destination_v1:TRON").v_json["address"], self.first)

        with patch.object(mini, "assess_rotation", return_value={
            "open_invoices": 0, "recent_closed_invoices": 0,
            "needs_manual_review": 0, "historical_invoices": 0,
        }):
            activated = self.client.post("/bot/admin/crypto-wallets/activate", json={
                "network": "TRON", "expected_version": 1,
                "expected_current_address": self.first,
                "proposed_address": self.second,
                "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
            })
        self.assertEqual(activated.status_code, 200, activated.text)
        with Session(self.engine) as db:
            state = db.get(AppSetting, "crypto_destination_v1:TRON").v_json
            self.assertEqual(state["address"], self.second)
            self.assertEqual(state["version"], 2)
            self.assertFalse(CryptoDepositService.runtime_enabled(db))
        self.assertEqual(self.client.get("/bot/admin/crypto-wallets").json()["networks"][0]["address"], self.second)

    def test_activation_rejects_open_invoice_or_stale_version(self):
        self.assertEqual(self.add_initial().status_code, 200)
        self.assertEqual(self.client.post("/bot/admin/crypto-wallets/propose", json={
            "network": "TRON", "address": self.second,
            "expected_current_address": self.first,
            "confirmation": "REQUEST_ADDRESS_CHANGE",
        }).status_code, 201)
        body = {
            "network": "TRON", "expected_version": 1,
            "expected_current_address": self.first, "proposed_address": self.second,
            "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
        }
        with patch.object(mini, "assess_rotation", return_value={
            "open_invoices": 1, "recent_closed_invoices": 0,
            "needs_manual_review": 0, "historical_invoices": 0,
        }):
            self.assertEqual(self.client.post("/bot/admin/crypto-wallets/activate", json=body).status_code, 409)
        with patch.object(mini, "assess_rotation", return_value={
            "open_invoices": 0, "recent_closed_invoices": 0,
            "needs_manual_review": 0, "historical_invoices": 0,
        }):
            self.assertEqual(self.client.post(
                "/bot/admin/crypto-wallets/activate",
                json={**body, "expected_version": 9},
            ).status_code, 409)
        with Session(self.engine) as db:
            self.assertEqual(db.get(AppSetting, "crypto_destination_v1:TRON").v_json["address"], self.first)

    def test_non_owner_denied_in_bot_and_mini(self):
        self.app.dependency_overrides[get_admin_identity] = (
            lambda: AdminIdentity(scope=AdminScope.ADMIN, token="TEST",
                                  user_id=1, roles={"ADMIN"})
        )
        self.assertEqual(self.client.get("/bot/admin/crypto-wallets").status_code, 403)
        self.app.dependency_overrides[mini.get_mini_admin_identity] = (
            lambda: mini.MiniAdminIdentity(user_id=2, tg_user_id=1234, roles=["ADMIN"])
        )
        self.assertEqual(self.add_initial().status_code, 403)

    def test_gate_disabled_blocks_first_add(self):
        with patch.object(mini, "production_rotation_enabled", return_value=False):
            self.assertEqual(self.add_initial().status_code, 409)


if __name__ == "__main__":
    unittest.main()
