"""Isolated contracts for persistent crypto scan observations."""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from app.services.crypto_scan_observation import observation_key, record_scan_observation

class ScanObservationTests(unittest.TestCase):
    def setUp(self):
        self.since = datetime(2026, 11, 10)

    def test_keys_are_scoped_and_fit_column(self):
        self.assertLessEqual(len(observation_key("TON", "OLD")), 64)
        self.assertNotEqual(observation_key("TON", "OLD"), observation_key("TRON", "OLD"))
        self.assertNotEqual(observation_key("TON", "OLD"), observation_key("TON", "NEW"))

    def test_gate_off_does_not_access_database(self):
        db = MagicMock()
        with patch("app.services.crypto_scan_observation.rotation_enabled", return_value=False):
            record_scan_observation(db, network="TON", address="OLD", since=self.since,
                                    pages_complete=True, processing_complete=True,
                                    historical_gap=False, transfer_count=1)
        db.get.assert_not_called()
        db.add.assert_not_called()

    def test_completed_pages_do_not_certify_backfill(self):
        db = MagicMock()
        db.get.return_value = None
        with patch("app.services.crypto_scan_observation.rotation_enabled", return_value=True):
            record_scan_observation(db, network="TON", address="OLD", since=self.since,
                                    pages_complete=True, processing_complete=True,
                                    historical_gap=False, transfer_count=1)
        data = db.add.call_args.args[0].v_json
        self.assertTrue(data["pages_complete"])
        self.assertFalse(data["backfill_verified"])
        self.assertNotIn("OLD", data.values())

    def test_provider_failure_remains_incomplete(self):
        db = MagicMock()
        db.get.return_value = None
        with patch("app.services.crypto_scan_observation.rotation_enabled", return_value=True):
            record_scan_observation(db, network="TRON", address="OLD", since=self.since,
                                    pages_complete=False, processing_complete=False,
                                    historical_gap=True, transfer_count=0)
        data = db.add.call_args.args[0].v_json
        self.assertFalse(data["pages_complete"])
        self.assertFalse(data["backfill_verified"])
        self.assertTrue(data["historical_gap"])

if __name__ == "__main__":
    unittest.main()
