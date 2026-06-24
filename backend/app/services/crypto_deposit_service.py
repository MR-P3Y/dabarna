from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto import CryptoDepositRequest
from app.models.settings import AppSetting
from app.models.wallet import WalletTx
from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_rate_service import CryptoRateService, CryptoRateUnavailable
from app.services.wallet_service import WalletService

OPEN_STATUSES = ("WAITING_PAYMENT", "CONFIRMING")
CRYPTO_RUNTIME_SETTING_KEY = "crypto_payments_runtime_enabled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CryptoDepositService:
    @staticmethod
    def configured_options() -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        warnings = set(cfg.crypto_config_warnings())
        tron_invalid = any(message.startswith("CRYPTO_TRON_USDT_") for message in warnings)
        ton_invalid = any(message.startswith("CRYPTO_TON_ADDRESS") for message in warnings)
        if cfg.CRYPTO_TRON_USDT_ENABLED and cfg.CRYPTO_TRON_USDT_ADDRESS and not tron_invalid:
            out.append(
                {
                    "network": "TRON",
                    "asset": "USDT",
                    "address": cfg.CRYPTO_TRON_USDT_ADDRESS,
                    "decimals": 6,
                }
            )
        if cfg.CRYPTO_TON_ENABLED and cfg.CRYPTO_TON_ADDRESS and not ton_invalid:
            out.append(
                {
                    "network": "TON",
                    "asset": "TON",
                    "address": cfg.CRYPTO_TON_ADDRESS,
                    "decimals": min(9, int(cfg.CRYPTO_TON_DECIMALS)),
                }
            )
        return out

    @staticmethod
    def runtime_enabled(db: Session) -> bool:
        row = db.get(AppSetting, CRYPTO_RUNTIME_SETTING_KEY)
        if row is None:
            return False
        value = row.v_json
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            value = value.get("enabled")
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, (int, float)):
            return bool(value)
        return False

    @staticmethod
    def runtime_status(db: Session) -> dict[str, object]:
        options = CryptoDepositService.configured_options()
        master_enabled = bool(cfg.CRYPTO_PAYMENTS_ENABLED)
        runtime_enabled = CryptoDepositService.runtime_enabled(db)
        return {
            "master_enabled": master_enabled,
            "runtime_enabled": runtime_enabled,
            "configured": bool(options),
            "enabled": bool(master_enabled and runtime_enabled and options),
            "options": options,
        }

    @staticmethod
    def enabled_options(db: Session) -> list[dict[str, object]]:
        status = CryptoDepositService.runtime_status(db)
        return list(status["options"]) if bool(status["enabled"]) else []

    @staticmethod
    def create_invoice(
        db: Session,
        *,
        user_id: int,
        amount_toman: int,
        network: str,
    ) -> CryptoDepositRequest:
        if not cfg.CRYPTO_PAYMENTS_ENABLED:
            raise HTTPException(status_code=503, detail="واریز ارز دیجیتال در تنظیمات سرور فعال نیست.")
        if not CryptoDepositService.runtime_enabled(db):
            raise HTTPException(status_code=503, detail="واریز ارز دیجیتال توسط مدیریت موقتاً غیرفعال شده است.")

        amount_toman = int(amount_toman or 0)
        if amount_toman < int(cfg.CRYPTO_MIN_TOMAN_AMOUNT):
            raise HTTPException(
                status_code=400,
                detail=f"حداقل مبلغ واریز ارز دیجیتال {int(cfg.CRYPTO_MIN_TOMAN_AMOUNT):,} تومان است.",
            )
        if amount_toman > int(cfg.CRYPTO_MAX_TOMAN_AMOUNT):
            raise HTTPException(
                status_code=400,
                detail=f"حداکثر مبلغ واریز ارز دیجیتال {int(cfg.CRYPTO_MAX_TOMAN_AMOUNT):,} تومان است.",
            )

        CryptoDepositService._enforce_daily_user_limits(
            db,
            user_id=int(user_id),
            requested_toman=amount_toman,
        )
        spec = CryptoDepositService._network_spec(db, network)
        try:
            quote = CryptoRateService.get_live_quote(str(spec["asset"]))
        except CryptoRateUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        buffer_multiplier = Decimal("1") + (cfg.CRYPTO_RATE_BUFFER_PERCENT / Decimal("100"))
        raw_amount = (Decimal(amount_toman) / quote.rate_toman) * buffer_multiplier
        amount_crypto = CryptoDepositService._unique_open_amount(
            db,
            network=str(spec["network"]),
            asset=str(spec["asset"]),
            raw_amount=raw_amount,
            decimals=int(spec["decimals"]),
        )
        now = _utcnow()
        public_id = secrets.token_hex(8)
        memo = f"DAV-{public_id.upper()}" if str(spec["network"]) == "TON" else None
        invoice = CryptoDepositRequest(
            public_id=public_id,
            user_id=int(user_id),
            network=str(spec["network"]),
            asset=str(spec["asset"]),
            amount_toman=amount_toman,
            rate_toman_per_asset=quote.rate_toman,
            amount_crypto=amount_crypto,
            rate_provider=quote.provider + ("-stale" if quote.is_stale else ""),
            destination_address=str(spec["address"]),
            memo=memo,
            status="WAITING_PAYMENT",
            expires_at=now + timedelta(minutes=int(cfg.CRYPTO_INVOICE_EXPIRE_MINUTES)),
            created_at=now,
            updated_at=now,
        )
        db.add(invoice)
        db.flush()
        return invoice

    @staticmethod
    def get_owned(db: Session, *, invoice_id: int, user_id: int) -> CryptoDepositRequest:
        invoice = db.execute(
            select(CryptoDepositRequest).where(
                CryptoDepositRequest.id == int(invoice_id),
                CryptoDepositRequest.user_id == int(user_id),
            )
        ).scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="فاکتور واریز ارز دیجیتال پیدا نشد.")
        return invoice

    @staticmethod
    def list_owned(
        db: Session,
        *,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CryptoDepositRequest]:
        return list(
            db.execute(
                select(CryptoDepositRequest)
                .where(CryptoDepositRequest.user_id == int(user_id))
                .order_by(CryptoDepositRequest.id.desc())
                .offset(max(0, int(offset)))
                .limit(min(100, max(1, int(limit))))
            ).scalars().all()
        )

    @staticmethod
    def claim_tx_hash(
        db: Session,
        *,
        invoice_id: int,
        user_id: int,
        tx_hash: str,
    ) -> CryptoDepositRequest:
        invoice = db.execute(
            select(CryptoDepositRequest)
            .where(
                CryptoDepositRequest.id == int(invoice_id),
                CryptoDepositRequest.user_id == int(user_id),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="فاکتور واریز ارز دیجیتال پیدا نشد.")
        if invoice.status != "WAITING_PAYMENT":
            raise HTTPException(status_code=400, detail="این فاکتور در وضعیت دریافت هش تراکنش نیست.")
        if invoice.expires_at < _utcnow():
            raise HTTPException(status_code=400, detail="مهلت پرداخت این فاکتور تمام شده است.")

        normalized = CryptoDepositService._normalize_tx_hash(invoice.network, tx_hash)
        duplicate = db.execute(
            select(CryptoDepositRequest.id).where(
                CryptoDepositRequest.network == invoice.network,
                CryptoDepositRequest.tx_hash == normalized,
                CryptoDepositRequest.id != invoice.id,
            )
        ).scalar_one_or_none()
        if duplicate:
            raise HTTPException(status_code=409, detail="این تراکنش قبلاً برای فاکتور دیگری ثبت شده است.")
        invoice.tx_hash = normalized
        invoice.updated_at = _utcnow()
        db.flush()
        return invoice

    @staticmethod
    def process_transfer(db: Session, transfer: ChainTransfer) -> CryptoDepositRequest | None:
        existing = db.execute(
            select(CryptoDepositRequest).where(
                CryptoDepositRequest.network == transfer.network,
                CryptoDepositRequest.tx_hash == transfer.tx_hash,
            )
        ).scalar_one_or_none()
        if existing and existing.status in ("CREDITED", "NEEDS_REVIEW", "REJECTED"):
            return None

        invoice = CryptoDepositService._match_invoice(db, transfer)
        if invoice is None:
            return None

        invoice = db.execute(
            select(CryptoDepositRequest)
            .where(CryptoDepositRequest.id == int(invoice.id))
            .with_for_update()
        ).scalar_one()
        if invoice.status not in OPEN_STATUSES:
            return invoice

        duplicate = db.execute(
            select(CryptoDepositRequest.id).where(
                CryptoDepositRequest.network == transfer.network,
                CryptoDepositRequest.tx_hash == transfer.tx_hash,
                CryptoDepositRequest.id != invoice.id,
            )
        ).scalar_one_or_none()
        if duplicate:
            return None

        now = _utcnow()
        invoice.tx_hash = transfer.tx_hash
        invoice.sender_address = transfer.sender_address
        invoice.paid_amount_crypto = transfer.amount
        invoice.detected_at = now
        invoice.confirmed_at = now
        invoice.last_checked_at = now
        invoice.updated_at = now
        expected = Decimal(invoice.amount_crypto)
        difference = transfer.amount - expected
        invoice.variance_amount_crypto = abs(difference)

        if difference < 0:
            invoice.payment_variance = "UNDERPAID"
            invoice.status = "NEEDS_REVIEW"
            invoice.failure_reason = "مبلغ دریافتی کمتر از مبلغ فاکتور است."
            db.flush()
            return invoice
        if difference > 0:
            invoice.payment_variance = "OVERPAID"
            invoice.status = "NEEDS_REVIEW"
            invoice.failure_reason = "مبلغ دریافتی بیشتر از مبلغ فاکتور است و نیازمند تایید ادمین است."
            db.flush()
            return invoice
        else:
            invoice.payment_variance = "EXACT"

        if int(invoice.amount_toman) >= int(cfg.CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD):
            invoice.status = "NEEDS_REVIEW"
            invoice.failure_reason = "مبلغ فاکتور نیازمند تایید ادمین است."
            db.flush()
            return invoice

        return CryptoDepositService._credit_locked_invoice(db, invoice)

    @staticmethod
    def approve_review(db: Session, *, invoice_id: int) -> tuple[CryptoDepositRequest, WalletTx]:
        invoice = db.execute(
            select(CryptoDepositRequest)
            .where(CryptoDepositRequest.id == int(invoice_id))
            .with_for_update()
        ).scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="فاکتور واریز ارز دیجیتال پیدا نشد.")
        if invoice.status != "NEEDS_REVIEW":
            raise HTTPException(status_code=400, detail="این فاکتور نیازمند بررسی ادمین نیست.")
        if not invoice.tx_hash or invoice.paid_amount_crypto is None:
            raise HTTPException(status_code=400, detail="تراکنش تاییدشده‌ای برای این فاکتور ثبت نشده است.")
        if Decimal(invoice.paid_amount_crypto) < Decimal(invoice.amount_crypto):
            raise HTTPException(status_code=400, detail="مبلغ دریافت‌شده کمتر از مبلغ فاکتور است.")
        credited = CryptoDepositService._credit_locked_invoice(db, invoice)
        tx = db.get(WalletTx, int(credited.wallet_tx_id))
        if not tx:
            raise HTTPException(status_code=500, detail="تراکنش کیف پول ثبت نشد.")
        return credited, tx

    @staticmethod
    def reject_review(db: Session, *, invoice_id: int, reason: str | None) -> CryptoDepositRequest:
        invoice = db.execute(
            select(CryptoDepositRequest)
            .where(CryptoDepositRequest.id == int(invoice_id))
            .with_for_update()
        ).scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="فاکتور واریز ارز دیجیتال پیدا نشد.")
        if invoice.status not in ("WAITING_PAYMENT", "NEEDS_REVIEW"):
            raise HTTPException(status_code=400, detail="این فاکتور قابل رد کردن نیست.")
        invoice.status = "REJECTED"
        invoice.failure_reason = str(reason or "رد شده توسط ادمین").strip()[:255]
        invoice.updated_at = _utcnow()
        db.flush()
        return invoice

    @staticmethod
    def expire_due(db: Session, *, now: datetime | None = None) -> int:
        current = now or _utcnow()
        cutoff = current - timedelta(minutes=int(cfg.CRYPTO_PAYMENT_GRACE_MINUTES))
        rows = db.execute(
            select(CryptoDepositRequest)
            .where(
                CryptoDepositRequest.status == "WAITING_PAYMENT",
                CryptoDepositRequest.expires_at < cutoff,
            )
            .with_for_update()
        ).scalars().all()
        for invoice in rows:
            invoice.status = "EXPIRED"
            invoice.failure_reason = "مهلت پرداخت فاکتور تمام شده است."
            invoice.updated_at = current
        db.flush()
        return len(rows)

    @staticmethod
    def _credit_locked_invoice(db: Session, invoice: CryptoDepositRequest) -> CryptoDepositRequest:
        if invoice.status == "CREDITED":
            return invoice
        invoice.status = "CONFIRMING"
        tx = WalletService.credit(
            db=db,
            user_id=int(invoice.user_id),
            amount=int(invoice.amount_toman),
            reason="DEPOSIT_CRYPTO",
            idempotency_key=f"crypto:{invoice.network}:{invoice.tx_hash}",
            ref_type="CRYPTO_DEPOSIT",
            ref_id=int(invoice.id),
        )
        now = _utcnow()
        invoice.status = "CREDITED"
        invoice.wallet_tx_id = int(tx.id)
        invoice.credited_at = now
        if invoice.payment_variance != "OVERPAID":
            invoice.failure_reason = None
        invoice.updated_at = now
        db.flush()
        return invoice

    @staticmethod
    def _match_invoice(db: Session, transfer: ChainTransfer) -> CryptoDepositRequest | None:
        claimed = db.execute(
            select(CryptoDepositRequest).where(
                CryptoDepositRequest.network == transfer.network,
                CryptoDepositRequest.asset == transfer.asset,
                CryptoDepositRequest.tx_hash == transfer.tx_hash,
                CryptoDepositRequest.status.in_(OPEN_STATUSES),
            )
        ).scalar_one_or_none()
        if claimed:
            if not CryptoDepositService._transfer_is_in_window(claimed, transfer):
                return None
            if claimed.memo and claimed.memo != transfer.memo:
                return None

        if transfer.memo and claimed is None:
            memo_candidates = db.execute(
                select(CryptoDepositRequest)
                .where(
                    CryptoDepositRequest.network == transfer.network,
                    CryptoDepositRequest.asset == transfer.asset,
                    CryptoDepositRequest.memo == transfer.memo,
                    CryptoDepositRequest.status.in_(OPEN_STATUSES),
                )
                .order_by(CryptoDepositRequest.id.asc())
            ).scalars().all()
            valid_memo_matches = [
                invoice
                for invoice in memo_candidates
                if CryptoDepositService._transfer_is_in_window(invoice, transfer)
            ]
            if len(valid_memo_matches) == 1:
                return valid_memo_matches[0]

        candidates = db.execute(
            select(CryptoDepositRequest)
            .where(
                CryptoDepositRequest.network == transfer.network,
                CryptoDepositRequest.asset == transfer.asset,
                CryptoDepositRequest.amount_crypto == transfer.amount,
                CryptoDepositRequest.status.in_(OPEN_STATUSES),
            )
            .order_by(CryptoDepositRequest.id.asc())
        ).scalars().all()
        valid: list[CryptoDepositRequest] = []
        for invoice in candidates:
            if not CryptoDepositService._transfer_is_in_window(invoice, transfer):
                continue
            if invoice.memo and transfer.memo and invoice.memo != transfer.memo:
                continue
            valid.append(invoice)
        if claimed:
            competing = [invoice for invoice in valid if int(invoice.id) != int(claimed.id)]
            if competing:
                return None
            return claimed
        if len(valid) == 1:
            return valid[0]
        return None

    @staticmethod
    def _transfer_is_in_window(
        invoice: CryptoDepositRequest,
        transfer: ChainTransfer,
    ) -> bool:
        if invoice.created_at and transfer.occurred_at < invoice.created_at:
            return False
        grace = timedelta(minutes=int(cfg.CRYPTO_PAYMENT_GRACE_MINUTES))
        if invoice.expires_at and transfer.occurred_at > invoice.expires_at + grace:
            return False
        return True

    @staticmethod
    def _network_spec(db: Session, network: str) -> dict[str, object]:
        normalized = str(network or "").strip().upper()
        for item in CryptoDepositService.enabled_options(db):
            if item["network"] == normalized:
                return item
        if normalized not in ("TRON", "TON"):
            raise HTTPException(status_code=400, detail="شبکه ارز دیجیتال نامعتبر است.")
        raise HTTPException(status_code=503, detail="این شبکه برای واریز تنظیم نشده است.")

    @staticmethod
    def _daily_window() -> tuple[datetime, datetime]:
        try:
            local_tz = ZoneInfo(str(cfg.CRYPTO_DAILY_TIMEZONE or "Asia/Tehran"))
        except Exception:
            local_tz = timezone.utc
        now_local = datetime.now(local_tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return (
            start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None),
        )

    @staticmethod
    def _enforce_daily_user_limits(
        db: Session,
        *,
        user_id: int,
        requested_toman: int,
    ) -> None:
        start_at, end_at = CryptoDepositService._daily_window()
        count, total = db.execute(
            select(
                func.count(CryptoDepositRequest.id),
                func.coalesce(func.sum(CryptoDepositRequest.amount_toman), 0),
            ).where(
                CryptoDepositRequest.user_id == int(user_id),
                CryptoDepositRequest.created_at >= start_at,
                CryptoDepositRequest.created_at < end_at,
            )
        ).one()
        max_count = int(cfg.CRYPTO_DAILY_USER_MAX_COUNT)
        max_toman = int(cfg.CRYPTO_DAILY_USER_MAX_TOMAN)
        if max_count > 0 and int(count or 0) >= max_count:
            raise HTTPException(
                status_code=429,
                detail=f"سقف روزانه صدور فاکتور ارز دیجیتال ({max_count} فاکتور) تکمیل شده است.",
            )
        projected = int(total or 0) + int(requested_toman)
        if max_toman > 0 and projected > max_toman:
            remaining = max(0, max_toman - int(total or 0))
            raise HTTPException(
                status_code=429,
                detail=f"سقف مبلغ روزانه ارز دیجیتال تکمیل شده است. ظرفیت باقی‌مانده: {remaining:,} تومان.",
            )

    @staticmethod
    def _unique_open_amount(
        db: Session,
        *,
        network: str,
        asset: str,
        raw_amount: Decimal,
        decimals: int,
    ) -> Decimal:
        safe_decimals = min(18, max(1, int(decimals)))
        unit = Decimal("1").scaleb(-safe_decimals)
        amount = raw_amount.quantize(unit, rounding=ROUND_UP)
        for _ in range(10_000):
            exists = db.execute(
                select(CryptoDepositRequest.id).where(
                    CryptoDepositRequest.network == network,
                    CryptoDepositRequest.asset == asset,
                    CryptoDepositRequest.amount_crypto == amount,
                    CryptoDepositRequest.status.in_(OPEN_STATUSES),
                )
            ).scalar_one_or_none()
            if not exists:
                return amount
            amount += unit
        raise HTTPException(status_code=503, detail="صدور مبلغ یکتای فاکتور ممکن نشد. کمی بعد دوباره تلاش کنید.")

    @staticmethod
    def _normalize_tx_hash(network: str, tx_hash: str) -> str:
        value = str(tx_hash or "").strip()
        if str(network).upper() == "TRON":
            if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
                raise HTTPException(status_code=400, detail="هش تراکنش ترون نامعتبر است.")
            return value.lower()
        if not re.fullmatch(r"[A-Za-z0-9_+/=-]{20,160}", value):
            raise HTTPException(status_code=400, detail="هش تراکنش تون نامعتبر است.")
        return value
