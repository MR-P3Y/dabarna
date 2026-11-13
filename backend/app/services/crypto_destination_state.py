"""Experimental atomic wallet destination state. NEVER enabled by default.

A pre-existing app_settings row is required before activation or invoice issue in
rotation mode: locking a missing row does not protect against concurrent writers.
"""
from __future__ import annotations

import os

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import AppSetting
from app.services.crypto_address_change import validate_crypto_destination, same_crypto_destination

ROTATION_GATE = "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL"
KEY_PREFIX = "crypto_destination_v1:"


PRODUCTION_GATE = "DAVARNA_CRYPTO_ROTATION_PRODUCTION"
PRODUCTION_APPROVAL = "I_ACK_REAL_FUNDS_PRODUCTION_WALLET_ROTATION"


def production_rotation_enabled() -> bool:
    """Explicit two-variable opt-in; never infer Production from a test flag.

    The actual MySQL schema name must be pinned independently. There is no
    default and no wildcard. Turning the gate on is NOT permission to change
    any active address; each API call still requires owner auth, frozen
    crypto issuance, an unchanged version and a clean readiness assessment.
    """
    from sqlalchemy.engine import make_url
    if os.getenv(PRODUCTION_GATE, "") != PRODUCTION_APPROVAL:
        return False
    approved_schema = os.getenv("DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB", "").strip()
    if not approved_schema or approved_schema == "davarna_wallet_rotation_test":
        return False
    try:
        url = make_url(os.getenv("DATABASE_URL", ""))
    except Exception:
        return False
    approved_host = os.getenv("DAVARNA_CRYPTO_ROTATION_PRODUCTION_DB_HOST", "mysql").strip()
    if approved_host not in {"mysql", "davarna-zero-mysql-20261110"}:
        return False
    return (
        url.get_backend_name() == "mysql"
        and url.host == approved_host
        and url.database == approved_schema
    )


def disposable_rotation_enabled() -> bool:
    """Only the strictly isolated MySQL harness may invoke experimental APIs."""
    from sqlalchemy.engine import make_url
    if os.getenv(ROTATION_GATE, "").strip() != "I_ACK_DISPOSABLE_DB_ONLY":
        return False
    try:
        url = make_url(os.getenv("DATABASE_URL", ""))
    except Exception:
        return False
    return (url.get_backend_name() == "mysql"
            and url.host == "davarna-wallet-mysql"
            and url.database == "davarna_wallet_rotation_test")


def rotation_enabled() -> bool:
    return disposable_rotation_enabled() or production_rotation_enabled()


def state_key(network: str) -> str:
    if network not in ("TRON", "TON"):
        raise ValueError("unsupported network")
    return KEY_PREFIX + network


def lock_destination_state(db: Session, network: str) -> dict[str, object]:
    """Lock same row that rotation transaction will update. No implicit INSERT."""
    row = db.execute(select(AppSetting).where(
        AppSetting.k == state_key(network)
    ).with_for_update()).scalar_one_or_none()
    if row is None or not isinstance(row.v_json, dict):
        raise HTTPException(status_code=503, detail="نسخه آدرس کیف پول آماده نیست؛ تغییرات متوقف است.")
    record = dict(row.v_json)
    if record.get("network") != network or type(record.get("version")) is not int or record["version"] < 1:
        raise HTTPException(status_code=409, detail="ساختار نسخه‌بندی آدرس نامعتبر است.")
    try:
        record["address"] = validate_crypto_destination(network, record.get("address"))
    except ValueError:
        raise HTTPException(status_code=409, detail="آدرس فعال ثبت‌شده نامعتبر است.") from None
    return record


def rotate_locked(
    db: Session, *, network: str, expected_version: int,
    expected_address: str, new_address: str,
) -> dict[str, object]:
    """Caller commits in SAME transaction as audit. No direct commit here."""
    if not rotation_enabled():
        raise HTTPException(status_code=409, detail="تغییر آدرس فعال در محیط عملیاتی غیرفعال است.")
    row = db.execute(select(AppSetting).where(
        AppSetting.k == state_key(network)
    ).with_for_update()).scalar_one_or_none()
    if row is None or not isinstance(row.v_json, dict):
        raise HTTPException(status_code=503, detail="رکورد نسخه‌بندی کیف پول ایجاد نشده است.")
    before = lock_destination_state_from_record(network, row.v_json)
    if int(before["version"]) != int(expected_version) or before["address"] != expected_address:
        raise HTTPException(status_code=409, detail="نسخه یا آدرس فعال تغییر کرده؛ دوباره بررسی کنید.")
    try:
        updated_address = validate_crypto_destination(network, new_address)
    except ValueError:
        raise HTTPException(status_code=422, detail="آدرس مقصد نامعتبر است.") from None
    if same_crypto_destination(network, updated_address, str(before["address"])):
        raise HTTPException(status_code=409, detail="آدرس جدید با آدرس فعال یکسان است.")
    updated = {**before, "address": updated_address, "version": int(before["version"]) + 1}
    row.v_json = dict(updated)
    db.add(row)
    db.flush()
    return updated


def lock_destination_state_from_record(network: str, raw: dict) -> dict[str, object]:
    if raw.get("network") != network or type(raw.get("version")) is not int or raw["version"] < 1:
        raise HTTPException(status_code=409, detail="نسخه آدرس نامعتبر است.")
    try:
        address = validate_crypto_destination(network, raw.get("address"))
    except ValueError:
        raise HTTPException(status_code=409, detail="آدرس ذخیره‌شده نامعتبر است.") from None
    return {"network": network, "address": address, "version": raw["version"]}


def seed_destination_state(
    db: Session, *, network: str, address: str,
) -> dict[str, object]:
    """Explicit gated preparation (disposable or approved frozen production).

    Never create the version row as an implicit invoice side effect.
    """
    if not rotation_enabled():
        raise HTTPException(status_code=409, detail="آماده‌سازی فقط در محیط آزمایشی مجاز است.")
    record = {"network": network, "address": validate_crypto_destination(network, address), "version": 1}
    if db.get(AppSetting, state_key(network)) is not None:
        raise HTTPException(status_code=409, detail="نسخه آدرس از قبل موجود است.")
    db.add(AppSetting(k=state_key(network), v_json=record))
    db.flush()
    return record
