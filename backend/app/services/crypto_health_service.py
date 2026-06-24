from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import config as cfg
from app.services.crypto_chain_service import CryptoChainService
from app.services.crypto_deposit_service import CryptoDepositService
from app.services.crypto_rate_service import CryptoRateService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CryptoHealthService:
    @staticmethod
    def check() -> dict[str, Any]:
        options = CryptoDepositService.configured_options()
        assets = sorted({str(item["asset"]) for item in options})
        networks = sorted({str(item["network"]) for item in options})

        rate_checks: list[dict[str, Any]] = []
        asset_healthy: dict[str, bool] = {asset: False for asset in assets}
        providers: list[str] = []
        for raw in (cfg.CRYPTO_RATE_PROVIDER_PRIMARY, cfg.CRYPTO_RATE_PROVIDER_FALLBACK):
            provider = str(raw or "").strip().lower()
            if provider and provider not in providers:
                providers.append(provider)

        for asset in assets:
            for provider in providers:
                started = time.perf_counter()
                try:
                    quote = CryptoRateService._fetch(provider=provider, asset=asset)
                    elapsed = int((time.perf_counter() - started) * 1000)
                    rate_checks.append(
                        {
                            "provider": provider,
                            "asset": asset,
                            "ok": True,
                            "latency_ms": elapsed,
                            "rate_toman": str(quote.rate_toman),
                        }
                    )
                    asset_healthy[asset] = True
                except Exception as exc:
                    elapsed = int((time.perf_counter() - started) * 1000)
                    rate_checks.append(
                        {
                            "provider": provider,
                            "asset": asset,
                            "ok": False,
                            "latency_ms": elapsed,
                            "error": CryptoHealthService._error_text(exc),
                        }
                    )

        chain_checks: list[dict[str, Any]] = []
        since = _utcnow() - timedelta(minutes=5)
        for network in networks:
            started = time.perf_counter()
            try:
                transfers = CryptoChainService.list_incoming(network=network, since=since)
                chain_checks.append(
                    {
                        "network": network,
                        "ok": True,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "recent_transfers": len(transfers),
                    }
                )
            except Exception as exc:
                chain_checks.append(
                    {
                        "network": network,
                        "ok": False,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "error": CryptoHealthService._error_text(exc),
                    }
                )

        rates_ok = bool(assets) and all(asset_healthy.values())
        chains_ok = bool(networks) and all(bool(item["ok"]) for item in chain_checks)
        degraded = any(not bool(item["ok"]) for item in rate_checks + chain_checks)
        return {
            "checked_at": _utcnow().isoformat(),
            "enabled": bool(cfg.CRYPTO_PAYMENTS_ENABLED),
            "configured": bool(options),
            "ok": bool(rates_ok and chains_ok),
            "degraded": degraded,
            "rates_ok": rates_ok,
            "chains_ok": chains_ok,
            "rate_checks": rate_checks,
            "chain_checks": chain_checks,
        }

    @staticmethod
    def _error_text(exc: Exception) -> str:
        text = str(exc or exc.__class__.__name__).strip()
        return text[:240] if text else exc.__class__.__name__
