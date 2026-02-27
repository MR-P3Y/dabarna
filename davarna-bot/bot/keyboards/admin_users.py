from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_users_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 جستجو کاربر", callback_data="admin:users:search")
    kb.button(text="📘 راهنمای ورودی", callback_data="admin:users:help")
    kb.button(text="❌ لغو عملیات", callback_data="admin:users:cancel")
    kb.button(text="⬅️ منوی اصلی", callback_data="nav:menu")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def admin_users_search_results_kb(items: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for item in items[:15]:
        tg_user_id = int(item.get("tg_user_id") or 0)
        if tg_user_id <= 0:
            continue
        username = str(item.get("username") or "").strip()
        display_name = str(item.get("display_name") or "").strip()
        title = f"👤 {display_name}" if display_name else f"👤 {tg_user_id}"
        if username:
            title = f"{title} (@{username})"
        kb.button(text=title[:64], callback_data=f"admin:users:open:{tg_user_id}")
    kb.button(text="🔎 جستجوی جدید", callback_data="admin:users:search")
    kb.button(text="⬅️ پنل ادمین کاربران", callback_data="admin:users")
    kb.adjust(1)
    return kb.as_markup()


def admin_user_profile_kb(tg_user_id: int) -> InlineKeyboardMarkup:
    uid = int(tg_user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 تاریخچه مالی", callback_data=f"admin:users:fin:{uid}")
    kb.button(text="🎮 تاریخچه بازی", callback_data=f"admin:users:games:{uid}")
    kb.button(text="⛔ محدودسازی", callback_data=f"admin:users:restrict:{uid}")
    kb.button(text="✅ رفع محدودیت", callback_data=f"admin:users:unrestrict:{uid}")
    kb.button(text="💳 اصلاح کیف پول", callback_data=f"admin:users:adjust:{uid}")
    kb.button(text="🧩 پیام آماده", callback_data=f"admin:users:compose:{uid}")
    kb.button(text="✉️ پیام دستی", callback_data=f"admin:users:notify:{uid}")
    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:users:profile:{uid}")
    kb.button(text="⬅️ پنل ادمین کاربران", callback_data="admin:users")
    kb.adjust(2, 2, 2, 2, 1)
    return kb.as_markup()


def admin_users_compose_templates_kb(tg_user_id: int) -> InlineKeyboardMarkup:
    uid = int(tg_user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 رد واریز", callback_data=f"admin:users:compose:pick:{uid}:deposit_reject")
    kb.button(text="📤 رد برداشت", callback_data=f"admin:users:compose:pick:{uid}:withdraw_reject")
    kb.button(text="💳 اصلاح کیف پول", callback_data=f"admin:users:compose:pick:{uid}:wallet_adjust")
    kb.button(text="⛔ اعلان محدودیت", callback_data=f"admin:users:compose:pick:{uid}:restriction")
    kb.button(text="📨 پیام عمومی", callback_data=f"admin:users:compose:pick:{uid}:generic")
    kb.button(text="✍️ ورود پیام دستی", callback_data=f"admin:users:notify:{uid}")
    kb.button(text="⬅️ بازگشت به پروفایل", callback_data=f"admin:users:profile:{uid}")
    kb.adjust(2, 2, 1, 1, 1)
    return kb.as_markup()


def admin_users_cancel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="admin:users:cancel")
    kb.button(text="⬅️ پنل ادمین کاربران", callback_data="admin:users")
    kb.adjust(2)
    return kb.as_markup()
