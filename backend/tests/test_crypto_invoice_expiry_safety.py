"""Isolated expiry/late-payment safeguards for open crypto invoices.

No Production data or external provider calls.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.crypto import CryptoDepositRequest
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_chain_service import ChainTransfer
from app.core import config as cfg


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


class CryptoInvoiceExpirySafetyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        User.__table__.create(self.engine)
        CryptoDepositRequest.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add(User(id=91001, tg_user_id=91001))
        self.db.commit()
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def invoice(self, key, *, status="WAITING_PAYMENT", expires_at=None,
                tx_hash=None, detected_at=None, payment_requested_at=None):
        row = CryptoDepositRequest(
            public_id=f"fixture-{key}", user_id=91001, network="TON", asset="TON",
            amount_toman=50000, rate_toman_per_asset=Decimal("100000"),
            amount_crypto=Decimal("0.5"), rate_provider="synthetic",
            destination_address="not-a-live-wallet", status=status,
            expires_at=expires_at or (self.now - timedelta(hours=2)),
            tx_hash=tx_hash, detected_at=detected_at,
            payment_requested_at=payment_requested_at,
        )
        self.db.add(row)
        return row

    def test_only_unclaimed_unobserved_invoice_may_expire(self):
        unpaid = self.invoice("unpaid")
        confirming = self.invoice(
            "confirming", status="CONFIRMING", tx_hash="ton-confirming",
            detected_at=self.now - timedelta(hours=3),
        )
        claimed = self.invoice("claimed", tx_hash="ton-claimed")
        detected = self.invoice(
            "detected", detected_at=self.now - timedelta(hours=3),
        )
        wallet_requested = self.invoice(
            "wallet-requested", payment_requested_at=self.now - timedelta(hours=3),
        )
        future = self.invoice(
            "future", expires_at=self.now + timedelta(hours=1),
        )
        self.db.commit()
        expired_count = CryptoDepositService.expire_due(self.db, now=self.now)
        self.db.commit()
        self.assertEqual(expired_count, 1)
        self.assertEqual(unpaid.status, "EXPIRED")
        self.assertEqual(confirming.status, "CONFIRMING")
        self.assertEqual(claimed.status, "WAITING_PAYMENT")
        self.assertEqual(detected.status, "WAITING_PAYMENT")
        self.assertEqual(wallet_requested.status, "WAITING_PAYMENT")
        self.assertEqual(future.status, "WAITING_PAYMENT")
        self.assertEqual(CryptoDepositService.expire_due(self.db, now=self.now), 0)

    def test_transfer_in_window_after_restart_is_eligible(self):
        created = self.now - timedelta(days=3)
        expires = created + timedelta(minutes=15)
        invoice = SimpleNamespace(created_at=created, expires_at=expires)
        def transfer(at):
            return ChainTransfer(
                network="TON", asset="TON", tx_hash="synthetic-tx",
                amount=Decimal("0.5"), sender_address="synthetic-sender",
                destination_address="synthetic-destination", occurred_at=at,
            )
        grace = int(cfg.CRYPTO_PAYMENT_GRACE_MINUTES)
        self.assertTrue(CryptoDepositService._transfer_is_in_window(
            invoice, transfer(expires + timedelta(minutes=grace)),
        ))
        self.assertFalse(CryptoDepositService._transfer_is_in_window(
            invoice, transfer(expires + timedelta(minutes=grace, seconds=1)),
        ))
        self.assertFalse(CryptoDepositService._transfer_is_in_window(
            invoice, transfer(created - timedelta(seconds=1)),
        ))

    def test_restart_does_not_unexpire_or_credit_unmatched_late_payment(self):
        expired = self.invoice("already-expired", status="EXPIRED")
        self.db.commit()
        self.assertEqual(CryptoDepositService.expire_due(self.db, now=self.now), 0)
        self.assertEqual(expired.status, "EXPIRED")
        # Funds seen after expiry require a separate reconciliation/review
        # workflow; they must NOT silently credit another invoice.


if __name__ == "__main__":
    unittest.main()
