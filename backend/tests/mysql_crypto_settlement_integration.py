"""Real service+ledger integration against a *fresh* restricted MySQL schema (#30).

No chain API, Production wallet or real address. Reads actual app models and
CryptoDepositService.process_transfer / WalletService.credit without mocks.
Run only through dev/release/test-crypto-settlement-mysql-20261109.sh.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.user import User
from app.models.wallet import Wallet, WalletTx
from app.models.crypto import CryptoDepositRequest
from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_chain_service import ChainTransfer
from app.services.crypto_deposit_service import CryptoDepositService

DB = "davarna_crypto_settlement_test_20261109"
USER = "davarna_rot_settle_0014"


def ton(seed: int) -> str:
    raw = bytes([0x11, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(raw + _crc16_xmodem(raw)).decode().rstrip("=")


def transfer(address: str, txhash: str, amount: str, time: datetime, *, final: bool) -> ChainTransfer:
    return ChainTransfer(
        network="TON", asset="TON", tx_hash=txhash,
        amount=Decimal(amount), sender_address=ton(5),
        destination_address=address, occurred_at=time,
        confirmed=final, confirmations=1 if final else 0,
    )


def check(db: Session, user_id: int, balance: int, ledger_count: int) -> None:
    w = db.execute(select(Wallet).where(Wallet.user_id == user_id)).scalar_one()
    actual_tx = db.scalar(select(func.count()).select_from(WalletTx))
    assert int(w.balance) == balance, f"balance drift: {w.balance} != {balance}"
    assert int(actual_tx) == ledger_count, f"ledger drift: {actual_tx} != {ledger_count}"


def invoice(db: Session, *, label: str, address: str, amount: str,
            created: datetime, expires: datetime, state="WAITING_PAYMENT") -> CryptoDepositRequest:
    item = CryptoDepositRequest(
        public_id=label, user_id=91001, network="TON", asset="TON",
        amount_toman=50000, rate_toman_per_asset=Decimal("100000"),
        amount_crypto=Decimal(amount), rate_provider="synthetic",
        destination_address=address, status=state,
        created_at=created, expires_at=expires,
    )
    db.add(item)
    db.flush()
    return item


def run() -> None:
    raw = os.getenv("DATABASE_URL", "")
    if not raw:
        raise SystemExit("BLOCKER: DATABASE_URL missing")
    target = make_url(raw)
    if (
        os.getenv("DAVARNA_CRYPTO_SETTLEMENT_SCOPE") != "ISOLATED_SETTLEMENT_ONLY"
        or target.get_backend_name() != "mysql"
        or target.host != "davarna-mysql"
        or target.database != DB
        or target.username != USER
    ):
        raise SystemExit("BLOCKER: settlement test refused non-test connection")
    engine = create_engine(raw, pool_pre_ping=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT DATABASE()")).scalar_one() == DB
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).scalar_one()
        if count != 0:
            raise SystemExit("BLOCKER: test schema not empty; inspect before retry")

    # Only tables required for this isolated integration. Avoid copying
    # financial rows or touching the real Alembic revision.
    from app.core.db import Base
    Base.metadata.create_all(engine, tables=[
        User.__table__, Wallet.__table__, WalletTx.__table__,
        CryptoDepositRequest.__table__,
    ])

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old, new, other = ton(1), ton(2), ton(3)
    with patch.object(cfg, "CRYPTO_ADMIN_REVIEW_TOMAN_THRESHOLD", 1_000_000_000):
        with Session(engine, expire_on_commit=False) as db:
            db.add(User(id=91001, tg_user_id=991001001))
            db.add(Wallet(user_id=91001, balance=0))
            db.commit()
            old_invoice = invoice(
                db, label="synthetic-old", address=old, amount="0.5",
                created=now - timedelta(minutes=10),
                expires=now + timedelta(minutes=5),
            )
            new_invoice = invoice(
                db, label="synthetic-new", address=new, amount="0.7",
                created=now - timedelta(minutes=10),
                expires=now + timedelta(minutes=5),
            )
            invalid_match = invoice(
                db, label="synthetic-wrong-address", address=new, amount="0.9",
                created=now - timedelta(minutes=10),
                expires=now + timedelta(minutes=5),
            )
            expired = invoice(
                db, label="synthetic-expired", address=old, amount="1.1",
                created=now - timedelta(days=3),
                expires=now - timedelta(days=3) + timedelta(minutes=15),
                state="EXPIRED",
            )
            db.commit()
            check(db, 91001, 0, 0)

            # Real processor credits old-pinned invoice exactly once.
            exact_old = transfer(old, "synthetic-hash-old", "0.5", now, final=True)
            credited = CryptoDepositService.process_transfer(db, exact_old)
            assert credited and credited.id == old_invoice.id and credited.status == "CREDITED"
            db.commit()
            check(db, 91001, 50000, 1)
            assert CryptoDepositService.process_transfer(db, exact_old) is None
            db.commit()
            check(db, 91001, 50000, 1)

            # Newly pinned destination supports pending -> final transition.
            pending_new = transfer(new, "synthetic-hash-new", "0.7", now, final=False)
            pending = CryptoDepositService.process_transfer(db, pending_new)
            assert pending and pending.id == new_invoice.id and pending.status == "CONFIRMING"
            db.commit()
            check(db, 91001, 50000, 1)
            confirmed_new = transfer(new, "synthetic-hash-new", "0.7", now, final=True)
            credited_new = CryptoDepositService.process_transfer(db, confirmed_new)
            assert credited_new and credited_new.id == new_invoice.id
            assert credited_new.status == "CREDITED"
            db.commit()
            check(db, 91001, 100000, 2)

            # A user-claimed hash with an amount discrepancy must be
            # REVIEW-only; it cannot credit the wallet automatically.
            underpaid = invoice(
                db, label="synthetic-underpaid", address=new, amount="0.8",
                created=now - timedelta(minutes=10),
                expires=now + timedelta(minutes=5),
            )
            overpaid = invoice(
                db, label="synthetic-overpaid", address=new, amount="0.9",
                created=now - timedelta(minutes=10),
                expires=now + timedelta(minutes=5),
            )
            underpaid.tx_hash = "synthetic-hash-underpaid"
            overpaid.tx_hash = "synthetic-hash-overpaid"
            db.commit()
            under_result = CryptoDepositService.process_transfer(
                db, transfer(new, "synthetic-hash-underpaid", "0.6", now, final=True),
            )
            assert under_result and under_result.id == underpaid.id
            assert under_result.status == "NEEDS_REVIEW"
            assert under_result.payment_variance == "UNDERPAID"
            db.commit()
            check(db, 91001, 100000, 2)
            over_result = CryptoDepositService.process_transfer(
                db, transfer(new, "synthetic-hash-overpaid", "1.0", now, final=True),
            )
            assert over_result and over_result.id == overpaid.id
            assert over_result.status == "NEEDS_REVIEW"
            assert over_result.payment_variance == "OVERPAID"
            db.commit()
            check(db, 91001, 100000, 2)
            assert CryptoDepositService.process_transfer(
                db, transfer(new, "synthetic-hash-underpaid", "0.6", now, final=True),
            ) is None
            db.rollback()

            # Same amount on *another* destination must never match this invoice.
            wrong = transfer(other, "synthetic-hash-wrong", "0.9", now, final=True)
            assert CryptoDepositService.process_transfer(db, wrong) is None
            db.rollback()
            check(db, 91001, 100000, 2)
            assert db.get(CryptoDepositRequest, invalid_match.id).status == "WAITING_PAYMENT"

            # Already EXPIRED invoices must not be silently auto-credited, even
            # if their transfer timestamp falls inside the historic valid window.
            on_time_but_seen_later = transfer(
                old, "synthetic-hash-late", "1.1",
                expired.created_at + timedelta(minutes=5), final=True,
            )
            assert CryptoDepositService.process_transfer(db, on_time_but_seen_later) is None
            db.rollback()
            check(db, 91001, 100000, 2)
            assert db.get(CryptoDepositRequest, expired.id).status == "EXPIRED"

            # Replay as an entirely new hash and mismatched recipient can't credit.
            assert CryptoDepositService.process_transfer(
                db, transfer(other, "synthetic-hash-new-other", "0.5", now, final=True),
            ) is None
            db.rollback()
            check(db, 91001, 100000, 2)

            # Verify a failed, uncommitted credit can be rolled back atomically.
            rollback_invoice = invoice(
                db, label="synthetic-rollback", address=new, amount="1.3",
                created=now - timedelta(minutes=10),
                expires=now + timedelta(minutes=5),
            )
            db.commit()
            attempted = CryptoDepositService.process_transfer(
                db, transfer(new, "synthetic-hash-rollback", "1.3", now, final=True),
            )
            assert attempted and attempted.status == "CREDITED"
            db.rollback()
            check(db, 91001, 100000, 2)
            db.refresh(rollback_invoice)
            assert rollback_invoice.status == "WAITING_PAYMENT"
            assert rollback_invoice.wallet_tx_id is None

            rows = db.execute(select(WalletTx).order_by(WalletTx.id)).scalars().all()
            assert len(rows) == 2 and all(x.reason == "DEPOSIT_CRYPTO" for x in rows)
            assert len({x.idempotency_key for x in rows}) == 2
            assert {x.ref_id for x in rows} == {old_invoice.id, new_invoice.id}
            print("PASS: old/new pinned invoices, pending->final, replay, wrong destination and expired no-credit")
            print("PASS: underpaid/overpaid verified claims require review, never auto-credit")
            print("PASS: wallet 100000; exactly 2 ledger credits; rollback leaves invoice and balance unchanged")
    engine.dispose()


if __name__ == "__main__":
    run()
