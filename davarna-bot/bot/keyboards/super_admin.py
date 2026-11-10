from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def super_admin_panel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 فهرست ادمین‌ها", callback_data="super:admin:list")
    kb.button(text="➕ ادمین جدید", callback_data="super:admin:add")
    kb.button(text="➖ لغو دسترسی ادمین", callback_data="super:admin:remove")
    kb.button(text="🧑‍💼 مدیریت کاربران", callback_data="admin:users")
    kb.button(text="💳 کارت‌های مقصد", callback_data="super:deposit:cards")
    kb.button(text="🟦 کارت‌به‌کارت", callback_data="super:deposit:settings")
    kb.button(text="🪙 پرداخت رمزارزی", callback_data="super:crypto:settings")
    kb.button(text="🔄 تازه‌سازی", callback_data="super:admin:panel")
    kb.button(text="⬅️ منوی اصلی", callback_data="nav:menu")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


def super_admin_cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="super:admin:panel")
    kb.adjust(1)
    return kb.as_markup()


def super_admin_role_select_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎮 اپراتور بازی", callback_data="super:admin:add:role:GAME_OPERATOR")
    kb.button(text="💰 ادمین مالی", callback_data="super:admin:add:role:FINANCE_ADMIN")
    kb.button(text="🛠 ادمین کامل", callback_data="super:admin:add:role:ADMIN")
    kb.button(text="👑 سوپرادمین", callback_data="super:admin:add:role:SUPER_ADMIN")
    kb.button(text="❌ لغو", callback_data="super:admin:panel")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def super_admin_admins_list_kb(items: list[dict], *, mode: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    normalized_mode = "remove" if str(mode).lower() == "remove" else "list"
    for it in items:
        tg_user_id = int(it.get("tg_user_id") or 0)
        display = str(it.get("display_name") or "").strip() or f"کاربر ناشناس | {tg_user_id}"
        short = display if len(display) <= 24 else f"{display[:24]}..."
        role_txt = str(it.get("roles_fa") or "").strip()
        if normalized_mode == "remove":
            cb = f"super:admin:remove:pick:{tg_user_id}"
            txt = f"🗑 {short}"
        else:
            cb = f"super:admin:view:{tg_user_id}:{normalized_mode}"
            txt = f"👤 {short}"
        if role_txt:
            txt = f"{txt} | {role_txt}"
        kb.button(text=txt, callback_data=cb)
    kb.button(text="⬅️ بازگشت", callback_data="super:admin:panel")
    layout = [1] * len(items)
    layout.append(1)
    kb.adjust(*layout)
    return kb.as_markup()


def super_admin_admin_detail_kb(*, tg_user_id: int, source: str = "list") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 پروفایل و فعالیت کاربر", callback_data=f"admin:users:profile:{int(tg_user_id)}")
    kb.button(text="🗑 حذف ادمین", callback_data=f"super:admin:remove:pick:{int(tg_user_id)}")
    if str(source).lower() == "remove":
        kb.button(text="⬅️ بازگشت به لیست حذف", callback_data="super:admin:remove")
    else:
        kb.button(text="⬅️ بازگشت به لیست ادمین‌ها", callback_data="super:admin:list")
    kb.button(text="⬅️ پنل سوپرادمین", callback_data="super:admin:panel")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def super_admin_remove_confirm_kb(*, tg_user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید حذف", callback_data=f"super:admin:remove:confirm:{int(tg_user_id)}")
    kb.button(text="❌ انصراف", callback_data="super:admin:remove")
    kb.button(text="⬅️ پنل سوپرادمین", callback_data="super:admin:panel")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def super_admin_deposit_cards_kb(items: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item in items:
        did = str(item.get("id") or "").strip()
        if not did:
            continue
        title = str(item.get("title") or "").strip() or "کارت"
        bank = str(item.get("bank_name") or "").strip()
        card = str(item.get("card_number") or "").strip()
        tail = card[-4:] if len(card) >= 4 else "----"
        active = "🟢" if bool(item.get("is_active", True)) else "🔴"
        text = f"{active} {title} | {bank} | ****{tail}"
        kb.button(text=text, callback_data=f"super:deposit:card:view:{did}")
    kb.button(text="➕ افزودن کارت جدید", callback_data="super:deposit:card:add")
    kb.button(text="⬅️ پنل سوپرادمین", callback_data="super:admin:panel")
    layout = [1] * len(items)
    layout.extend([1, 1])
    kb.adjust(*layout)
    return kb.as_markup()


def super_admin_deposit_card_item_kb(destination_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    did = str(destination_id)
    kb.button(text="✏️ ویرایش کارت", callback_data=f"super:deposit:card:edit:{did}")
    kb.button(text="🗑 حذف کارت", callback_data=f"super:deposit:card:delete:{did}")
    kb.button(text="⬅️ لیست کارت‌ها", callback_data="super:deposit:cards")
    kb.button(text="⬅️ پنل سوپرادمین", callback_data="super:admin:panel")
    kb.adjust(1, 1, 1, 1)
    return kb.as_markup()


def super_admin_deposit_card_delete_confirm_kb(destination_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    did = str(destination_id)
    kb.button(text="✅ تایید حذف", callback_data=f"super:deposit:card:delete:confirm:{did}")
    kb.button(text="❌ انصراف", callback_data=f"super:deposit:card:view:{did}")
    kb.button(text="⬅️ لیست کارت‌ها", callback_data="super:deposit:cards")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def super_admin_deposit_card_cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="super:deposit:cards")
    kb.adjust(1)
    return kb.as_markup()



def super_admin_bank_deposit_settings_kb(*, runtime_enabled: bool, can_enable: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if runtime_enabled:
        kb.button(text="🔴 خاموش کردن کارت‌به‌کارت", callback_data="super:deposit:settings:toggle")
    else:
        text = "🟢 روشن کردن کارت‌به‌کارت" if can_enable else "🟢 روشن کردن کارت‌به‌کارت (نیازمند کارت فعال)"
        kb.button(text=text, callback_data="super:deposit:settings:toggle")
    kb.button(text="🔄 تازه‌سازی", callback_data="super:deposit:settings")
    kb.button(text="⬅️ پنل سوپرادمین", callback_data="super:admin:panel")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def super_admin_crypto_settings_kb(*, runtime_enabled: bool, can_enable: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if runtime_enabled:
        kb.button(text="🔴 خاموش کردن پرداخت رمزارزی", callback_data="super:crypto:settings:toggle")
    else:
        text = "🟢 روشن کردن پرداخت رمزارزی" if can_enable else "🟢 روشن کردن پرداخت رمزارزی (نیازمند تنظیمات)"
        kb.button(text=text, callback_data="super:crypto:settings:toggle")
    kb.button(text="💼 آدرس‌های TON/TRON", callback_data="super:crypto:addresses")
    kb.button(text="🧾 واریزهای نیازمند بررسی", callback_data="admin:crypto:pending")
    kb.button(text="🩺 سلامت سرویس‌ها", callback_data="super:crypto:health")
    kb.button(text="🧮 تطبیق ۲۴ ساعت اخیر", callback_data="super:crypto:reconcile")
    kb.button(text="🔄 تازه‌سازی", callback_data="super:crypto:settings")
    kb.button(text="⬅️ پنل سوپرادمین", callback_data="super:admin:panel")
    kb.adjust(1, 1, 1, 2, 1, 1)
    return kb.as_markup()


def super_admin_crypto_wallets_kb(
    *, networks: list[dict], proposals: list[dict], runtime_enabled: bool,
) -> InlineKeyboardMarkup:
    """Owner wallet menu: no address ever appears in callback_data."""
    kb = InlineKeyboardBuilder()
    by_network = {str(row.get("network") or ""): row for row in networks if isinstance(row, dict)}
    by_proposal = {str(row.get("network") or ""): row for row in proposals if isinstance(row, dict)}
    for network in ("TRON", "TON"):
        item = by_network.get(network) or {}
        address = str(item.get("address") or "")
        if not address:
            kb.button(text=f"➕ افزودن آدرس {network}", callback_data=f"super:crypto:wallet:edit:{network}")
        else:
            kb.button(text=f"✏️ تغییر آدرس {network}", callback_data=f"super:crypto:wallet:edit:{network}")
            if item.get("requires_bootstrap"):
                kb.button(text=f"🛡 آماده‌سازی {network}", callback_data=f"super:crypto:wallet:prepare:{network}")
        if network in by_proposal:
            text = "⏸ پرداخت فعال است؛ ابتدا خاموش کنید" if runtime_enabled else f"✅ تأیید تغییر {network}"
            kb.button(text=text, callback_data=f"super:crypto:wallet:activate:{network}")
    kb.button(text="🔄 تازه‌سازی آدرس‌ها", callback_data="super:crypto:addresses")
    kb.button(text="⬅️ تنظیمات رمزارز", callback_data="super:crypto:settings")
    kb.adjust(1)
    return kb.as_markup()


def super_admin_crypto_wallet_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ ثبت آدرس", callback_data="super:crypto:wallet:save")
    kb.button(text="❌ انصراف", callback_data="super:crypto:addresses")
    kb.adjust(1)
    return kb.as_markup()
