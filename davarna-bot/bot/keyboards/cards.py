from aiogram.utils.keyboard import InlineKeyboardBuilder

def cards_nav_kb(page: int, total_pages: int, game_id: int | None = None):
    kb = InlineKeyboardBuilder()

    gid = game_id or 0
    if page > 1:
        kb.button(text="⬅️ قبلی", callback_data=f"mycards:page:{page-1}:{gid}")
    if page < total_pages:
        kb.button(text="بعدی ➡️", callback_data=f"mycards:page:{page+1}:{gid}")

    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()
