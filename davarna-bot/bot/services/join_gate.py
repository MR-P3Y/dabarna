from __future__ import annotations

from dataclasses import dataclass
from html import escape

from aiogram import Bot

from bot.config import settings

_EXPORTED_INVITE_LINKS: dict[int, str] = {}


@dataclass(frozen=True)
class JoinGateTarget:
    chat_id: int
    invite_link: str | None = None
    title: str | None = None


def configured_join_group_id(fallback: int | None = None) -> int | None:
    if settings.BOT_JOIN_GROUP_ID is not None:
        return int(settings.BOT_JOIN_GROUP_ID)
    return fallback


def configured_join_invite_link() -> str | None:
    raw = str(settings.BOT_JOIN_GROUP_INVITE_LINK or "").strip()
    return raw or None


async def resolve_join_gate_target(bot: Bot, chat_id: int) -> JoinGateTarget:
    title: str | None = None
    invite_link = configured_join_invite_link()

    try:
        chat = await bot.get_chat(chat_id)
        raw_title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
        if raw_title:
            title = str(raw_title)

        if not invite_link:
            raw_invite = getattr(chat, "invite_link", None)
            if isinstance(raw_invite, str) and raw_invite.strip():
                invite_link = raw_invite.strip()

        if not invite_link:
            username = getattr(chat, "username", None)
            if isinstance(username, str) and username.strip():
                invite_link = f"https://t.me/{username.strip()}"
    except Exception:
        pass

    if not invite_link:
        invite_link = _EXPORTED_INVITE_LINKS.get(int(chat_id))

    if not invite_link:
        try:
            # Telegram may revoke the previous primary invite link on export;
            # cache the generated value so one process does not rotate it per user.
            generated = await bot.export_chat_invite_link(chat_id)
            if isinstance(generated, str) and generated.strip():
                invite_link = generated.strip()
                _EXPORTED_INVITE_LINKS[int(chat_id)] = invite_link
        except Exception:
            pass

    return JoinGateTarget(chat_id=int(chat_id), invite_link=invite_link, title=title)


def join_gate_body(reason: str, target: JoinGateTarget) -> str:
    lines = [reason.strip()]

    if target.title:
        lines.append(f"👥 نام گروه: <b>{escape(target.title)}</b>")

    if target.invite_link:
        safe_url = escape(target.invite_link, quote=True)
        lines.append(f'🔗 لینک گروه: <a href="{safe_url}">عضویت در گروه</a>')
        lines.append("برای عضویت مستقیم، روی دکمه «🔗 عضویت در گروه» بزن.")
    else:
        lines.append(f"🆔 شناسه گروه: <code>{target.chat_id}</code>")
        lines.append("لینک مستقیم گروه تنظیم نشده است؛ از ادمین گروه لینک دعوت بگیر.")

    lines.append("بعد از عضویت، روی «✅ عضو شدم» بزن.")
    return "
".join(lines)
