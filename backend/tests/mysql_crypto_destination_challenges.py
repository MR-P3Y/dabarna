"""Real MySQL smoke test of the inert confirmation schema and one-use challenge.

The paired runner creates a new test-only schema and restricted login. It must
NOT be run using any Production connection, nor does it activate any address.
"""
from __future__ import annotations

import base64
import os
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core import config as cfg
from app.models.crypto_destination_challenge import CryptoDestinationChallenge
from app.models.crypto_destination_version import CryptoDestinationVersion
from app.services.crypto_address_rotation_validation import _crc16_xmodem
from app.services.crypto_destination_draft_service import CryptoDestinationDraftService
from app.services.crypto_destination_confirmation_service import CryptoDestinationConfirmationService

DB = "davarna_crypto_challenge_test_20261109"
USER = "davarna_rot_chal_0014"


def ton_addr(seed: int) -> str:
    raw = bytes([0x11, 0]) + bytes([seed]) * 32
    return base64.urlsafe_b64encode(raw + _crc16_xmodem(raw)).decode().rstrip("=")


def run() -> None:
    parsed = make_url(os.getenv("DATABASE_URL", ""))
    if (
        os.getenv("DAVARNA_CHALLENGE_TEST_SCOPE") != "ISOLATED_CHALLENGE_ONLY"
        or parsed.get_backend_name() != "mysql"
        or parsed.host != "davarna-mysql"
        or parsed.database != DB
        or parsed.username != USER
    ):
        raise SystemExit("BLOCKER: this test requires the exact isolated MySQL user and schema")
    engine = create_engine(parsed, pool_pre_ping=True)
    with engine.begin() as conn:
        if conn.execute(text("SELECT DATABASE()")).scalar_one() != DB:
            raise SystemExit("BLOCKER: wrong database")
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()"
        )).scalar_one()
        if count:
            raise SystemExit("BLOCKER: expected empty test schema")
        conn.execute(text("CREATE TABLE users (id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"))
        conn.execute(text("INSERT INTO users (id) VALUES (91001)"))
        conn.execute(text(
            "CREATE TABLE crypto_deposit_requests ("
            "id BIGINT PRIMARY KEY, network VARCHAR(8) NOT NULL, "
            "status VARCHAR(32) NOT NULL, destination_address VARCHAR(128) NOT NULL"
            ") ENGINE=InnoDB"
        ))

    config = Config("/app/alembic.ini")
    command.stamp(config, "20261108_0012")
    command.upgrade(config, "20261109_0014")
    insp = inspect(engine)
    assert "previous_address" in {
        col["name"] for col in insp.get_columns("crypto_destination_versions")
    }
    assert insp.has_table("crypto_destination_challenges")
    assert "ix_crypto_challenge_draft_expiry" in {
        ind["name"] for ind in insp.get_indexes("crypto_destination_challenges")
    }
    challenge_fks = {
        col for item in insp.get_foreign_keys("crypto_destination_challenges")
        for col in item["constrained_columns"]
    }
    assert challenge_fks == {"draft_id", "actor_id"}

    with patch.object(cfg, "CRYPTO_TON_ADDRESS", ton_addr(1)):
        with Session(engine) as db:
            draft, replayed, _ = CryptoDestinationDraftService.create_draft(
                db, network="TON", address=ton_addr(2),
                reason="synthetic MySQL confirmation test", expected_version=0,
                operation_id="mysql-confirm-operation-001", actor_id=91001,
            )
            assert not replayed
            db.commit()
            assert draft.previous_address == ton_addr(1)

            challenge, secret, _ = CryptoDestinationConfirmationService.prepare(
                db, draft_id=draft.id, actor_id=91001,
            )
            db.commit()
            assert secret != challenge.secret_digest

            confirmed, row = CryptoDestinationConfirmationService.confirm(
                db, draft_id=draft.id, challenge_id=challenge.id,
                token=secret, confirmed_address=ton_addr(2), actor_id=91001,
            )
            db.commit()
            assert confirmed.consumed_at is not None
            assert row.state == "DRAFT"  # never ACTIVE
            try:
                CryptoDestinationConfirmationService.confirm(
                    db, draft_id=draft.id, challenge_id=challenge.id,
                    token=secret, confirmed_address=ton_addr(2), actor_id=91001,
                )
            except HTTPException as exc:
                assert exc.status_code == 409
                db.rollback()
            else:
                raise SystemExit("BLOCKER: replayed MySQL confirmation was not rejected")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261109_0014"
        assert conn.execute(text("SELECT COUNT(*) FROM crypto_destination_versions")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM crypto_destination_challenges WHERE consumed_at IS NOT NULL")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM crypto_deposit_requests")).scalar_one() == 0
    engine.dispose()
    print("PASS: MySQL confirmation migration 0014, FK/index/snapshot and one-time review")
    print("PASS: no activation, no crypto invoices or financial rows modified")


if __name__ == "__main__":
    run()
