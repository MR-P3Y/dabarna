"""Super-admin bank deposit destinations: validation and optimistic revision.

No payment/wallet operation is performed by these helpers. Existing deposit
requests keep their own destination snapshot. An inactive card must be
explicitly enabled in a separate, confirmed step before it can receive funds.
"""
from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

from fastapi import HTTPException

MAX_DESTINATIONS = 20
MAX_TITLE = 100
CARD_RE = re.compile(r"^[0-9]{16,19}$")
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def revision(items: list[dict]) -> str:
    canonical = json.dumps(
        items, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_new_details(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="اطلاعات کارت مقصد نامعتبر است.")
    card = re.sub(r"[\s-]+", "", str(raw.get("card_number") or ""))
    # Only ASCII digits. No silent truncation or conversion of partial strings.
    if not CARD_RE.fullmatch(card):
        raise HTTPException(status_code=422, detail="شماره کارت باید ۱۶ تا ۱۹ رقم باشد.")
    title = str(raw.get("title") or "").strip()
    bank = str(raw.get("bank_name") or "").strip()
    owner = str(raw.get("account_name") or "").strip()
    if not (title or bank):
        raise HTTPException(status_code=422, detail="نام بانک یا عنوان کارت الزامی است.")
    if any(len(s) > MAX_TITLE for s in (title, bank, owner)):
        raise HTTPException(status_code=422, detail="عنوان، بانک یا صاحب حساب بیش از حد طولانی است.")
    iban = re.sub(r"[\s-]+", "", str(raw.get("iban") or "")).upper()
    if iban and not re.fullmatch(r"IR[0-9]{24}", iban):
        raise HTTPException(status_code=422, detail="شماره شبا باید IR و ۲۴ رقم داشته باشد.")
    account_number = re.sub(r"[\s-]+", "", str(raw.get("account_number") or ""))
    if account_number and (not account_number.isascii()
                           or not account_number.isdigit()
                           or len(account_number) > 40):
        raise HTTPException(status_code=422, detail="شماره حساب نامعتبر است.")
    return {
        "title": title or bank,
        "account_name": owner,
        "bank_name": bank,
        "iban": iban,
        "card_number": card,
        "account_number": account_number,
    }


def check_revision(expected: str, items: list[dict]) -> None:
    if not expected or expected != revision(items):
        raise HTTPException(
            status_code=409,
            detail="فهرست کارت‌ها تغییر کرده؛ ابتدا فهرست را تازه‌سازی کنید.",
        )


def add_destination(items: list[dict], raw: dict) -> list[dict]:
    if len(items) >= MAX_DESTINATIONS:
        raise HTTPException(status_code=409, detail="حداکثر ۲۰ کارت مقصد مجاز است.")
    details = validate_new_details(raw)
    if any(str(x.get("card_number") or "") == details["card_number"] for x in items):
        raise HTTPException(status_code=409, detail="این شماره کارت قبلاً ثبت شده است.")
    new_id = "bank_" + uuid4().hex[:16]
    return [*items, {"id": new_id, **details, "is_active": False}]


def update_destination(items: list[dict], dest_id: str, raw: dict, *,
                       bank_enabled: bool) -> list[dict]:
    if not ID_RE.fullmatch(str(dest_id)):
        raise HTTPException(status_code=404, detail="شناسه کارت نامعتبر است.")
    original = next((x for x in items if str(x.get("id")) == dest_id), None)
    if original is None:
        raise HTTPException(status_code=404, detail="کارت مقصد پیدا نشد.")
    details = validate_new_details(raw)
    if any(str(x.get("id")) != dest_id
           and str(x.get("card_number") or "") == details["card_number"]
           for x in items):
        raise HTTPException(status_code=409, detail="این شماره کارت قبلاً ثبت شده است.")
    active = raw.get("is_active")
    if type(active) is not bool:
        raise HTTPException(status_code=422, detail="وضعیت فعال/غیرفعال کارت باید صریح باشد.")
    if (bank_enabled and not active and bool(original.get("is_active", True))
            and sum(bool(x.get("is_active", True)) for x in items) <= 1):
        raise HTTPException(status_code=409, detail="برای غیرفعال‌کردن آخرین کارت، ابتدا پرداخت کارت‌به‌کارت را خاموش کنید.")
    return [
        ({**x, **details, "is_active": active} if str(x.get("id")) == dest_id else x)
        for x in items
    ]


def remove_destination(items: list[dict], dest_id: str) -> list[dict]:
    original = next((x for x in items if str(x.get("id")) == dest_id), None)
    if original is None:
        raise HTTPException(status_code=404, detail="کارت مقصد پیدا نشد.")
    if bool(original.get("is_active", True)):
        raise HTTPException(status_code=409, detail="برای حذف کارت، ابتدا آن را غیرفعال کنید.")
    if len(items) <= 1:
        raise HTTPException(status_code=409, detail="آخرین کارت قابل حذف نیست؛ آن را غیرفعال نگه دارید تا کارت تنظیمات سرور دوباره ظاهر نشود.")
    return [x for x in items if str(x.get("id")) != dest_id]
