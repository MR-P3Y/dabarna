from aiogram.utils.keyboard import InlineKeyboardBuilder

def game_cards_control_kb(game_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 بروزرسانی همه", callback_data=f"mycards:refresh_all:{game_id}")
    kb.button(text="⬅️ انتخاب بازی", callback_data="menu:mycards")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 2)
    return kb.as_markup()
