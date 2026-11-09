"""Offline read-only historical crypto review contracts (#30).

SQLite fixtures and mocked chain history only. No external network, wallet
credit, Production access, invoice status update, or new payment claim.
"""
from __future__ import annotations

import base64
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.crypto import CryptoDepositRequest
from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_chain_service import ChainTransfer, CryptoChainService, CryptoChainUnavailable
from app.services.crypto_late_payment_review_service import CryptoLatePaymentReviewService


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_as_integer(element, compiler, **kwargs):
    return "INTEGER"


def ton_addr(seed: int, tag: int = 0x11) -> str:
    body = bytes([tag, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(body + _crc16_xmodem(body)).decode().rstrip("=")


class HistoricalCryptoReviewTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (User.__table__, Wallet.__table__, WalletTx.__table__,
                      CryptoDepositRequest.__table__):
            table.create(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.db.add(User(id=91001, tg_user_id=9910091001))
        self.db.add(Wallet(user_id=91001, balance=77777))
        self.db.commit()
        self.end = datetime(2026, 11, 9, 18, 0, 0)
        self.start = self.end - timedelta(hours=24)
        self.old = ton_addr(1)
        self.new = ton_addr(2)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def invoice(self, key: str, *, addr=None, amount="0.5",
                status="EXPIRED", tx_hash=None, memo=None):
        row = CryptoDepositRequest(
            public_id=key, user_id=91001, network="TON", asset="TON",
            status=status, amount_toman=50000,
            rate_toman_per_asset=Decimal("100000"),
            amount_crypto=Decimal(amount), rate_provider="synthetic",
            destination_address=addr or self.old,
            created_at=self.end - timedelta(hours=10),
            expires_at=self.end - timedelta(hours=9),
            tx_hash=tx_hash, memo=memo,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def transfer(self, hash_value: str, *, destination=None, amount="0.5",
                 at=None, memo=None, confirmed=True):
        return ChainTransfer(
            network="TON", asset="TON", tx_hash=hash_value,
            amount=Decimal(amount), sender_address=ton_addr(9),
            destination_address=destination or self.old,
            occurred_at=at or (self.end - timedelta(hours=8)),
            confirmed=confirmed, confirmations=1 if confirmed else 0,
            memo=memo,
        )

    def scan(self, rows):
        with patch.object(CryptoChainService, "list_incoming_for_addresses", return_value=rows) as provider:
            data = CryptoLatePaymentReviewService.scan(
                self.db, start_at=self.start, end_at=self.end,
            )
        return data, provider

    def test_expired_old_destination_detected_without_any_ledger_mutation(self):
        row = self.invoice("old-expired")
        before_status = row.status
        result, provider = self.scan([self.transfer("tx-late")])
        self.assertEqual(result["review_needed_count"], 1)
        self.assertEqual(result["items"][0]["classification"], "POSSIBLE_HISTORICAL_MATCH")
        self.assertEqual(result["items"][0]["timing"], "AFTER_INVOICE_WINDOW")
        self.assertEqual(result["items"][0]["candidate_invoice_ids"], [row.id])
        self.assertFalse(result["items"][0]["can_auto_credit"])
        self.assertNotIn(self.old, str(result))
        self.assertEqual(row.status, before_status)
        self.assertEqual(self.db.scalar(select(Wallet.balance)), 77777)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(WalletTx)), 0)
        self.assertEqual(provider.call_args.kwargs["addresses"], [self.old])

    def test_known_transaction_never_reappears_for_new_credit(self):
        self.invoice("claimed", tx_hash="already-reconciled")
        result, _ = self.scan([self.transfer("already-reconciled")])
        self.assertEqual(result["already_linked_tx_count"], 1)
        self.assertEqual(result["review_needed_count"], 0)

    def test_multiple_matching_expired_invoices_are_ambiguous(self):
        first = self.invoice("same-1")
        second = self.invoice("same-2")
        result, _ = self.scan([self.transfer("ambiguous")])
        self.assertEqual(result["items"][0]["classification"], "AMBIGUOUS_MULTIPLE_INVOICES")
        self.assertEqual(
            set(result["items"][0]["candidate_invoice_ids"]), {first.id, second.id},
        )
        self.assertFalse(result["can_auto_credit"])

    def test_amount_mismatch_goes_to_review_not_credit(self):
        self.invoice("mismatch", amount="0.5")
        result, _ = self.scan([self.transfer("wrong-amount", amount="0.9")])
        self.assertEqual(result["items"][0]["classification"], "AMOUNT_OR_MEMO_MISMATCH")
        self.assertEqual(self.db.scalar(select(func.count()).select_from(WalletTx)), 0)

    def test_nonbounceable_same_ton_account_is_candidate(self):
        self.invoice("alias")
        result, _ = self.scan([
            self.transfer("ton-alias", destination=ton_addr(1, 0x51))
        ])
        self.assertEqual(result["items"][0]["classification"], "POSSIBLE_HISTORICAL_MATCH")

    def test_unrelated_destination_is_not_attributed_to_invoice(self):
        self.invoice("old-1")
        result, _ = self.scan([self.transfer("unrelated", destination=self.new)])
        self.assertEqual(result["items"][0]["classification"], "NO_MATCHING_HISTORICAL_INVOICE")
        self.assertEqual(result["items"][0]["candidate_invoice_ids"], [])

    def test_provider_failure_fails_closed_with_no_partial_report(self):
        self.invoice("old-1")
        with patch.object(
            CryptoChainService, "list_incoming_for_addresses",
            side_effect=CryptoChainUnavailable("provider history truncated"),
        ):
            with self.assertRaises(CryptoChainUnavailable):
                CryptoLatePaymentReviewService.scan(
                    self.db, start_at=self.start, end_at=self.end,
                )

    def test_duplicate_hash_with_conflicting_destination_fails_closed(self):
        self.invoice("old-1")
        with self.assertRaises(CryptoChainUnavailable):
            self.scan([
                self.transfer("duplicate", destination=self.old),
                self.transfer("duplicate", destination=self.new),
            ])

    def test_excess_invoice_count_fails_closed(self):
        self.invoice("old-1")
        self.invoice("old-2")
        with patch(
            "app.services.crypto_late_payment_review_service.MAX_HISTORICAL_INVOICES", 1,
        ), patch.object(CryptoChainService, "list_incoming_for_addresses") as provider:
            with self.assertRaises(HTTPException) as err:
                CryptoLatePaymentReviewService.scan(
                    self.db, start_at=self.start, end_at=self.end,
                )
        self.assertEqual(err.exception.status_code, 409)
        provider.assert_not_called()

    def test_excess_historical_destinations_fails_before_external_call(self):
        self.invoice("old-1", addr=self.old)
        self.invoice("new-2", addr=self.new)
        with patch(
            "app.services.crypto_late_payment_review_service.MAX_DESTINATIONS_PER_NETWORK", 1,
        ), patch.object(CryptoChainService, "list_incoming_for_addresses") as provider:
            with self.assertRaises(HTTPException) as err:
                CryptoLatePaymentReviewService.scan(
                    self.db, start_at=self.start, end_at=self.end,
                )
        self.assertEqual(err.exception.status_code, 409)
        provider.assert_not_called()

    def test_scan_window_must_be_bounded(self):
        with self.assertRaises(HTTPException) as err:
            CryptoLatePaymentReviewService.scan(
                self.db, start_at=self.end - timedelta(days=8), end_at=self.end,
            )
        self.assertEqual(err.exception.status_code, 400)

    def test_route_is_owner_superadmin_guarded(self):
        from app.routers.mini_router import router, get_mini_super_admin_identity
        matched = [
            route for route in router.routes if getattr(route, "path", "") ==
            "/mini-api/admin/super/crypto-late-payment-review"
        ]
        self.assertEqual(len(matched), 1)
        self.assertIn(
            get_mini_super_admin_identity,
            [dep.call for dep in matched[0].dependant.dependencies],
        )


if __name__ == "__main__":
    unittest.main()
