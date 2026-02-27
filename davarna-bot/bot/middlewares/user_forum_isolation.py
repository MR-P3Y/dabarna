from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


def _extract_chat_id(event: TelegramObject, data: dict) -> int | None:
    chat = data.get("event_chat")
    if chat is not None:
        try:
            return int(chat.id)
        except Exception:
            pass

    direct_chat = getattr(event, "chat", None)
    if direct_chat is not None:
        try:
            return int(direct_chat.id)
        except Exception:
            pass

    message = getattr(event, "message", None)
    if message is not None and getattr(message, "chat", None) is not None:
        try:
            return int(message.chat.id)
        except Exception:
            pass

    for attr in ("edited_message", "channel_post", "edited_channel_post"):
        msg = getattr(event, attr, None)
        if msg is None or getattr(msg, "chat", None) is None:
            continue
        try:
            return int(msg.chat.id)
        except Exception:
            continue

    callback_query = getattr(event, "callback_query", None)
    if callback_query is not None:
        cb_message = getattr(callback_query, "message", None)
        if cb_message is not None and getattr(cb_message, "chat", None) is not None:
            try:
                return int(cb_message.chat.id)
            except Exception:
                pass

    return None


class UserForumIsolationMiddleware(BaseMiddleware):
    """
    Blocks all incoming updates from the public user forum chat.
    This keeps that group broadcast-only while allowing private/admin flows.
    """

    def __init__(self, isolated_chat_id: int | None):
        self._isolated_chat_id = int(isolated_chat_id) if isolated_chat_id is not None else None

    async def __call__(self, handler, event: TelegramObject, data: dict):
        if self._isolated_chat_id is None:
            return await handler(event, data)

        chat_id = _extract_chat_id(event, data)
        if chat_id is not None and int(chat_id) == self._isolated_chat_id:
            return None

        return await handler(event, data)
