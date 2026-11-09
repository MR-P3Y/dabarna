"""Record historical crypto transfer observations in an audited queue only.

No wallet credit/debit, invoice mutation, payment approval or address activation.
The report comes from the server's own complete, fail-closed historical scan,
not from user-supplied JSON. Caller must enforce owner/SuperAdmin RBAC.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity
from app.models.crypto import CryptoDepositRequest
from app.models.crypto_late_payment_case import CryptoLatePaymentCase
from app.services.admin_audit_service import AdminAuditService
from app.services.crypto_late_payment_review_service import CryptoLatePaymentReviewService

_ALLOWED_CLASSIFICATIONS = {
    "POSSIBLE_HISTORICAL_MATCH", "AMBIGUOUS_MULTIPLE_INVOICES",
    "AMOUNT_OR_MEMO_MISMATCH", "NO_MATCHING_HISTORICAL_INVOICE",
}
_ALLOWED_TIMING = {
    "WITHIN_INVOICE_WINDOW", "AFTER_INVOICE_WINDOW", "NEEDS_MANUAL_VERIFICATION",
}


class CryptoLatePaymentQueueService:
    @staticmethod
    def capture(
        db: Session, *, start_at: datetime, end_at: datetime,
        admin: AdminIdentity, request: Request | None = None,
    ) -> dict[str, object]:
        report = CryptoLatePaymentReviewService.scan(
            db, start_at=start_at, end_at=end_at,
        )
        items = report.get("items")
        if (
            report.get("ok") is not True
            or report.get("read_only") is not True
            or report.get("can_auto_credit") is not False
            or not isinstance(items, list)
            or len(items) > 1000
            or report.get("review_needed_count") != len(items)
        ):
            raise HTTPException(status_code=409, detail="گزارش کامل و معتبر نیست.")

        added_ids: list[int] = []
        skipped_linked = 0
        already_seen = 0
        in_batch: set[tuple[str, str]] = set()

        for item in items:
            if not isinstance(item, dict):
                raise HTTPException(status_code=409, detail="گزارش شامل داده نامعتبر است.")
            network = item.get("network")
            asset = item.get("asset")
            tx_hash = item.get("tx_hash")
            masked = item.get("destination_masked")
            classification = item.get("classification")
            timing = item.get("timing")
            candidate_ids = item.get("candidate_invoice_ids")
            confirmed = item.get("confirmed_on_chain")
            if (
                network not in ("TRON", "TON")
                or asset != ("USDT" if network == "TRON" else "TON")
                or not isinstance(tx_hash, str) or not 1 <= len(tx_hash) <= 160
                or not isinstance(masked, str) or "…" not in masked or len(masked) > 40
                or classification not in _ALLOWED_CLASSIFICATIONS
                or timing not in _ALLOWED_TIMING
                or not isinstance(confirmed, bool)
                or not isinstance(candidate_ids, list) or len(candidate_ids) > 1000
                or any(not isinstance(x, int) or x <= 0 for x in candidate_ids)
                or item.get("can_auto_credit") is not False
            ):
                raise HTTPException(status_code=409, detail="اطلاعات پرداخت تاریخی نامعتبر است.")
            identity = (network, tx_hash)
            if identity in in_batch:
                raise HTTPException(status_code=409, detail="تراکنش در گزارش دوبار آمده است.")
            in_batch.add(identity)
            try:
                amount = Decimal(str(item["amount_crypto"]))
                occurred_at = datetime.fromisoformat(item["occurred_at"])
            except (InvalidOperation, KeyError, TypeError, ValueError, OverflowError) as exc:
                raise HTTPException(status_code=409, detail="زمان یا مبلغ تراکنش معتبر نیست.") from exc
            if (
                not amount.is_finite() or amount <= 0
                or amount.as_tuple().exponent < -18
                or occurred_at.tzinfo is not None
                or not start_at <= occurred_at <= end_at
            ):
                raise HTTPException(status_code=409, detail="مبلغ یا زمان تراکنش خارج از محدوده است.")

            # Recheck all invoice statuses, including new credits since scan.
            linked_id = db.execute(
                select(CryptoDepositRequest.id).where(
                    CryptoDepositRequest.network == network,
                    CryptoDepositRequest.tx_hash == tx_hash,
                ).limit(1)
            ).scalar_one_or_none()
            if linked_id is not None:
                skipped_linked += 1
                continue

            prior = db.execute(
                select(CryptoLatePaymentCase).where(
                    CryptoLatePaymentCase.network == network,
                    CryptoLatePaymentCase.tx_hash == tx_hash,
                ).limit(1)
            ).scalar_one_or_none()
            if prior is not None:
                # A contradictory provider response must not silently overwrite
                # the original evidence snapshot.
                if (
                    prior.asset != asset or Decimal(prior.amount_crypto) != amount
                    or prior.occurred_at != occurred_at
                    or prior.destination_masked != masked
                ):
                    raise HTTPException(status_code=409, detail="شواهد قبلی همین تراکنش متفاوت است.")
                already_seen += 1
                continue

            row = CryptoLatePaymentCase(
                network=network, asset=asset, tx_hash=tx_hash,
                destination_masked=masked, amount_crypto=amount,
                occurred_at=occurred_at, confirmed_on_chain=confirmed,
                classification=classification, timing=timing,
                candidate_invoice_ids=sorted(set(candidate_ids)),
                state="OPEN", created_by=int(admin.user_id),
            )
            db.add(row)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail="درخواست هم‌زمان شناسایی شد؛ وضعیت صف را تازه کنید.") from exc
            added_ids.append(int(row.id))

        if added_ids:
            AdminAuditService.record(
                db, admin=admin, request=request,
                action="crypto.late_payment.queue.capture",
                target_type="crypto_late_payment_case",
                details={
                    "case_ids": added_ids,
                    "created_count": len(added_ids),
                    "already_seen_count": already_seen,
                    "skipped_linked_count": skipped_linked,
                    "from_at": start_at.isoformat(),
                    "to_at": end_at.isoformat(),
                    "no_wallet_mutation": True,
                },
            )
        return {
            "ok": True, "created": len(added_ids),
            "already_queued": already_seen, "already_linked": skipped_linked,
            "case_ids": added_ids, "can_auto_credit": False,
        }

    @staticmethod
    def list_cases(db: Session, *, limit: int = 50) -> list[dict[str, object]]:
        rows = db.execute(
            select(CryptoLatePaymentCase)
            .order_by(CryptoLatePaymentCase.id.desc())
            .limit(min(100, max(1, int(limit))))
        ).scalars().all()
        return [
            {
                "id": int(row.id), "network": row.network,
                "asset": row.asset, "tx_hash": row.tx_hash,
                "destination_masked": row.destination_masked,
                "amount_crypto": format(row.amount_crypto, "f"),
                "confirmed_on_chain": bool(row.confirmed_on_chain),
                "occurred_at": row.occurred_at.isoformat(),
                "classification": row.classification, "timing": row.timing,
                "candidate_invoice_ids": row.candidate_invoice_ids,
                "state": row.state,
                "created_by": int(row.created_by),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "can_auto_credit": False,
            }
            for row in rows
        ]
