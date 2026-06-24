from aiogram.utils.keyboard import InlineKeyboardBuilder


def crypto_network_kb(options: list[dict]):
    kb = InlineKeyboardBuilder()
    for item in options:
        network = str(item.get("network") or "").upper()
        asset = str(item.get("asset") or "").upper()
        if network == "TRON":
            text = "🟢 تتر روی شبکه ترون"
        elif network == "TON":
            text = "🔵 تون روی شبکه TON"
        else:
            text = f"{asset} روی {network}"
        kb.button(text=text, callback_data=f"crypto:network:{network}")
    kb.button(text="⬅️ کیف پول", callback_data="menu:wallet")
    kb.adjust(1)
    return kb.as_markup()


def crypto_cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="crypto:cancel")
    kb.button(text="⬅️ کیف پول", callback_data="menu:wallet")
    kb.adjust(2)
    return kb.as_markup()


def crypto_invoice_kb(invoice_id: int, status: str):
    kb = InlineKeyboardBuilder()
    normalized = str(status or "").upper()
    if normalized in {"WAITING_PAYMENT", "CONFIRMING"}:
        kb.button(text="🔄 بررسی پرداخت", callback_data=f"crypto:status:{int(invoice_id)}")
        kb.button(text="🔗 ثبت هش تراکنش", callback_data=f"crypto:tx:{int(invoice_id)}")
    kb.button(text="⬅️ کیف پول", callback_data="menu:wallet")
    kb.adjust(1)
    return kb.as_markup()


def admin_crypto_list_kb(items: list[dict]):
    kb = InlineKeyboardBuilder()
    for item in items:
        invoice_id = int(item.get("id") or 0)
        if invoice_id <= 0:
            continue
        amount = int(item.get("amount_toman") or 0)
        asset = str(item.get("asset") or "")
        kb.button(
            text=f"💎 #{invoice_id} | {amount:,} تومان | {asset}",
            callback_data=f"admin:crypto:view:{invoice_id}",
        )
    kb.button(text="🔄 تازه‌سازی", callback_data="admin:crypto:pending")
    kb.button(text="⬅️ ادمین مالی", callback_data="admin:finance")
    kb.adjust(1)
    return kb.as_markup()


def admin_crypto_item_kb(*, invoice_id: int, status: str, tg_user_id: int | None = None):
    kb = InlineKeyboardBuilder()
    normalized = str(status or "").upper()
    if tg_user_id and int(tg_user_id) > 0:
        kb.button(
            text="👤 مشاهده پروفایل کاربر",
            callback_data=f"admin:users:profile:{int(tg_user_id)}",
        )
    if normalized == "NEEDS_REVIEW":
        kb.button(text="✅ تایید و شارژ کیف پول", callback_data=f"admin:crypto:approve:{int(invoice_id)}")
        kb.button(text="❌ رد واریز", callback_data=f"admin:crypto:reject:{int(invoice_id)}")
    kb.button(text="⬅️ لیست رمزارز", callback_data="admin:crypto:pending")
    kb.adjust(1)
    return kb.as_markup()
