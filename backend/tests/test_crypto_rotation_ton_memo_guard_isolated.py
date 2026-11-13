"""Isolated strict TON invoice attribution for the experimental address-rotation path."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_deposit_service import CryptoDepositService


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows


class Db:
    def __init__(self, *results):
        self.results = list(results)

    def execute(self, stmt):
        if not self.results:
            raise AssertionError("Unexpected query")
        return Result(self.results.pop(0))


class TonMemoGuardTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.invoice = SimpleNamespace(
            id=9, memo="DAV-INVOICE", destination_address="TON_OLD",
            created_at=now-timedelta(minutes=1), expires_at=now+timedelta(minutes=5),
        )
        self.transfer = ChainTransfer(
            network="TON", asset="TON", tx_hash="transaction",
            amount=Decimal("2"), sender_address="SENDER",
            destination_address="TON_OLD", occurred_at=now,
            memo=None, confirmed=True,
        )

    def test_rotation_rejects_amount_only_without_memo(self):
        with patch("app.services.crypto_deposit_service.rotation_enabled", return_value=True):
            self.assertIsNone(CryptoDepositService._match_invoice(
                Db([], [self.invoice]), self.transfer
            ))

    def test_rotation_rejects_claimed_hash_without_memo(self):
        with patch("app.services.crypto_deposit_service.rotation_enabled", return_value=True):
            self.assertIsNone(CryptoDepositService._match_invoice(
                Db([self.invoice]), self.transfer
            ))

    def test_rotation_rejects_claimed_wrong_memo(self):
        transfer = ChainTransfer(**{**self.transfer.__dict__, "memo": "DAV-OTHER"})
        with patch("app.services.crypto_deposit_service.rotation_enabled", return_value=True):
            self.assertIsNone(CryptoDepositService._match_invoice(
                Db([self.invoice]), transfer
            ))

    def test_rotation_accepts_exact_memo(self):
        transfer = ChainTransfer(**{**self.transfer.__dict__, "memo": "DAV-INVOICE"})
        with patch("app.services.crypto_deposit_service.rotation_enabled", return_value=True):
            self.assertIs(CryptoDepositService._match_invoice(
                Db([], [self.invoice]), transfer
            ), self.invoice)

    def test_non_rotation_legacy_amount_match_still_works(self):
        with patch("app.services.crypto_deposit_service.rotation_enabled", return_value=False):
            self.assertIs(CryptoDepositService._match_invoice(
                Db([], [self.invoice]), self.transfer
            ), self.invoice)


if __name__ == "__main__":
    unittest.main()
