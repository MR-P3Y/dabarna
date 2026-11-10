"""Read-only safety assessment before a crypto destination switch.

Never changes active settings, invoices, scanner configuration, or wallets.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto import CryptoDepositRequest
from app.services.crypto_deposit_service import OPEN_STATUSES
from app.services.crypto_destination_state import rotation_enabled
from app.services.crypto_scan_observation import observation_key
from app.models.settings import AppSetting


def assess_rotation(db: Session, *, network: str, current_address: str, proposed_address: str) -> dict[str, object]:
    if network not in ("TRON", "TON"):
        raise ValueError("Unsupported network")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    grace = timedelta(minutes=max(0, int(cfg.CRYPTO_PAYMENT_GRACE_MINUTES)))
    open_count = int(db.execute(select(func.count(CryptoDepositRequest.id)).where(
        CryptoDepositRequest.network == network,
        CryptoDepositRequest.destination_address == current_address,
        CryptoDepositRequest.status.in_(OPEN_STATUSES),
    )).scalar_one() or 0)
    # Expired or cancelled invoices may still have an in-flight transfer.
    recent_closed_count = int(db.execute(select(func.count(CryptoDepositRequest.id)).where(
        CryptoDepositRequest.network == network,
        CryptoDepositRequest.destination_address == current_address,
        CryptoDepositRequest.status.in_(("EXPIRED", "CANCELLED")),
        CryptoDepositRequest.expires_at >= now - grace,
    )).scalar_one() or 0)
    manual_review_count = int(db.execute(select(func.count(CryptoDepositRequest.id)).where(
        CryptoDepositRequest.network == network,
        CryptoDepositRequest.destination_address == current_address,
        CryptoDepositRequest.status == "NEEDS_REVIEW",
    )).scalar_one() or 0)
    # Observations are operational diagnostics, NOT verified historical
    # backfill. The experimental gate keeps Production's prior report shape.
    scan_coverage = None
    if rotation_enabled():
        row = db.get(AppSetting, observation_key(network, current_address))
        data = row.v_json if row is not None and isinstance(row.v_json, dict) else {}
        scan_coverage = {
            "observation_present": bool(data),
            "checked_at": data.get("checked_at"),
            "pages_complete": data.get("pages_complete") is True,
            "processing_complete": data.get("processing_complete") is True,
            "historical_gap": data.get("historical_gap") is True,
            # Never trust a mutable diagnostic flag as readiness evidence.
            "backfill_verified": False,
        }
    report = {
        "network": network,
        "candidate_matches_current": proposed_address == current_address,
        "open_invoices": open_count,
        "recent_closed_invoices": recent_closed_count,
        "needs_manual_review": manual_review_count,
        "active_change_allowed": False,
        "reason": "Active wallet switching is disabled pending atomic revision locking, provider preflight, old-address scan and reconciliation tests.",
    }
    if scan_coverage is not None:
        report["scan_coverage"] = scan_coverage
    return report
