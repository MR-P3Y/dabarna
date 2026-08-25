from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.api_client import ApiClient, ApiError
from bot.services.html import h
from bot.services.jalali import format_jalali_datetime
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel

router = Router()

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_FA_DIGITS_TRANS = str.maketrans("0123456789", _FA_DIGITS)


def require_admin(is_admin: bool) -> bool:
    return bool(is_admin)


def _to_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS_TRANS)


def _fmt_count(value: object) -> str:
    return _fa(f"{_to_int(value):,}".replace(",", "٬"))


def _fmt_toman(value: object) -> str:
    return f"{_fmt_count(value)} تومان"


def _ops_home_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 بروزرسانی", callback_data="admin:ops:dashboard")
    kb.button(text="⚠️ هشدارهای ریسک", callback_data="admin:ops:risk")
    kb.button(text="🧾 لاگ عملیات", callback_data="admin:ops:audit:all:0")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


def _ops_back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📡 داشبورد عملیات", callback_data="admin:ops:dashboard")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


def _audit_kb(*, offset: int, has_next: bool, category: str = "all"):
    kb = InlineKeyboardBuilder()
    cat = str(category or "all")
    kb.button(text="همه", callback_data="admin:ops:audit:all:0")
    kb.button(text="مالی", callback_data="admin:ops:audit:finance:0")
    kb.button(text="بازی", callback_data="admin:ops:audit:game:0")
    kb.button(text="کاربران", callback_data="admin:ops:audit:users:0")
    if offset > 0:
        kb.button(text="◀️ صفحه قبل", callback_data=f"admin:ops:audit:{cat}:{max(0, offset - 10)}")
    if has_next:
        kb.button(text="صفحه بعد ▶️", callback_data=f"admin:ops:audit:{cat}:{offset + 10}")
    kb.button(text="📡 داشبورد عملیات", callback_data="admin:ops:dashboard")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    nav_count = int(offset > 0) + int(has_next)
    if nav_count:
        kb.adjust(4, nav_count, 1, 1)
    else:
        kb.adjust(4, 1, 1)
    return kb.as_markup()


def _service_line(item: dict) -> str:
    ok = item.get("ok")
    raw_status = str(item.get("status") or "").strip().upper()
    if ok is True or raw_status == "OK":
        status = "سالم"
    elif ok is False or raw_status in {"FAIL", "ERROR"}:
        status = "خطا"
    elif raw_status == "MONITORED":
        status = "در پایش سرور"
    else:
        status = "در حال بررسی"
    icon = "🟢" if ok is True else ("⚪️" if ok is None else "🔴")
    return f"{icon} {h(str(item.get('title') or item.get('key') or '-'))}: <b>{h(status)}</b>"


def _action_fa(action: object) -> str:
    raw = str(action or "").strip()
    names = {
        "game.create": "ایجاد بازی",
        "game.start": "شروع بازی",
        "game.call": "اعلام عدد",
        "game.undo": "حذف آخرین عدد",
        "game.undo_call": "برگشت عدد",
        "game.close_lobby": "لغو لابی",
        "deposit.approve": "تایید واریز",
        "deposit.reject": "رد واریز",
        "withdraw.approve": "تایید برداشت",
        "withdraw.reject": "رد برداشت",
        "withdraw.paid": "پرداخت برداشت",
        "crypto.deposit.approve": "تایید واریز رمزارز",
        "crypto.deposit.reject": "رد واریز رمزارز",
        "wallet.adjust": "اصلاح کیف پول",
        "user.restrict": "محدودسازی کاربر",
        "user.unrestrict": "رفع محدودیت کاربر",
        "user.notify": "ارسال پیام به کاربر",
        "admin.grant": "اعطای نقش",
        "admin.revoke": "حذف نقش",
        "settings.update": "تغییر تنظیمات",
        "risk.buy.insufficient_balance": "موجودی ناکافی خرید",
    }
    return names.get(raw, raw or "-")


@router.callback_query(F.data == "admin:ops:dashboard")
async def admin_ops_dashboard(
    cq: CallbackQuery,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
    is_game_admin: bool = False,
    is_finance_admin: bool = False,
    is_user_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    try:
        out = await api.admin_ops_dashboard()
    except ApiError as exc:
        await cq.answer(exc.detail, show_alert=True)
        return

    counts = out.get("counts") or {}
    services = ((out.get("system") or {}).get("services") or [])[:6]
    games = out.get("active_games") or []
    can_finance = bool(is_super_admin or is_user_admin or is_finance_admin)
    can_game = bool(is_super_admin or is_user_admin or is_game_admin)

    game_lines: list[str] = []
    for game in (games if can_game else [])[:4]:
        status = "در حال اجرا" if str(game.get("status")) == "RUNNING" else "لابی"
        last_number = game.get("last_number")
        game_lines.append(
            f"🎮 بازی #{_fa(game.get('id'))} | {h(status)} | عدد آخر: <b>{h(_fa(last_number) if last_number is not None else '—')}</b> | کارت: <b>{_fmt_count(game.get('cards_count'))}</b>"
        )
    if not game_lines:
        game_lines.append("برای نقش فعلی بازی فعالی برای نمایش نیست.")

    lines = ["وضعیت سریع عملیات:"]
    if can_finance:
        lines.extend(
            [
                f"📥 واریز در انتظار: <b>{_fmt_count(counts.get('pending_deposits'))}</b>",
                f"📤 برداشت در انتظار: <b>{_fmt_count(counts.get('pending_withdraws'))}</b>",
                f"✅ برداشت تاییدشده: <b>{_fmt_count(counts.get('approved_withdraws'))}</b>",
                f"💎 کریپتو نیازمند بررسی: <b>{_fmt_count(counts.get('crypto_needs_review'))}</b>",
            ]
        )
    if can_game or can_finance:
        lines.append(f"⚠️ ریسک ۲۴ ساعت: <b>{_fmt_count(counts.get('risk_events_24h'))}</b>")
    lines.extend(["", "سلامت سرویس‌ها:", *[_service_line(item) for item in services]])
    if can_game:
        lines.extend(["", "بازی‌های فعال:", *game_lines])
    text = "\n".join(lines)
    await safe_edit_or_send(
        cq.message,
        panel("داشبورد عملیات", text),
        reply_markup=_ops_home_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "admin:ops:risk")
async def admin_ops_risk(
    cq: CallbackQuery,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
    is_game_admin: bool = False,
    is_finance_admin: bool = False,
    is_user_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    try:
        out = await api.admin_risk_alerts()
    except ApiError as exc:
        await cq.answer(exc.detail, show_alert=True)
        return

    items = out.get("items") or []
    if not items:
        text = "هشدار فعالی ثبت نشده است."
    else:
        lines: list[str] = []
        for item in items[:10]:
            severity = str(item.get("severity") or "info")
            icon = "🔴" if severity == "danger" else ("🟡" if severity == "warning" else "🔵")
            lines.append(
                f"{icon} <b>{h(str(item.get('title') or '-'))}</b>\n"
                f"{h(str(item.get('body') or '-'))}\n"
                f"⏱ <code>{h(format_jalali_datetime(item.get('created_at'), default='—'))}</code>"
            )
        text = "\n\n".join(lines)

    await safe_edit_or_send(
        cq.message,
        panel("هشدارهای ریسک", text),
        reply_markup=_ops_back_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:ops:audit:"))
async def admin_ops_audit(
    cq: CallbackQuery,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
    is_game_admin: bool = False,
    is_finance_admin: bool = False,
    is_user_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    parts = str(cq.data or "").split(":")
    category = "all"
    offset_raw = parts[-1] if parts else "0"
    if len(parts) >= 5:
        category = str(parts[-2] or "all")
    offset = max(0, _to_int(offset_raw, 0))
    limit = 10

    try:
        out = await api.admin_audit_logs(
            limit=limit,
            offset=offset,
            category=None if category == "all" else category,
        )
    except ApiError as exc:
        await cq.answer(exc.detail, show_alert=True)
        return

    items = out.get("items") or []
    total = _to_int(out.get("total"), 0)
    if total <= 0:
        total = offset + len(items)

    page = (offset // limit) + 1
    total_pages = max(1, ((total + limit - 1) // limit))
    has_next = offset + len(items) < total if total else len(items) >= limit

    cat_label = {
        "all": "همه",
        "finance": "مالی",
        "game": "بازی",
        "users": "کاربران",
        "risk": "ریسک",
        "admin": "نقش‌ها",
        "settings": "تنظیمات",
    }.get(category, category)

    if not items:
        text = f"دسته: <b>{h(cat_label)}</b>\nلاگی برای نمایش وجود ندارد."
    else:
        lines: list[str] = [
            f"دسته: <b>{h(cat_label)}</b>\n"
            f"صفحه <b>{_fa(page)}</b> از <b>{_fa(total_pages)}</b> | مجموع لاگ‌ها: <b>{_fmt_count(total)}</b>"
        ]

        for item in items:
            details = item.get("details_json") or item.get("details") or {}
            if not isinstance(details, dict):
                details = {}

            actor = (
                item.get("actor_label")
                or details.get("actor_tg_user_id")
                or details.get("actor_user_id")
                or item.get("actor_user_id")
                or "-"
            )
            target = (
                details.get("target_tg_user_id")
                or details.get("tg_user_id")
                or details.get("target_user_id")
                or details.get("user_id")
                or item.get("target_id")
                or "-"
            )
            amount = details.get("amount")
            before_balance = details.get("before_balance")
            after_balance = details.get("after_balance")
            reason = details.get("reason") or details.get("failure_reason") or details.get("status") or ""

            extra: list[str] = []
            if amount is not None:
                extra.append(f"💰 مبلغ/تغییر: <b>{h(_fmt_toman(amount))}</b>")
            if before_balance is not None or after_balance is not None:
                extra.append(
                    f"📊 قبل/بعد: <code>{h(str(before_balance or '—'))}</code> → <code>{h(str(after_balance or '—'))}</code>"
                )
            if reason:
                extra.append(f"📝 علت/وضعیت: {h(str(reason))}")

            extra_text = "\n".join(extra)
            lines.append(
                f"#{_fa(item.get('id'))} | <b>{h(_action_fa(item.get('action')))}</b>\n"
                f"👮 ادمین: <code>{h(str(actor))}</code>\n"
                f"🎯 هدف: <code>{h(str(target))}</code> | {h(str(item.get('target_type') or '-'))} #{h(_fa(item.get('target_id') or '-'))}\n"
                f"⏱ <code>{h(format_jalali_datetime(item.get('created_at'), default='—'))}</code>"
                + (f"\n{extra_text}" if extra_text else "")
            )

        text = "\n\n".join(lines)

    await safe_edit_or_send(
        cq.message,
        panel("لاگ عملیات ادمین", text),
        reply_markup=_audit_kb(offset=offset, has_next=has_next, category=category),
        parse_mode="HTML",
    )
    await cq.answer()
