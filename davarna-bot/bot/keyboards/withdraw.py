from aiogram.utils.keyboard import InlineKeyboardBuilder

def withdraw_confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید و ثبت", callback_data="withdraw:confirm")
    kb.button(text="✏️ ویرایش", callback_data="withdraw:edit")
    kb.button(text="❌ لغو", callback_data="withdraw:cancel")
    kb.adjust(2, 1)
    return kb.as_markup()

def withdraw_cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="withdraw:cancel")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(2)
    return kb.as_markup()
