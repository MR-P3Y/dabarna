from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.constants import BACK_TO_MENU


def back_to_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=BACK_TO_MENU, callback_data="nav:menu")
    return kb.as_markup()
