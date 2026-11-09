"""Restricted MySQL integration for durable historical review queue (#30).

This test runs only in the fixed, new, isolated MySQL test database created
by the paired runner. No wallet tables or live blockchain access are present.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.admin_guard import AdminIdentity, AdminScope
from app.models.user import User
from app.models.admin_audit import AdminAuditLog
from app.models.crypto_late_payment_case import CryptoLatePaymentCase
from app.services.crypto_late_payment_review_service import CryptoLatePaymentReviewService
from app.services.crypto_late_payment_queue_service import CryptoLatePaymentQueueService


DB = "davarna_crypto_queue_test_20261109"
USERNAME = "davarna_rot_queue_0015"


def run() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("BLOCKER: missing test DATABASE_URL")
    parsed = make_url(url)
    if (
        os.environ.get("DAVARNA_CRYPTO_QUEUE_SCOPE") != "ISOLATED_QUEUE_ONLY"
        or parsed.get_backend_name() != "mysql"
        or parsed.host != "davarna-mysql"
        or parsed.database != DB
        or parsed.username != USERNAME
    ):
        raise SystemExit("BLOCKER: refused non-isolated MySQL connection")

    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        if conn.execute(text("SELECT DATABASE()")).scalar_one() != DB:
            raise SystemExit("BLOCKER: wrong MySQL database")
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
        )).scalar_one()
        if count:
            raise SystemExit("BLOCKER: test database contains existing tables")
        User.__table__.create(conn)
        conn.execute(text(
            "INSERT INTO users (id, tg_user_id, first_name) "
            "VALUES (91001, 9910091001, 'synthetic')"
        ))
        # Only the three columns required for *read-only* linked-hash check.
        conn.execute(text(
            "CREATE TABLE crypto_deposit_requests ("
            "id BIGINT PRIMARY KEY, network VARCHAR(8) NOT NULL, "
            "tx_hash VARCHAR(160) NULL) ENGINE=InnoDB"
        ))

    config = Config("/app/alembic.ini")
    command.stamp(config, "20261108_0012")
    command.upgrade(config, "20261109_0015")
    AdminAuditLog.__table__.create(engine)

    inspector = inspect(engine)
    assert inspector.has_table("crypto_late_payment_cases")
    assert "ix_crypto_late_case_state_created" in {
        item["name"] for item in inspector.get_indexes("crypto_late_payment_cases")
    }
    assert {"created_by"} <= {
        col for fk in inspector.get_foreign_keys("crypto_late_payment_cases")
        for col in fk["constrained_columns"]
    }
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261109_0015"

    end = datetime(2026, 11, 9, 20, 0)
    start = end - timedelta(hours=24)
    item = {
        "network": "TON", "asset": "TON", "tx_hash": "synthetic-history-hash",
        "destination_masked": "EQABCD…123456",
        "amount_crypto": "0.500000000",
        "occurred_at": (end - timedelta(hours=4)).isoformat(),
        "confirmed_on_chain": True,
        "classification": "POSSIBLE_HISTORICAL_MATCH",
        "timing": "AFTER_INVOICE_WINDOW",
        "candidate_invoice_ids": [112233],
        "can_auto_credit": False,
    }
    report = {
        "ok": True, "read_only": True, "can_auto_credit": False,
        "review_needed_count": 1, "items": [item],
    }
    actor = AdminIdentity(
        scope=AdminScope.SUPER_ADMIN, token="SYNTHETIC", user_id=91001,
    )
    with Session(engine, expire_on_commit=False) as db:
        with patch.object(CryptoLatePaymentReviewService, "scan", return_value=report):
            result = CryptoLatePaymentQueueService.capture(
                db, start_at=start, end_at=end, admin=actor,
            )
            db.commit()
            assert result["created"] == 1
            again = CryptoLatePaymentQueueService.capture(
                db, start_at=start, end_at=end, admin=actor,
            )
            db.commit()
            assert again["created"] == 0 and again["already_queued"] == 1

        row = db.scalar(select(CryptoLatePaymentCase))
        assert row and row.tx_hash == item["tx_hash"] and row.state == "OPEN"
        assert row.candidate_invoice_ids == [112233]
        assert db.scalar(select(func.count()).select_from(CryptoLatePaymentCase)) == 1
        assert db.scalar(select(func.count()).select_from(AdminAuditLog)) == 1
        audit = db.scalar(select(AdminAuditLog))
        assert audit.action == "crypto.late_payment.queue.capture"
        assert audit.details_json["no_wallet_mutation"] is True

        with patch.object(CryptoLatePaymentReviewService, "scan", return_value={
            **report, "items": [{**item, "tx_hash": "rollback-test-hash"}],
        }):
            CryptoLatePaymentQueueService.capture(
                db, start_at=start, end_at=end, admin=actor,
            )
            db.rollback()
        assert db.scalar(select(func.count()).select_from(CryptoLatePaymentCase)) == 1
        assert db.scalar(select(func.count()).select_from(AdminAuditLog)) == 1

    with engine.connect() as conn:
        names = {row[0] for row in conn.execute(text("SHOW TABLES"))}
        assert "wallets" not in names and "wallet_txs" not in names
        assert conn.execute(text("SELECT COUNT(*) FROM crypto_deposit_requests")).scalar_one() == 0
    engine.dispose()
    print("PASS: isolated MySQL migration 0015, FK/index and unique historical transaction queue")
    print("PASS: one persisted case + one audit, duplicate capture idempotent, rollback atomic")
    print("PASS: test schema contains no wallet/ledger tables and no invoice mutations")


if __name__ == "__main__":
    run()
