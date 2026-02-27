from aiogram.utils.keyboard import InlineKeyboardBuilder

def cards_list_kb(cards: list[dict], page: int, total_pages: int, game_id: int | None):
    kb = InlineKeyboardBuilder()
    for c in cards[:8]:
        kb.button(
            text=f"🃏 کارت {c.get('id')} (بازی {c.get('game_id')})",
            callback_data=f"card:open:{c.get('id')}"
        )

    gid = game_id or 0
    if page > 1:
        kb.button(text="⬅️ قبلی", callback_data=f"mycards:page:{page-1}:{gid}")
    if page < total_pages:
        kb.button(text="بعدی ➡️", callback_data=f"mycards:page:{page+1}:{gid}")

    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()
