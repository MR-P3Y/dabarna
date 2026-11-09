"""Real isolated MySQL concurrency tests for draft address versioning.

Requires dedicated mysql database and low-privilege login provisioned by the
paired release test script. No Production DB access, no external chain API.
"""
from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto_destination_version import CryptoDestinationVersion
from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_destination_draft_service import CryptoDestinationDraftService

TEST_DATABASE = "davarna_crypto_race_test_20261109"
TEST_USERNAME = "davarna_rot_race_0013"


def ton_address(seed: int) -> str:
    body = bytes([0x11, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(body + _crc16_xmodem(body)).decode().rstrip("=")


def run() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("BLOCKER: no isolated MySQL connection configured")
    parsed = make_url(url)
    if (
        os.getenv("DAVARNA_ROTATION_RACE_SCOPE") != "ISOLATED_RACE_ONLY"
        or parsed.get_backend_name() != "mysql"
        or parsed.host != "davarna-mysql"
        or parsed.database != TEST_DATABASE
        or parsed.username != TEST_USERNAME
    ):
        raise SystemExit("BLOCKER: isolated MySQL identity mismatch")

    engine = create_engine(url, pool_size=4, max_overflow=0, pool_pre_ping=True)
    with engine.begin() as conn:
        if conn.execute(text("SELECT DATABASE()")).scalar_one() != TEST_DATABASE:
            raise SystemExit("BLOCKER: wrong database")
        n = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()"
        )).scalar_one()
        if n:
            raise SystemExit("BLOCKER: test DB not empty")
        conn.execute(text("CREATE TABLE users (id BIGINT PRIMARY KEY) ENGINE=InnoDB"))
        conn.execute(text("INSERT INTO users (id) VALUES (91001)"))
        conn.execute(text(
            "CREATE TABLE crypto_deposit_requests ("
            "id BIGINT PRIMARY KEY, network VARCHAR(8) NOT NULL, "
            "status VARCHAR(32) NOT NULL, destination_address VARCHAR(128) NOT NULL"
            ") ENGINE=InnoDB"
        ))

    command.stamp(Config("/app/alembic.ini"), "20261108_0012")
    command.upgrade(Config("/app/alembic.ini"), "20261109_0013")
    old = ton_address(1)
    start = Barrier(2)

    def submit(seed: int) -> tuple[str, int]:
        with Session(engine) as db:
            start.wait(timeout=12)
            try:
                row, replay, _ = CryptoDestinationDraftService.create_draft(
                    db=db, network="TON", address=ton_address(seed),
                    reason="synthetic concurrent version test",
                    expected_version=0, operation_id=f"race-operation-{seed}",
                    actor_id=91001,
                )
                assert not replay
                db.commit()
                return ("accepted", int(row.id))
            except HTTPException as exc:
                db.rollback()
                if exc.status_code != 409:
                    raise
                return ("conflict", exc.status_code)

    with patch.object(cfg, "CRYPTO_TON_ADDRESS", old):
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(submit, 2)
            b = pool.submit(submit, 3)
            results = [a.result(timeout=30), b.result(timeout=30)]
    kinds = sorted(x[0] for x in results)
    if kinds != ["accepted", "conflict"]:
        raise SystemExit(f"BLOCKER: concurrent draft race result={kinds}")
    with Session(engine) as db:
        rows = db.query(CryptoDestinationVersion).all()
        assert len(rows) == 1 and rows[0].version == 1 and rows[0].state == "DRAFT"
        stored_address, stored_operation = rows[0].address, rows[0].operation_id
        with patch.object(cfg, "CRYPTO_TON_ADDRESS", old):
            replay, was_replay, _ = CryptoDestinationDraftService.create_draft(
                db=db, network="TON", address=stored_address,
                reason="synthetic concurrent version test", expected_version=0,
                operation_id=stored_operation, actor_id=91001,
            )
        assert was_replay and replay.id == rows[0].id
        assert db.execute(text("SELECT COUNT(*) FROM crypto_deposit_requests")).scalar_one() == 0
    engine.dispose()
    print("PASS: concurrent MySQL draft CAS rejects loser, persists exactly one, replay idempotent")
    print("PASS: no invoice, wallet, or Production data changed")


if __name__ == "__main__":
    run()
