"""Read-only destination history review; never grants rotation or credits funds.

Provider pagination and parsing must succeed for the whole fixed interval.
Results describe the provider response, not a proof of blockchain completeness.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto import CryptoDepositRequest
from app.models.wallet import Wallet, WalletTx
from app.services.crypto_address_change import same_crypto_destination, validate_crypto_destination
from app.services.crypto_chain_service import CryptoChainService


def review_destination_history(db: Session, *, network: str, address: str, lock: bool = False) -> dict:
    address = validate_crypto_destination(network, address)
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    blockers: set[str] = set()
    # Inspect aliases as account identities; never rewrite historical strings.
    query = select(CryptoDepositRequest).where(
        CryptoDepositRequest.network == network,
    ).order_by(CryptoDepositRequest.id)
    rows = db.execute(query.with_for_update() if lock else query).scalars().all()
    invoices = []
    for invoice in rows:
        try:
            matches = same_crypto_destination(network, address, invoice.destination_address)
        except ValueError:
            blockers.add("INVALID_HISTORICAL_DESTINATION")
            continue
        if matches:
            invoices.append(invoice)
    report = {
        "network": network,
        "destination_sha256": hashlib.sha256(address.encode()).hexdigest(),
        "checked_at": now.isoformat() + "Z",
        "historical_invoices": len(invoices),
        "provider_scan_complete": False,
        "reconciled_invoices": 0,
        "observed_transfers": 0,
        "unassigned_transfers": 0,
        "unconfirmed_transfers": 0,
        "activation_allowed": False,
        "writes_performed": False,
    }
    if not invoices:
        report.update(status="NO_HISTORY" if not blockers else "BLOCKED", blockers=sorted(blockers))
        return report
    grace = timedelta(minutes=max(0, int(cfg.CRYPTO_PAYMENT_GRACE_MINUTES)))
    for invoice in invoices:
        if invoice.status not in {"CREDITED", "EXPIRED", "CANCELLED", "REJECTED"}:
            blockers.add("UNRESOLVED_INVOICE")
        if invoice.status != "CREDITED" and (invoice.expires_at is None or invoice.expires_at + grace >= now):
            blockers.add("PAYMENT_GRACE_ACTIVE")
        if invoice.created_at is None or invoice.created_at > now:
            blockers.add("INVALID_INVOICE_TIME")
    if "INVALID_INVOICE_TIME" in blockers:
        report.update(status="BLOCKED", blockers=sorted(blockers))
        return report
    since = min(invoice.created_at for invoice in invoices).replace(microsecond=0) - timedelta(minutes=2)
    report["scan_since"] = since.isoformat() + "Z"
    report["scan_until"] = now.isoformat() + "Z"
    try:
        transfers = CryptoChainService.list_incoming(
            network=network, destination_address=address, since=since,
            until=now, include_pending=True, strict=True,
        )
    except Exception as exc:
        # Provider exceptions can contain credentials or full destination URLs.
        report.update(status="BLOCKED", blockers=sorted(blockers | {"PROVIDER_SCAN_FAILED"}),
                      provider_error_type=type(exc).__name__)
        return report
    report["provider_scan_complete"] = True
    by_hash = {}
    for transfer in transfers:
        if transfer.tx_hash in by_hash:
            blockers.add("DUPLICATE_PROVIDER_TRANSACTION")
        by_hash[transfer.tx_hash] = transfer
    report["observed_transfers"] = len(transfers)
    assigned = {str(i.tx_hash): i for i in invoices if i.tx_hash}
    for transfer in transfers:
        if not transfer.confirmed:
            report["unconfirmed_transfers"] += 1
            blockers.add("UNCONFIRMED_TRANSFER")
        if transfer.tx_hash not in assigned:
            report["unassigned_transfers"] += 1
            blockers.add("UNASSIGNED_TRANSFER")
    for invoice in invoices:
        transfer = by_hash.get(str(invoice.tx_hash)) if invoice.tx_hash else None
        if invoice.status == "CREDITED":
            tx = db.get(WalletTx, invoice.wallet_tx_id) if invoice.wallet_tx_id else None
            wallet = db.get(Wallet, tx.wallet_id) if tx is not None else None
            ledger_matches = (tx is not None and wallet is not None
                and tx.direction == 'CREDIT' and tx.reason == 'DEPOSIT_CRYPTO'
                and tx.ref_type == 'CRYPTO_DEPOSIT' and tx.ref_id == invoice.id
                and wallet.user_id == invoice.user_id and tx.amount == invoice.amount_toman)
            if (transfer is None or not transfer.confirmed or not invoice.wallet_tx_id
                    or not ledger_matches
                    or invoice.paid_amount_crypto is None
                    or Decimal(invoice.paid_amount_crypto) != transfer.amount
                    or invoice.asset != transfer.asset
                    or not same_crypto_destination(network, invoice.destination_address, transfer.destination_address)
                    or (network == "TON" and invoice.memo != transfer.memo)):
                blockers.add("CREDITED_INVOICE_MISMATCH")
            else:
                report["reconciled_invoices"] += 1
        elif invoice.tx_hash or transfer is not None or invoice.wallet_tx_id:
            blockers.add("CLOSED_INVOICE_REQUIRES_REVIEW")
        else:
            report["reconciled_invoices"] += 1
    report.update(status="BLOCKED" if blockers else "REVIEWED_NO_DISCREPANCY", blockers=sorted(blockers))
    return report
