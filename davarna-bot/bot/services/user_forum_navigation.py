"""Central user-forum map and short, useful navigation buttons.

All links refer to existing Telegram topic IDs. No topics are created, renamed,
deleted or automatically pinned by this module.
"""
from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings


def thread_url(chat_id: int | None, thread_id: int | None) -> str | None:
    """Only private supergroup IDs (-100...) have known stable /c links."""
    if chat_id is None or thread_id is None:
        return None
    raw = str(chat_id)
    try:
        topic = int(thread_id)
    except (ValueError, TypeError):
        return None
    if not raw.startswith("-100") or not raw[4:].isdigit() or topic < 1:
        return None
    return f"https://t.me/c/{raw[4:]}/{topic}"


def topic_link(topic_id: int | None) -> str | None:
    return thread_url(settings.USER_FORUM_CHAT_ID, topic_id)


def navigation_keyboard(
    *,
    game_topic_id: int | None = None,
    show_live: bool = False,
    show_results: bool = False,
    show_rules: bool = False,
) -> InlineKeyboardMarkup | None:
    kb = InlineKeyboardBuilder()
    seen: set[str] = set()
    candidates = [
        ("🎮 تاپیک بازی", game_topic_id),
        ("🔢 اعداد زنده", settings.USER_TOPIC_LIVE_NUMBERS_ID if show_live else None),
        ("🏁 نتایج", settings.USER_TOPIC_RESULTS_ID if show_results else None),
        ("📖 قوانین", settings.USER_TOPIC_RULES_ID if show_rules else None),
    ]
    for label, configured in candidates:
        url = topic_link(configured)
        if url and url not in seen:
            kb.button(text=label, url=url)
            seen.add(url)
    if not seen:
        return None
    kb.adjust(2)
    return kb.as_markup()


def group_guide_text() -> str:
    """One clearly labeled entrypoint; absent topics have no dead links."""
    topics = [
        ("📢 اعلان‌ها", settings.USER_TOPIC_ANNOUNCE_ID, "خبرهای مهم و شروع بازی"),
        ("🎯 بازی ۱ | خطی", settings.USER_TOPIC_GAME_LOW_ID, "پیگیری بازی سطح یک"),
        ("🎯 بازی ۲ | خطی", settings.USER_TOPIC_GAME_MEDIUM_ID, "پیگیری بازی سطح دو"),
        ("🏆 بازی ۳ | پرکردنی", settings.USER_TOPIC_GAME_HIGH_ID, "پیگیری بازی سطح سه"),
        ("🔢 اعداد زنده", settings.USER_TOPIC_LIVE_NUMBERS_ID, "عددهای اعلام‌شده"),
        ("🏁 نتایج", settings.USER_TOPIC_RESULTS_ID, "پایان بازی و برندگان"),
        ("📖 قوانین و آموزش", settings.USER_TOPIC_RULES_ID, "روش بازی و پرسش‌های رایج"),
        ("💬 گفت‌وگو", settings.USER_TOPIC_CHAT_ID, "گفت‌وگوی کاربران"),
    ]
    lines = ["📌 <b>راهنمای گروه دبرنای طوفان</b>", "",
             "🛒 <b>خرید کارت، کیف پول و کارت‌های من فقط در گفت‌وگوی خصوصی ربات است.</b>",
             "در گروه برای پیدا کردن بخش موردنظر از این راهنما استفاده کنید:", ""]
    for title, topic, description in topics:
        url = topic_link(topic)
        label = escape(title)
        if url:
            lines.append(f'• <a href="{url}">{label}</a> — {escape(description)}')
        else:
            lines.append(f"• {label} — {escape(description)}")
    lines.extend(["", "برای شروع، ربات را خصوصی باز کنید و «خرید کارت» یا «بازی‌های فعال» را بزنید.",
                  "اطلاعات پرداخت و رسید را در گروه عمومی ارسال نکنید."])
    return "\n".join(lines)
