"""Experimental historical-destination late-transfer inbox, never auto-credit.

Explicitly restricted by the same disposable-MySQL-only rotation gate.
Each observed (network, tx_hash) is recorded at most once by its unique
app_settings key. No wallet ledger writes happen in this module.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crypto import CryptoDepositRequest
from app.models.settings import AppSetting
from app.services.crypto_destination_state import rotation_enabled

HISTORICAL_STATUSES = ("EXPIRED", "CANCELLED", "REJECTED")
PREFIX = "crypto_late_review_v1:"


def late_review_key(network: str, tx_hash: str) -> str:
    net = str(network or "").strip().upper()
    tx = str(tx_hash or "").strip()
    if net not in ("TRON", "TON") or not tx:
        raise ValueError("Invalid chain transfer identity")
    return PREFIX + hashlib.sha256(f"{net}:{tx}".encode("utf-8")).hexdigest()[:40]


def record_unmatched_historical_transfer(db: Session, transfer, *, retired: bool = False) -> bool:
    """Queue a chain observation for human review, never infer ownership."""
    if not rotation_enabled():
        return False
    network = str(transfer.network).upper()
    if network not in ("TRON", "TON"):
        return False
    candidates = db.execute(select(CryptoDepositRequest).where(
        CryptoDepositRequest.network == network,
        CryptoDepositRequest.asset == transfer.asset,
        CryptoDepositRequest.destination_address == transfer.destination_address,
        CryptoDepositRequest.status.in_(HISTORICAL_STATUSES),
        CryptoDepositRequest.created_at <= transfer.occurred_at,
    ).order_by(CryptoDepositRequest.id.asc()).limit(20)).scalars().all()
    if not candidates and not retired:
        return False
    # Do not create an observation if this tx has ever been assigned an invoice.
    assigned = db.execute(select(CryptoDepositRequest.id).where(
        CryptoDepositRequest.network == network,
        CryptoDepositRequest.tx_hash == transfer.tx_hash,
    ).limit(1)).scalar_one_or_none()
    if assigned is not None:
        return False

    key = late_review_key(network, transfer.tx_hash)
    existing = db.execute(select(AppSetting.k).where(AppSetting.k == key).with_for_update()).scalar_one_or_none()
    if existing is not None:
        return False
    payload = {
        "kind": "UNMATCHED_HISTORICAL_DEPOSIT",
        "status": "PENDING_MANUAL_RECONCILIATION",
        "network": network,
        "asset": str(transfer.asset),
        "tx_hash": str(transfer.tx_hash),
        "destination_address": str(transfer.destination_address),
        "sender_address": str(transfer.sender_address or ""),
        "amount_crypto": str(transfer.amount),
        "memo": str(transfer.memo or ""),
        "confirmed": bool(transfer.confirmed),
        "occurred_at": transfer.occurred_at.isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "candidate_invoice_ids": [int(x.id) for x in candidates],
        "automatically_credited": False,
    }
    db.add(AppSetting(k=key, v_json=payload))
    db.flush()  # duplicate key races fail closed; caller rolls back
    return True
