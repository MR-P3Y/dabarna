"""Real MySQL HTTP contract for owner-managed TON/TRON wallets; NO real payments.

Only permitted against ephemeral davarna-wallet-mysql/davarna_wallet_rotation_test.
Inserts test-only public addresses; mocks blockchain network and audit messaging.
"""
from __future__ import annotations

import hashlib
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

if os.getenv("DAVARNA_WALLET_MYSQL_CONCURRENCY") != "I_ACK_DISPOSABLE_DB":
    raise unittest.SkipTest("explicit disposable-MySQL opt-in required")
url = make_url(os.getenv("DATABASE_URL", ""))
if not (url.get_backend_name() == "mysql" and url.host == "davarna-wallet-mysql"
        and url.database == "davarna_wallet_rotation_test"):
    raise unittest.SkipTest("refusing any non-disposable database")

from app.core.db import get_db, Base
from app.core.admin_guard import AdminIdentity, AdminScope, get_admin_identity
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.crypto import CryptoDepositRequest
from app.routers import mini_router as mini, bot_router as bot
from app.services.crypto_deposit_service import CryptoDepositService


def tron(seed: int) -> str:
    data = bytes([0x41]) + bytes([seed]) * 20
    raw = data + hashlib.sha256(hashlib.sha256(data).digest()).digest()[:4]
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = alphabet[rem] + out
    return out


class RealMySQLOwnerWalletFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(str(url), pool_pre_ping=True, pool_size=3)
        with cls.engine.connect() as con:
            assert con.exec_driver_sql("SELECT DATABASE()").scalar_one() == "davarna_wallet_rotation_test"
        Base.metadata.create_all(
            cls.engine,
            tables=[
                User.__table__, Wallet.__table__, WalletTx.__table__,
                CryptoDepositRequest.__table__, AppSetting.__table__,
            ],
            checkfirst=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        # These tables are used only inside disposable MySQL. Do not truncate or
        # touch anything outside the test-only database.
        with self.engine.begin() as con:
            con.execute(delete(CryptoDepositRequest))
            con.execute(delete(WalletTx))
            con.execute(delete(Wallet))
            con.execute(delete(AppSetting))
            con.execute(delete(User))
        with Session(self.engine) as db:
            db.add(User(id=1, tg_user_id=9988123401))
            db.commit()

        self.app = FastAPI()
        self.app.include_router(mini.router)
        self.app.include_router(bot.router)

        def get_test_db():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = get_test_db
        self.app.dependency_overrides[get_admin_identity] = lambda: AdminIdentity(
            scope=AdminScope.SUPER_ADMIN, token="DISPOSABLE_ONLY",
            user_id=1, roles={"SUPER_ADMIN"}
        )
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(
            user_id=1, tg_user_id=9988123401, roles=["SUPER_ADMIN"]
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
            patch.object(mini.cfg, "CRYPTO_TRON_USDT_ENABLED", True),
            patch.object(mini.cfg, "CRYPTO_TON_ENABLED", True),
            patch.object(mini.cfg, "CRYPTO_PAYMENTS_ENABLED", False),
        ]
        self.patchers = specs
        for p in specs:
            p.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patchers):
            p.stop()

    def test_add_both_networks_cross_surface_then_rotate_with_mysql_locks(self):
        first, second = tron(17), tron(18)
        ton_initial = "0:" + "a" * 64
        for method, uri, payload in (
            ("POST", "/mini-api/admin/super/crypto-address-initialize-production",
             {"network": "TRON", "address": first,
              "confirmation": "ADD_NEW_CRYPTO_DESTINATION_WITH_PAYMENTS_OFF"}),
            ("POST", "/bot/admin/crypto-wallets/add",
             {"network": "TON", "address": ton_initial,
              "confirmation": "ADD_NEW_CRYPTO_DESTINATION_WITH_PAYMENTS_OFF"}),
        ):
            response = self.client.request(method, uri, json=payload)
            self.assertEqual(response.status_code, 200, response.text)

        with Session(self.engine) as db:
            status = CryptoDepositService.runtime_status(db)
            selected = {str(it["network"]): str(it["address"]) for it in status["options"]}
            self.assertEqual(selected, {"TRON": first, "TON": ton_initial})
            self.assertFalse(CryptoDepositService.runtime_enabled(db))
            self.assertEqual(int(db.execute(select(func.count()).select_from(WalletTx)).scalar_one()), 0)
            self.assertEqual(int(db.execute(select(func.count()).select_from(CryptoDepositRequest)).scalar_one()), 0)

        bot_view = self.client.get("/bot/admin/crypto-wallets")
        self.assertEqual(bot_view.status_code, 200, bot_view.text)
        self.assertEqual(
            {str(item["network"]): str(item["address"])
             for item in bot_view.json()["networks"]},
            selected,
        )

        proposed = self.client.post("/mini-api/admin/super/crypto-address-proposals", json={
            "network": "TRON", "address": second,
            "expected_current_address": first, "confirmation": "REQUEST_ADDRESS_CHANGE",
        })
        self.assertEqual(proposed.status_code, 201, proposed.text)
        with Session(self.engine) as db:
            self.assertEqual(db.get(AppSetting, "crypto_destination_v1:TRON").v_json["address"], first)

        # In a real DB, readiness calculates real invoice counts (zero);
        # only the external provider is mocked to guarantee NO network transfer.
        activated = self.client.post("/bot/admin/crypto-wallets/activate", json={
            "network": "TRON", "expected_version": 1,
            "expected_current_address": first, "proposed_address": second,
            "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
        })
        self.assertEqual(activated.status_code, 200, activated.text)
        with Session(self.engine) as db:
            state = db.get(AppSetting, "crypto_destination_v1:TRON").v_json
            self.assertEqual(state["address"], second)
            self.assertEqual(state["version"], 2)
            self.assertFalse(CryptoDepositService.runtime_enabled(db))
            self.assertEqual(db.execute(select(func.count()).select_from(WalletTx)).scalar_one(), 0)

        stale = self.client.post("/bot/admin/crypto-wallets/activate", json={
            "network": "TRON", "expected_version": 1,
            "expected_current_address": first, "proposed_address": second,
            "confirmation": "ACTIVATE_PRODUCTION_CRYPTO_DESTINATION",
        })
        self.assertEqual(stale.status_code, 409)

    def test_refuse_when_runtime_is_on_and_do_not_change_stored_address(self):
        first = tron(19)
        added = self.client.post("/bot/admin/crypto-wallets/add", json={
            "network": "TRON", "address": first,
            "confirmation": "ADD_NEW_CRYPTO_DESTINATION_WITH_PAYMENTS_OFF",
        })
        self.assertEqual(added.status_code, 200, added.text)
        with Session(self.engine) as db:
            db.get(AppSetting, "crypto_payments_runtime_enabled").v_json = True
            db.commit()
        response = self.client.post("/mini-api/admin/super/crypto-address-initialize-production", json={
            "network": "TON", "address": "0:" + "b" * 64,
            "confirmation": "ADD_NEW_CRYPTO_DESTINATION_WITH_PAYMENTS_OFF",
        })
        self.assertEqual(response.status_code, 409, response.text)
        with Session(self.engine) as db:
            self.assertIsNone(db.get(AppSetting, "crypto_destination_v1:TON"))
            self.assertEqual(db.get(AppSetting, "crypto_destination_v1:TRON").v_json["address"], first)


if __name__ == "__main__":
    unittest.main()
