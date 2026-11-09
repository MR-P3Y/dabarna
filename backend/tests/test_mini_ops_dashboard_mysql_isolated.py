"""Real MySQL HTTP/RBAC contract on a DISPOSABLE database only.

Requires isolated Docker network, host davarna-v11-mysql, schema davarna_v11_rbac_test.
No production volumes, credentials or services.
"""
import os
import unittest
from unittest.mock import patch

if os.environ.get("DAVARNA_V11_ISOLATED_MYSQL") != "I_ACK_DISPOSABLE_DB":
    raise unittest.SkipTest("isolated MySQL opt-in required")
os.environ["DATABASE_URL"] = "mysql+pymysql://v11test:v11test_local_only@davarna-v11-mysql:3306/davarna_v11_rbac_test"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
os.environ["RECEIPTS_DIR"] = "/tmp/receipts"
os.environ["GAME_AUTOPILOT_RUNTIME_ENABLED"] = "false"
os.environ["GAME_AUTO_DRAW_ENABLED"] = "false"
os.environ["CRYPTO_AUTO_CONFIRM_ENABLED"] = "false"

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.routers import mini_router as mini
from app.core.db import get_db

url = make_url(os.environ["DATABASE_URL"])
assert url.get_backend_name() == "mysql"
assert url.host == "davarna-v11-mysql"
assert url.database == "davarna_v11_rbac_test"

SCHEMA = (
    "CREATE TABLE games (id BIGINT PRIMARY KEY, status VARCHAR(16), admin_user_id BIGINT, card_price BIGINT, sold_amount BIGINT, prize_pool BIGINT)",
    "CREATE TABLE game_called_numbers (id BIGINT PRIMARY KEY, game_id BIGINT, number INT)",
    "CREATE TABLE game_cards (id BIGINT PRIMARY KEY, game_id BIGINT, user_id BIGINT)",
    "CREATE TABLE game_events (id BIGINT PRIMARY KEY, game_id BIGINT, kind VARCHAR(32))",
    "CREATE TABLE deposit_requests (id BIGINT PRIMARY KEY, status VARCHAR(32))",
    "CREATE TABLE withdraw_requests (id BIGINT PRIMARY KEY, status VARCHAR(32))",
    "CREATE TABLE crypto_deposit_requests (id BIGINT PRIMARY KEY, status VARCHAR(32))",
    "CREATE TABLE admin_audit_logs (id BIGINT PRIMARY KEY, action VARCHAR(80), created_at DATETIME)",
)
SEED = (
    "INSERT INTO games VALUES (1001,'RUNNING',101,5000,15000,13500),(1002,'RUNNING',202,5000,25000,22500)",
    "INSERT INTO game_called_numbers VALUES (1,1001,17),(2,1002,28)",
    "INSERT INTO game_cards VALUES (1,1001,301),(2,1002,302)",
    "INSERT INTO game_events VALUES (1,1001,'ERROR'),(2,1002,'ERROR'),(3,1002,'ERROR')",
    "INSERT INTO deposit_requests VALUES (1,'PENDING_REVIEW'),(2,'PENDING_REVIEW')",
    "INSERT INTO withdraw_requests VALUES (1,'PENDING'),(2,'APPROVED')",
    "INSERT INTO crypto_deposit_requests VALUES (1,'NEEDS_REVIEW')",
    "INSERT INTO admin_audit_logs VALUES (1,'risk.detected',UTC_TIMESTAMP())",
)

class RealMySQLDashboardRBAC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        with cls.engine.begin() as conn:
            assert conn.execute(text("SELECT DATABASE()")).scalar_one() == "davarna_v11_rbac_test"
            for stmt in SCHEMA:
                conn.execute(text(stmt))
            for stmt in SEED:
                conn.execute(text(stmt))
        cls.app = FastAPI()
        cls.app.include_router(mini.router)
        cls.app.dependency_overrides[get_db] = cls._session_dependency
        cls.client = TestClient(cls.app)
        cls.health_patch = patch.object(mini, "_mini_system_health", return_value={"services": []})
        cls.health_patch.start()

    @classmethod
    def _session_dependency(cls):
        with Session(cls.engine) as db:
            yield db

    @classmethod
    def tearDownClass(cls):
        cls.health_patch.stop()
        cls.client.close()
        cls.engine.dispose()

    def _request_as(self, role, user_id=101):
        def identity():
            if not role:
                raise HTTPException(status_code=403)
            return mini.MiniAdminIdentity(user_id=user_id, tg_user_id=user_id, roles=[role])
        self.app.dependency_overrides[mini.get_mini_admin_identity] = identity
        return self.client.get("/mini-api/admin/ops-dashboard")

    def test_denied_user(self):
        self.assertEqual(self._request_as(None).status_code, 403)

    def test_game_operator_is_scoped(self):
        r = self._request_as("GAME_OPERATOR")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertFalse(d["finance_visible"])
        self.assertEqual([g["id"] for g in d["active_games"]], [1001])
        self.assertEqual(d["counts"]["game_errors"], 1)
        for key in ("pending_deposits","pending_withdraws","approved_withdraws","crypto_needs_review","risk_events_24h"):
            self.assertEqual(d["counts"][key], 0)

    def test_regular_admin_is_scoped(self):
        r = self._request_as("ADMIN", 202)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertFalse(d["finance_visible"])
        self.assertEqual([g["id"] for g in d["active_games"]], [1002])
        self.assertEqual(d["counts"]["game_errors"], 2)

    def test_finance_admin_gets_counts_but_only_own_games(self):
        r = self._request_as("FINANCE_ADMIN")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["finance_visible"])
        self.assertEqual([g["id"] for g in d["active_games"]], [1001])
        self.assertEqual(d["counts"]["pending_deposits"], 2)
        self.assertEqual(d["counts"]["pending_withdraws"], 1)
        self.assertEqual(d["counts"]["approved_withdraws"], 1)
        self.assertEqual(d["counts"]["crypto_needs_review"], 1)
        self.assertEqual(d["counts"]["risk_events_24h"], 1)

    def test_superadmin_sees_all(self):
        r = self._request_as("SUPER_ADMIN")
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["finance_visible"])
        self.assertEqual({g["id"] for g in d["active_games"]}, {1001,1002})
        self.assertEqual(d["counts"]["game_errors"], 3)

    def test_post_disallowed(self):
        self.app.dependency_overrides[mini.get_mini_admin_identity] = lambda: mini.MiniAdminIdentity(user_id=101,tg_user_id=101,roles=["SUPER_ADMIN"])
        self.assertEqual(self.client.post("/mini-api/admin/ops-dashboard").status_code, 405)

if __name__ == "__main__":
    unittest.main()
