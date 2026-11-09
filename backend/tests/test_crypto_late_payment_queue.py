"""Offline queue contracts for historical crypto review (no settlement).

Uses the real SQLite models and real AdminAuditService. Provider history is
stubbed: no web access, Production data, wallet mutation or address activation.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity, AdminScope
from app.models.user import User
from app.models.crypto import CryptoDepositRequest
from app.models.wallet import Wallet, WalletTx
from app.models.admin_audit import AdminAuditLog
from app.models.crypto_late_payment_case import CryptoLatePaymentCase
from app.services.crypto_chain_service import CryptoChainUnavailable
from app.services.crypto_late_payment_review_service import CryptoLatePaymentReviewService
from app.services.crypto_late_payment_queue_service import CryptoLatePaymentQueueService


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


class HistoricalCryptoQueueTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (
            User.__table__, Wallet.__table__, WalletTx.__table__,
            CryptoDepositRequest.__table__, CryptoLatePaymentCase.__table__,
            AdminAuditLog.__table__,
        ):
            table.create(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.db.add(User(id=91001, tg_user_id=9910091001))
        self.db.add(Wallet(user_id=91001, balance=33333))
        self.db.commit()
        self.admin = AdminIdentity(
            scope=AdminScope.SUPER_ADMIN, token="TEST", user_id=91001,
        )
        self.end = datetime(2026, 11, 9, 20, 0, 0)
        self.start = self.end - timedelta(hours=24)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def example(self, *, tx_hash="synthetic-hash-1", amount="0.500000000",
                classification="POSSIBLE_HISTORICAL_MATCH", candidate_ids=None):
        return {
            "network": "TON", "asset": "TON", "tx_hash": tx_hash,
            "destination_masked": "EQABCD…123456",
            "amount_crypto": amount,
            "occurred_at": (self.end - timedelta(hours=4)).isoformat(),
            "confirmed_on_chain": True,
            "classification": classification,
            "timing": "AFTER_INVOICE_WINDOW",
            "candidate_invoice_ids": [10] if candidate_ids is None else candidate_ids,
            "can_auto_credit": False,
        }

    def report(self, rows):
        return {
            "ok": True, "read_only": True, "can_auto_credit": False,
            "review_needed_count": len(rows), "items": rows,
        }

    def capture(self, rows):
        with patch.object(
            CryptoLatePaymentReviewService, "scan", return_value=self.report(rows),
        ):
            return CryptoLatePaymentQueueService.capture(
                self.db, start_at=self.start, end_at=self.end,
                admin=self.admin,
            )

    def count(self, model):
        return int(self.db.scalar(select(func.count()).select_from(model)))

    def assert_no_money_changed(self):
        self.assertEqual(self.db.scalar(select(Wallet.balance)), 33333)
        self.assertEqual(self.count(WalletTx), 0)

    def test_case_and_audit_commit_together_without_wallet_write(self):
        result = self.capture([self.example()])
        self.assertEqual(result["created"], 1)
        self.assertFalse(result["can_auto_credit"])
        self.db.commit()
        self.assertEqual(self.count(CryptoLatePaymentCase), 1)
        self.assertEqual(self.count(AdminAuditLog), 1)
        audit = self.db.scalar(select(AdminAuditLog))
        self.assertEqual(audit.action, "crypto.late_payment.queue.capture")
        self.assertEqual(audit.details_json["created_count"], 1)
        self.assertEqual(audit.details_json["no_wallet_mutation"], True)
        case = self.db.scalar(select(CryptoLatePaymentCase))
        self.assertEqual(case.state, "OPEN")
        self.assertEqual(case.candidate_invoice_ids, [10])
        self.assert_no_money_changed()

    def test_repeated_capture_is_idempotent_with_no_extra_audit(self):
        self.capture([self.example()])
        self.db.commit()
        again = self.capture([self.example()])
        self.db.commit()
        self.assertEqual(again["created"], 0)
        self.assertEqual(again["already_queued"], 1)
        self.assertEqual(self.count(CryptoLatePaymentCase), 1)
        self.assertEqual(self.count(AdminAuditLog), 1)
        self.assert_no_money_changed()

    def test_same_hash_with_different_amount_fails_closed(self):
        self.capture([self.example()])
        self.db.commit()
        with self.assertRaises(HTTPException) as err:
            self.capture([self.example(amount="0.900000000")])
        self.assertEqual(err.exception.status_code, 409)
        self.db.rollback()
        self.assertEqual(self.count(CryptoLatePaymentCase), 1)
        self.assertEqual(self.count(AdminAuditLog), 1)
        self.assert_no_money_changed()

    def test_network_hash_uniqueness_is_enforced_by_database(self):
        self.capture([self.example()])
        self.db.commit()
        from sqlalchemy.exc import IntegrityError
        original = self.db.scalar(select(CryptoLatePaymentCase))
        duplicate = CryptoLatePaymentCase(
            network=original.network, asset=original.asset,
            tx_hash=original.tx_hash, destination_masked=original.destination_masked,
            amount_crypto=Decimal("0.5"), occurred_at=original.occurred_at,
            confirmed_on_chain=True, classification=original.classification,
            timing=original.timing, candidate_invoice_ids=[],
            state="OPEN", created_by=91001,
        )
        self.db.add(duplicate)
        with self.assertRaises(IntegrityError):
            self.db.flush()
        self.db.rollback()
        self.assertEqual(self.count(CryptoLatePaymentCase), 1)

    def test_already_linked_invoice_is_skipped(self):
        self.db.add(CryptoDepositRequest(
            public_id="linked-1", user_id=91001, network="TON", asset="TON",
            amount_toman=50000, rate_toman_per_asset=Decimal("100000"),
            amount_crypto=Decimal("0.5"), rate_provider="synthetic",
            destination_address="synthetic-address", status="CREDITED",
            tx_hash="synthetic-hash-1", expires_at=self.end,
        ))
        self.db.commit()
        result = self.capture([self.example()])
        self.db.commit()
        self.assertEqual(result["already_linked"], 1)
        self.assertEqual(result["created"], 0)
        self.assertEqual(self.count(CryptoLatePaymentCase), 0)
        self.assertEqual(self.count(AdminAuditLog), 0)
        self.assert_no_money_changed()

    def test_failure_after_first_row_can_be_rolled_back_atomically(self):
        first = self.example()
        second = self.example(tx_hash="synthetic-hash-2", amount="-1")
        with self.assertRaises(HTTPException):
            self.capture([first, second])
        self.db.rollback()
        self.assertEqual(self.count(CryptoLatePaymentCase), 0)
        self.assertEqual(self.count(AdminAuditLog), 0)
        self.assert_no_money_changed()

    def test_provider_failure_does_not_persist_any_case(self):
        with patch.object(
            CryptoLatePaymentReviewService, "scan",
            side_effect=CryptoChainUnavailable("provider out of sync"),
        ):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoLatePaymentQueueService.capture(
                    self.db, start_at=self.start, end_at=self.end,
                    admin=self.admin,
                )
        self.assertEqual(self.count(CryptoLatePaymentCase), 0)
        self.assertEqual(self.count(AdminAuditLog), 0)
        self.assert_no_money_changed()

    def test_duplicate_hash_in_same_report_rejected(self):
        with self.assertRaises(HTTPException) as err:
            self.capture([self.example(), self.example()])
        self.assertEqual(err.exception.status_code, 409)
        self.db.rollback()
        self.assertEqual(self.count(CryptoLatePaymentCase), 0)

    def test_incomplete_report_cannot_be_captured(self):
        bad = self.report([self.example()])
        bad["ok"] = False
        with patch.object(CryptoLatePaymentReviewService, "scan", return_value=bad):
            with self.assertRaises(HTTPException):
                CryptoLatePaymentQueueService.capture(
                    self.db, start_at=self.start, end_at=self.end,
                    admin=self.admin,
                )
        self.assertEqual(self.count(CryptoLatePaymentCase), 0)

    def test_list_never_offers_credit_or_approval(self):
        self.capture([self.example()])
        self.db.commit()
        rows = CryptoLatePaymentQueueService.list_cases(self.db)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["can_auto_credit"])
        self.assertNotIn("approve", str(rows[0]).lower())
        self.assert_no_money_changed()

    def test_routes_are_owner_superadmin_guarded(self):
        from app.routers.mini_router import router, get_mini_super_admin_identity
        names = {
            "/mini-api/admin/super/crypto-late-payment-cases",
            "/mini-api/admin/super/crypto-late-payment-cases/capture",
        }
        for route in router.routes:
            if getattr(route, "path", "") in names:
                self.assertIn(
                    get_mini_super_admin_identity,
                    [d.call for d in route.dependant.dependencies],
                )
                names.discard(route.path)
        self.assertEqual(names, set())


if __name__ == "__main__":
    unittest.main()
