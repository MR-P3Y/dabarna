from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_finance_menu_kb(*, deposit_filter_active: bool = False, withdraw_filter_active: bool = False):
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 واریزهای در انتظار", callback_data="admin:deposits:pending")
    kb.button(text="🔎 فیلتر واریز", callback_data="admin:deposits:filter")
    if deposit_filter_active:
        kb.button(text="🧹 حذف فیلتر واریز", callback_data="admin:deposits:filter:clear")
    kb.button(text="📤 برداشت‌های در انتظار", callback_data="admin:withdraws:pending")
    kb.button(text="🔎 فیلتر برداشت", callback_data="admin:withdraws:filter")
    if withdraw_filter_active:
        kb.button(text="🧹 حذف فیلتر برداشت", callback_data="admin:withdraws:filter:clear")
    kb.button(text="✅ برداشت‌های تاییدشده", callback_data="admin:withdraws:approved")
    kb.button(text="📊 گزارش فروش بازه‌ای", callback_data="admin:finance:sales:range")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_finance_sales_range_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ بازگشت به ادمین مالی", callback_data="admin:finance")
    kb.adjust(1)
    return kb.as_markup()


def admin_deposits_list_kb(items: list[dict], *, offset: int, has_next: bool):
    kb = InlineKeyboardBuilder()
    for it in items:
        deposit_id = int(it.get("id"))
        amount = it.get("amount", "—")
        kb.button(
            text=f"🧾 #{deposit_id} | {amount}",
            callback_data=f"admin:deposits:view:{deposit_id}:{offset}",
        )

    if offset > 0:
        prev_offset = max(0, offset - 5)
        kb.button(text="◀️ قبلی", callback_data=f"admin:deposits:page:{prev_offset}")
    if has_next:
        kb.button(text="▶️ بعدی", callback_data=f"admin:deposits:page:{offset + 5}")
    kb.button(text="⬅️ ادمین مالی", callback_data="admin:finance")

    layout = [1] * len(items)
    nav_count = int(offset > 0) + int(has_next)
    if nav_count:
        layout.append(nav_count)
    layout.append(1)
    kb.adjust(*layout)
    return kb.as_markup()


def deposit_item_kb(deposit_id: int, *, back_offset: int = 0):
    approve_cb = f"admin:deposit:approve:{deposit_id}:o:{back_offset}"
    reject_cb = f"admin:deposit:reject:{deposit_id}:o:{back_offset}"

    kb = InlineKeyboardBuilder()
    kb.button(text="👁 مشاهده رسید", callback_data=f"admin:deposit:receipt:{deposit_id}")
    kb.button(text="✅ تایید", callback_data=approve_cb)
    kb.button(text="❌ رد", callback_data=reject_cb)
    kb.button(text="⬅️ بازگشت به لیست", callback_data=f"admin:deposits:page:{back_offset}")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def admin_withdraws_list_kb(items: list[dict], *, status: str, offset: int, has_next: bool):
    kb = InlineKeyboardBuilder()
    status_u = (status or "PENDING").upper()
    for it in items:
        withdraw_id = int(it.get("id"))
        amount = it.get("amount", "—")
        kb.button(
            text=f"📤 #{withdraw_id} | {amount}",
            callback_data=f"admin:withdraws:view:{withdraw_id}:{status_u}:{offset}",
        )

    if offset > 0:
        prev_offset = max(0, offset - 5)
        kb.button(text="◀️ قبلی", callback_data=f"admin:withdraws:page:{status_u}:{prev_offset}")
    if has_next:
        kb.button(text="▶️ بعدی", callback_data=f"admin:withdraws:page:{status_u}:{offset + 5}")
    kb.button(text="⬅️ ادمین مالی", callback_data="admin:finance")

    layout = [1] * len(items)
    nav_count = int(offset > 0) + int(has_next)
    if nav_count:
        layout.append(nav_count)
    layout.append(1)
    kb.adjust(*layout)
    return kb.as_markup()


def withdraw_item_kb(*, withdraw_id: int, status: str, back_offset: int = 0, tg_user_id: int | None = None):
    kb = InlineKeyboardBuilder()
    st = (status or "PENDING").upper()
    if st == "PENDING":
        try:
            live_tg_user_id = int(tg_user_id or 0)
        except Exception:
            live_tg_user_id = 0
        if live_tg_user_id > 0:
            kb.button(text="🔄 بروزرسانی موجودی", callback_data=f"admin:withdraw:live:{withdraw_id}:{live_tg_user_id}")
        kb.button(text="✅ تایید برداشت", callback_data=f"admin:withdraw:approve:{withdraw_id}:{st}:{back_offset}")
        kb.button(text="❌ رد برداشت", callback_data=f"admin:withdraw:reject:{withdraw_id}:{st}:{back_offset}")
    elif st == "APPROVED":
        try:
            live_tg_user_id = int(tg_user_id or 0)
        except Exception:
            live_tg_user_id = 0
        if live_tg_user_id > 0:
            kb.button(text="\U0001f504 \u0628\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc \u0645\u0648\u062c\u0648\u062f\u06cc", callback_data=f"admin:withdraw:live:{withdraw_id}:{live_tg_user_id}")
        kb.button(text="\u2705 \u067e\u0631\u062f\u0627\u062e\u062a \u0646\u0647\u0627\u06cc\u06cc \u0628\u0627 \u0631\u0633\u06cc\u062f", callback_data=f"admin:withdraw:send-receipt:{withdraw_id}:{st}:{back_offset}")
        kb.button(text="\U0001f4b8 \u062b\u0628\u062a \u067e\u0631\u062f\u0627\u062e\u062a \u0628\u062f\u0648\u0646 \u0641\u06cc\u0634", callback_data=f"admin:withdraw:paid:{withdraw_id}:{st}:{back_offset}")
    elif st == "PAID":
        pass

    kb.button(text="⬅️ بازگشت به لیست", callback_data=f"admin:withdraws:page:{st}:{back_offset}")
    kb.button(text="⬅️ ادمین مالی", callback_data="admin:finance")
    kb.adjust(1)
    return kb.as_markup()

def withdraw_admin_alert_kb(*, withdraw_id: int, tg_user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="👁 مشاهده درخواست", callback_data=f"admin:withdraws:view:{withdraw_id}:PENDING:0")
    kb.button(text="🔄 تازه‌سازی موجودی", callback_data=f"admin:withdraw:live:{withdraw_id}:{tg_user_id}")
    kb.button(text="✅ تایید برداشت", callback_data=f"admin:withdraw:approve:{withdraw_id}:PENDING:0")
    kb.button(text="❌ رد برداشت", callback_data=f"admin:withdraw:reject:{withdraw_id}:PENDING:0")
    kb.adjust(1)
    return kb.as_markup()


def deposit_admin_alert_kb(*, deposit_id: int, tg_user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="👁 مشاهده رسید", callback_data=f"admin:deposits:view:{deposit_id}:0")
    kb.button(text="🔄 تازه‌سازی موجودی", callback_data=f"admin:deposit:live:{deposit_id}:{tg_user_id}")
    kb.button(text="✅ تایید واریز", callback_data=f"admin:deposit:approve:{deposit_id}:o:0")
    kb.button(text="❌ رد واریز", callback_data=f"admin:deposit:reject:{deposit_id}:o:0")
    kb.adjust(1)
    return kb.as_markup()


def deposit_filter_quick_kb(*, filter_active: bool):
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 امروز", callback_data="admin:deposits:filter:quick:today")
    kb.button(text="📆 دیروز", callback_data="admin:deposits:filter:quick:yesterday")
    kb.button(text="🗓 ۷ روز اخیر", callback_data="admin:deposits:filter:quick:7d")
    kb.button(text="💵 بالای ۵۰۰هزار", callback_data="admin:deposits:filter:quick:high500")
    kb.button(text="💰 بالای ۱ میلیون", callback_data="admin:deposits:filter:quick:high1m")
    kb.button(text="⌨️ فیلتر دستی", callback_data="admin:deposits:filter:manual")
    if filter_active:
        kb.button(text="🧹 حذف فیلتر", callback_data="admin:deposits:filter:clear")
    kb.button(text="⬅️ بازگشت", callback_data="admin:finance")
    kb.adjust(1)
    return kb.as_markup()


def withdraw_filter_quick_kb(*, filter_active: bool):
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 امروز", callback_data="admin:withdraws:filter:quick:today")
    kb.button(text="📆 دیروز", callback_data="admin:withdraws:filter:quick:yesterday")
    kb.button(text="🗓 ۷ روز اخیر", callback_data="admin:withdraws:filter:quick:7d")
    kb.button(text="💵 بالای ۵۰۰هزار", callback_data="admin:withdraws:filter:quick:high500")
    kb.button(text="💰 بالای ۱ میلیون", callback_data="admin:withdraws:filter:quick:high1m")
    kb.button(text="⌨️ فیلتر دستی", callback_data="admin:withdraws:filter:manual")
    if filter_active:
        kb.button(text="🧹 حذف فیلتر", callback_data="admin:withdraws:filter:clear")
    kb.button(text="⬅️ بازگشت", callback_data="admin:finance")
    kb.adjust(1)
    return kb.as_markup()


def admin_cancel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو", callback_data="admin:cancel")
    kb.button(text="⬅️ بازگشت", callback_data="admin:deposits:pending")
    kb.adjust(2)
    return kb.as_markup()

def admin_reject_reason_kb(*, kind: str):
    kb = InlineKeyboardBuilder()
    k = (kind or "").strip().lower()
    if k == "withdraw":
        kb.button(text="⚡ عدم موجودی", callback_data="admin:reject:quick:no_balance")
        kb.button(text="⚡ مشکل شبکه بانکی", callback_data="admin:reject:quick:bank_issue")
    else:
        kb.button(text="⚡ رسید نامعتبر", callback_data="admin:reject:quick:invalid_receipt")
        kb.button(text="⚡ عدم تطابق مبلغ", callback_data="admin:reject:quick:amount_mismatch")
    kb.button(text="❌ لغو", callback_data="admin:cancel")
    kb.adjust(1)
    return kb.as_markup()


def withdraw_receipt_prompt_kb(*, withdraw_id: int, status: str, back_offset: int = 0):
    kb = InlineKeyboardBuilder()
    st = (status or "APPROVED").upper()
    kb.button(text="⬅️ بازگشت به درخواست", callback_data=f"admin:withdraws:view:{withdraw_id}:{st}:{back_offset}")
    kb.button(text="❌ لغو", callback_data="admin:cancel")
    kb.adjust(1)
    return kb.as_markup()

