from __future__ import annotations

import threading
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import config as cfg
from app.services.crypto_chain_service import CryptoChainService
from app.services.crypto_rate_service import CryptoRateQuote, CryptoRateService

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CryptoPreflightService:
    _cache: dict[str, tuple[float, dict[str, Any]]] = {}
    _lock = threading.Lock()

    @classmethod
    def check(
        cls,
        spec: dict[str, object],
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        network = str(spec["network"]).upper()
        now_mono = time.monotonic()
        if use_cache:
            with cls._lock:
                cached = cls._cache.get(network)
            if cached and (now_mono - cached[0]) <= int(cfg.CRYPTO_PREFLIGHT_CACHE_SEC):
                return dict(cached[1])

        checked_at = _utcnow()
        try:
            quote = CryptoRateService.get_live_quote(str(spec["asset"]))
        except Exception as exc:
            log.warning(
                "crypto preflight rate failed: network=%s asset=%s error=%s",
                network,
                spec.get("asset"),
                exc,
            )
            result = cls._failure(
                network,
                checked_at,
                "نرخ لحظه‌ای این شبکه موقتاً در دسترس نیست.",
            )
            cls._remember(network, result)
            return result

        try:
            CryptoChainService.list_incoming(
                network=network,
                since=checked_at - timedelta(minutes=2),
                include_pending=False,
            )
        except Exception as exc:
            log.warning(
                "crypto preflight chain failed: network=%s error=%s",
                network,
                exc,
            )
            result = cls._failure(
                network,
                checked_at,
                "ارتباط با شبکه موقتاً پایدار نیست. چند لحظه دیگر دوباره تلاش کنید.",
                quote=quote,
            )
            cls._remember(network, result)
            return result

        fee_value, fee_asset = cls.estimated_fee(network)
        result = {
            "network": network,
            "healthy": True,
            "reason": None,
            "checked_at": checked_at,
            "quote": quote,
            "estimated_network_fee": fee_value,
            "estimated_network_fee_asset": fee_asset,
        }
        cls._remember(network, result)
        return dict(result)

    @staticmethod
    def estimated_fee(network: str) -> tuple[object, str]:
        if str(network).upper() == "TRON":
            return cfg.CRYPTO_TRON_ESTIMATED_FEE_TRX, "TRX"
        return cfg.CRYPTO_TON_ESTIMATED_FEE_TON, "TON"

    @classmethod
    def _remember(cls, network: str, result: dict[str, Any]) -> None:
        with cls._lock:
            cls._cache[network] = (time.monotonic(), dict(result))

    @staticmethod
    def _failure(
        network: str,
        checked_at: datetime,
        reason: str,
        *,
        quote: CryptoRateQuote | None = None,
    ) -> dict[str, Any]:
        fee_value, fee_asset = CryptoPreflightService.estimated_fee(network)
        return {
            "network": network,
            "healthy": False,
            "reason": reason,
            "checked_at": checked_at,
            "quote": quote,
            "estimated_network_fee": fee_value,
            "estimated_network_fee_asset": fee_asset,
        }
