from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core import config as cfg

log = logging.getLogger(__name__)


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
    ) -> list[ChainTransfer]:
        normalized = str(network or "").strip().upper()
        if normalized == "TRON":
            return cls._list_tron_usdt(since=since, include_pending=include_pending)
        if normalized == "TON":
            return cls._list_ton(since=since, include_pending=include_pending)
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
    ) -> list[ChainTransfer]:
        if not cfg.CRYPTO_TRON_USDT_ADDRESS:
            return []
        headers: dict[str, str] = {}
        if cfg.TRONGRID_API_KEY:
            headers["TRON-PRO-API-KEY"] = cfg.TRONGRID_API_KEY
        base_params: dict[str, object] = {
            "only_to": "true",
            "limit": 200,
            "contract_address": cfg.CRYPTO_TRON_USDT_CONTRACT,
            "min_timestamp": int(since.timestamp() * 1000),
            "order_by": "block_timestamp,desc",
        }
        url = (
            f"{cfg.CRYPTO_TRONGRID_BASE_URL}/v1/accounts/"
            f"{cfg.CRYPTO_TRON_USDT_ADDRESS}/transactions/trc20"
        )
        with cls._client() as client:
            params = dict(base_params, only_confirmed="false" if include_pending else "true")
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            confirmed_hashes: set[str] = set()
            if include_pending:
                confirmed_response = client.get(
                    url,
                    params=dict(base_params, only_confirmed="true"),
                    headers=headers,
                )
                confirmed_response.raise_for_status()
                confirmed_data = confirmed_response.json()
                if isinstance(confirmed_data, dict):
                    confirmed_hashes = {
                        str(item.get("transaction_id") or "").strip()
                        for item in (confirmed_data.get("data") or [])
                        if isinstance(item, dict)
                    }
        if not isinstance(data, dict) or data.get("success") is False:
            raise CryptoChainUnavailable("TronGrid returned an invalid response")

        out: list[ChainTransfer] = []
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            token_info = row.get("token_info") if isinstance(row.get("token_info"), dict) else {}
            if str(token_info.get("address") or "") != cfg.CRYPTO_TRON_USDT_CONTRACT:
                continue
            if str(row.get("to") or "") != cfg.CRYPTO_TRON_USDT_ADDRESS:
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
                    destination_address=cfg.CRYPTO_TRON_USDT_ADDRESS,
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
    ) -> list[ChainTransfer]:
        if not cfg.CRYPTO_TON_ADDRESS:
            return []
        headers: dict[str, str] = {}
        if cfg.TONCENTER_API_KEY:
            headers["X-API-Key"] = cfg.TONCENTER_API_KEY
        params: dict[str, object] = {
            "account": cfg.CRYPTO_TON_ADDRESS,
            "start_utime": int(since.timestamp()),
            "limit": 100,
            "sort": "desc",
        }
        with cls._client() as client:
            response = client.get(f"{cfg.CRYPTO_TONCENTER_BASE_URL}/api/v3/transactions", params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise CryptoChainUnavailable("TON Center returned an invalid response")

        out: list[ChainTransfer] = []
        for row in data.get("transactions") or []:
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
                    destination_address=cfg.CRYPTO_TON_ADDRESS,
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
