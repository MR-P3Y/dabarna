#!/usr/bin/env python3
"""Read-only TON/TRON chain history audit for the retired Davarna destinations.

Run inside the backend container so existing provider credentials/config are used.
This script calls public/provider read APIs only. It does not connect to MySQL,
write AppSettings, process invoices, or credit wallets.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

from app.services.crypto_chain_service import CryptoChainService

SINCE = datetime(2026, 6, 24, 0, 0, 0)
DESTINATIONS = (
    ("TRON", "TLG8VxQSVW94BiM8sDfBpDkYQe5FrBxx8G"),
    ("TON", "UQBbsfJy0Aarob9tIYze92O_wPpFuFiwpVEP1EHUACGpf8cH"),
)


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def main() -> int:
    emit({
        "section": "chain_history_audit_start",
        "read_only": True,
        "database_access": False,
        "wallet_credit": False,
        "since_utc": SINCE.isoformat() + "Z",
        "through_utc": datetime.now(timezone.utc).isoformat(),
    })
    failed = False
    for network, address in DESTINATIONS:
        try:
            transfers = CryptoChainService.list_incoming(
                network=network,
                since=SINCE,
                include_pending=False,
                destination_address=address,
            )
            transfers.sort(key=lambda x: (x.occurred_at, x.tx_hash))
            emit({
                "section": "chain_history",
                "network": network,
                "destination_address": address,
                "complete": True,
                "transfer_count": len(transfers),
            })
            for transfer in transfers:
                emit({
                    "section": "transfer",
                    "network": transfer.network,
                    "asset": transfer.asset,
                    "tx_hash": transfer.tx_hash,
                    "amount": str(transfer.amount),
                    "sender_address": transfer.sender_address,
                    "destination_address": transfer.destination_address,
                    "occurred_at_utc": transfer.occurred_at.isoformat() + "Z",
                    "memo": transfer.memo,
                    "confirmed": transfer.confirmed,
                    "confirmations_reported": transfer.confirmations,
                })
        except Exception as exc:
            failed = True
            # Do not print exception strings: provider URLs may contain secrets.
            emit({
                "section": "chain_history",
                "network": network,
                "destination_address": address,
                "complete": False,
                "error_type": type(exc).__name__,
                "error": "Provider query or bounded pagination failed; no completeness claim.",
            })
    emit({
        "section": "chain_history_audit_finish",
        "complete": not failed,
        "note": "No database, invoice, wallet, or ledger rows were read or changed.",
    })
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
