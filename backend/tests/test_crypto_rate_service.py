import os
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.core import config as cfg
from app.services.crypto_rate_service import CryptoRateService


class CryptoRateServiceTests(unittest.TestCase):
    def setUp(self):
        CryptoRateService._last_good.clear()

    def test_wallex_uses_best_ask_in_toman(self):
        with patch.object(
            CryptoRateService,
            "_http_get",
            return_value={"result": {"ask": [{"price": 164_500}, {"price": 164_600}]}},
        ):
            rate = CryptoRateService._fetch_wallex("USDT")
        self.assertEqual(rate, Decimal("164500"))

    def test_nobitex_converts_irr_to_toman(self):
        with patch.object(
            CryptoRateService,
            "_http_get",
            return_value={"status": "ok", "asks": [["1645000", "1"]]},
        ):
            rate = CryptoRateService._fetch_nobitex("USDT")
        self.assertEqual(rate, Decimal("164500"))

    def test_fallback_provider_is_used(self):
        original_primary = cfg.CRYPTO_RATE_PROVIDER_PRIMARY
        original_fallback = cfg.CRYPTO_RATE_PROVIDER_FALLBACK
        cfg.CRYPTO_RATE_PROVIDER_PRIMARY = "nobitex"
        cfg.CRYPTO_RATE_PROVIDER_FALLBACK = "wallex"
        try:
            with patch.object(
                CryptoRateService,
                "_fetch",
                side_effect=[RuntimeError("primary down"), DecimalQuoteFactory.wallex_usdt()],
            ):
                quote = CryptoRateService.get_live_quote("USDT")
        finally:
            cfg.CRYPTO_RATE_PROVIDER_PRIMARY = original_primary
            cfg.CRYPTO_RATE_PROVIDER_FALLBACK = original_fallback
        self.assertEqual(quote.provider, "wallex")
        self.assertEqual(quote.rate_toman, Decimal("164500"))


class DecimalQuoteFactory:
    @staticmethod
    def wallex_usdt():
        from app.services.crypto_rate_service import CryptoRateQuote
        from datetime import datetime, timezone

        return CryptoRateQuote(
            asset="USDT",
            rate_toman=Decimal("164500"),
            provider="wallex",
            fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )


if __name__ == "__main__":
    unittest.main()
