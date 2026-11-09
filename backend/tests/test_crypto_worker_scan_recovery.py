"""Offline worker fail-closed regressions for chain provider gaps (#30)."""
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.crypto_worker import CryptoDepositWorker
from app.services.crypto_chain_service import ChainTransfer, CryptoChainUnavailable
from app.services.crypto_deposit_service import CryptoDepositService


class CryptoWorkerRecoveryTests(unittest.TestCase):
    def test_oldest_open_invoice_is_not_lost_after_lookback_window(self):
        fixed = datetime(2026, 11, 9, 11, 0, 0)
        earliest = fixed - timedelta(days=4)
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = earliest
        with patch("app.services.crypto_worker._utcnow", return_value=fixed), \
             patch("app.services.crypto_worker.SessionLocal") as factory:
            factory.return_value.__enter__.return_value = db
            self.assertEqual(
                CryptoDepositWorker._network_scan_since("TRON"),
                earliest - timedelta(minutes=2),
            )

    def test_scan_failure_never_expires_open_invoice(self):
        with patch.object(
            CryptoDepositWorker, "_network_has_open_invoices",
            side_effect=lambda network: network == "TON",
        ), patch.object(
            CryptoDepositWorker, "_network_scan_since",
            return_value=datetime(2026, 11, 8),
        ), patch.object(
            CryptoDepositWorker, "_network_invoice_destinations",
            return_value=["old-address"],
        ), patch(
            "app.services.crypto_worker.CryptoChainService.list_incoming_for_addresses",
            side_effect=CryptoChainUnavailable("truncated history"),
        ), patch(
            "app.services.crypto_worker.SessionLocal",
        ) as sessions, patch.object(
            CryptoDepositService, "expire_due",
        ) as expire:
            stats = CryptoDepositWorker._process_cycle(
                {"transfers": 0, "matched": 0, "credited": 0, "review": 0, "expired": 0}
            )
        self.assertEqual(stats["expired"], 0)
        expire.assert_not_called()
        sessions.assert_not_called()

    def test_processing_failure_defers_expiry(self):
        transfer = ChainTransfer(
            network="TON", asset="TON", tx_hash="hash",
            amount=Decimal("1"), sender_address=None,
            destination_address="old-address",
            occurred_at=datetime(2026, 11, 8),
        )
        db = MagicMock()
        with patch.object(
            CryptoDepositWorker, "_network_has_open_invoices",
            side_effect=lambda network: network == "TON",
        ), patch.object(
            CryptoDepositWorker, "_network_scan_since",
            return_value=datetime(2026, 11, 8),
        ), patch.object(
            CryptoDepositWorker, "_network_invoice_destinations",
            return_value=["old-address"],
        ), patch(
            "app.services.crypto_worker.CryptoChainService.list_incoming_for_addresses",
            return_value=[transfer],
        ), patch(
            "app.services.crypto_worker.SessionLocal",
        ) as sessions, patch.object(
            CryptoDepositService, "process_transfer",
            side_effect=RuntimeError("database processing failed"),
        ), patch.object(
            CryptoDepositService, "expire_due",
        ) as expire:
            sessions.return_value.__enter__.return_value = db
            stats = CryptoDepositWorker._process_cycle(
                {"transfers": 0, "matched": 0, "credited": 0, "review": 0, "expired": 0}
            )
        self.assertEqual(stats["transfers"], 1)
        self.assertEqual(stats["expired"], 0)
        db.rollback.assert_called()
        expire.assert_not_called()

    def test_expiry_runs_when_all_scans_succeed(self):
        db = MagicMock()
        with patch.object(
            CryptoDepositWorker, "_network_has_open_invoices",
            return_value=False,
        ), patch("app.services.crypto_worker.SessionLocal") as sessions, \
             patch.object(
                CryptoDepositService, "expire_due", return_value=2
             ) as expire:
            sessions.return_value.__enter__.return_value = db
            stats = CryptoDepositWorker._process_cycle(
                {"transfers": 0, "matched": 0, "credited": 0, "review": 0, "expired": 0}
            )
        self.assertEqual(stats["expired"], 2)
        expire.assert_called_once()
        db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
