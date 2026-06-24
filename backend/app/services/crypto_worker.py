from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core import config as cfg
from app.core.db import SessionLocal
from app.core.redis_client import RedisLock
from app.models.crypto import CryptoDepositRequest
from app.services.crypto_chain_service import CryptoChainService
from app.services.crypto_deposit_service import CryptoDepositService, OPEN_STATUSES

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CryptoDepositWorker:
    @staticmethod
    def run_once() -> dict[str, int]:
        stats = {"transfers": 0, "matched": 0, "credited": 0, "review": 0, "expired": 0}
        lock = RedisLock(
            "davarna:crypto-deposit-worker",
            ttl_ms=max(30_000, int(cfg.CRYPTO_CONFIRM_INTERVAL_SEC) * 3_000),
        )
        lock_owned = False
        lock_available = True
        try:
            lock_owned = lock.acquire()
        except Exception as exc:
            lock_available = False
            log.warning("crypto worker lock unavailable; relying on database idempotency: %s", exc)
        if lock_available and not lock_owned:
            return stats

        try:
            return CryptoDepositWorker._process_cycle(stats)
        finally:
            if lock_owned:
                try:
                    lock.release()
                except Exception:
                    log.warning("crypto worker lock release failed", exc_info=True)

    @staticmethod
    def _process_cycle(stats: dict[str, int]) -> dict[str, int]:
        for network in ("TRON", "TON"):
            if not CryptoDepositWorker._network_has_open_invoices(network):
                continue
            since = CryptoDepositWorker._network_scan_since(network)
            try:
                transfers = CryptoChainService.list_incoming(network=network, since=since)
            except Exception as exc:
                log.warning("crypto chain scan failed: network=%s error=%s", network, exc)
                continue
            stats["transfers"] += len(transfers)
            for transfer in transfers:
                with SessionLocal() as db:
                    try:
                        invoice = CryptoDepositService.process_transfer(db, transfer)
                        if invoice is None:
                            db.rollback()
                            continue
                        db.commit()
                        stats["matched"] += 1
                        if invoice.status == "CREDITED":
                            stats["credited"] += 1
                        elif invoice.status == "NEEDS_REVIEW":
                            stats["review"] += 1
                    except Exception as exc:
                        db.rollback()
                        log.exception(
                            "crypto transfer processing failed: network=%s tx_hash=%s error=%s",
                            transfer.network,
                            transfer.tx_hash,
                            exc,
                        )

        with SessionLocal() as db:
            try:
                stats["expired"] = CryptoDepositService.expire_due(db)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("crypto invoice expiration failed")
        return stats

    @staticmethod
    def _network_has_open_invoices(network: str) -> bool:
        with SessionLocal() as db:
            count = db.execute(
                select(func.count(CryptoDepositRequest.id)).where(
                    CryptoDepositRequest.network == network,
                    CryptoDepositRequest.status.in_(OPEN_STATUSES),
                )
            ).scalar_one()
            return int(count or 0) > 0

    @staticmethod
    def _network_scan_since(network: str) -> datetime:
        floor = _utcnow() - timedelta(hours=int(cfg.CRYPTO_SCAN_LOOKBACK_HOURS))
        with SessionLocal() as db:
            earliest = db.execute(
                select(func.min(CryptoDepositRequest.created_at)).where(
                    CryptoDepositRequest.network == network,
                    CryptoDepositRequest.status.in_(OPEN_STATUSES),
                )
            ).scalar_one_or_none()
        if isinstance(earliest, datetime) and earliest > floor:
            return earliest - timedelta(minutes=2)
        return floor


async def run_crypto_worker_forever(stop_event: asyncio.Event) -> None:
    interval = max(10, int(cfg.CRYPTO_CONFIRM_INTERVAL_SEC))
    while not stop_event.is_set():
        try:
            stats = await asyncio.to_thread(CryptoDepositWorker.run_once)
            if stats["matched"] or stats["expired"]:
                log.info("crypto worker cycle: %s", stats)
        except Exception:
            log.exception("crypto worker cycle failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
