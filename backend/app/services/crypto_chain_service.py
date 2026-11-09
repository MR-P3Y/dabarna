from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core import config as cfg

log = logging.getLogger(__name__)

# Bounded scans fail closed rather than silently discarding older transfers.
TRON_PAGE_LIMIT = 200
TON_PAGE_LIMIT = 100
MAX_CHAIN_SCAN_PAGES = 25


class CryptoChainUnavailable(RuntimeError):
    pass


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
    ) -> list[ChainTransfer]:
        normalized = str(network or "").strip().upper()
        # Default is exactly the original server-configured address.
        # Explicit destinations allow old invoices to remain monitorable.
        if normalized == "TRON":
            return cls._list_tron_usdt(since=since, include_pending=include_pending, destination_address=destination_address)
        if normalized == "TON":
            return cls._list_ton(since=since, include_pending=include_pending, destination_address=destination_address)
        raise CryptoChainUnavailable(f"unsupported crypto network: {normalized}")

    @classmethod
    def list_incoming_for_addresses(
        cls, *, network: str, addresses: list[str], since: datetime,
        include_pending: bool = True,
    ) -> list[ChainTransfer]:
        """Scan all intended destinations or fail the entire scan.

        The caller must provide BOTH active and still-creditable invoice destinations.
        No partial successes are returned if any remote scan fails.
        """
        from app.services.crypto_address_rotation_validation import validate_deposit_address

        normalized = str(network or "").strip().upper()
        unique = sorted({validate_deposit_address(normalized, addr) for addr in addresses})
        if not unique:
            return []
        out: list[ChainTransfer] = []
        seen: set[tuple[str, str, str]] = set()
        for addr in unique:
            for tx in cls.list_incoming(
                network=normalized, since=since, include_pending=include_pending,
                destination_address=addr,
            ):
                identity = (tx.network, tx.tx_hash, tx.destination_address)
                if identity not in seen:
                    seen.add(identity)
                    out.append(tx)
        return out

    @staticmethod
    def _client() -> httpx.Client:
        return httpx.Client(
            timeout=float(cfg.CRYPTO_HTTP_TIMEOUT_SEC),
            follow_redirects=True,
            headers={"Accept": "application/json", "User-Agent": "Davarna/1.0"},
        )

    @classmethod
    def _tron_history_pages(
        cls, *, url: str, base_params: dict[str, object],
        headers: dict[str, str], only_confirmed: bool,
    ) -> list[dict[str, Any]]:
        """Collect TronGrid fingerprint pages or raise on an incomplete scan."""
        params = dict(
            base_params,
            only_confirmed="true" if only_confirmed else "false",
        )
        collected: list[dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        with cls._client() as client:
            for _ in range(MAX_CHAIN_SCAN_PAGES):
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if (
                    not isinstance(payload, dict)
                    or payload.get("success") is False
                    or not isinstance(payload.get("data"), list)
                ):
                    raise CryptoChainUnavailable("TronGrid returned an invalid page")
                page = payload["data"]
                if any(not isinstance(item, dict) for item in page):
                    raise CryptoChainUnavailable("TronGrid returned malformed transfers")
                collected.extend(page)
                meta = payload.get("meta") or {}
                if not isinstance(meta, dict):
                    raise CryptoChainUnavailable("TronGrid pagination metadata malformed")
                fingerprint = meta.get("fingerprint")
                if not fingerprint:
                    # A full page without cursor might hide additional results.
                    if len(page) >= TRON_PAGE_LIMIT:
                        raise CryptoChainUnavailable("TronGrid truncated a full page without a cursor")
                    return collected
                if (
                    not isinstance(fingerprint, str)
                    or fingerprint in seen_fingerprints
                ):
                    raise CryptoChainUnavailable("TronGrid repeated or invalid pagination cursor")
                seen_fingerprints.add(fingerprint)
                params = dict(params, fingerprint=fingerprint)
        raise CryptoChainUnavailable("TronGrid pagination page budget exceeded")

    @classmethod
    def _ton_history_pages(
        cls, *, url: str, params: dict[str, object],
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Collect TON Center offset pages; reject truncated or repeated pages."""
        collected: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        with cls._client() as client:
            for page_no in range(MAX_CHAIN_SCAN_PAGES):
                response = client.get(
                    url, params=dict(params, offset=page_no * TON_PAGE_LIMIT),
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("transactions"), list):
                    raise CryptoChainUnavailable("TON Center returned an invalid page")
                rows = payload["transactions"]
                if any(not isinstance(item, dict) for item in rows):
                    raise CryptoChainUnavailable("TON Center returned malformed transactions")
                for item in rows:
                    tx_hash = str(item.get("hash") or "").strip()
                    if not tx_hash or tx_hash in seen_hashes:
                        raise CryptoChainUnavailable("TON Center returned missing/repeated transaction hash")
                    seen_hashes.add(tx_hash)
                collected.extend(rows)
                if len(rows) < TON_PAGE_LIMIT:
                    return collected
        raise CryptoChainUnavailable("TON Center pagination page budget exceeded")

    @classmethod
    def _list_tron_usdt(
        cls,
        *,
        since: datetime,
        include_pending: bool = True,
        destination_address: str | None = None,
    ) -> list[ChainTransfer]:
        target = destination_address if destination_address is not None else cfg.CRYPTO_TRON_USDT_ADDRESS
        if not target:
            return []
        headers: dict[str, str] = {}
        if cfg.TRONGRID_API_KEY:
            headers["TRON-PRO-API-KEY"] = cfg.TRONGRID_API_KEY
        base_params: dict[str, object] = {
            "only_to": "true",
            "limit": TRON_PAGE_LIMIT,
            "contract_address": cfg.CRYPTO_TRON_USDT_CONTRACT,
            "min_timestamp": int(since.timestamp() * 1000),
            "order_by": "block_timestamp,desc",
        }
        url = (
            f"{cfg.CRYPTO_TRONGRID_BASE_URL}/v1/accounts/"
            f"{target}/transactions/trc20"
        )
        history = cls._tron_history_pages(
            url=url, base_params=base_params, headers=headers,
            only_confirmed=not include_pending,
        )
        confirmed_hashes: set[str] = set()
        if include_pending:
            confirmed = cls._tron_history_pages(
                url=url, base_params=base_params, headers=headers,
                only_confirmed=True,
            )
            confirmed_hashes = {
                str(item.get("transaction_id") or "").strip()
                for item in confirmed
            }

        out: list[ChainTransfer] = []
        for row in history:
            if not isinstance(row, dict):
                continue
            token_info = row.get("token_info") if isinstance(row.get("token_info"), dict) else {}
            if str(token_info.get("address") or "") != cfg.CRYPTO_TRON_USDT_CONTRACT:
                continue
            if str(row.get("to") or "") != target:
                continue
            try:
                decimals = int(token_info.get("decimals") or 6)
                amount = Decimal(str(row.get("value"))) / (Decimal("10") ** decimals)
                occurred_at = datetime.fromtimestamp(
                    int(row.get("block_timestamp")) / 1000,
                    timezone.utc,
                ).replace(tzinfo=None)
            except (InvalidOperation, TypeError, ValueError, OverflowError):
                continue
            tx_hash = str(row.get("transaction_id") or "").strip()
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
                    destination_address=target,
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
    ) -> list[ChainTransfer]:
        target = destination_address if destination_address is not None else cfg.CRYPTO_TON_ADDRESS
        if not target:
            return []
        headers: dict[str, str] = {}
        if cfg.TONCENTER_API_KEY:
            headers["X-API-Key"] = cfg.TONCENTER_API_KEY
        params: dict[str, object] = {
            "account": target,
            "start_utime": int(since.timestamp()),
            "limit": TON_PAGE_LIMIT,
            "sort": "desc",
        }
        history = cls._ton_history_pages(
            url=f"{cfg.CRYPTO_TONCENTER_BASE_URL}/api/v3/transactions",
            params=params, headers=headers,
        )

        out: list[ChainTransfer] = []
        for row in history:
            if not isinstance(row, dict):
                continue
            finality = str(row.get("finality") or "").lower()
            confirmed = finality == "finalized"
            if not include_pending and not confirmed:
                continue
            description = row.get("description") if isinstance(row.get("description"), dict) else {}
            if bool(description.get("aborted")):
                continue
            in_msg = row.get("in_msg") if isinstance(row.get("in_msg"), dict) else None
            if not in_msg:
                continue
            try:
                amount = Decimal(str(in_msg.get("value"))) / Decimal("1000000000")
                occurred_at = datetime.fromtimestamp(
                    int(row.get("now")),
                    timezone.utc,
                ).replace(tzinfo=None)
            except (InvalidOperation, TypeError, ValueError, OverflowError):
                continue
            tx_hash = str(row.get("hash") or "").strip()
            if not tx_hash or amount <= 0:
                continue
            out.append(
                ChainTransfer(
                    network="TON",
                    asset="TON",
                    tx_hash=tx_hash,
                    amount=amount,
                    sender_address=str(in_msg.get("source") or "").strip() or None,
                    destination_address=target,
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
