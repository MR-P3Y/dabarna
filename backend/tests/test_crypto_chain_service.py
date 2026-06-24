import os
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core import config as cfg
from app.services.crypto_chain_service import CryptoChainService


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return _FakeResponse(self.payload)


class CryptoChainServiceTests(unittest.TestCase):
    def test_tron_parser_accepts_confirmed_usdt_transfer(self):
        old_address = cfg.CRYPTO_TRON_USDT_ADDRESS
        cfg.CRYPTO_TRON_USDT_ADDRESS = "TReceiver"
        payload = {
            "success": True,
            "data": [
                {
                    "transaction_id": "a" * 64,
                    "token_info": {
                        "address": cfg.CRYPTO_TRON_USDT_CONTRACT,
                        "decimals": 6,
                    },
                    "block_timestamp": 1_800_000_000_000,
                    "from": "TSender",
                    "to": "TReceiver",
                    "value": "12500000",
                }
            ],
        }
        try:
            with patch.object(CryptoChainService, "_client", return_value=_FakeClient(payload)):
                transfers = CryptoChainService._list_tron_usdt(since=datetime(2026, 1, 1))
        finally:
            cfg.CRYPTO_TRON_USDT_ADDRESS = old_address
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0].amount, Decimal("12.5"))
        self.assertEqual(transfers[0].asset, "USDT")

    def test_ton_parser_rejects_aborted_and_accepts_finalized(self):
        old_address = cfg.CRYPTO_TON_ADDRESS
        cfg.CRYPTO_TON_ADDRESS = "EQReceiver"
        payload = {
            "transactions": [
                {
                    "hash": "valid_hash_12345678901234567890",
                    "now": 1_800_000_000,
                    "finality": "finalized",
                    "description": {"aborted": False},
                    "in_msg": {
                        "source": "0:sender",
                        "value": "2500000000",
                        "message_content": {"decoded": {"comment": "DAV-ABC"}},
                    },
                },
                {
                    "hash": "aborted_hash_123456789012345678",
                    "now": 1_800_000_000,
                    "finality": "finalized",
                    "description": {"aborted": True},
                    "in_msg": {"source": "0:sender", "value": "999000000000"},
                },
            ]
        }
        try:
            with patch.object(CryptoChainService, "_client", return_value=_FakeClient(payload)):
                transfers = CryptoChainService._list_ton(since=datetime(2026, 1, 1))
        finally:
            cfg.CRYPTO_TON_ADDRESS = old_address
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0].amount, Decimal("2.5"))
        self.assertEqual(transfers[0].memo, "DAV-ABC")


if __name__ == "__main__":
    unittest.main()
