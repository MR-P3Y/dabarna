"""Historical coverage alarm: isolated, no DB/network/crediting operations."""
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.crypto_worker import CryptoDepositWorker


@contextmanager
def fake_session(earliest):
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = earliest
    yield db


class HistoricalScanGapTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 12, 0, 0)
        self.floor = self.now - timedelta(hours=24)

    def scan(self, earliest, rotation):
        stats = {}
        with (
            patch("app.services.crypto_worker._utcnow", return_value=self.now),
            patch("app.services.crypto_worker.cfg.CRYPTO_SCAN_LOOKBACK_HOURS", 24),
            patch("app.services.crypto_worker.rotation_enabled", return_value=rotation),
            patch("app.services.crypto_worker.SessionLocal",
                  side_effect=lambda: fake_session(earliest)),
        ):
            with self.assertLogs("app.services.crypto_worker", level="ERROR") if rotation and earliest and earliest < self.floor else _NullLogs():
                result = CryptoDepositWorker._network_scan_since(
                    "TON", destination_address="OLD", coverage_stats=stats)
        return result, stats

    def test_old_invoice_marks_incomplete_coverage(self):
        result, stats = self.scan(self.floor - timedelta(days=10), True)
        self.assertEqual(result, self.floor)
        self.assertEqual(stats["historical_gaps"], 1)

    def test_recent_invoice_scan_preserves_overlap(self):
        result, stats = self.scan(self.now - timedelta(hours=1), True)
        self.assertEqual(result, self.now - timedelta(hours=1, minutes=2))
        self.assertEqual(stats, {})

    def test_legacy_scan_does_not_change_behavior(self):
        result, stats = self.scan(self.floor - timedelta(days=10), False)
        self.assertEqual(result, self.floor)
        self.assertEqual(stats, {})

    def test_empty_history_uses_default_floor(self):
        result, stats = self.scan(None, True)
        self.assertEqual(result, self.floor)
        self.assertEqual(stats, {})


class _NullLogs:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


if __name__ == "__main__":
    unittest.main()
