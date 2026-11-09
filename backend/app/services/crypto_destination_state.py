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
from app.services.crypto_address_change import validate_crypto_destination

ROTATION_GATE = "DAVARNA_CRYPTO_ROTATION_EXPERIMENTAL"
KEY_PREFIX = "crypto_destination_v1:"


def rotation_enabled() -> bool:
    return os.getenv(ROTATION_GATE, "").strip() == "I_ACK_DISPOSABLE_DB_ONLY"


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
    if record.get("network") != network or not isinstance(record.get("version"), int):
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
    if updated_address == before["address"]:
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
    """Explicit disposable-DB preparation only, never an invoice side effect."""
    if not rotation_enabled():
        raise HTTPException(status_code=409, detail="آماده‌سازی فقط در محیط آزمایشی مجاز است.")
    record = {"network": network, "address": validate_crypto_destination(network, address), "version": 1}
    if db.get(AppSetting, state_key(network)) is not None:
        raise HTTPException(status_code=409, detail="نسخه آدرس از قبل موجود است.")
    db.add(AppSetting(k=state_key(network), v_json=record))
    db.flush()
    return record
