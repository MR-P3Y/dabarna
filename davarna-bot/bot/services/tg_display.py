from __future__ import annotations

import time
from typing import Iterable

from aiogram import Bot

from bot.config import settings

_CACHE_TTL_SEC = 1800.0
_DISPLAY_NAME_CACHE: dict[int, tuple[str, float]] = {}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _pick_name(
    *,
    tg_user_id: int,
    username: str | None = None,
    full_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> str:
    uname = str(username or "").strip().lstrip("@")
    if uname:
        return f"@{uname}"

    full = str(full_name or "").strip()
    if full:
        return full

    f = str(first_name or "").strip()
    l = str(last_name or "").strip()
    if f and l:
        return f"{f} {l}"
    if f:
        return f
    if l:
        return l

    if tg_user_id > 0:
        return f"کاربر {tg_user_id}"
    return "کاربر ناشناس"


def _is_placeholder_name(name: str | None, tg_user_id: int) -> bool:
    txt = str(name or "").strip()
    if not txt:
        return True
    if txt == "کاربر ناشناس":
        return True
    return txt == f"کاربر {int(tg_user_id)}"


def format_tg_identity(display_name: str | None, tg_user_id: int | None) -> str:
    uid = _safe_int(tg_user_id, 0)
    name = str(display_name or "").strip()
    if uid <= 0:
        return name or "کاربر ناشناس"
    if not name:
        return f"کاربر ناشناس | {uid}"
    if _is_placeholder_name(name, uid):
        return f"کاربر ناشناس | {uid}"
    if f"| {uid}" in name:
        return name
    return f"{name} | {uid}"


async def resolve_tg_display_name(
    bot: Bot,
    tg_user_id: int | None,
    *,
    username: str | None = None,
    full_name: str | None = None,
    allow_fetch: bool = True,
) -> str:
    uid = _safe_int(tg_user_id, 0)
    if uid <= 0:
        return _pick_name(tg_user_id=uid, username=username, full_name=full_name)

    now = time.time()
    cached = _DISPLAY_NAME_CACHE.get(uid)
    if cached and now - float(cached[1]) <= _CACHE_TTL_SEC:
        cached_name = str(cached[0] or "").strip()
        if cached_name:
            return cached_name

    direct = _pick_name(tg_user_id=uid, username=username, full_name=full_name)
    if direct and not direct.startswith("کاربر "):
        _DISPLAY_NAME_CACHE[uid] = (direct, now)
        return direct

    if allow_fetch:
        try:
            chat = await bot.get_chat(uid)
            resolved = _pick_name(
                tg_user_id=uid,
                username=getattr(chat, "username", None),
                full_name=getattr(chat, "full_name", None),
                first_name=getattr(chat, "first_name", None),
                last_name=getattr(chat, "last_name", None),
            )
            _DISPLAY_NAME_CACHE[uid] = (resolved, now)
            return resolved
        except Exception:
            pass
        # Secondary fallback: if direct private-chat lookup fails, try user forums/groups
        # where the bot can read member identities.
        fallback_chat_ids = (
            settings.BOT_JOIN_GROUP_ID,
            settings.USER_FORUM_CHAT_ID,
            settings.ADMIN_FORUM_CHAT_ID,
        )
        for raw_chat_id in fallback_chat_ids:
            chat_id = _safe_int(raw_chat_id, 0)
            if chat_id == 0:
                continue
            try:
                member = await bot.get_chat_member(chat_id=chat_id, user_id=uid)
                user = getattr(member, "user", None)
                resolved = _pick_name(
                    tg_user_id=uid,
                    username=getattr(user, "username", None),
                    full_name=getattr(user, "full_name", None),
                    first_name=getattr(user, "first_name", None),
                    last_name=getattr(user, "last_name", None),
                )
                if not _is_placeholder_name(resolved, uid):
                    _DISPLAY_NAME_CACHE[uid] = (resolved, now)
                    return resolved
            except Exception:
                continue

    fallback = _pick_name(tg_user_id=uid, username=username, full_name=full_name)
    _DISPLAY_NAME_CACHE[uid] = (fallback, now)
    return fallback


async def resolve_tg_display_names(
    bot: Bot,
    tg_user_ids: Iterable[int],
) -> list[str]:
    out: list[str] = []
    seen: set[int] = set()
    for raw in tg_user_ids:
        uid = _safe_int(raw, 0)
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(await resolve_tg_display_name(bot, uid))
    return out


async def resolve_tg_identity(
    bot: Bot,
    tg_user_id: int | None,
    *,
    username: str | None = None,
    full_name: str | None = None,
    allow_fetch: bool = True,
) -> str:
    uid = _safe_int(tg_user_id, 0)
    display = await resolve_tg_display_name(
        bot,
        uid,
        username=username,
        full_name=full_name,
        allow_fetch=allow_fetch,
    )
    return format_tg_identity(display, uid)


async def resolve_tg_identities(
    bot: Bot,
    tg_user_ids: Iterable[int],
) -> list[str]:
    out: list[str] = []
    seen: set[int] = set()
    for raw in tg_user_ids:
        uid = _safe_int(raw, 0)
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(await resolve_tg_identity(bot, uid))
    return out
