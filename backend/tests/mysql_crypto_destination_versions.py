"""Isolated MySQL schema migration contract for crypto address versions (#30).

Run only using dev/release/test-crypto-destinations-mysql-20261109.sh.
Never execute on Production or a DB with existing business tables.
"""
from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

TEST_DB = "davarna_crypto_rotation_test_20261109_0013"
TEST_USER = "davarna_rot_stage_0013"


def run() -> None:
    url = os.environ.get("DATABASE_URL", "")
    parsed = make_url(url)
    if (
        os.environ.get("DAVARNA_ROTATION_MYSQL_TEST_SCOPE") != "TEST_SCHEMA_ONLY"
        or parsed.get_backend_name() != "mysql"
        or parsed.host != "davarna-mysql"
        or parsed.database != TEST_DB
        or parsed.username != TEST_USER
    ):
        raise SystemExit("BLOCKER: not connected to the isolated migration test schema")

    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        if conn.execute(text("SELECT DATABASE()")).scalar_one() != TEST_DB:
            raise SystemExit("BLOCKER: database name mismatch")
        existing = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()"
        )).scalar_one()
        if existing:
            raise SystemExit("BLOCKER: migration test schema already contains tables")
        conn.execute(text("CREATE TABLE users (id BIGINT NOT NULL PRIMARY KEY) ENGINE=InnoDB"))
        conn.execute(text("INSERT INTO users (id) VALUES (91001), (91002)"))

    os.chdir("/app")
    config = Config("/app/alembic.ini")
    command.stamp(config, "20261108_0012")
    command.upgrade(config, "20261109_0013")
    with engine.connect() as conn:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20261109_0013", f"unexpected migration {revision}"
        insp = inspect(conn)
        assert insp.has_table("crypto_destination_versions")
        columns = {c["name"]: c for c in insp.get_columns("crypto_destination_versions")}
        assert set(("id", "network", "asset", "address", "version", "state",
                    "requested_by", "activated_by", "reason", "operation_id",
                    "created_at", "activated_at", "retired_at")) <= set(columns)
        for name in ("activated_by", "activated_at", "retired_at"):
            assert columns[name]["nullable"], f"{name} must allow null"
        assert not columns["address"]["nullable"]
        indexes = insp.get_indexes("crypto_destination_versions")
        index_names = {x["name"] for x in indexes}
        assert "ix_crypto_dest_network_state" in index_names
        foreign_keys = {c for row in insp.get_foreign_keys("crypto_destination_versions")
                        for c in row["constrained_columns"]}
        assert {"requested_by", "activated_by"} <= foreign_keys

    statement = text(
        "INSERT INTO crypto_destination_versions "
        "(network, asset, address, version, state, requested_by, reason, operation_id) "
        "VALUES (:network, :asset, :address, :version, :state, :requested_by, :reason, :operation_id)"
    )
    sample = dict(network="TON", asset="TON", address="test-fixture-not-live", version=1,
                  state="DRAFT", requested_by=91001, reason="synthetic migration test",
                  operation_id="synthetic-op-001")
    with engine.begin() as conn:
        conn.execute(statement, sample)

    # A duplicate operation ID and duplicate network/asset version must fail.
    for changes in ({"operation_id": "synthetic-op-001", "version": 2},
                    {"operation_id": "synthetic-op-002", "version": 1}):
        duplicate = dict(sample, **changes)
        try:
            with engine.begin() as conn:
                conn.execute(statement, duplicate)
        except IntegrityError:
            pass
        else:
            raise SystemExit("BLOCKER: migration uniqueness constraint not enforced")

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM crypto_destination_versions")).scalar_one() == 1
    engine.dispose()
    print("PASS: isolated MySQL migration 20261109_0013, FKs, indexes, nullable and uniqueness checks")


if __name__ == "__main__":
    run()
