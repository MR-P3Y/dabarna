"""Read-only wallet rotation readiness and invoice grace-window contracts."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_rotation_readiness import assess_rotation


class _CountResult:
    def __init__(self, value):
        self.value = value
    def scalar_one(self):
        return self.value


class _ReadOnlyDb:
    def __init__(self, counts):
        self.counts = list(counts)
        self.queries = []
    def execute(self, query):
        self.queries.append(str(query))
        return _CountResult(self.counts.pop(0))
    def commit(self):
        raise AssertionError("readiness must never commit")
    def flush(self):
        raise AssertionError("readiness must never flush")


class RotationReadinessContracts(TestCase):
    def test_open_expired_and_review_blockers_reported_without_mutation(self):
        db = _ReadOnlyDb([2, 1, 3])
        report = assess_rotation(db, network="TRON", current_address="OLD", proposed_address="NEW")
        self.assertEqual(report["open_invoices"], 2)
        self.assertEqual(report["recent_closed_invoices"], 1)
        self.assertEqual(report["needs_manual_review"], 3)
        self.assertFalse(report["active_change_allowed"])
        self.assertEqual(len(db.queries), 3)
        self.assertTrue(all("crypto_deposit_requests" in x for x in db.queries))
        self.assertIn("destination_address", db.queries[0])
        self.assertIn("expires_at", db.queries[1])

    def test_candidate_cannot_equal_current(self):
        db = _ReadOnlyDb([0, 0, 0])
        report = assess_rotation(db, network="TON", current_address="OLD", proposed_address="OLD")
        self.assertTrue(report["candidate_matches_current"])
        self.assertFalse(report["active_change_allowed"])

    def test_invalid_network_refused(self):
        with self.assertRaises(ValueError):
            assess_rotation(_ReadOnlyDb([]), network="ETH", current_address="OLD", proposed_address="NEW")

    def test_transfer_within_invoice_payment_grace(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        inv = SimpleNamespace(created_at=now-timedelta(minutes=20), expires_at=now-timedelta(minutes=1))
        transfer = ChainTransfer(
            network="TON", asset="TON", tx_hash="hash", amount=Decimal("1"),
            sender_address=None, destination_address="OLD",
            occurred_at=now-timedelta(seconds=20),
        )
        with patch("app.services.crypto_deposit_service.cfg.CRYPTO_PAYMENT_GRACE_MINUTES", 15):
            self.assertTrue(CryptoDepositService._transfer_is_in_window(inv, transfer))

    def test_payment_beyond_grace_not_eligible(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        inv = SimpleNamespace(created_at=now-timedelta(hours=3), expires_at=now-timedelta(hours=2))
        transfer = ChainTransfer(
            network="TRON", asset="USDT", tx_hash="hash", amount=Decimal("1"),
            sender_address=None, destination_address="OLD", occurred_at=now,
        )
        with patch("app.services.crypto_deposit_service.cfg.CRYPTO_PAYMENT_GRACE_MINUTES", 15):
            self.assertFalse(CryptoDepositService._transfer_is_in_window(inv, transfer))


if __name__ == "__main__":
    import unittest
    unittest.main()
