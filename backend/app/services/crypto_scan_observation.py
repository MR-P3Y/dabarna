"""Experimental durable per-destination scan observations, NOT backfill proof.

Records only what this scan attempt observed. The flag backfill_verified is
always False: page completion does not establish complete chain history.
No wallet ledger or invoice mutations are performed here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.settings import AppSetting
from app.services.crypto_destination_state import rotation_enabled

PREFIX = "crypto_scan_observation_v1:"


def observation_key(network: str, address: str) -> str:
    network = str(network).upper().strip()
    address = str(address).strip()
    if network not in ("TRON", "TON") or not address:
        raise ValueError("Invalid scan destination")
    digest = hashlib.sha256(f"{network}:{address}".encode()).hexdigest()[:32]
    key = PREFIX + digest
    if len(key) > 64:
        raise ValueError("AppSetting key too long")
    return key


def record_scan_observation(
    db: Session, *, network: str, address: str, since: datetime,
    pages_complete: bool, processing_complete: bool, historical_gap: bool,
    transfer_count: int,
) -> None:
    """Keep a durable diagnostic; never assert backfill verification.

    Caller owns the DB transaction and must rollback on failure.
    """
    if not rotation_enabled():
        return
    key = observation_key(network, address)
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "network": str(network).upper(),
        "address_sha256": hashlib.sha256(str(address).encode()).hexdigest(),
        "scan_since": since.isoformat(),
        "checked_at": now,
        "pages_complete": bool(pages_complete),
        "processing_complete": bool(processing_complete),
        "historical_gap": bool(historical_gap),
        "transfer_count": max(0, int(transfer_count)),
        "backfill_verified": False,
    }
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(k=key, v_json=data))
    else:
        # Lock a pre-existing observation, but never use this as the
        # versioned destination lock used for invoice issuance.
        row = db.get(AppSetting, key, with_for_update=True)
        row.v_json = data
    db.flush()
