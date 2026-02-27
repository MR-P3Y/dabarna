from aiogram.utils.keyboard import InlineKeyboardBuilder

def notif_toggle_kb(game_id: int, is_on: bool):
    kb = InlineKeyboardBuilder()
    if is_on:
        kb.button(text="🔕 خاموش کردن نوتیف", callback_data=f"notif:off:{game_id}")
    else:
        kb.button(text="🔔 روشن کردن نوتیف", callback_data=f"notif:on:{game_id}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 1)
    return kb.as_markup()
