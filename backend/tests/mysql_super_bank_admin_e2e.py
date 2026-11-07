"""Opt-in MySQL bank destination admin E2E, ROLLBACK on test database only.

APPROVED_TEST_DB exactly davarna_tambola_v2_test_20261104; MySQL host pinned.
No production bank destinations, wallet balance or permissions are modified.
"""
from __future__ import annotations

import os
import secrets
import unittest
from pathlib import Path
from unittest.mock import patch

DATABASE = "davarna_tambola_v2_test_20261104"
if os.environ.get("DAVARNA_SUPER_BANK_TEST_DB") != DATABASE:
    raise unittest.SkipTest("opt-in isolated MySQL test DB required")

from dotenv import dotenv_values
from fastapi import HTTPException, Request
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

envfile = Path("/run/secrets/davarna_env")
if not envfile.is_file():
    raise RuntimeError("BLOCKER: private test-only database credentials mount missing")
url = dotenv_values(envfile).get("DATABASE_URL")
if not url:
    raise RuntimeError("BLOCKER: DATABASE_URL missing")
url = make_url(url)
if url.get_backend_name() != "mysql":
    raise RuntimeError("BLOCKER: MySQL test expected")
url = url.set(host="davarna-mysql", port=3306, database=DATABASE)
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["RECEIPTS_DIR"] = "/tmp/receipts"
os.environ["GAME_AUTO_DRAW_ENABLED"] = "false"
os.environ["GAME_AUTOPILOT_RUNTIME_ENABLED"] = "false"

from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import WalletTx
from app.models.admin_audit import AdminAuditLog
from app.routers import mini_router as mini

BASE_CARD = {
    "id": "stage_bank_base",
    "title": "بانک اولیه تست",
    "bank_name": "بانک آزمایشی",
    "card_number": "6037991234567890",
    "account_name": "صاحب حساب تست",
    "account_number": "",
    "iban": "",
    "is_active": True,
}


class BankAdminMySQLEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(url, pool_pre_ping=True)
        with cls.engine.connect() as conn:
            actual = conn.execute(text("SELECT DATABASE()")).scalar_one()
            if actual != DATABASE:
                raise RuntimeError("SAFETY STOP: wrong database " + str(actual))
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if rev != "20261104_0011":
                raise RuntimeError("SAFETY STOP: migration changed")
        print("ISOLATED DB ONLY:", DATABASE)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.conn = self.engine.connect()
        self.outer_tx = self.conn.begin()
        self.db = Session(
            bind=self.conn, expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        self.addCleanup(self.cleanup)
        self.user = User(
            tg_user_id=8600000000000 + secrets.randbelow(10**10),
            first_name="super-admin-bank-test",
        )
        self.db.add(self.user)
        self.db.flush()
        self.ident = mini.MiniAdminIdentity(
            user_id=int(self.user.id), tg_user_id=int(self.user.tg_user_id),
            roles=["SUPER_ADMIN"],
        )
        self.req = Request({
            "type": "http", "method": "POST",
            "path": "/mini-api/admin/super/deposit-destinations",
            "headers": [], "query_string": b"",
            "client": ("127.0.0.1", 8000), "server": ("localhost", 8000),
            "scheme": "http",
        })
        existing = self.db.get(AppSetting, mini.DEPOSIT_DESTINATIONS_SETTING_KEY)
        if existing:
            existing.v_json = [dict(BASE_CARD)]
        else:
            self.db.add(AppSetting(k=mini.DEPOSIT_DESTINATIONS_SETTING_KEY, v_json=[dict(BASE_CARD)]))
        bank_flag = self.db.get(AppSetting, mini.BANK_DEPOSIT_RUNTIME_SETTING_KEY)
        if bank_flag:
            bank_flag.v_json = False
        else:
            self.db.add(AppSetting(k=mini.BANK_DEPOSIT_RUNTIME_SETTING_KEY, v_json=False))
        self.db.flush()

    def cleanup(self):
        try:
            self.db.close()
        finally:
            try:
                if self.outer_tx.is_active:
                    self.outer_tx.rollback()
            finally:
                self.conn.close()

    def test_create_update_delete_with_revisions_and_audit(self):
        first = mini.mini_super_deposit_destination_list(ident=self.ident, db=self.db)
        self.assertEqual(first["total"], 1)
        prev_revision = first["revision"]
        start_wallet_txs = int(self.db.execute(select(func.count()).select_from(WalletTx)).scalar_one())
        req = mini.MiniSuperBankDestinationIn(
            expected_revision=prev_revision, title="کارت دوم",
            bank_name="بانک دوم", card_number="6037999876543210",
        )
        second = mini.mini_super_deposit_destination_add(req, self.req, self.ident, self.db)
        self.assertEqual(second["total"], 2)
        new_id = str(second["items"][-1]["id"])
        self.assertFalse(second["items"][-1]["is_active"])
        self.assertNotEqual(prev_revision, second["revision"])
        with self.assertRaises(HTTPException) as stale:
            mini.mini_super_deposit_destination_add(req, self.req, self.ident, self.db)
        self.assertEqual(stale.exception.status_code, 409)
        self.db.rollback()  # only rolls back current savepoint, not the committed test actions

        status = mini.mini_super_deposit_destination_list(ident=self.ident, db=self.db)
        self.assertEqual(status["total"], 2)
        payload = mini.MiniSuperBankDestinationIn(
            expected_revision=status["revision"], title="کارت دوم",
            bank_name="بانک دوم", card_number="6037999876543210",
            is_active=True,
        )
        activated = mini.mini_super_deposit_destination_update(
            new_id, payload, self.req, self.ident, self.db
        )
        self.assertTrue(next(x for x in activated["items"] if x["id"] == new_id)["is_active"])
        with self.assertRaises(HTTPException):
            mini.mini_super_deposit_destination_delete(
                new_id,
                mini.MiniSuperBankDestinationDeleteIn(expected_revision=activated["revision"]),
                self.req, self.ident, self.db,
            )
        self.db.rollback()

        status = mini.mini_super_deposit_destination_list(ident=self.ident, db=self.db)
        disabled = mini.mini_super_deposit_destination_update(
            new_id,
            mini.MiniSuperBankDestinationIn(
                expected_revision=status["revision"], title="کارت دوم",
                bank_name="بانک دوم", card_number="6037999876543210",
                is_active=False,
            ),
            self.req, self.ident, self.db,
        )
        deleted = mini.mini_super_deposit_destination_delete(
            new_id,
            mini.MiniSuperBankDestinationDeleteIn(expected_revision=disabled["revision"]),
            self.req, self.ident, self.db,
        )
        self.assertEqual(deleted["total"], 1)
        self.assertEqual(deleted["items"][0]["id"], BASE_CARD["id"])
        self.assertEqual(
            int(self.db.execute(select(func.count()).select_from(WalletTx)).scalar_one()),
            start_wallet_txs,
        )
        audits = self.db.execute(
            select(AdminAuditLog)
            .where(AdminAuditLog.actor_user_id == int(self.user.id))
        ).scalars().all()
        self.assertGreaterEqual(len(audits), 4)
        self.assertTrue(all("card_number" not in str(x.details_json) for x in audits))
        print("PASS: bank destination create/activate/deactivate/delete + stale revision + no wallet writes; outer rollback")


if __name__ == "__main__":
    unittest.main()
