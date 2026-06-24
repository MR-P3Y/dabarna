import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_rate_service import CryptoRateQuote
from app.services.crypto_chain_service import ChainTransfer
from app.core import config as cfg


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None


class _FakeResult:
    def __init__(self, *, scalar=None, rows=None):
        self.scalar = scalar
        self.rows = list(rows or [])

    def scalar_one_or_none(self):
        return self.scalar

    def scalar_one(self):
        return self.scalar

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _SequenceSession:
    def __init__(self, results):
        self.results = list(results)
        self.flush_count = 0

    def execute(self, statement):
        return self.results.pop(0)

    def flush(self):
        self.flush_count += 1


class CryptoDepositHelperTests(unittest.TestCase):
    def test_tron_hash_is_normalized(self):
        value = "A" * 64
        self.assertEqual(
            CryptoDepositService._normalize_tx_hash("TRON", value),
            "a" * 64,
        )

    def test_invalid_tron_hash_is_rejected(self):
        with self.assertRaises(HTTPException):
            CryptoDepositService._normalize_tx_hash("TRON", "not-a-hash")

    def test_ton_hash_accepts_base64_characters(self):
        value = "AbCdEf0123456789_+/=-AbCdEf"
        self.assertEqual(
            CryptoDepositService._normalize_tx_hash("TON", value),
            value,
        )

    def test_create_invoice_locks_toman_and_crypto_amounts(self):
        old_values = {
            "enabled": cfg.CRYPTO_PAYMENTS_ENABLED,
            "ton_enabled": cfg.CRYPTO_TON_ENABLED,
            "ton_address": cfg.CRYPTO_TON_ADDRESS,
        }
        cfg.CRYPTO_PAYMENTS_ENABLED = True
        cfg.CRYPTO_TON_ENABLED = True
        cfg.CRYPTO_TON_ADDRESS = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"
        db = _FakeSession()
        quote = CryptoRateQuote(
            asset="TON",
            rate_toman=Decimal("250000"),
            provider="wallex",
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        try:
            with (
                patch(
                    "app.services.crypto_deposit_service.CryptoRateService.get_live_quote",
                    return_value=quote,
                ),
                patch.object(
                    CryptoDepositService,
                    "_unique_open_amount",
                    return_value=Decimal("2.000001"),
                ),
            ):
                invoice = CryptoDepositService.create_invoice(
                    db,
                    user_id=10,
                    amount_toman=500_000,
                    network="TON",
                )
        finally:
            cfg.CRYPTO_PAYMENTS_ENABLED = old_values["enabled"]
            cfg.CRYPTO_TON_ENABLED = old_values["ton_enabled"]
            cfg.CRYPTO_TON_ADDRESS = old_values["ton_address"]
        self.assertEqual(invoice.amount_toman, 500_000)
        self.assertEqual(invoice.amount_crypto, Decimal("2.000001"))
        self.assertEqual(invoice.status, "WAITING_PAYMENT")
        self.assertTrue(invoice.memo.startswith("DAV-"))
        self.assertEqual(db.added, [invoice])

    def test_transfer_before_invoice_is_not_accepted(self):
        invoice = SimpleNamespace(
            created_at=datetime(2026, 6, 24, 12, 0, 0),
            expires_at=datetime(2026, 6, 24, 12, 15, 0),
        )
        transfer = ChainTransfer(
            network="TRON",
            asset="USDT",
            tx_hash="a" * 64,
            amount=Decimal("10"),
            sender_address="TSender",
            destination_address="TReceiver",
            occurred_at=datetime(2026, 6, 24, 11, 59, 59),
        )
        self.assertFalse(
            CryptoDepositService._transfer_is_in_window(invoice, transfer)
        )

    def test_confirmed_transfer_credits_wallet_once(self):
        invoice = SimpleNamespace(
            id=25,
            user_id=10,
            network="TRON",
            asset="USDT",
            amount_toman=500_000,
            amount_crypto=Decimal("3.25"),
            paid_amount_crypto=None,
            memo=None,
            tx_hash=None,
            sender_address=None,
            status="WAITING_PAYMENT",
            wallet_tx_id=None,
            failure_reason=None,
            created_at=datetime(2026, 6, 24, 12, 0, 0),
            expires_at=datetime(2026, 6, 24, 12, 15, 0),
            detected_at=None,
            confirmed_at=None,
            credited_at=None,
            last_checked_at=None,
            updated_at=None,
        )
        transfer = ChainTransfer(
            network="TRON",
            asset="USDT",
            tx_hash="b" * 64,
            amount=Decimal("3.25"),
            sender_address="TSender",
            destination_address="TReceiver",
            occurred_at=datetime(2026, 6, 24, 12, 5, 0),
        )
        db = _SequenceSession(
            [
                _FakeResult(scalar=None),
                _FakeResult(scalar=None),
                _FakeResult(rows=[invoice]),
                _FakeResult(scalar=invoice),
                _FakeResult(scalar=None),
            ]
        )
        with patch(
            "app.services.crypto_deposit_service.WalletService.credit",
            return_value=SimpleNamespace(id=777),
        ) as credit:
            result = CryptoDepositService.process_transfer(db, transfer)
        self.assertIs(result, invoice)
        self.assertEqual(invoice.status, "CREDITED")
        self.assertEqual(invoice.wallet_tx_id, 777)
        credit.assert_called_once()
        self.assertEqual(credit.call_args.kwargs["idempotency_key"], f"crypto:TRON:{'b' * 64}")

        already_processed_db = _SequenceSession([_FakeResult(scalar=invoice)])
        with patch(
            "app.services.crypto_deposit_service.WalletService.credit",
        ) as repeated_credit:
            repeated = CryptoDepositService.process_transfer(
                already_processed_db,
                transfer,
            )
        self.assertIsNone(repeated)
        repeated_credit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
