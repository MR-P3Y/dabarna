from aiogram.utils.keyboard import InlineKeyboardBuilder


def join_gate_kb(game_id: int, chat_id: int, invite_link: str | None = None):
    kb = InlineKeyboardBuilder()

    if invite_link:
        kb.button(text="🔗 عضویت در گروه", url=invite_link)

    kb.button(text="✅ عضو شدم", callback_data=f"join:check:{game_id}:{chat_id}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def join_gate_action_kb(action_key: str, chat_id: int, invite_link: str | None = None):
    kb = InlineKeyboardBuilder()

    if invite_link:
        kb.button(text="🔗 عضویت در گروه", url=invite_link)

    kb.button(text="✅ عضو شدم", callback_data=f"join:check:action:{action_key}:{chat_id}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 1, 1)
    return kb.as_markup()
