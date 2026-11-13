"""Restart-aware, per-destination Telegram lifecycle delivery acknowledgments.

Acknowledgment is written *only after* Telegram API reports success. A durable
pending marker is written *before* attempting delivery, so failed attempts are
retried even after a bot restart. Telegram does not provide idempotent sends:
a process crash between a successful send and the local ACK can still cause a
duplicate. This provides at-least-once attempts, not exactly-once delivery.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

from bot.services.notify_store import (
    get_event_marker,
    get_meta_marker,
    set_event_marker,
    set_meta_marker,
)

logger = logging.getLogger(__name__)

# Recover events that arrived while the Bot was down; don't flood the forum
# with ancient notifications on the first rollout of this implementation.
FIRST_SEEN_RECOVERY_SECONDS = 3600


def _event_timestamp(event: dict | None) -> float | None:
    raw = str((event or {}).get("created_at") or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


async def deliver_lifecycle_event(
    *,
    game_id: int,
    event_key: str,
    event: dict | None,
    is_first_seen: bool,
    legacy_event_key: str | None,
    send: Callable[[], Awaitable[bool]],
    already_delivered: bool = False,
) -> bool:
    """Attempt the particular destination once, or acknowledge a known prior send.

    False is returned when Telegram fails; a pending marker is kept for the
    next scan/restart. Raises on persistence errors: fail closed, never report
    successful delivery if ACK persistence failed.
    """
    event_id = int((event or {}).get("id") or 0)
    if event_id <= 0:
        return False
    ack_id = get_event_marker(game_id, event_key)
    if ack_id >= event_id:
        return True
    pending_key = f"lifecycle_pending:{int(game_id)}:{event_key}"
    pending_id = get_meta_marker(pending_key, "")
    was_pending = pending_id == str(event_id)

    # Legacy marker is an already-existing acceptance record. Earlier code
    # may have set it on failed sends; this cannot be reconstructed. Avoid
    # replaying every historical message on upgrade.
    legacy_id = (
        get_event_marker(game_id, legacy_event_key)
        if legacy_event_key else 0
    )
    if legacy_id >= event_id and not was_pending:
        set_event_marker(game_id, event_key, event_id)
        return True

    # Mini App can send GAME_CREATED synchronously and writes its delivery
    # result in the saved event payload; never double-send this event.
    if already_delivered:
        set_event_marker(game_id, event_key, event_id)
        if was_pending:
            set_meta_marker(pending_key, "")
        return True

    if is_first_seen and ack_id <= 0 and not was_pending:
        created_at = _event_timestamp(event)
        now = time.time()
        if (
            created_at is None
            or created_at > now + 120
            or created_at < now - FIRST_SEEN_RECOVERY_SECONDS
        ):
            # Initial backfill of stale events only; a persisted failed
            # attempt always bypasses this check after process restart.
            set_event_marker(game_id, event_key, event_id)
            return True

    # Persist a retry anchor before calling Telegram. If this write fails,
    # never send: the attempt could not be recovered.
    if not was_pending:
        set_meta_marker(pending_key, str(event_id))
    try:
        sent = bool(await send())
    except Exception:
        logger.exception(
            "lifecycle delivery exception: game=%s destination=%s event=%s",
            game_id, event_key, event_id,
        )
        sent = False
    if not sent:
        logger.warning(
            "lifecycle delivery pending retry: game=%s destination=%s event=%s",
            game_id, event_key, event_id,
        )
        return False

    set_event_marker(game_id, event_key, event_id)
    set_meta_marker(pending_key, "")
    return True
