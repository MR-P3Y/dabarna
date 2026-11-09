"""Read-only triage of historically expired/cancelled crypto invoices (#30).

No address rotation, payment claim, wallet credit, audit writes or invoice state
transition. An operator must investigate before making any financial decision.
Never equate a likely invoice match with proof of payment ownership.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto import CryptoDepositRequest
from app.services.crypto_address_rotation_validation import (
    InvalidDepositAddress,
    masked_address,
    same_deposit_destination,
    validate_deposit_address,
)
from app.services.crypto_chain_service import ChainTransfer, CryptoChainService, CryptoChainUnavailable

HISTORICAL_STATUSES = ("EXPIRED", "CANCELLED", "REJECTED")
MAX_HISTORICAL_INVOICES = 1000
MAX_DESTINATIONS_PER_NETWORK = 25
MAX_REVIEW_TRANSFERS = 1000
MAX_WINDOW = timedelta(days=7)


def _same_address(network: str, a: str, b: str) -> bool:
    try:
        return same_deposit_destination(network, a, b)
    except InvalidDepositAddress as exc:
        raise CryptoChainUnavailable("Unverifiable historical destination account") from exc


class CryptoLatePaymentReviewService:
    @staticmethod
    def scan(
        db: Session, *, start_at: datetime, end_at: datetime,
    ) -> dict[str, Any]:
        """Build a complete, non-mutating review report for a bounded time window.

        Scans addresses pinned to historical invoices, not current .env values.
        Returns NO partial report if a provider/validation/budget check fails.
        """
        if (
            start_at.tzinfo is not None or end_at.tzinfo is not None
            or end_at <= start_at or end_at - start_at > MAX_WINDOW
        ):
            raise HTTPException(status_code=400, detail="بازه زمانی بررسی نامعتبر یا بیشتر از هفت روز است.")

        historic = db.execute(
            select(CryptoDepositRequest)
            .where(
                CryptoDepositRequest.status.in_(HISTORICAL_STATUSES),
                CryptoDepositRequest.created_at <= end_at,
            )
            .order_by(CryptoDepositRequest.id.asc())
            .limit(MAX_HISTORICAL_INVOICES + 1)
        ).scalars().all()
        if len(historic) > MAX_HISTORICAL_INVOICES:
            raise HTTPException(
                status_code=409,
                detail="تعداد فاکتورهای تاریخی برای بررسی کامل بیش از حد مجاز است؛ بررسی دستی لازم است.",
            )

        addresses: dict[str, list[str]] = {}
        for inv in historic:
            network = str(inv.network)
            if network not in ("TRON", "TON"):
                raise CryptoChainUnavailable("Unsupported historical network")
            try:
                target = validate_deposit_address(network, str(inv.destination_address))
            except InvalidDepositAddress as exc:
                raise CryptoChainUnavailable("Invalid destination on historical invoice") from exc
            group = addresses.setdefault(network, [])
            if not any(_same_address(network, target, existing) for existing in group):
                group.append(target)
                if len(group) > MAX_DESTINATIONS_PER_NETWORK:
                    raise HTTPException(
                        status_code=409,
                        detail="تعداد آدرس‌های تاریخی برای اسکن خودکار بیش از حد مجاز است.",
                    )

        # Gather the complete provider result BEFORE deciding which transfers
        # might belong to expired invoices. A failed address invalidates the report.
        found: dict[tuple[str, str], ChainTransfer] = {}
        for network, destinations in sorted(addresses.items()):
            try:
                transfers = CryptoChainService.list_incoming_for_addresses(
                    network=network, addresses=destinations, since=start_at,
                    include_pending=True,
                )
            except Exception as exc:
                raise CryptoChainUnavailable(
                    "Historical provider scan unavailable or incomplete"
                ) from exc
            for tx in transfers:
                if (
                    tx.occurred_at < start_at or tx.occurred_at > end_at
                    or tx.asset != ("USDT" if network == "TRON" else "TON")
                    or tx.network != network
                ):
                    continue
                if not tx.tx_hash:
                    raise CryptoChainUnavailable("On-chain transfer without hash")
                identity = (network, str(tx.tx_hash))
                before = found.get(identity)
                if before is not None:
                    if (
                        not _same_address(network, before.destination_address, tx.destination_address)
                        or before.amount != tx.amount
                        or before.occurred_at != tx.occurred_at
                    ):
                        raise CryptoChainUnavailable("Inconsistent evidence for same transaction")
                    if tx.confirmed and not before.confirmed:
                        found[identity] = tx
                else:
                    found[identity] = tx
                if len(found) > MAX_REVIEW_TRANSFERS:
                    raise CryptoChainUnavailable("Too many historical transfers for full review")

        linked: set[tuple[str, str]] = set()
        for network in ("TRON", "TON"):
            hashes = [h for (n, h) in found if n == network]
            if not hashes:
                continue
            # Keep each SQL IN bounded for MySQL/provider compatibility.
            for offset in range(0, len(hashes), 250):
                rows = db.execute(
                    select(CryptoDepositRequest.network, CryptoDepositRequest.tx_hash)
                    .where(
                        CryptoDepositRequest.network == network,
                        CryptoDepositRequest.tx_hash.in_(hashes[offset:offset + 250]),
                    )
                ).all()
                linked.update((str(n), str(h)) for n, h in rows if h)

        review: list[dict[str, Any]] = []
        for identity, tx in sorted(found.items()):
            if identity in linked:
                continue
            same_account = [
                row for row in historic
                if str(row.network) == tx.network
                and str(row.asset) == tx.asset
                and row.created_at is not None
                and row.created_at <= tx.occurred_at
                and _same_address(tx.network, str(row.destination_address), tx.destination_address)
            ]
            exact = [
                row for row in same_account
                if Decimal(row.amount_crypto) == tx.amount
                and (not row.memo or str(row.memo) == str(tx.memo or ""))
            ]
            if len(exact) == 1:
                status = "POSSIBLE_HISTORICAL_MATCH"
                nominated = exact
                expiry = exact[0].expires_at
                grace = timedelta(minutes=int(cfg.CRYPTO_PAYMENT_GRACE_MINUTES))
                timing = (
                    "WITHIN_INVOICE_WINDOW"
                    if expiry is not None and tx.occurred_at <= expiry + grace
                    else "AFTER_INVOICE_WINDOW"
                )
            elif len(exact) > 1:
                status = "AMBIGUOUS_MULTIPLE_INVOICES"
                nominated = exact
                timing = "NEEDS_MANUAL_VERIFICATION"
            elif same_account:
                status = "AMOUNT_OR_MEMO_MISMATCH"
                nominated = same_account
                timing = "NEEDS_MANUAL_VERIFICATION"
            else:
                status = "NO_MATCHING_HISTORICAL_INVOICE"
                nominated = []
                timing = "NEEDS_MANUAL_VERIFICATION"
            review.append({
                "network": tx.network,
                "asset": tx.asset,
                "tx_hash": str(tx.tx_hash),
                "destination_masked": masked_address(str(tx.destination_address)),
                "amount_crypto": format(tx.amount, "f"),
                "occurred_at": tx.occurred_at.isoformat(),
                "confirmed_on_chain": bool(tx.confirmed),
                "classification": status,
                "timing": timing,
                "candidate_invoice_ids": [int(item.id) for item in nominated],
                "can_auto_credit": False,
            })

        return {
            "ok": True,
            "read_only": True,
            "can_auto_credit": False,
            "from_at": start_at.isoformat(),
            "to_at": end_at.isoformat(),
            "historical_invoice_count": len(historic),
            "address_count": sum(len(values) for values in addresses.values()),
            "onchain_transfer_count": len(found),
            "already_linked_tx_count": len(linked),
            "review_needed_count": len(review),
            "items": review,
        }
