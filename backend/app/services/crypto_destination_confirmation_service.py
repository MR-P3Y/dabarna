"""Human verification of crypto deposit destination draft — never an activation.

The caller must enforce owner-only Mini App identity and rate limiting.
Only a short-lived random secret digest is persisted; the plaintext secret is
returned once and MUST NOT be logged or included in audit details.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.crypto_destination_challenge import CryptoDestinationChallenge
from app.models.crypto_destination_version import CryptoDestinationVersion
from app.services.crypto_destination_draft_service import _current_address, _same_destination

CHALLENGE_TTL_SECONDS = 120


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _draft_locked(db: Session, draft_id: int, actor_id: int) -> CryptoDestinationVersion:
    row = db.execute(select(CryptoDestinationVersion).where(
        CryptoDestinationVersion.id == int(draft_id),
    ).with_for_update()).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="پیش‌نویس پیدا نشد.")
    if row.state != "DRAFT":
        raise HTTPException(status_code=409, detail="این پیش‌نویس دیگر منتظر تأیید نیست.")
    if int(row.requested_by) != int(actor_id):
        raise HTTPException(status_code=403, detail="فقط سازنده پیش‌نویس مجاز به تأیید است.")
    if not row.previous_address:
        raise HTTPException(status_code=409, detail="نسخه قدیمی آدرس ثبت نشده است.")
    try:
        unchanged = _same_destination(
            str(row.network), str(row.previous_address),
            _current_address(str(row.network)),
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail="آدرس فعلی سرور قابل بررسی نیست.") from exc
    if not unchanged:
        raise HTTPException(status_code=409, detail="آدرس فعلی سرور از زمان ثبت پیش‌نویس تغییر کرده است.")
    return row


def _already_confirmed(db: Session, draft_id: int) -> bool:
    return db.execute(select(CryptoDestinationChallenge.id).where(
        CryptoDestinationChallenge.draft_id == int(draft_id),
        CryptoDestinationChallenge.consumed_at.is_not(None),
    ).limit(1).with_for_update()).scalar_one_or_none() is not None


class CryptoDestinationConfirmationService:
    @staticmethod
    def prepare(
        db: Session, *, draft_id: int, actor_id: int,
    ) -> tuple[CryptoDestinationChallenge, str, CryptoDestinationVersion]:
        draft = _draft_locked(db, draft_id, actor_id)
        if _already_confirmed(db, draft.id):
            raise HTTPException(status_code=409, detail="این پیش‌نویس قبلاً تأیید شده است.")
        now = _now()
        pending = db.execute(select(CryptoDestinationChallenge.id).where(
            CryptoDestinationChallenge.draft_id == int(draft.id),
            CryptoDestinationChallenge.consumed_at.is_(None),
            CryptoDestinationChallenge.expires_at > now,
        ).limit(1).with_for_update()).scalar_one_or_none()
        if pending is not None:
            raise HTTPException(status_code=409, detail="چالش قبلی هنوز معتبر است؛ تا پایان مهلت آن صبر کنید.")

        token = secrets.token_urlsafe(32)
        row = CryptoDestinationChallenge(
            id=uuid4().hex,
            draft_id=int(draft.id),
            actor_id=int(actor_id),
            secret_digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
            expires_at=now + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        )
        db.add(row)
        db.flush()
        return row, token, draft

    @staticmethod
    def confirm(
        db: Session, *, draft_id: int, challenge_id: str, token: str,
        confirmed_address: str, actor_id: int,
    ) -> tuple[CryptoDestinationChallenge, CryptoDestinationVersion]:
        # Lock the draft first to serialize confirmations of separate challenges.
        draft = _draft_locked(db, draft_id, actor_id)
        if _already_confirmed(db, draft.id):
            raise HTTPException(status_code=409, detail="این پیش‌نویس قبلاً تأیید شده است.")
        challenge = db.execute(select(CryptoDestinationChallenge).where(
            CryptoDestinationChallenge.id == str(challenge_id),
            CryptoDestinationChallenge.draft_id == int(draft.id),
            CryptoDestinationChallenge.actor_id == int(actor_id),
        ).with_for_update()).scalar_one_or_none()
        if challenge is None:
            raise HTTPException(status_code=404, detail="چالش تأیید پیدا نشد.")
        if challenge.consumed_at is not None or challenge.expires_at <= _now():
            raise HTTPException(status_code=409, detail="چالش استفاده‌شده یا منقضی است.")
        # Requiring exact retyping of the complete address is a human-check step,
        # not an independent MFA factor (the session and token are in one client).
        if str(confirmed_address) != str(draft.address):
            raise HTTPException(status_code=400, detail="آدرس واردشده با پیش‌نویس مطابقت ندارد.")
        if not isinstance(token, str) or not hmac.compare_digest(
            challenge.secret_digest, hashlib.sha256(token.encode("utf-8")).hexdigest(),
        ):
            raise HTTPException(status_code=403, detail="کد چالش تأیید نامعتبر است.")
        challenge.consumed_at = _now()
        db.flush()
        return challenge, draft
