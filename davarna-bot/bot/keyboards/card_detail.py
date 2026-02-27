from aiogram.utils.keyboard import InlineKeyboardBuilder

def card_detail_kb(card_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📩 ارسال به خصوصی", callback_data=f"card:pv:{card_id}")
    kb.button(text="🔄 به‌روزرسانی", callback_data=f"card:refresh:{card_id}")
    kb.button(text="⬅️ بازگشت", callback_data="menu:mycards")
    kb.adjust(2, 1)
    return kb.as_markup()
