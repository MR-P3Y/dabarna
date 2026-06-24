from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.crypto import CryptoDepositRequest
from app.models.wallet import WalletTx
from app.services.crypto_chain_service import CryptoChainService
from app.services.crypto_deposit_service import CryptoDepositService


class CryptoReconciliationService:
    @staticmethod
    def run(db: Session, *, start_at: datetime, end_at: datetime) -> dict[str, Any]:
        configured = CryptoDepositService.configured_options()
        network_results: list[dict[str, Any]] = []
        onchain_by_network: dict[str, dict[str, Any]] = {}
        healthy_networks: set[str] = set()

        for option in configured:
            network = str(option["network"])
            try:
                transfers = [
                    transfer
                    for transfer in CryptoChainService.list_incoming(
                        network=network,
                        since=start_at,
                    )
                    if transfer.occurred_at <= end_at
                ]
                onchain_by_network[network] = {transfer.tx_hash: transfer for transfer in transfers}
                healthy_networks.add(network)
                network_results.append(
                    {
                        "network": network,
                        "ok": True,
                        "transfers_count": len(transfers),
                        "amount_crypto": CryptoReconciliationService._decimal_text(
                            sum((transfer.amount for transfer in transfers), Decimal("0"))
                        ),
                    }
                )
            except Exception as exc:
                onchain_by_network[network] = {}
                network_results.append(
                    {
                        "network": network,
                        "ok": False,
                        "transfers_count": 0,
                        "amount_crypto": "0",
                        "error": str(exc)[:240],
                    }
                )

        invoices = list(
            db.execute(
                select(CryptoDepositRequest).where(
                    CryptoDepositRequest.created_at <= end_at,
                    or_(
                        CryptoDepositRequest.expires_at >= start_at,
                        CryptoDepositRequest.detected_at.between(start_at, end_at),
                        CryptoDepositRequest.credited_at.between(start_at, end_at),
                    ),
                )
            ).scalars().all()
        )
        known_hashes = {
            (str(row.network), str(row.tx_hash)): row
            for row in invoices
            if str(row.tx_hash or "").strip()
        }

        unmatched: list[dict[str, Any]] = []
        for network, transfers in onchain_by_network.items():
            for tx_hash, transfer in transfers.items():
                if (network, tx_hash) in known_hashes:
                    continue
                unmatched.append(
                    {
                        "network": network,
                        "tx_hash": tx_hash,
                        "amount_crypto": CryptoReconciliationService._decimal_text(transfer.amount),
                        "occurred_at": transfer.occurred_at.isoformat(),
                    }
                )

        missing_onchain: list[dict[str, Any]] = []
        for row in invoices:
            tx_hash = str(row.tx_hash or "").strip()
            if not tx_hash or str(row.status) not in ("CREDITED", "NEEDS_REVIEW"):
                continue
            if str(row.network) not in healthy_networks:
                continue
            network_map = onchain_by_network.get(str(row.network), {})
            if tx_hash not in network_map:
                missing_onchain.append(
                    {
                        "invoice_id": int(row.id),
                        "network": str(row.network),
                        "tx_hash": tx_hash,
                        "status": str(row.status),
                    }
                )

        ledger_mismatches: list[dict[str, Any]] = []
        credited_rows = [row for row in invoices if str(row.status) == "CREDITED"]
        for row in credited_rows:
            tx = db.get(WalletTx, int(row.wallet_tx_id)) if row.wallet_tx_id is not None else None
            if (
                tx is None
                or str(tx.direction) != "CREDIT"
                or str(tx.reason) != "DEPOSIT_CRYPTO"
                or int(tx.amount) != int(row.amount_toman)
                or str(tx.ref_type or "") != "CRYPTO_DEPOSIT"
                or int(tx.ref_id or 0) != int(row.id)
            ):
                ledger_mismatches.append(
                    {
                        "invoice_id": int(row.id),
                        "wallet_tx_id": int(row.wallet_tx_id) if row.wallet_tx_id is not None else None,
                        "amount_toman": int(row.amount_toman),
                        "kind": "invoice_wallet_mismatch",
                    }
                )

        linked_wallet_tx_ids = {
            int(row.wallet_tx_id)
            for row in credited_rows
            if row.wallet_tx_id is not None
        }
        crypto_wallet_txs = list(
            db.execute(
                select(WalletTx).where(
                    WalletTx.reason == "DEPOSIT_CRYPTO",
                    WalletTx.created_at >= start_at,
                    WalletTx.created_at <= end_at,
                )
            ).scalars().all()
        )
        for tx in crypto_wallet_txs:
            if int(tx.id) in linked_wallet_tx_ids:
                continue
            ledger_mismatches.append(
                {
                    "invoice_id": int(tx.ref_id) if tx.ref_id is not None else None,
                    "wallet_tx_id": int(tx.id),
                    "amount_toman": int(tx.amount),
                    "kind": "orphan_wallet_transaction",
                }
            )

        chain_errors = [item for item in network_results if not bool(item["ok"])]
        ok = not unmatched and not missing_onchain and not ledger_mismatches and not chain_errors
        return {
            "from_at": start_at.isoformat(),
            "to_at": end_at.isoformat(),
            "ok": ok,
            "credited_invoices_count": len(credited_rows),
            "credited_toman_total": sum(int(row.amount_toman) for row in credited_rows),
            "network_results": network_results,
            "unmatched_onchain_count": len(unmatched),
            "unmatched_onchain": unmatched[:30],
            "missing_onchain_count": len(missing_onchain),
            "missing_onchain": missing_onchain[:30],
            "ledger_mismatch_count": len(ledger_mismatches),
            "ledger_mismatches": ledger_mismatches[:30],
        }

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        text = format(value, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
