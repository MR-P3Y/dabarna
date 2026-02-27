from aiogram.utils.keyboard import InlineKeyboardBuilder


def _mask_card(card_number: str) -> str:
    digits = "".join(ch for ch in str(card_number or "") if ch.isdigit())
    if len(digits) < 4:
        return "----"
    return f"****{digits[-4:]}"


def deposit_destination_kb(items: list[dict]):
    kb = InlineKeyboardBuilder()
    for it in items:
        dest_id = str(it.get("id") or "").strip()
        if not dest_id:
            continue
        title = str(it.get("title") or "").strip()
        bank = str(it.get("bank_name") or "").strip()
        card = _mask_card(str(it.get("card_number") or ""))
        label = title or bank or f"کارت {card}"
        if bank and bank not in label:
            label = f"{label} | {bank}"
        kb.button(text=f"💳 {label} ({card})", callback_data=f"deposit:dest:{dest_id}")

    kb.button(text="❌ لغو", callback_data="deposit:cancel")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    layout = [1] * max(0, len(items))
    layout.extend([2])
    kb.adjust(*layout)
    return kb.as_markup()


def deposit_confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید و ثبت", callback_data="deposit:confirm")
    kb.button(text="❌ لغو", callback_data="deposit:cancel")
    kb.adjust(2)
    return kb.as_markup()


def deposit_cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="deposit:cancel")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(2)
    return kb.as_markup()


def deposit_status_kb(deposit_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 بروزرسانی وضعیت", callback_data=f"deposit:status:{deposit_id}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 1)
    return kb.as_markup()


def deposit_pending_kb(deposit_id: int):
    return deposit_status_kb(deposit_id)
