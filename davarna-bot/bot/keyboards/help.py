from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def help_menu_kb(*, topics: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    for key, label in topics:
        kb.button(text=label, callback_data=f"help:topic:{key}")

    kb.button(text="⬅️ بازگشت به منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


def help_topic_kb(*, prev_key: str | None, next_key: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    if prev_key is not None:
        kb.button(text="⬅️ موضوع قبلی", callback_data=f"help:topic:{prev_key}")
    if next_key is not None:
        kb.button(text="موضوع بعدی ➡️", callback_data=f"help:topic:{next_key}")

    kb.button(text="📚 فهرست راهنما", callback_data="menu:help")
    kb.button(text="⬅️ بازگشت به منو", callback_data="nav:menu")

    if prev_key is not None and next_key is not None:
        kb.adjust(2, 1, 1)
    elif prev_key is not None or next_key is not None:
        kb.adjust(1, 1, 1)
    else:
        kb.adjust(1, 1)

    return kb.as_markup()
