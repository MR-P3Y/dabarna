"""Guard against duplicate credit and automatic settlement of closed invoices.

No external network or persistent database access.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.wallet_service import WalletService


class _Result:
    def __init__(self, item=None, rows=None):
        self.item = item
        self.rows = rows if rows is not None else ([] if item is None else [item])

    def scalar_one_or_none(self):
        return self.item

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _SequenceDb:
    def __init__(self, responses):
        self.responses = list(responses)

    def execute(self, stmt):
        if not self.responses:
            raise AssertionError("unexpected SQL query")
        return _Result(**self.responses.pop(0))

    def flush(self):
        raise AssertionError("should not mutate invoice")


class LateTransferAndReplayGuards(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.now = now
        self.transfer = ChainTransfer(
            network="TRON", asset="USDT", tx_hash="tx-replay",
            amount=Decimal("1.25"), sender_address="sender",
            destination_address="OLD", occurred_at=now, confirmed=True,
        )

    def test_already_credited_hash_never_recredits(self):
        invoice = SimpleNamespace(status="CREDITED", tx_hash="tx-replay")
        db = _SequenceDb([{"item": invoice}])
        with patch("app.services.crypto_deposit_service.WalletService.credit") as credit:
            result = CryptoDepositService.process_transfer(db, self.transfer)
        self.assertIsNone(result)
        credit.assert_not_called()

    def test_already_rejected_hash_never_recredits(self):
        invoice = SimpleNamespace(status="REJECTED", tx_hash="tx-replay")
        db = _SequenceDb([{"item": invoice}])
        with patch("app.services.crypto_deposit_service.WalletService.credit") as credit:
            self.assertIsNone(CryptoDepositService.process_transfer(db, self.transfer))
        credit.assert_not_called()

    def test_expired_invoice_is_not_a_candidate_for_auto_matching(self):
        expired = SimpleNamespace(
            id=42, status="EXPIRED", network="TRON", asset="USDT",
            tx_hash=None, destination_address="OLD",
            amount_crypto=Decimal("1.25"), created_at=self.now-timedelta(minutes=30),
            expires_at=self.now-timedelta(minutes=20), memo=None,
        )
        db = _SequenceDb([
            {"item": None},  # existing tx
            {"item": None},  # claimed open tx
            {"rows": []},    # open amount candidates: expired invoice absent
        ])
        with patch("app.services.crypto_deposit_service.WalletService.credit") as credit:
            self.assertIsNone(CryptoDepositService.process_transfer(db, self.transfer))
        credit.assert_not_called()
        self.assertEqual(len(db.responses), 0)
        # This test intentionally models the DB filtering EXPIRED from OPEN_STATUSES.
        # A separate manual reconciliation workflow must detect late transfers.

    def test_wallet_idempotency_replay_conflict_fails_closed(self):
        existing = SimpleNamespace(
            direction="CREDIT", amount=200000, reason="DEPOSIT_CRYPTO",
            ref_type="CRYPTO_DEPOSIT", ref_id=42,
        )
        WalletService.validate_replay(
            existing, direction="CREDIT", amount=200000,
            reason="DEPOSIT_CRYPTO", ref_type="CRYPTO_DEPOSIT", ref_id=42,
        )
        for changed in [
            dict(amount=200001, ref_id=42),
            dict(amount=200000, ref_id=43),
        ]:
            with self.assertRaises(HTTPException) as cm:
                WalletService.validate_replay(
                    existing, direction="CREDIT", amount=changed["amount"],
                    reason="DEPOSIT_CRYPTO", ref_type="CRYPTO_DEPOSIT",
                    ref_id=changed["ref_id"],
                )
            self.assertEqual(cm.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
