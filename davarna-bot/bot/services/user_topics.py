from __future__ import annotations

import asyncio
import time
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from bot.config import settings

TopicName = Literal["announce", "game_start", "game_low", "game_medium", "game_high", "live", "results", "rules", "chat"]


def forum_enabled() -> bool:
    return settings.USER_FORUM_CHAT_ID is not None and int(settings.USER_FORUM_CHAT_ID) < 0


def topic_id(name: TopicName) -> int | None:
    if name == "announce":
        return settings.USER_TOPIC_ANNOUNCE_ID
    if name == "game_start":
        return settings.USER_TOPIC_GAME_START_ID
    if name == "game_low":
        return settings.USER_TOPIC_GAME_LOW_ID
    if name == "game_medium":
        return settings.USER_TOPIC_GAME_MEDIUM_ID
    if name == "game_high":
        return settings.USER_TOPIC_GAME_HIGH_ID
    if name == "live":
        return settings.USER_TOPIC_LIVE_NUMBERS_ID
    if name == "results":
        return settings.USER_TOPIC_RESULTS_ID
    if name == "rules":
        return settings.USER_TOPIC_RULES_ID
    if name == "chat":
        return settings.USER_TOPIC_CHAT_ID
    return None


def game_start_announcement_topic() -> TopicName:
    """GAME_STARTED uses a verified dedicated thread only when configured.

    No fallback after a failed send: misrouting must be noticed, not hidden.
    With the option unset the historical announcement topic is preserved.
    """
    configured = settings.USER_TOPIC_GAME_START_ID
    return "game_start" if configured is not None and int(configured) > 0 else "announce"


def game_topic_name_for_id(topic_id_value: int | None) -> TopicName | None:
    if topic_id_value is None:
        return None
    tid = int(topic_id_value)
    mapping: list[tuple[TopicName, int | None]] = [
        ("game_low", settings.USER_TOPIC_GAME_LOW_ID),
        ("game_medium", settings.USER_TOPIC_GAME_MEDIUM_ID),
        ("game_high", settings.USER_TOPIC_GAME_HIGH_ID),
    ]
    for name, configured in mapping:
        if configured is not None and int(configured) == tid:
            return name
    return None


def game_topic_title(topic_id_value: int | None) -> str:
    name = game_topic_name_for_id(topic_id_value)
    if name == "game_low":
        return "بازی سطح پایین"
    if name == "game_medium":
        return "بازی سطح متوسط"
    if name == "game_high":
        return "بازی سطح بالا"
    if topic_id_value is None:
        return "بازی"
    return f"تاپیک {int(topic_id_value)}"


async def _send(
    bot: Bot,
    *,
    thread_id: int,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_notification: bool = True,
    expires_at: float | None = None,
) -> bool:
    if not forum_enabled() or (expires_at is not None and time.time() >= expires_at):
        return False

    chat_id = int(settings.USER_FORUM_CHAT_ID or 0)
    try:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=int(thread_id),
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_notification=disable_notification,
        )
        return True
    except TelegramRetryAfter as e:
        delay = float(getattr(e, "retry_after", 1.0)) + 0.1
        if expires_at is not None and time.time() + delay >= expires_at:
            return False
        await asyncio.sleep(delay)
        if expires_at is not None and time.time() >= expires_at:
            return False
        try:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=int(thread_id),
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
            return True
        except Exception:
            return False
    except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError):
        return False
    except Exception:
        return False


async def send_to_topic(
    bot: Bot,
    *,
    name: TopicName,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_notification: bool = True,
    expires_at: float | None = None,
) -> bool:
    thread_id = topic_id(name)
    if thread_id is None:
        return False
    return await _send(
        bot,
        thread_id=int(thread_id),
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_notification=disable_notification,
        expires_at=expires_at,
    )


async def send_to_game_topic(
    bot: Bot,
    *,
    game_topic_id: int | None,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_notification: bool = True,
    expires_at: float | None = None,
) -> bool:
    if game_topic_id is None:
        return False
    return await _send(
        bot,
        thread_id=int(game_topic_id),
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_notification=disable_notification,
        expires_at=expires_at,
    )
