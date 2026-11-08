"""MySQL-only finance rejection integration; all writes rollback under an outer transaction.

REQUIRED:
  DAVARNA_FINANCE_REJECT_TEST_DB=davarna_finance_reject_test_20261108_v2
  DATABASE_URL pointing to the same isolated DB, NEVER Production.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from dotenv import dotenv_values
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.requests import Request

TEST_DB = "davarna_finance_reject_test_20261108_v2"
if os.environ.get("DAVARNA_FINANCE_REJECT_TEST_DB") != TEST_DB:
    raise unittest.SkipTest("explicit isolated MySQL opt-in required")

raw_url = os.environ.get("DATABASE_URL", "")
if not raw_url or make_url(raw_url).get_backend_name() != "mysql":
    raise RuntimeError("MySQL integration requires an explicit isolated DATABASE_URL")
if make_url(raw_url).database != TEST_DB or make_url(raw_url).host != "davarna-mysql":
    raise RuntimeError("SAFETY STOP: integration tests refuse non-isolated DB")

from app.models.admin_audit import AdminAuditLog
from app.models.finance import DepositRequest
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.routers.mini_router import (
    MiniAdminDepositRejectIn,
    MiniAdminIdentity,
    mini_admin_reject_deposit,
)
from app.services.finance_service import FinanceService


class MySQLDepositRejectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(raw_url, pool_pre_ping=True)
        with cls.engine.connect() as connection:
            actual = connection.execute(text("SELECT DATABASE()")).scalar_one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            col = connection.execute(text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema=DATABASE() AND table_name='deposit_requests' "
                "AND column_name='rejection_reason'"
            )).scalar_one()
            if actual != TEST_DB or revision != "20261108_0012" or col != 1:
                raise RuntimeError("SAFETY STOP: test schema/revision is wrong")
        print("PASS: isolated MySQL schema for finance rejection, revision", revision)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.outer = self.connection.begin()
        self.db = Session(bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        self.addCleanup(self._cleanup)

        self.admin = User(tg_user_id=7300000000001, first_name="test-admin")
        self.customer = User(tg_user_id=7300000000002, first_name="test-customer")
        self.db.add_all([self.admin, self.customer])
        self.db.flush()
        self.wallet = Wallet(user_id=int(self.customer.id), balance=85000)
        self.deposit = DepositRequest(user_id=int(self.customer.id), amount=12000, status="PENDING_REVIEW")
        self.db.add_all([self.wallet, self.deposit])
        self.db.flush()
        self.db.commit()
        self.actor = MiniAdminIdentity(
            user_id=int(self.admin.id), tg_user_id=int(self.admin.tg_user_id), roles=["FINANCE_ADMIN"]
        )
        self.request = Request({
            "type": "http", "method": "POST",
            "path": f"/mini-api/admin/deposits/{self.deposit.id}/reject",
            "headers": [], "query_string": b"", "scheme": "http", "server": ("test", 80),
        })

    def _cleanup(self):
        try:
            self.db.close()
        finally:
            try:
                if self.outer.is_active:
                    self.outer.rollback()
            finally:
                self.connection.close()

    def test_persisted_reason_audit_one_notification_and_zero_ledger_changes(self):
        before_tx = self.db.execute(select(func.count()).select_from(WalletTx)).scalar_one()
        with patch(
            "app.routers.mini_router._mini_notify_deposit_final_to_user",
            return_value={"sent": True},
        ) as notice:
            out = mini_admin_reject_deposit(
                deposit_id=int(self.deposit.id),
                payload=MiniAdminDepositRejectIn(reason="  رسید بانکی تطبیق نداشت  "),
                request=self.request, ident=self.actor, db=self.db,
            )
            self.assertEqual(out["rejection_reason"], "رسید بانکی تطبیق نداشت")
            notice.assert_called_once()
            with self.assertRaises(HTTPException) as cm:
                mini_admin_reject_deposit(
                    deposit_id=int(self.deposit.id),
                    payload=MiniAdminDepositRejectIn(reason="تلاش برای رد تکراری"),
                    request=self.request, ident=self.actor, db=self.db,
                )
            self.assertEqual(cm.exception.status_code, 400)
            self.db.rollback()
            self.assertEqual(notice.call_count, 1)

        row = self.db.get(DepositRequest, int(self.deposit.id))
        self.assertEqual(row.status, "REJECTED")
        self.assertEqual(row.rejection_reason, "رسید بانکی تطبیق نداشت")
        self.assertEqual(row.reviewed_by, int(self.admin.id))
        self.assertEqual(
            self.db.execute(select(func.count()).select_from(WalletTx)).scalar_one(), before_tx
        )
        self.assertEqual(self.db.get(Wallet, self.wallet.id).balance, 85000)
        audits = self.db.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "deposit.reject",
                AdminAuditLog.target_id == int(self.deposit.id),
            )
        ).scalars().all()
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].details_json["reason"], "رسید بانکی تطبیق نداشت")

    def test_legacy_bot_service_contract_stays_compatible(self):
        # Some Bot APIs invoke FinanceService directly with the old 3-argument
        # signature; this must continue to reject without wallet mutations.
        row = FinanceService.reject_deposit(
            db=self.db,
            deposit_id=int(self.deposit.id),
            admin_user_id=int(self.admin.id),
        )
        self.db.commit()
        self.assertEqual(row.status, "REJECTED")
        self.assertIsNone(row.rejection_reason)
        self.assertEqual(self.db.get(Wallet, self.wallet.id).balance, 85000)
        self.assertEqual(
            self.db.execute(select(func.count()).select_from(WalletTx)).scalar_one(), 0
        )


if __name__ == "__main__":
    unittest.main()
