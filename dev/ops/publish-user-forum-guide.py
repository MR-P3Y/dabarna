#!/usr/bin/env python3
"""Publish/pin one canonical navigation message in the existing user forum.

Operator-only, explicit invocation after bot release and tests.
One durable Redis claim prevents duplicates; ambiguous network errors do not
trigger automatic retries. No Telegram topics are created/deleted/renamed.
"""
from __future__ import annotations

import asyncio
import sys

from aiogram import Bot
from redis.asyncio import Redis

from bot.config import settings
from bot.services.user_forum_navigation import group_guide_text

KEY = "davarna:userforum:guide:v1:20261107"


async def main() -> int:
    chat_id = settings.USER_FORUM_CHAT_ID
    topic_id = settings.USER_TOPIC_ANNOUNCE_ID
    if chat_id is None or int(chat_id) >= 0 or topic_id is None or int(topic_id) <= 0:
        raise RuntimeError("BLOCKER: valid existing user forum and announcement topic required")
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("BLOCKER: bot token missing")

    text = group_guide_text()
    if len(text) >= 4000:
        raise RuntimeError("BLOCKER: group navigation message too long")
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    bot = Bot(settings.TELEGRAM_BOT_TOKEN)
    try:
        claimed = await redis.set(KEY, "CLAIMED_UNCONFIRMED", nx=True)
        if not claimed:
            print("BLOCKER: publication already claimed or attempted; inspect Telegram before retry")
            return 2

        try:
            result = await bot.send_message(
                chat_id=int(chat_id),
                message_thread_id=int(topic_id),
                text=text,
                parse_mode="HTML",
                disable_notification=True,
                link_preview_options=None,
            )
        except Exception as exc:
            await redis.set(KEY, "UNCERTAIN")
            print("UNCERTAIN: Telegram guide may have been delivered; no automatic retry.")
            print("Error type:", type(exc).__name__)
            return 3

        await redis.set(KEY, f"SENT:{int(result.message_id)}")
        print("GUIDE SENT; message ID:", int(result.message_id))
        try:
            await bot.pin_chat_message(
                chat_id=int(chat_id),
                message_id=int(result.message_id),
                disable_notification=True,
            )
            await redis.set(KEY, f"PINNED:{int(result.message_id)}")
            print("GUIDE PINNED IN ANNOUNCEMENTS")
        except Exception as exc:
            print("GUIDE SENT, PIN NOT CONFIRMED. Pin manually; do not repost.")
            print("Error type:", type(exc).__name__)
        return 0
    finally:
        await bot.session.close()
        await redis.aclose()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc))
        sys.exit(2)
