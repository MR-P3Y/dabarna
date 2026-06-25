from __future__ import annotations

import os
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.services.crypto_health_service import CryptoHealthService
from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_qr_service import CryptoQrService
from app.services.crypto_rate_service import CryptoRateQuote
from app.services.crypto_reconciliation_service import CryptoReconciliationService
from app.schemas.crypto import crypto_deposit_dict


class CryptoOperationsTests(unittest.TestCase):
    def test_crypto_payload_marks_utc_times_and_includes_server_clock(self):
        invoice = SimpleNamespace(
            id=1,
            public_id="DAV-1",
            user_id=2,
            network="TRON",
            asset="USDT",
            amount_toman=100_000,
            rate_toman_per_asset=Decimal("90000"),
            amount_crypto=Decimal("1.1"),
            paid_amount_crypto=None,
            rate_provider="nobitex",
            destination_address="TAddress",
            memo=None,
            tx_hash=None,
            status="WAITING_PAYMENT",
            wallet_tx_id=None,
            failure_reason=None,
            payment_variance=None,
            variance_amount_crypto=None,
            expires_at=datetime(2026, 6, 24, 12, 15, 0),
            detected_at=None,
            credited_at=None,
            created_at=datetime(2026, 6, 24, 12, 0, 0),
        )
        payload = crypto_deposit_dict(invoice)
        self.assertTrue(payload["created_at"].endswith("Z"))
        self.assertTrue(payload["expires_at"].endswith("Z"))
        self.assertTrue(payload["server_now"].endswith("Z"))

    def test_qr_png_is_generated_for_ton_payment_uri(self):
        invoice = SimpleNamespace(
            network="TON",
            destination_address="EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c",
            amount_crypto=Decimal("2.5"),
            memo="DAV-TEST",
        )
        payload = CryptoQrService.png_bytes(invoice)
        self.assertTrue(payload.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(payload), 200)

    def test_health_is_ok_when_rate_and_chain_providers_respond(self):
        quote = CryptoRateQuote(
            asset="USDT",
            rate_toman=Decimal("90000"),
            provider="nobitex",
            fetched_at=datetime(2026, 6, 24, 12, 0, 0),
        )
        with (
            patch(
                "app.services.crypto_health_service.CryptoDepositService.configured_options",
                return_value=[
                    {
                        "network": "TRON",
                        "asset": "USDT",
                        "address": "TAddress",
                        "decimals": 6,
                    }
                ],
            ),
            patch(
                "app.services.crypto_health_service.CryptoRateService._fetch",
                return_value=quote,
            ),
            patch(
                "app.services.crypto_health_service.CryptoChainService.list_incoming",
                return_value=[],
            ),
            patch("app.services.crypto_health_service.cfg.CRYPTO_PAYMENTS_ENABLED", True),
        ):
            out = CryptoHealthService.check()
        self.assertTrue(out["ok"])
        self.assertTrue(out["rates_ok"])
        self.assertTrue(out["chains_ok"])

    def test_health_is_degraded_but_available_when_fallback_rate_works(self):
        quote = CryptoRateQuote(
            asset="USDT",
            rate_toman=Decimal("90000"),
            provider="wallex",
            fetched_at=datetime(2026, 6, 24, 12, 0, 0),
        )
        with (
            patch(
                "app.services.crypto_health_service.CryptoDepositService.configured_options",
                return_value=[
                    {
                        "network": "TRON",
                        "asset": "USDT",
                        "address": "TAddress",
                        "decimals": 6,
                    }
                ],
            ),
            patch(
                "app.services.crypto_health_service.CryptoRateService._fetch",
                side_effect=[RuntimeError("primary down"), quote],
            ),
            patch(
                "app.services.crypto_health_service.CryptoChainService.list_incoming",
                return_value=[],
            ),
            patch("app.services.crypto_health_service.cfg.CRYPTO_PAYMENTS_ENABLED", True),
            patch("app.services.crypto_health_service.cfg.CRYPTO_RATE_PROVIDER_PRIMARY", "nobitex"),
            patch("app.services.crypto_health_service.cfg.CRYPTO_RATE_PROVIDER_FALLBACK", "wallex"),
        ):
            out = CryptoHealthService.check()
        self.assertTrue(out["ok"])
        self.assertTrue(out["degraded"])
        self.assertTrue(out["rates_ok"])

    def test_reconciliation_detects_unmatched_chain_transfer(self):
        transfer = ChainTransfer(
            network="TRON",
            asset="USDT",
            tx_hash="d" * 64,
            amount=Decimal("5"),
            sender_address="TSender",
            destination_address="TReceiver",
            occurred_at=datetime(2026, 6, 24, 12, 0, 0),
        )
        db = SimpleNamespace(
            execute=lambda statement: SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [])
            ),
            get=lambda model, key: None,
        )
        with (
            patch(
                "app.services.crypto_reconciliation_service.CryptoDepositService.configured_options",
                return_value=[
                    {
                        "network": "TRON",
                        "asset": "USDT",
                        "address": "TAddress",
                        "decimals": 6,
                    }
                ],
            ),
            patch(
                "app.services.crypto_reconciliation_service.CryptoChainService.list_incoming",
                return_value=[transfer],
            ),
        ):
            out = CryptoReconciliationService.run(
                db,
                start_at=datetime(2026, 6, 24, 0, 0, 0),
                end_at=datetime(2026, 6, 24, 23, 59, 59),
            )
        self.assertFalse(out["ok"])
        self.assertEqual(out["unmatched_onchain_count"], 1)
        self.assertEqual(out["unmatched_onchain"][0]["tx_hash"], "d" * 64)


if __name__ == "__main__":
    unittest.main()
