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
    return {
        "network": network,
        "candidate_matches_current": proposed_address == current_address,
        "open_invoices": open_count,
        "recent_closed_invoices": recent_closed_count,
        "needs_manual_review": manual_review_count,
        "active_change_allowed": False,
        "reason": "Active wallet switching is disabled pending atomic revision locking, provider preflight, old-address scan and reconciliation tests.",
    }
