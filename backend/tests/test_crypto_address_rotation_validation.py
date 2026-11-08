"""Regression tests for the pure #30 address validators (no network/DB)."""
import base64
import hashlib
import unittest

from app.services.crypto_address_rotation_validation import (
    InvalidDepositAddress,
    _crc16_xmodem,
    masked_address,
    validate_deposit_address,
)


def tron_address(body: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    full = body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    value = int.from_bytes(full, "big")
    chars = ""
    while value:
        value, mod = divmod(value, 58)
        chars = alphabet[mod] + chars
    return "1" * (len(full) - len(full.lstrip(b"\\x00"))) + chars


def ton_address(*, tag: int = 0x11, workchain: int = 0, account: bytes = bytes(32)) -> str:
    payload = bytes([tag, workchain & 0xFF]) + account
    return base64.urlsafe_b64encode(payload + _crc16_xmodem(payload)).decode().rstrip("=")


class RotationAddressValidationTests(unittest.TestCase):
    def test_tron_accepts_base58check_mainnet(self):
        address = tron_address(b"\\x41" + bytes(range(20)))
        self.assertEqual(validate_deposit_address("TRON", address), address)

    def test_tron_rejects_bad_checksum(self):
        addr = tron_address(b"\\x41" + bytes(range(20)))
        with self.assertRaises(InvalidDepositAddress):
            validate_deposit_address("TRON", addr[:-1] + ("2" if addr[-1] != "2" else "3"))

    def test_tron_rejects_wrong_prefix(self):
        address = tron_address(b"\\xa0" + bytes(range(20)))
        with self.assertRaises(InvalidDepositAddress):
            validate_deposit_address("TRON", address)

    def test_ton_accepts_mainnet_friendly(self):
        address = ton_address(account=bytes(range(32)))
        self.assertEqual(validate_deposit_address("TON", address), address)

    def test_ton_normalizes_raw(self):
        raw = "0:" + bytes(range(32)).hex()
        self.assertEqual(validate_deposit_address("TON", raw), ton_address(account=bytes(range(32))))

    def test_ton_rejects_testnet_tag(self):
        with self.assertRaises(InvalidDepositAddress):
            validate_deposit_address("TON", ton_address(tag=0x91))

    def test_ton_rejects_corrupt_checksum(self):
        value = ton_address(account=bytes(range(32)))
        with self.assertRaises(InvalidDepositAddress):
            validate_deposit_address("TON", value[:-1] + ("A" if value[-1] != "A" else "B"))

    def test_ton_keeps_nonbounceable(self):
        address = ton_address(tag=0x51, workchain=-1)
        self.assertEqual(validate_deposit_address("TON", address), address)

    def test_rejects_whitespace_and_other_network(self):
        with self.assertRaises(InvalidDepositAddress):
            validate_deposit_address("TON", " " + ton_address())
        with self.assertRaises(InvalidDepositAddress):
            validate_deposit_address("ETH", "0x" + "0" * 40)

    def test_masks_without_exposing_full_destination(self):
        self.assertEqual(masked_address("1234567890123456"), "123456…123456")


if __name__ == "__main__":
    unittest.main()
