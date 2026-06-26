from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, Field


class CryptoDepositCreateIn(BaseModel):
    amount_toman: int = Field(gt=0)
    network: str = Field(min_length=3, max_length=10)


class CryptoTxClaimIn(BaseModel):
    tx_hash: str = Field(min_length=20, max_length=160)


class CryptoWalletEventIn(BaseModel):
    event: str = Field(min_length=3, max_length=40)
    provider: str = Field(min_length=3, max_length=32)
    invoice_id: int | None = Field(default=None, gt=0)
    wallet_address: str | None = Field(default=None, max_length=160)
    client_event_id: str | None = Field(default=None, max_length=80)
    detail: str | None = Field(default=None, max_length=240)


class CryptoAdminRejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class CryptoDepositOut(BaseModel):
    id: int
    public_id: str
    user_id: int
    network: str
    asset: str
    amount_toman: int
    rate_toman_per_asset: str
    amount_crypto: str
    paid_amount_crypto: str | None = None
    rate_provider: str
    rate_fetched_at: str | None = None
    estimated_network_fee: str | None = None
    estimated_network_fee_asset: str | None = None
    destination_address: str
    memo: str | None = None
    tx_hash: str | None = None
    wallet_provider: str | None = None
    wallet_account_address: str | None = None
    status: str
    confirmation_count: int = 0
    required_confirmations: int = 1
    wallet_tx_id: int | None = None
    failure_reason: str | None = None
    payment_variance: str | None = None
    variance_amount_crypto: str | None = None
    payment_uri: str
    explorer_url: str | None = None
    tracking_code: str
    server_now: str
    expires_at: str
    detected_at: str | None = None
    confirmed_at: str | None = None
    credited_at: str | None = None
    payment_requested_at: str | None = None
    cancelled_at: str | None = None
    created_at: str


class CryptoDepositListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CryptoDepositOut]


class CryptoOptionOut(BaseModel):
    network: str
    asset: str
    address: str
    decimals: int
    healthy: bool = True
    unavailable_reason: str | None = None
    rate_toman: str | None = None
    rate_provider: str | None = None
    checked_at: str | None = None
    direct_payment_available: bool = False
    direct_payment_reason: str | None = None
    estimated_network_fee: str | None = None
    estimated_network_fee_asset: str | None = None


class CryptoOptionsOut(BaseModel):
    enabled: bool
    min_toman_amount: int
    max_toman_amount: int
    invoice_expire_minutes: int
    daily_user_max_count: int
    daily_user_max_toman: int
    walletconnect_project_id: str | None = None
    ton_manifest_url: str = ""
    tron_usdt_contract: str = ""
    trongrid_base_url: str = ""
    options: list[CryptoOptionOut]


def crypto_deposit_dict(row, *, tg_user_id: int | None = None, tg_username: str | None = None) -> dict:
    def decimal_text(value) -> str | None:
        if value is None:
            return None
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def datetime_text(value) -> str | None:
        if value is None:
            return None
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)
        return current.isoformat().replace("+00:00", "Z")

    out = {
        "id": int(row.id),
        "public_id": str(row.public_id),
        "user_id": int(row.user_id),
        "network": str(row.network),
        "asset": str(row.asset),
        "amount_toman": int(row.amount_toman),
        "rate_toman_per_asset": decimal_text(row.rate_toman_per_asset) or "0",
        "amount_crypto": decimal_text(row.amount_crypto) or "0",
        "paid_amount_crypto": decimal_text(row.paid_amount_crypto),
        "rate_provider": str(row.rate_provider),
        "rate_fetched_at": datetime_text(getattr(row, "rate_fetched_at", None)),
        "estimated_network_fee": decimal_text(getattr(row, "estimated_network_fee", None)),
        "estimated_network_fee_asset": getattr(row, "estimated_network_fee_asset", None),
        "destination_address": str(row.destination_address),
        "memo": row.memo,
        "tx_hash": row.tx_hash,
        "wallet_provider": getattr(row, "wallet_provider", None),
        "wallet_account_address": getattr(row, "wallet_account_address", None),
        "status": str(row.status),
        "confirmation_count": int(getattr(row, "confirmation_count", 0) or 0),
        "required_confirmations": int(getattr(row, "required_confirmations", 1) or 1),
        "wallet_tx_id": int(row.wallet_tx_id) if row.wallet_tx_id is not None else None,
        "failure_reason": row.failure_reason,
        "payment_variance": row.payment_variance,
        "variance_amount_crypto": decimal_text(row.variance_amount_crypto),
        "payment_uri": _payment_uri(row),
        "explorer_url": _explorer_url(row),
        "tracking_code": (
            str(row.public_id).upper()
            if str(row.public_id).upper().startswith("DAV-")
            else f"DAV-{str(row.public_id).upper()}"
        ),
        "server_now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expires_at": datetime_text(row.expires_at) or "",
        "detected_at": datetime_text(row.detected_at),
        "confirmed_at": datetime_text(getattr(row, "confirmed_at", None)),
        "credited_at": datetime_text(row.credited_at),
        "payment_requested_at": datetime_text(getattr(row, "payment_requested_at", None)),
        "cancelled_at": datetime_text(getattr(row, "cancelled_at", None)),
        "created_at": datetime_text(row.created_at) or "",
    }
    if tg_user_id is not None:
        out["tg_user_id"] = int(tg_user_id)
    if tg_username is not None:
        out["tg_username"] = str(tg_username)
    return out


def _payment_uri(row) -> str:
    address = str(row.destination_address or "").strip()
    if str(row.network).upper() != "TON":
        return address
    amount_nano = int(Decimal(row.amount_crypto) * Decimal("1000000000"))
    uri = f"ton://transfer/{address}?amount={amount_nano}"
    memo = str(row.memo or "").strip()
    if memo:
        from urllib.parse import quote

        uri += f"&text={quote(memo, safe='')}"
    return uri


def _explorer_url(row) -> str | None:
    tx_hash = str(row.tx_hash or "").strip()
    if not tx_hash:
        return None
    from app.core import config as cfg
    from urllib.parse import quote

    base = (
        cfg.CRYPTO_TRON_EXPLORER_TX_BASE
        if str(row.network).upper() == "TRON"
        else cfg.CRYPTO_TON_EXPLORER_TX_BASE
    )
    return f"{base}/{quote(tx_hash, safe='')}"
