"""Immutable watch records for retired destinations. Never credit a wallet."""
from datetime import datetime, timezone
import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from app.models.settings import AppSetting
from app.services.crypto_address_change import canonical_ton_address, validate_crypto_destination
from app.services import crypto_destination_state as destination_state

PREFIX = 'crypto_retired_v1:'


def retired_key(network: str, address: str) -> str:
    address = validate_crypto_destination(network, address)
    identity = canonical_ton_address(address) if network == 'TON' else address
    return PREFIX + hashlib.sha256(f'{network}:{identity}'.encode()).hexdigest()[:40]


def retired_destination(db, network: str, address: str):
    if not destination_state.rotation_enabled():
        return None
    row = db.get(AppSetting, retired_key(network, address))
    if row is None:
        return None
    data = row.v_json
    if not isinstance(data, dict) or data.get('network') != network or not data.get('scan_since'):
        raise ValueError('Invalid retired destination record')
    return dict(data)


def retired_destinations(db, network: str) -> list[dict]:
    if not destination_state.rotation_enabled():
        return []
    rows = db.execute(select(AppSetting).where(AppSetting.k.like(PREFIX+'%'))).scalars().all()
    return [dict(row.v_json) for row in rows if isinstance(row.v_json, dict) and row.v_json.get('network') == network]


def retain_retired_destination(db, *, network: str, address: str, version: int, scan_since: str):
    if not destination_state.rotation_enabled():
        raise HTTPException(status_code=409, detail='مدیریت مقصدهای قبلی فعال نیست.')
    key = retired_key(network, address)
    if db.get(AppSetting, key) is not None:
        raise HTTPException(status_code=409, detail='این مقصد قبلاً بازنشسته شده؛ بازنویسی سابقه مجاز نیست.')
    since = datetime.fromisoformat(scan_since.replace('Z', '+00:00'))
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if since > datetime.now(timezone.utc):
        raise ValueError('Future retirement scan start')
    db.add(AppSetting(k=key, v_json={'network':network,'address':address,'version':version,
        'scan_since':since.isoformat(), 'retired_at':datetime.now(timezone.utc).isoformat(),
        'automatic_credit':False}))
    db.flush()
