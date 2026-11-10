"""Isolated multi-wallet scanning tests; no blockchain, Redis or Production access."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services.crypto_chain_service import ChainTransfer, CryptoChainService
from app.services.crypto_worker import CryptoDepositWorker


class _Db:
    def rollback(self):
        pass

    def commit(self):
        pass


@contextmanager
def _session():
    yield _Db()


class MultiDestinationWorkerTests(unittest.TestCase):
    def make_transfer(self, dest, network="TRON"):
        return ChainTransfer(
            network=network, asset="USDT" if network == "TRON" else "TON",
            tx_hash="tx-" + dest, amount=Decimal("1"),
            sender_address=None, destination_address=dest,
            occurred_at=datetime(2026, 11, 10, 10, 0),
        )

    def test_open_invoice_addresses_are_scanned_individually(self):
        scanned = []
        def fake_scan(**kwargs):
            scanned.append((kwargs["network"], kwargs["destination_address"]))
            return [self.make_transfer(kwargs["destination_address"], kwargs["network"])]
        with (
            patch.object(CryptoDepositWorker, "_network_open_destinations",
                         side_effect=lambda network: ["OLD", "NEW"] if network == "TRON" else []),
            patch.object(CryptoDepositWorker, "_network_scan_since", return_value=datetime(2026, 11, 10)),
            patch.object(CryptoChainService, "list_incoming", side_effect=fake_scan),
            patch("app.services.crypto_worker.SessionLocal", side_effect=_session),
            patch("app.services.crypto_worker.CryptoDepositService.process_transfer", return_value=None),
            patch("app.services.crypto_worker.CryptoDepositService.expire_due", return_value=0),
        ):
            stats = CryptoDepositWorker._process_cycle(
                {"transfers": 0, "matched": 0, "credited": 0, "review": 0, "expired": 0}
            )
        self.assertEqual(scanned, [("TRON", "OLD"), ("TRON", "NEW")])
        self.assertEqual(stats["transfers"], 2)

    def test_failure_on_old_wallet_does_not_skip_new_wallet(self):
        scanned = []
        def fake_scan(**kwargs):
            scanned.append(kwargs["destination_address"])
            if kwargs["destination_address"] == "OLD":
                raise RuntimeError("provider unavailable")
            return [self.make_transfer("NEW")]
        with (
            patch.object(CryptoDepositWorker, "_network_open_destinations",
                         side_effect=lambda network: ["OLD", "NEW"] if network == "TRON" else []),
            patch.object(CryptoDepositWorker, "_network_scan_since", return_value=datetime(2026, 11, 10)),
            patch.object(CryptoChainService, "list_incoming", side_effect=fake_scan),
            patch("app.services.crypto_worker.SessionLocal", side_effect=_session),
            patch("app.services.crypto_worker.CryptoDepositService.process_transfer", return_value=None),
            patch("app.services.crypto_worker.CryptoDepositService.expire_due", return_value=0),
        ):
            stats = CryptoDepositWorker._process_cycle(
                {"transfers": 0, "matched": 0, "credited": 0, "review": 0, "expired": 0}
            )
        self.assertEqual(scanned, ["OLD", "NEW"])
        self.assertEqual(stats["transfers"], 1)

    def test_default_scan_remains_backward_compatible(self):
        with (
            patch.object(CryptoChainService, "_list_tron_usdt", return_value=[]) as tron,
            patch.object(CryptoChainService, "_list_ton", return_value=[]) as ton,
        ):
            CryptoChainService.list_incoming(network="TRON", since=datetime(2026, 11, 10))
            CryptoChainService.list_incoming(network="TON", since=datetime(2026, 11, 10))
        self.assertIsNone(tron.call_args.kwargs["destination_address"])
        self.assertIsNone(ton.call_args.kwargs["destination_address"])


if __name__ == "__main__":
    unittest.main()
