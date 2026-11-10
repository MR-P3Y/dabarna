"""Isolated safety contract for late historical transfers; no chain or DB."""
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.crypto_late_transfer_review import (
    late_review_key, record_unmatched_historical_transfer,
)


class LateTransferInboxSafetyTests(unittest.TestCase):
    def setUp(self):
        self.transfer = SimpleNamespace(
            network="TRON", asset="USDT", tx_hash="0xabc", amount=Decimal("1.00"),
            sender_address="sender", destination_address="old_destination",
            memo=None, confirmed=True, occurred_at=datetime(2026, 11, 10),
        )

    def test_unique_keys_fit_app_settings_column(self):
        key = late_review_key("TRON", "0xabc")
        self.assertLessEqual(len(key), 64)
        self.assertEqual(key, late_review_key("TRON", "0xabc"))
        self.assertNotEqual(key, late_review_key("TON", "0xabc"))
        self.assertNotEqual(key, late_review_key("TRON", "0xabd"))

    def test_hard_gate_off_never_reads_or_writes_database(self):
        db = MagicMock()
        with patch("app.services.crypto_late_transfer_review.rotation_enabled", return_value=False):
            self.assertFalse(record_unmatched_historical_transfer(db, self.transfer))
        db.execute.assert_not_called()
        db.add.assert_not_called()

    def test_historical_observation_never_calls_wallet_credit(self):
        db = MagicMock()
        first = MagicMock()
        first.scalars.return_value.all.return_value = [SimpleNamespace(id=19)]
        second = MagicMock()
        second.scalar_one_or_none.return_value = None
        third = MagicMock()
        third.scalar_one_or_none.return_value = None
        db.execute.side_effect = [first, second, third]
        with patch("app.services.crypto_late_transfer_review.rotation_enabled", return_value=True):
            self.assertTrue(record_unmatched_historical_transfer(db, self.transfer))
        db.add.assert_called_once()
        row = db.add.call_args.args[0]
        self.assertEqual(row.v_json["status"], "PENDING_MANUAL_RECONCILIATION")
        self.assertEqual(row.v_json["candidate_invoice_ids"], [19])
        self.assertFalse(row.v_json["automatically_credited"])
        db.flush.assert_called_once()

    def test_repeated_hash_is_not_added_twice(self):
        db = MagicMock()
        first = MagicMock()
        first.scalars.return_value.all.return_value = [SimpleNamespace(id=19)]
        second = MagicMock()
        second.scalar_one_or_none.return_value = None
        third = MagicMock()
        third.scalar_one_or_none.return_value = "already-recorded"
        db.execute.side_effect = [first, second, third]
        with patch("app.services.crypto_late_transfer_review.rotation_enabled", return_value=True):
            self.assertFalse(record_unmatched_historical_transfer(db, self.transfer))
        db.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
