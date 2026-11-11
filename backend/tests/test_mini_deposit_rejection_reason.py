"""Financial regression tests for admin deposit rejection (isolated SQLite only)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import BigInteger, MetaData, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.models.admin_audit import AdminAuditLog
from app.models.finance import DepositRequest
from app.models.settings import AppSetting
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.routers.mini_router import (
    MiniAdminDepositRejectIn,
    MiniAdminIdentity,
    list_my_deposits,
    mini_admin_reject_deposit,
)


@compiles(BigInteger, "sqlite")
def _compile_bigint(_type, _compiler, **_kwargs):
    return "INTEGER"


ROOT = Path(__file__).resolve().parents[1]


class MiniDepositRejectTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        metadata = MetaData()
        for table in (
            User.__table__,
            Wallet.__table__,
            WalletTx.__table__,
            DepositRequest.__table__,
            AdminAuditLog.__table__,
            AppSetting.__table__,
        ):
            table.to_metadata(metadata)
        for table in metadata.tables.values():
            for index in table.indexes:
                index.name = f"{table.name}_{index.name}"
        metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        # unittest cleanups run in LIFO order: close Session before disposing Engine.
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)

        self.admin = User(tg_user_id=99090001, first_name="admin")
        self.customer = User(tg_user_id=99090002, first_name="customer")
        self.db.add_all([self.admin, self.customer])
        self.db.flush()
        self.wallet = Wallet(user_id=self.customer.id, balance=52000)
        self.deposit = DepositRequest(
            user_id=self.customer.id, amount=12000,
            status="PENDING_REVIEW",
        )
        self.db.add_all([self.wallet, self.deposit])
        self.db.commit()
        self.actor = MiniAdminIdentity(
            user_id=self.admin.id, tg_user_id=self.admin.tg_user_id,
            roles=["FINANCE_ADMIN"],
        )
        self.request = Request({
            "type": "http",
            "method": "POST",
            "path": f"/mini-api/admin/deposits/{self.deposit.id}/reject",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        })

    def audit_count(self):
        return int(self.db.execute(
            select(func.count()).select_from(AdminAuditLog)
        ).scalar_one())

    def tx_count(self):
        return int(self.db.execute(
            select(func.count()).select_from(WalletTx)
        ).scalar_one())

    def reject(self, reason, *, ident=None):
        return mini_admin_reject_deposit(
            deposit_id=int(self.deposit.id),
            payload=MiniAdminDepositRejectIn(reason=reason),
            request=self.request,
            ident=ident if ident is not None else self.actor,
            db=self.db,
        )

    def test_reason_is_saved_with_status_and_audit_without_credit(self):
        with patch(
            "app.routers.mini_router._mini_notify_deposit_final_to_user",
            return_value={"sent": True},
        ) as notice:
            result = self.reject("  اطلاعات رسید تأیید نشد.  ")
            self.assertTrue(result["ok"])
            self.assertEqual(result["rejection_reason"], "اطلاعات رسید تأیید نشد.")
            self.assertTrue(result["user_notify"]["sent"])
            notice.assert_called_once()
            self.assertEqual(
                notice.call_args.kwargs["reason"],
                "اطلاعات رسید تأیید نشد.",
            )

        self.db.expire_all()
        saved = self.db.get(DepositRequest, int(self.deposit.id))
        self.assertEqual(saved.status, "REJECTED")
        self.assertEqual(saved.rejection_reason, "اطلاعات رسید تأیید نشد.")
        self.assertEqual(saved.reviewed_by, int(self.admin.id))
        self.assertIsNotNone(saved.reviewed_at)
        audit = self.db.execute(select(AdminAuditLog)).scalar_one()
        self.assertEqual(audit.action, "deposit.reject")
        self.assertEqual(audit.details_json["reason"], saved.rejection_reason)
        self.assertEqual(self.db.get(Wallet, int(self.wallet.id)).balance, 52000)
        self.assertEqual(self.tx_count(), 0)

    def test_duplicate_rejection_never_notifies_twice_or_changes_wallet(self):
        with patch(
            "app.routers.mini_router._mini_notify_deposit_final_to_user",
            return_value={"sent": True},
        ) as notice:
            self.reject("دلیل معتبر برای رد واریز")
            with self.assertRaises(HTTPException) as caught:
                self.reject("دلیل دوم نباید ثبت شود")
            self.assertEqual(caught.exception.status_code, 400)
            self.db.rollback()
            self.assertEqual(notice.call_count, 1)
        saved = self.db.get(DepositRequest, int(self.deposit.id))
        self.assertEqual(saved.rejection_reason, "دلیل معتبر برای رد واریز")
        self.assertEqual(self.audit_count(), 1)
        self.assertEqual(self.tx_count(), 0)
        self.assertEqual(self.db.get(Wallet, int(self.wallet.id)).balance, 52000)

    def test_whitespace_reason_fails_before_financial_status_change(self):
        with self.assertRaises(HTTPException) as caught:
            self.reject("   ")
        self.assertEqual(caught.exception.status_code, 400)
        self.db.rollback()
        self.assertEqual(self.db.get(DepositRequest, int(self.deposit.id)).status, "PENDING_REVIEW")
        self.assertEqual(self.audit_count(), 0)
        self.assertEqual(self.tx_count(), 0)

    def test_missing_short_or_long_reason_rejected_at_contract_boundary(self):
        for data in ({}, {"reason": "ab"}, {"reason": "x" * 501}):
            with self.assertRaises(ValidationError):
                MiniAdminDepositRejectIn(**data)

    def test_game_operator_must_not_reject_deposits(self):
        game_actor = MiniAdminIdentity(
            user_id=self.admin.id,
            tg_user_id=self.admin.tg_user_id,
            roles=["GAME_OPERATOR"],
        )
        with self.assertRaises(HTTPException) as caught:
            self.reject("دلیل معتبر", ident=game_actor)
        self.assertEqual(caught.exception.status_code, 403)
        self.db.rollback()
        self.assertEqual(self.db.get(DepositRequest, self.deposit.id).status, "PENDING_REVIEW")

    def test_failed_telegram_notice_leaves_reason_durable_and_no_retries(self):
        with patch(
            "app.routers.mini_router._mini_notify_deposit_final_to_user",
            return_value={"sent": False},
        ) as notice:
            result = self.reject("مغایرت با واریز بانکی")
            self.assertFalse(result["user_notify"]["sent"])
            notice.assert_called_once()
        saved = self.db.get(DepositRequest, self.deposit.id)
        self.assertEqual(saved.status, "REJECTED")
        self.assertEqual(saved.rejection_reason, "مغایرت با واریز بانکی")
        self.assertEqual(self.tx_count(), 0)

    def test_customer_history_contains_rejection_reason(self):
        with patch(
            "app.routers.mini_router._mini_notify_deposit_final_to_user",
            return_value={"sent": True},
        ):
            self.reject("رسید تکراری است")
        response = list_my_deposits(
            user_id=int(self.customer.id), limit=20, offset=0, db=self.db
        )
        self.assertEqual(response.total, 1)
        self.assertEqual(response.items[0].rejection_reason, "رسید تکراری است")

    def test_historic_rejection_without_reason_stays_readable(self):
        self.deposit.status = "REJECTED"
        self.db.commit()
        response = list_my_deposits(
            user_id=int(self.customer.id), limit=20, offset=0, db=self.db
        )
        self.assertIsNone(response.items[0].rejection_reason)


class MiniDepositRejectContractTests(unittest.TestCase):
    def test_ui_both_bank_reject_buttons_open_same_reason_dialog(self):
        js = (ROOT / "app/static/mini/app.js").read_text(encoding="utf-8")
        html = (ROOT / "app/static/mini/index.html").read_text(encoding="utf-8")
        css = (ROOT / "app/static/mini/styles.css").read_text(encoding="utf-8")
        self.assertIn('openDepositRejectModal(depositId, item, { fromReceipt: true })', js)
        self.assertIn('openDepositRejectModal(id, state.admin.depositsById?.get(id) || null)', js)
        self.assertIn('function openFinanceRejectModal(kind, requestId, item = null, options = {})', js)
        self.assertIn('DEPOSIT_REJECTION_PRESETS', js)
        self.assertIn('body: { reason: cleanReason }', js)
        self.assertIn('id="withdrawRejectReasonLabel"', html)
        self.assertIn('id="withdrawRejectWarningText"', html)
        self.assertIn('z-index: 13020', css)
        self.assertIn("./app.js?v=autopilot-start-countdown-v1", html)

    def test_migration_has_nullable_field_and_exact_revision_parent(self):
        migration = (ROOT / "alembic/versions/20261108_0012_deposit_rejection_reason.py").read_text(encoding="utf-8")
        self.assertIn('down_revision = "20261104_0011"', migration)
        self.assertIn('sa.String(length=500), nullable=True', migration)
        self.assertIn('"deposit_requests"', migration)


if __name__ == "__main__":
    unittest.main()
