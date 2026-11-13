from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core import config as cfg
from app.services.crypto_address_change import same_crypto_destination

log = logging.getLogger(__name__)


class CryptoChainUnavailable(RuntimeError):
    pass


def _utc_timestamp(value: datetime) -> float:
    # Stored naive datetimes are UTC, including on Windows test workstations.
    return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()


@dataclass(frozen=True)
class ChainTransfer:
    network: str
    asset: str
    tx_hash: str
    amount: Decimal
    sender_address: str | None
    destination_address: str
    occurred_at: datetime
    memo: str | None = None
    confirmed: bool = True
    confirmations: int = 1


class CryptoChainService:
    @classmethod
    def list_incoming(
        cls,
        *,
        network: str,
        since: datetime,
        include_pending: bool = True,
        destination_address: str | None = None,
        until: datetime | None = None,
        strict: bool = False,
    ) -> list[ChainTransfer]:
        normalized = str(network or "").strip().upper()
        if until is not None and _utc_timestamp(until) < _utc_timestamp(since):
            raise CryptoChainUnavailable("Invalid scan interval")
        extra = {"until": until, "strict": strict}
        if normalized == "TRON":
            return cls._list_tron_usdt(since=since, include_pending=include_pending, destination_address=destination_address, **extra)
        if normalized == "TON":
            return cls._list_ton(since=since, include_pending=include_pending, destination_address=destination_address, **extra)
        raise CryptoChainUnavailable(f"unsupported crypto network: {normalized}")

    @staticmethod
    def _client() -> httpx.Client:
        return httpx.Client(
            timeout=float(cfg.CRYPTO_HTTP_TIMEOUT_SEC),
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "Davarna/1.0"},
        )

    @classmethod
    def _list_tron_usdt(
        cls,
        *,
        since: datetime,
        include_pending: bool = True,
        destination_address: str | None = None,
        until: datetime | None = None,
        strict: bool = False,
    ) -> list[ChainTransfer]:
        address = str(destination_address if destination_address is not None else cfg.CRYPTO_TRON_USDT_ADDRESS).strip()
        if not address:
            return []
        headers: dict[str, str] = {}
        if cfg.TRONGRID_API_KEY:
            headers["TRON-PRO-API-KEY"] = cfg.TRONGRID_API_KEY
        base_params: dict[str, object] = {
            "only_to": "true",
            "limit": 200,
            "contract_address": cfg.CRYPTO_TRON_USDT_CONTRACT,
            "min_timestamp": int(_utc_timestamp(since) * 1000),
            "order_by": "block_timestamp,desc",
        }
        if until is not None:
            base_params["max_timestamp"] = int(_utc_timestamp(until) * 1000)
        url = (
            f"{cfg.CRYPTO_TRONGRID_BASE_URL}/v1/accounts/"
            f"{address}/transactions/trc20"
        )
        def fetch_pages(client: httpx.Client, *, confirmed_only: bool) -> list[dict[str, Any]]:
            # TronGrid fingerprint must retain the exact same query filters.
            params = dict(base_params, only_confirmed="true" if confirmed_only else "false")
            fingerprint: str | None = None
            visited: set[str] = set()
            collected: list[dict[str, Any]] = []
            for _ in range(20):
                query = dict(params)
                if fingerprint:
                    query["fingerprint"] = fingerprint
                response = client.get(url, params=query, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("success") is False or not isinstance(payload.get("data"), list):
                    raise CryptoChainUnavailable("TronGrid returned invalid paginated data")
                if strict and any(not isinstance(row, dict) for row in payload["data"]):
                    raise CryptoChainUnavailable("TronGrid malformed transaction row")
                collected.extend(row for row in payload["data"] if isinstance(row, dict))
                meta = payload.get("meta")
                next_fingerprint = meta.get("fingerprint") if isinstance(meta, dict) else None
                if not next_fingerprint:
                    if len(payload["data"]) >= 200:
                        raise CryptoChainUnavailable("TronGrid full page without continuation token")
                    return collected
                if not isinstance(next_fingerprint, str) or next_fingerprint in visited:
                    raise CryptoChainUnavailable("TronGrid pagination cursor repeated or invalid")
                visited.add(next_fingerprint)
                fingerprint = next_fingerprint
            raise CryptoChainUnavailable("TronGrid pagination exceeded bounded scan; manual backfill required")

        with cls._client() as client:
            rows = fetch_pages(client, confirmed_only=not include_pending)
            confirmed_hashes: set[str] = set()
            if include_pending:
                confirmed_hashes = {
                    str(item.get("transaction_id") or "").strip()
                    for item in fetch_pages(client, confirmed_only=True)
                }

        out: list[ChainTransfer] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            token_info = row.get("token_info") if isinstance(row.get("token_info"), dict) else {}
            if strict and row.get("type") in {"Approval", "Approve"}:
                continue
            if str(token_info.get("address") or "") != cfg.CRYPTO_TRON_USDT_CONTRACT:
                if strict:
                    raise CryptoChainUnavailable("TronGrid unexpected token")
                continue
            if str(row.get("to") or "") != address:
                if strict:
                    raise CryptoChainUnavailable("TronGrid unexpected recipient")
                continue
            try:
                decimals = int(token_info.get("decimals") or 6)
                if strict and (token_info.get("decimals") not in (6, "6") or isinstance(token_info.get("decimals"), bool)):
                    raise ValueError("Unexpected USDT decimals")
                amount = Decimal(str(row.get("value"))) / (Decimal("10") ** decimals)
                occurred_at = datetime.fromtimestamp(
                    int(row.get("block_timestamp")) / 1000,
                    timezone.utc,
                ).replace(tzinfo=None)
            except (InvalidOperation, TypeError, ValueError, OverflowError):
                if strict:
                    raise CryptoChainUnavailable("TronGrid invalid transfer value or timestamp") from None
                continue
            tx_hash = str(row.get("transaction_id") or "").strip()
            if strict and (not tx_hash or not amount.is_finite() or amount <= 0
                           or _utc_timestamp(occurred_at) < _utc_timestamp(since)
                           or (until is not None and _utc_timestamp(occurred_at) > _utc_timestamp(until))):
                raise CryptoChainUnavailable("TronGrid incomplete or out-of-window transfer")
            if not tx_hash or amount <= 0:
                continue
            confirmed = not include_pending or tx_hash in confirmed_hashes
            out.append(
                ChainTransfer(
                    network="TRON",
                    asset="USDT",
                    tx_hash=tx_hash,
                    amount=amount,
                    sender_address=str(row.get("from") or "").strip() or None,
                    destination_address=address,
                    occurred_at=occurred_at,
                    confirmed=confirmed,
                    confirmations=1 if confirmed else 0,
                )
            )
        return out

    @classmethod
    def _list_ton(
        cls,
        *,
        since: datetime,
        include_pending: bool = True,
        destination_address: str | None = None,
        until: datetime | None = None,
        strict: bool = False,
    ) -> list[ChainTransfer]:
        address = str(destination_address if destination_address is not None else cfg.CRYPTO_TON_ADDRESS).strip()
        if not address:
            return []
        headers: dict[str, str] = {}
        if cfg.TONCENTER_API_KEY:
            headers["X-API-Key"] = cfg.TONCENTER_API_KEY
        params: dict[str, object] = {
            "account": address,
            "start_utime": int(_utc_timestamp(since)),
            "limit": 100,
            "sort": "desc",
        }
        if until is not None:
            params["end_utime"] = int(_utc_timestamp(until))
        with cls._client() as client:
            rows: list[dict[str, Any]] = []
            for page in range(20):
                response = client.get(
                    f"{cfg.CRYPTO_TONCENTER_BASE_URL}/api/v3/transactions",
                    params={**params, "offset": page * 100},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("transactions"), list):
                    raise CryptoChainUnavailable("TON Center returned invalid paginated data")
                batch = data["transactions"]
                if strict and any(not isinstance(row, dict) for row in batch):
                    raise CryptoChainUnavailable("TON malformed transaction row")
                rows.extend(row for row in batch if isinstance(row, dict))
                if len(batch) < 100:
                    break
            else:
                raise CryptoChainUnavailable("TON pagination exceeded bounded scan; manual backfill required")

        out: list[ChainTransfer] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            finality = str(row.get("finality") or "").lower()
            if strict:
                try:
                    if not same_crypto_destination("TON", str(row.get("account") or ""), address):
                        raise ValueError("Unexpected account")
                except ValueError:
                    raise CryptoChainUnavailable("TON invalid or unexpected transaction account") from None
                if finality not in {"finalized", "confirmed", "pending"}:
                    raise CryptoChainUnavailable("TON unrecognized finality")
            confirmed = finality == "finalized"
            if not include_pending and not confirmed:
                continue
            description = row.get("description") if isinstance(row.get("description"), dict) else {}
            if strict and type(description.get("aborted")) is not bool:
                raise CryptoChainUnavailable("TON missing transaction outcome")
            if bool(description.get("aborted")):
                continue
            in_msg = row.get("in_msg") if isinstance(row.get("in_msg"), dict) else None
            if not in_msg:
                continue
            if strict:
                try:
                    if not same_crypto_destination("TON", str(in_msg.get("destination") or ""), address):
                        raise ValueError("Unexpected recipient")
                except ValueError:
                    raise CryptoChainUnavailable("TON invalid or unexpected message recipient") from None
            try:
                amount = Decimal(str(in_msg.get("value"))) / Decimal("1000000000")
                occurred_at = datetime.fromtimestamp(
                    int(row.get("now")),
                    timezone.utc,
                ).replace(tzinfo=None)
            except (InvalidOperation, TypeError, ValueError, OverflowError):
                if strict:
                    raise CryptoChainUnavailable("TON invalid transfer value or timestamp") from None
                continue
            tx_hash = str(row.get("hash") or "").strip()
            if strict and (not tx_hash or not amount.is_finite() or amount < 0
                           or _utc_timestamp(occurred_at) < _utc_timestamp(since)
                           or (until is not None and _utc_timestamp(occurred_at) > _utc_timestamp(until))):
                raise CryptoChainUnavailable("TON incomplete or out-of-window transfer")
            if not tx_hash or amount <= 0:
                continue
            out.append(
                ChainTransfer(
                    network="TON",
                    asset="TON",
                    tx_hash=tx_hash,
                    amount=amount,
                    sender_address=str(in_msg.get("source") or "").strip() or None,
                    destination_address=address,
                    occurred_at=occurred_at,
                    memo=cls._ton_comment(in_msg),
                    confirmed=confirmed,
                    confirmations=1 if confirmed else 0,
                )
            )
        return out

    @staticmethod
    def _ton_comment(in_msg: dict[str, Any]) -> str | None:
        content = in_msg.get("message_content")
        if not isinstance(content, dict):
            return None
        decoded = content.get("decoded")
        if not isinstance(decoded, dict):
            return None
        for key in ("comment", "text", "message"):
            value = decoded.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
