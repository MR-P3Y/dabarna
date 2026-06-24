from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class CryptoDepositCreateIn(BaseModel):
    amount_toman: int = Field(gt=0)
    network: str = Field(min_length=3, max_length=10)


class CryptoTxClaimIn(BaseModel):
    tx_hash: str = Field(min_length=20, max_length=160)


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
    destination_address: str
    memo: str | None = None
    tx_hash: str | None = None
    status: str
    wallet_tx_id: int | None = None
    failure_reason: str | None = None
    payment_variance: str | None = None
    variance_amount_crypto: str | None = None
    payment_uri: str
    explorer_url: str | None = None
    expires_at: str
    detected_at: str | None = None
    credited_at: str | None = None
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


class CryptoOptionsOut(BaseModel):
    enabled: bool
    min_toman_amount: int
    max_toman_amount: int
    invoice_expire_minutes: int
    daily_user_max_count: int
    daily_user_max_toman: int
    options: list[CryptoOptionOut]


def crypto_deposit_dict(row, *, tg_user_id: int | None = None, tg_username: str | None = None) -> dict:
    def decimal_text(value) -> str | None:
        if value is None:
            return None
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def datetime_text(value) -> str | None:
        return value.isoformat() if value is not None else None

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
        "destination_address": str(row.destination_address),
        "memo": row.memo,
        "tx_hash": row.tx_hash,
        "status": str(row.status),
        "wallet_tx_id": int(row.wallet_tx_id) if row.wallet_tx_id is not None else None,
        "failure_reason": row.failure_reason,
        "payment_variance": row.payment_variance,
        "variance_amount_crypto": decimal_text(row.variance_amount_crypto),
        "payment_uri": _payment_uri(row),
        "explorer_url": _explorer_url(row),
        "expires_at": datetime_text(row.expires_at) or "",
        "detected_at": datetime_text(row.detected_at),
        "credited_at": datetime_text(row.credited_at),
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
