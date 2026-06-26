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

    def execute(self, statement):
        return _FakeResult(rows=[])


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

    def first(self):
        return self.rows[0] if self.rows else None


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
                    "app.services.crypto_deposit_service.CryptoPreflightService.check",
                    return_value={
                        "healthy": True,
                        "quote": quote,
                        "estimated_network_fee": Decimal("0.01"),
                        "estimated_network_fee_asset": "TON",
                    },
                ),
                patch.object(
                    CryptoDepositService,
                    "runtime_enabled",
                    return_value=True,
                ),
                patch.object(
                    CryptoDepositService,
                    "_enforce_daily_user_limits",
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

    def test_runtime_setting_defaults_to_disabled(self):
        db = SimpleNamespace(get=lambda model, key: None)
        self.assertFalse(CryptoDepositService.runtime_enabled(db))

    def test_runtime_setting_accepts_boolean_payload(self):
        db = SimpleNamespace(
            get=lambda model, key: SimpleNamespace(v_json={"enabled": True})
        )
        self.assertTrue(CryptoDepositService.runtime_enabled(db))

    def test_daily_count_limit_rejects_new_invoice(self):
        db = SimpleNamespace(
            execute=lambda statement: SimpleNamespace(one=lambda: (5, 1_000_000))
        )
        old_count = cfg.CRYPTO_DAILY_USER_MAX_COUNT
        old_total = cfg.CRYPTO_DAILY_USER_MAX_TOMAN
        cfg.CRYPTO_DAILY_USER_MAX_COUNT = 5
        cfg.CRYPTO_DAILY_USER_MAX_TOMAN = 100_000_000
        try:
            with self.assertRaises(HTTPException) as raised:
                CryptoDepositService._enforce_daily_user_limits(
                    db,
                    user_id=10,
                    requested_toman=100_000,
                )
        finally:
            cfg.CRYPTO_DAILY_USER_MAX_COUNT = old_count
            cfg.CRYPTO_DAILY_USER_MAX_TOMAN = old_total
        self.assertEqual(raised.exception.status_code, 429)

    def test_daily_amount_limit_rejects_projected_total(self):
        db = SimpleNamespace(
            execute=lambda statement: SimpleNamespace(one=lambda: (1, 900_000))
        )
        old_count = cfg.CRYPTO_DAILY_USER_MAX_COUNT
        old_total = cfg.CRYPTO_DAILY_USER_MAX_TOMAN
        cfg.CRYPTO_DAILY_USER_MAX_COUNT = 10
        cfg.CRYPTO_DAILY_USER_MAX_TOMAN = 1_000_000
        try:
            with self.assertRaises(HTTPException) as raised:
                CryptoDepositService._enforce_daily_user_limits(
                    db,
                    user_id=10,
                    requested_toman=200_000,
                )
        finally:
            cfg.CRYPTO_DAILY_USER_MAX_COUNT = old_count
            cfg.CRYPTO_DAILY_USER_MAX_TOMAN = old_total
        self.assertEqual(raised.exception.status_code, 429)

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

    def test_unconfirmed_transfer_moves_invoice_to_confirming_without_credit(self):
        invoice = SimpleNamespace(
            id=28,
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
            tx_hash="f" * 64,
            amount=Decimal("3.25"),
            sender_address="TSender",
            destination_address="TReceiver",
            occurred_at=datetime(2026, 6, 24, 12, 5, 0),
            confirmed=False,
            confirmations=0,
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
        ) as credit:
            result = CryptoDepositService.process_transfer(db, transfer)
        self.assertIs(result, invoice)
        self.assertEqual(invoice.status, "CONFIRMING")
        self.assertEqual(invoice.confirmation_count, 0)
        self.assertIsNotNone(invoice.detected_at)
        credit.assert_not_called()

    def test_user_can_cancel_only_untouched_waiting_invoice(self):
        invoice = SimpleNamespace(
            id=29,
            user_id=10,
            status="WAITING_PAYMENT",
            tx_hash=None,
            detected_at=None,
            active_user_id=10,
            cancelled_at=None,
            failure_reason=None,
            updated_at=None,
        )
        db = _SequenceSession([_FakeResult(scalar=invoice)])
        result = CryptoDepositService.cancel_owned(
            db,
            invoice_id=29,
            user_id=10,
        )
        self.assertIs(result, invoice)
        self.assertEqual(invoice.status, "CANCELLED")
        self.assertIsNone(invoice.active_user_id)
        self.assertIsNotNone(invoice.cancelled_at)

    def test_expired_confirming_invoice_releases_active_invoice_slot(self):
        invoice = SimpleNamespace(
            status="CONFIRMING",
            active_user_id=10,
            failure_reason=None,
            updated_at=None,
        )
        db = _SequenceSession([_FakeResult(rows=[invoice])])
        count = CryptoDepositService.expire_due(
            db,
            now=datetime(2026, 6, 24, 12, 30, 0),
        )
        self.assertEqual(count, 1)
        self.assertEqual(invoice.status, "EXPIRED")
        self.assertIsNone(invoice.active_user_id)

    def test_failed_wallet_event_reopens_direct_payment(self):
        invoice = SimpleNamespace(
            id=31,
            user_id=10,
            status="WAITING_PAYMENT",
            wallet_provider=None,
            wallet_account_address=None,
            payment_requested_at=datetime(2026, 6, 24, 12, 0, 0),
            updated_at=None,
        )
        db = _SequenceSession([_FakeResult(scalar=invoice)])
        result = CryptoDepositService.record_wallet_event(
            db,
            invoice_id=31,
            user_id=10,
            provider="TON_CONNECT",
            wallet_address=None,
            payment_requested=False,
            clear_payment_requested=True,
        )
        self.assertIs(result, invoice)
        self.assertIsNone(invoice.payment_requested_at)

    def test_payment_requested_invoice_cannot_be_cancelled(self):
        invoice = SimpleNamespace(
            id=32,
            user_id=10,
            status="WAITING_PAYMENT",
            tx_hash=None,
            detected_at=None,
            payment_requested_at=datetime(2026, 6, 24, 12, 0, 0),
        )
        db = _SequenceSession([_FakeResult(scalar=invoice)])
        with self.assertRaises(HTTPException) as raised:
            CryptoDepositService.cancel_owned(
                db,
                invoice_id=32,
                user_id=10,
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_existing_active_invoice_blocks_new_invoice(self):
        active = SimpleNamespace(id=30)
        db = _SequenceSession([_FakeResult(rows=[active])])
        with (
            patch.object(CryptoDepositService, "runtime_enabled", return_value=True),
            patch.object(CryptoDepositService, "_enforce_daily_user_limits"),
            patch.object(
                CryptoDepositService,
                "_network_spec",
                return_value={
                    "network": "TON",
                    "asset": "TON",
                    "address": "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c",
                    "decimals": 9,
                },
            ),
            patch.object(cfg, "CRYPTO_PAYMENTS_ENABLED", True),
        ):
            with self.assertRaises(HTTPException) as raised:
                CryptoDepositService.create_invoice(
                    db,
                    user_id=10,
                    amount_toman=500_000,
                    network="TON",
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_underpayment_is_sent_to_review(self):
        invoice = SimpleNamespace(
            id=26,
            user_id=10,
            network="TRON",
            asset="USDT",
            amount_toman=500_000,
            amount_crypto=Decimal("3.25"),
            paid_amount_crypto=None,
            memo=None,
            tx_hash="c" * 64,
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
            tx_hash="c" * 64,
            amount=Decimal("3.00"),
            sender_address="TSender",
            destination_address="TReceiver",
            occurred_at=datetime(2026, 6, 24, 12, 5, 0),
        )
        db = _SequenceSession(
            [
                _FakeResult(scalar=invoice),
                _FakeResult(scalar=invoice),
                _FakeResult(rows=[]),
                _FakeResult(scalar=invoice),
                _FakeResult(scalar=None),
            ]
        )
        result = CryptoDepositService.process_transfer(db, transfer)
        self.assertIs(result, invoice)
        self.assertEqual(invoice.status, "NEEDS_REVIEW")
        self.assertEqual(invoice.payment_variance, "UNDERPAID")
        self.assertEqual(invoice.variance_amount_crypto, Decimal("0.25"))

    def test_overpayment_requires_review_and_records_variance(self):
        invoice = SimpleNamespace(
            id=27,
            user_id=10,
            network="TRON",
            asset="USDT",
            amount_toman=500_000,
            amount_crypto=Decimal("3.25"),
            paid_amount_crypto=None,
            memo=None,
            tx_hash="e" * 64,
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
            tx_hash="e" * 64,
            amount=Decimal("3.50"),
            sender_address="TSender",
            destination_address="TReceiver",
            occurred_at=datetime(2026, 6, 24, 12, 5, 0),
        )
        db = _SequenceSession(
            [
                _FakeResult(scalar=invoice),
                _FakeResult(scalar=invoice),
                _FakeResult(rows=[]),
                _FakeResult(scalar=invoice),
                _FakeResult(scalar=None),
            ]
        )
        with patch(
            "app.services.crypto_deposit_service.WalletService.credit",
        ) as credit:
            result = CryptoDepositService.process_transfer(db, transfer)
        self.assertIs(result, invoice)
        self.assertEqual(invoice.status, "NEEDS_REVIEW")
        self.assertEqual(invoice.payment_variance, "OVERPAID")
        self.assertEqual(invoice.variance_amount_crypto, Decimal("0.25"))
        credit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
