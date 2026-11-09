"""Offline contracts for simultaneous old/new invoice destination scanning (#30)."""
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_chain_service import ChainTransfer, CryptoChainService
from app.services.crypto_deposit_service import CryptoDepositService


def ton_addr(seed: int) -> str:
    import base64
    body = bytes([0x11, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(body + _crc16_xmodem(body)).decode().rstrip("=")


def tx(address: str, hash_value: str) -> ChainTransfer:
    return ChainTransfer(
        network="TON", asset="TON", tx_hash=hash_value, amount=Decimal("1"),
        sender_address=None, destination_address=address,
        occurred_at=datetime(2026, 11, 8),
    )


class CryptoMultiAddressScanTests(unittest.TestCase):
    def test_old_and_new_addresses_both_scanned(self):
        old, new = ton_addr(1), ton_addr(2)
        seen = []

        def fake_list(*, network, since, include_pending, destination_address):
            seen.append(destination_address)
            return [tx(destination_address, "tx-" + destination_address[:8])]

        with patch.object(CryptoChainService, "list_incoming", side_effect=fake_list):
            result = CryptoChainService.list_incoming_for_addresses(
                network="TON", addresses=[new, old, new],
                since=datetime(2026, 11, 8),
            )
        self.assertEqual(sorted(seen), sorted([old, new]))
        self.assertEqual({x.destination_address for x in result}, {old, new})

    def test_scanner_failure_never_returns_partial_success(self):
        old, new = ton_addr(1), ton_addr(2)
        def fake_list(*, network, since, include_pending, destination_address):
            if destination_address == new:
                raise RuntimeError("provider unavailable")
            return [tx(old, "tx-old")]
        with patch.object(CryptoChainService, "list_incoming", side_effect=fake_list):
            with self.assertRaises(RuntimeError):
                CryptoChainService.list_incoming_for_addresses(
                    network="TON", addresses=[old, new], since=datetime(2026, 11, 8),
                )

    def test_invoice_cannot_be_credited_from_another_destination(self):
        old, new = ton_addr(1), ton_addr(2)
        invoice = SimpleNamespace(network="TON", destination_address=old)
        self.assertFalse(CryptoDepositService._transfer_matches_invoice_destination(invoice, tx(new, "tx2")))
        self.assertTrue(CryptoDepositService._transfer_matches_invoice_destination(invoice, tx(old, "tx1")))

    def test_bounceable_and_nonbounceable_ton_are_same_destination(self):
        import base64
        old = ton_addr(1)
        friendly_payload = bytes([0x51, 0]) + bytes([1] * 32)
        nonbounceable = base64.urlsafe_b64encode(
            friendly_payload + _crc16_xmodem(friendly_payload)
        ).decode().rstrip("=")
        invoice = SimpleNamespace(network="TON", destination_address=old)
        self.assertTrue(
            CryptoDepositService._transfer_matches_invoice_destination(
                invoice, tx(nonbounceable, "tx-friendly-alias"),
            )
        )
        self.assertFalse(
            CryptoDepositService._transfer_matches_invoice_destination(
                invoice, tx(ton_addr(2), "tx-other-account"),
            )
        )

    def test_raw_and_friendly_ton_are_same_destination(self):
        old = ton_addr(1)
        invoice = SimpleNamespace(network="TON", destination_address="0:" + bytes([1] * 32).hex())
        self.assertTrue(CryptoDepositService._transfer_matches_invoice_destination(invoice, tx(old, "tx1")))


if __name__ == "__main__":
    unittest.main()
