"""No wrong-address crypto invoice match, even with equal amount or memo.

Uses in-memory query stubs, never a payment DB or blockchain.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
import unittest
import base64
from app.services.crypto_address_change import _crc16_xmodem

from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_deposit_service import CryptoDepositService


class _Result:
    def __init__(self, items):
        self.items = items

    def scalar_one_or_none(self):
        return self.items[0] if self.items else None

    def scalars(self):
        return self

    def all(self):
        return self.items


class _Db:
    def __init__(self, *responses):
        self.responses = list(responses)

    def execute(self, _stmt):
        return _Result(self.responses.pop(0))


class DestinationMatchIsolation(unittest.TestCase):
    def setUp(self):
        self.now = datetime.utcnow()
        self.transfer = ChainTransfer(
            network="TRON", asset="USDT", tx_hash="tx1",
            amount=Decimal("1.250000"), sender_address="sender",
            destination_address="NEW_DESTINATION", occurred_at=self.now,
        )

    def invoice(self, address, **kw):
        return SimpleNamespace(
            id=kw.get("id", 1),
            destination_address=address,
            created_at=self.now-timedelta(minutes=1),
            expires_at=self.now+timedelta(minutes=10),
            memo=kw.get("memo"),
        )

    def test_same_amount_cannot_credit_old_wallet_invoice(self):
        db = _Db([], [self.invoice("OLD_DESTINATION")])
        self.assertIsNone(CryptoDepositService._match_invoice(db, self.transfer))

    def test_correct_wallet_matches(self):
        inv = self.invoice("NEW_DESTINATION")
        self.assertIs(CryptoDepositService._match_invoice(_Db([], [inv]), self.transfer), inv)

    def test_claimed_hash_on_wrong_wallet_is_rejected(self):
        inv = self.invoice("OLD_DESTINATION")
        self.assertIsNone(CryptoDepositService._match_invoice(_Db([inv]), self.transfer))

    def test_ton_memo_on_wrong_wallet_is_rejected(self):
        transfer = ChainTransfer(
            network="TON", asset="TON", tx_hash="tx2",
            amount=Decimal("2"), sender_address="sender",
            destination_address="NEW_DESTINATION",
            occurred_at=self.now, memo="DAV-TEST",
        )
        inv = self.invoice("OLD_DESTINATION", memo="DAV-TEST")
        self.assertIsNone(CryptoDepositService._match_invoice(_Db([], [inv], []), transfer))

    def test_ton_memo_on_correct_wallet_matches(self):
        transfer = ChainTransfer(
            network="TON", asset="TON", tx_hash="tx3",
            amount=Decimal("2"), sender_address="sender",
            destination_address="NEW_DESTINATION",
            occurred_at=self.now, memo="DAV-TEST",
        )
        inv = self.invoice("NEW_DESTINATION", memo="DAV-TEST")
        self.assertIs(CryptoDepositService._match_invoice(_Db([], [inv]), transfer), inv)

    def test_ton_friendly_invoice_matches_raw_provider_without_rewriting_invoice(self):
        raw = bytes([0x51, 0]) + bytes.fromhex("ab" * 32)
        friendly = base64.urlsafe_b64encode(raw + _crc16_xmodem(raw).to_bytes(2, "big")).decode()
        inv = self.invoice(friendly, memo="DAV-ALIAS")
        transfer = ChainTransfer(network="TON", asset="TON", tx_hash="alias", amount=Decimal("2"),
            sender_address="sender", destination_address="0:" + "ab" * 32, occurred_at=self.now, memo="DAV-ALIAS")
        self.assertIs(CryptoDepositService._match_invoice(_Db([], [inv]), transfer), inv)
        self.assertEqual(inv.destination_address, friendly)
        self.assertFalse(CryptoDepositService._same_destination("TON", friendly, "0:" + "ac" * 32))
        self.assertFalse(CryptoDepositService._same_destination("TON", "", ""))


if __name__ == "__main__":
    unittest.main()
