from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx

from app.core import config as cfg

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CryptoRateUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CryptoRateQuote:
    asset: str
    rate_toman: Decimal
    provider: str
    fetched_at: datetime
    is_stale: bool = False


class CryptoRateService:
    _last_good: dict[str, CryptoRateQuote] = {}
    _lock = threading.Lock()

    @classmethod
    def get_live_quote(cls, asset: str) -> CryptoRateQuote:
        normalized_asset = str(asset or "").strip().upper()
        if normalized_asset not in ("USDT", "TON"):
            raise CryptoRateUnavailable("ارز درخواستی برای نرخ‌گیری پشتیبانی نمی‌شود.")

        providers: list[str] = []
        for provider in (cfg.CRYPTO_RATE_PROVIDER_PRIMARY, cfg.CRYPTO_RATE_PROVIDER_FALLBACK):
            name = str(provider or "").strip().lower()
            if name and name not in providers:
                providers.append(name)

        errors: list[str] = []
        for provider in providers:
            try:
                quote = cls._fetch(provider=provider, asset=normalized_asset)
                cls._validate_against_recent(quote)
                with cls._lock:
                    cls._last_good[normalized_asset] = quote
                return quote
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                log.warning("crypto rate provider failed: provider=%s asset=%s error=%s", provider, normalized_asset, exc)

        stale = cls._allowed_stale_quote(normalized_asset)
        if stale is not None:
            log.warning(
                "using stale crypto rate: asset=%s provider=%s age_sec=%s",
                normalized_asset,
                stale.provider,
                int((_utcnow() - stale.fetched_at).total_seconds()),
            )
            return stale

        detail = "; ".join(errors) if errors else "no rate provider configured"
        raise CryptoRateUnavailable(f"دریافت نرخ لحظه‌ای ممکن نشد: {detail}")

    @classmethod
    def _fetch(cls, *, provider: str, asset: str) -> CryptoRateQuote:
        if provider == "nobitex":
            rate = cls._fetch_nobitex(asset)
        elif provider == "wallex":
            rate = cls._fetch_wallex(asset)
        else:
            raise CryptoRateUnavailable(f"rate provider is not supported: {provider}")
        if rate <= 0:
            raise CryptoRateUnavailable("provider returned a non-positive rate")
        return CryptoRateQuote(
            asset=asset,
            rate_toman=rate,
            provider=provider,
            fetched_at=_utcnow(),
        )

    @staticmethod
    def _http_get(url: str, *, params: dict[str, object] | None = None) -> dict:
        headers = {"Accept": "application/json", "User-Agent": "Davarna/1.0"}
        with httpx.Client(timeout=float(cfg.CRYPTO_HTTP_TIMEOUT_SEC), follow_redirects=True) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise CryptoRateUnavailable("provider returned an invalid response")
        return data

    @classmethod
    def _fetch_nobitex(cls, asset: str) -> Decimal:
        symbol = {"USDT": "USDTIRT", "TON": "TONIRT"}[asset]
        data = cls._http_get(f"{cfg.CRYPTO_NOBITEX_BASE_URL}/v3/orderbook/{symbol}")
        if str(data.get("status") or "").lower() != "ok":
            raise CryptoRateUnavailable(str(data.get("message") or "nobitex response is not ok"))
        asks = data.get("asks")
        if not isinstance(asks, list) or not asks:
            raise CryptoRateUnavailable("nobitex order book has no asks")
        try:
            price_irr = Decimal(str(asks[0][0]))
        except (InvalidOperation, IndexError, TypeError):
            raise CryptoRateUnavailable("nobitex ask price is invalid")
        return price_irr / Decimal("10")

    @classmethod
    def _fetch_wallex(cls, asset: str) -> Decimal:
        symbol = {"USDT": "USDTTMN", "TON": "TONTMN"}[asset]
        data = cls._http_get(f"{cfg.CRYPTO_WALLEX_BASE_URL}/v1/depth", params={"symbol": symbol})
        result = data.get("result")
        asks = result.get("ask") if isinstance(result, dict) else None
        if not isinstance(asks, list) or not asks:
            raise CryptoRateUnavailable("wallex order book has no asks")
        try:
            return Decimal(str(asks[0]["price"]))
        except (InvalidOperation, KeyError, TypeError):
            raise CryptoRateUnavailable("wallex ask price is invalid")

    @classmethod
    def _validate_against_recent(cls, quote: CryptoRateQuote) -> None:
        with cls._lock:
            previous = cls._last_good.get(quote.asset)
        if previous is None or previous.rate_toman <= 0:
            return
        age_sec = (_utcnow() - previous.fetched_at).total_seconds()
        if age_sec > 300:
            return
        deviation = abs(quote.rate_toman - previous.rate_toman) * Decimal("100") / previous.rate_toman
        if deviation > cfg.CRYPTO_RATE_MAX_DEVIATION_PERCENT:
            raise CryptoRateUnavailable(
                f"rate deviation {deviation:.2f}% exceeds allowed limit "
                f"{cfg.CRYPTO_RATE_MAX_DEVIATION_PERCENT}%"
            )

    @classmethod
    def _allowed_stale_quote(cls, asset: str) -> CryptoRateQuote | None:
        max_age = int(cfg.CRYPTO_RATE_FAIL_ALLOW_STALE_SEC)
        if max_age <= 0:
            return None
        with cls._lock:
            quote = cls._last_good.get(asset)
        if quote is None:
            return None
        age_sec = (_utcnow() - quote.fetched_at).total_seconds()
        if age_sec > max_age:
            return None
        return CryptoRateQuote(
            asset=quote.asset,
            rate_toman=quote.rate_toman,
            provider=quote.provider,
            fetched_at=quote.fetched_at,
            is_stale=True,
        )
