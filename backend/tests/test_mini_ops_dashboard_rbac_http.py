"""HTTP-level permission tests for the read-only operations dashboard.

Uses mocked database and health probes. Never connects to Production.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.routers import mini_router as mini
from app.core.db import get_db


class _QueryResult:
    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one(self):
        return 7


class _FakeDb:
    def __init__(self):
        self.queries = []

    def execute(self, query):
        self.queries.append(str(query))
        return _QueryResult()


class OpsDashboardHttpRBAC(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(mini.router)
        self.db = _FakeDb()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.health = patch.object(mini, "_mini_system_health", return_value={"services": []})
        self.health.start()
        self.addCleanup(self.health.stop)
        self.addCleanup(self.app.dependency_overrides.clear)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as_role(self, role):
        def identity():
            if role is None:
                raise HTTPException(status_code=403, detail="Not an admin")
            return mini.MiniAdminIdentity(user_id=101, tg_user_id=101, roles=[role])
        self.app.dependency_overrides[mini.get_mini_admin_identity] = identity

    def test_non_admin_denied(self):
        self._as_role(None)
        response = self.client.get("/mini-api/admin/ops-dashboard")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.queries, [])

    def test_game_and_regular_admin_get_no_global_finance(self):
        for role in ("GAME_OPERATOR", "ADMIN"):
            with self.subTest(role=role):
                self.db.queries.clear()
                self._as_role(role)
                response = self.client.get("/mini-api/admin/ops-dashboard")
                self.assertEqual(response.status_code, 200, response.text)
                counts = response.json()["counts"]
                for key in ("pending_deposits", "pending_withdraws", "approved_withdraws",
                            "crypto_needs_review", "risk_events_24h"):
                    self.assertEqual(counts[key], 0, key)
                self.assertEqual(counts["game_errors"], 7)
                sql = " ".join(self.db.queries).lower()
                for table in ("deposit_requests", "withdraw_requests",
                              "crypto_deposit_requests", "admin_audit_logs"):
                    self.assertNotIn(table, sql)

    def test_finance_and_superadmin_receive_finance_counts(self):
        for role in ("FINANCE_ADMIN", "SUPER_ADMIN"):
            with self.subTest(role=role):
                self.db.queries.clear()
                self._as_role(role)
                response = self.client.get("/mini-api/admin/ops-dashboard")
                self.assertEqual(response.status_code, 200, response.text)
                counts = response.json()["counts"]
                for key in ("pending_deposits", "pending_withdraws", "approved_withdraws",
                            "crypto_needs_review", "risk_events_24h", "game_errors"):
                    self.assertEqual(counts[key], 7, key)

    def test_only_read_method_exposed(self):
        self._as_role("SUPER_ADMIN")
        response = self.client.post("/mini-api/admin/ops-dashboard", json={})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.db.queries, [])


if __name__ == "__main__":
    unittest.main()
