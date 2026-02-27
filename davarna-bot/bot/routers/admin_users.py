from __future__ import annotations

import re
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.keyboards.admin_users import (
    admin_user_profile_kb,
    admin_users_cancel_kb,
    admin_users_compose_templates_kb,
    admin_users_menu_kb,
    admin_users_search_results_kb,
)
from bot.services.admin_topics import now_stamp, send_to_topic
from bot.services.api_client import ApiClient, ApiError
from bot.services.html import h
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel

router = Router()

_FA_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
_AR_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
_FA_TO_EN = str.maketrans(_FA_DIGITS + _AR_DIGITS, "0123456789" * 2)
_COMPOSE_KIND_LABEL: dict[str, str] = {
    "deposit_reject": "رد واریز",
    "withdraw_reject": "رد برداشت",
    "wallet_adjust": "اصلاح کیف پول",
    "restriction": "اعلان محدودیت",
    "generic": "پیام عمومی",
}
_COMPOSE_KIND_DEFAULT_REASON: dict[str, str] = {
    "deposit_reject": "درخواست واریز شما پس از بررسی رد شد.",
    "withdraw_reject": "درخواست برداشت شما پس از بررسی رد شد.",
    "wallet_adjust": "اصلاح حساب توسط مدیریت انجام شد.",
    "restriction": "به دلیل نقض قوانین، محدودیت موقت اعمال شد.",
    "generic": "اطلاع‌رسانی از سمت پشتیبانی دورنا",
}


class AdminUsersSG(StatesGroup):
    search_input = State()
    restrict_input = State()
    unrestrict_input = State()
    adjust_input = State()
    notify_input = State()


def require_admin(is_admin: bool) -> bool:
    return bool(is_admin)


def _to_int(raw: object, default: int = 0) -> int:
    try:
        return int(str(raw or "").translate(_FA_TO_EN))
    except Exception:
        return default


def _fmt_toman(value: object) -> str:
    n = _to_int(value, 0)
    return f"{n:,} تومان"


def _parse_uid_from_cb(data: str, prefix: str) -> int:
    if not data.startswith(prefix):
        return 0
    return _to_int(data.split(":")[-1], 0)


def _parse_compose_pick_cb(data: str) -> tuple[int, str]:
    m = re.match(r"^admin:users:compose:pick:(\d+):([a-z_]+)$", str(data or ""))
    if not m:
        return 0, ""
    return _to_int(m.group(1), 0), str(m.group(2))


async def _notify_users_topic(
    target: CallbackQuery | Message,
    *,
    action_title: str,
    target_tg_user_id: int | None,
    detail_lines: list[str],
) -> None:
    actor = target.from_user
    actor_name = str(getattr(actor, "full_name", "") or "").strip() or str(getattr(actor, "username", "") or "ادمین")
    actor_user = f"@{actor.username}" if getattr(actor, "username", None) else f"id:{int(actor.id)}"
    body = (
        "#ادمین_کاربران #گزارش_عملیات\n"
        f"🕒 زمان: <code>{now_stamp()}</code>\n"
        f"👤 ادمین: <b>{h(actor_name)}</b> ({h(actor_user)})\n"
        + (f"🎯 کاربر هدف: <code>{int(target_tg_user_id)}</code>\n" if target_tg_user_id and int(target_tg_user_id) > 0 else "")
        + "\n".join(detail_lines)
    )
    text = panel(f"🧑‍💼 {action_title}", body)
    sent = await send_to_topic(
        target.bot,
        name="users",
        text=text,
        parse_mode="HTML",
        disable_notification=False,
    )
    if not sent:
        await send_to_topic(
            target.bot,
            name="general",
            text=text,
            parse_mode="HTML",
            disable_notification=False,
        )


def _profile_text(profile: dict) -> str:
    user = profile.get("user") or {}
    stats = profile.get("stats") or {}
    wallet = profile.get("wallet") or {}
    membership = profile.get("membership") or {}
    restriction = profile.get("restriction") or {}
    roles = profile.get("roles") or []

    username = str(user.get("username") or "").strip()
    username_txt = f"@{username}" if username else "—"
    role_txt = "، ".join(str(x) for x in roles) if roles else "USER"
    member_txt = str(membership.get("status") or "UNKNOWN")
    restriction_txt = "فعال ⛔" if bool(restriction.get("active")) else "غیرفعال ✅"
    restriction_reason = str(restriction.get("reason") or "—")
    restriction_until = str(restriction.get("until") or "—")

    return panel(
        "🧾 پروفایل کاربر",
        "اطلاعات کامل کاربر:\n\n"
        f"🆔 TG ID: <code>{_to_int(user.get('tg_user_id'))}</code>\n"
        f"👤 نام: <b>{h(str(user.get('display_name') or '—'))}</b>\n"
        f"🔖 یوزرنیم: <b>{h(username_txt)}</b>\n"
        f"🎛 نقش‌ها: <b>{h(role_txt)}</b>\n"
        f"👥 عضویت گروه: <b>{h(member_txt)}</b>\n"
        f"💰 موجودی: <b>{h(_fmt_toman(wallet.get('balance')))}</b>\n"
        f"📊 تعداد بازی: <b>{_to_int(stats.get('games_participated'))}</b>\n"
        f"🃏 مجموع کارت: <b>{_to_int(stats.get('cards_purchased'))}</b>\n"
        f"🏆 برد کل: <b>{h(_fmt_toman(stats.get('wins_total_amount')))}</b>\n"
        f"⏱ آخرین فعالیت: <code>{h(str(stats.get('last_activity_at') or '—'))}</code>\n\n"
        f"🚫 محدودیت: <b>{h(restriction_txt)}</b>\n"
        f"📝 علت محدودیت: <code>{h(restriction_reason)}</code>\n"
        f"🕓 پایان محدودیت: <code>{h(restriction_until)}</code>",
    )


def _financial_text(payload: dict) -> str:
    txs = payload.get("wallet_transactions") or []
    deps = payload.get("deposit_requests") or []
    wds = payload.get("withdraw_requests") or []
    timeline = payload.get("timeline") or []

    lines: list[str] = []
    lines.append(f"💰 موجودی: <b>{h(_fmt_toman(payload.get('wallet_balance')))}</b>")
    lines.append(f"📦 تراکنش کیف: <b>{len(txs)}</b> مورد")
    lines.append(f"📥 واریزها: <b>{len(deps)}</b> مورد")
    lines.append(f"📤 برداشت‌ها: <b>{len(wds)}</b> مورد")
    lines.append("")
    lines.append("🕘 آخرین رویدادهای مالی:")
    for item in timeline[:8]:
        created_at = str(item.get("created_at") or "—")
        etype = str(item.get("entry_type") or "-")
        p = item.get("payload") or {}
        amount = _to_int(p.get("amount"), 0)
        rid = _to_int(p.get("id"), 0)
        if etype == "wallet_tx":
            reason = str(p.get("reason_label") or p.get("reason") or "-")
            lines.append(f"• [{h(created_at)}] کیف #{rid} | {h(reason)} | <b>{h(_fmt_toman(amount))}</b>")
        elif etype == "deposit_request":
            lines.append(f"• [{h(created_at)}] واریز #{rid} | وضعیت: <b>{h(str(p.get('status') or '-'))}</b> | مبلغ: <b>{h(_fmt_toman(amount))}</b>")
        elif etype == "withdraw_request":
            lines.append(f"• [{h(created_at)}] برداشت #{rid} | وضعیت: <b>{h(str(p.get('status') or '-'))}</b> | مبلغ: <b>{h(_fmt_toman(amount))}</b>")
        else:
            lines.append(f"• [{h(created_at)}] {h(etype)}")

    return panel("📊 تاریخچه مالی کاربر", "\n".join(lines))


def _games_text(payload: dict) -> str:
    summary = payload.get("summary") or {}
    items = payload.get("items") or []
    lines: list[str] = [
        f"🎮 بازی‌های شرکت‌کرده: <b>{_to_int(summary.get('games_participated'))}</b>",
        f"🃏 کارت خریداری‌شده: <b>{_to_int(summary.get('cards_purchased'))}</b>",
        f"💸 مجموع هزینه: <b>{h(_fmt_toman(summary.get('total_spent')))}</b>",
        f"🏆 مجموع برد: <b>{h(_fmt_toman(summary.get('total_win_amount')))}</b>",
        f"⏱ آخرین برد: <code>{h(str(summary.get('last_win_at') or '—'))}</code>",
        "",
        "📌 آخرین بازی‌ها:",
    ]
    for game in items[:8]:
        win = game.get("win") or {}
        lines.append(
            f"• بازی #{_to_int(game.get('game_id'))} | وضعیت: <b>{h(str(game.get('game_status') or '-'))}</b> | "
            f"کارت: <b>{_to_int(game.get('cards_qty'))}</b> | "
            f"هزینه: <b>{h(_fmt_toman(game.get('total_spent')))}</b> | "
            f"برد: <b>{h(_fmt_toman(win.get('wins_total_amount')))}</b>"
        )
    return panel("🎮 تاریخچه بازی کاربر", "\n".join(lines))


async def _render_users_panel(target: CallbackQuery | Message, *, state: FSMContext | None = None) -> None:
    if state is not None:
        await state.clear()
    text = panel(
        "🧑‍💼 ادمین کاربران",
        "از این بخش می‌تونی مدیریت کامل کاربر را انجام بدی:\n"
        "• جستجو با TG ID / @username / game_id / deposit_id / withdraw_id\n"
        "• مشاهده پروفایل کامل، تاریخچه مالی و تاریخچه بازی\n"
        "• محدودسازی/رفع محدودیت\n"
        "• اصلاح کیف پول با دلیل\n"
        "• ارسال پیام خصوصی به کاربر",
    )
    msg = target.message if isinstance(target, CallbackQuery) else target
    await safe_edit_or_send(
        msg,
        text,
        reply_markup=admin_users_menu_kb(),
        parse_mode="HTML",
    )


def _parse_search_input(raw: str) -> dict:
    txt = str(raw or "").strip().translate(_FA_TO_EN)
    if not txt:
        return {}
    low = txt.lower()

    for prefix in ("gid:", "game:", "game_id:"):
        if low.startswith(prefix):
            return {"game_id": _to_int(txt[len(prefix):], 0)}
    for prefix in ("dep:", "deposit:", "deposit_id:"):
        if low.startswith(prefix):
            return {"deposit_id": _to_int(txt[len(prefix):], 0)}
    for prefix in ("wdr:", "withdraw:", "withdraw_id:"):
        if low.startswith(prefix):
            return {"withdraw_id": _to_int(txt[len(prefix):], 0)}

    if txt.startswith("@"):
        return {"username": txt.lstrip("@")}
    if re.fullmatch(r"\d+", txt):
        return {"tg_user_id": _to_int(txt, 0)}
    return {"username": txt}


async def _show_profile(
    target: CallbackQuery | Message,
    *,
    api: ApiClient,
    tg_user_id: int,
) -> None:
    profile = await api.admin_user_profile(int(tg_user_id))
    msg = target.message if isinstance(target, CallbackQuery) else target
    await safe_edit_or_send(
        msg,
        _profile_text(profile),
        reply_markup=admin_user_profile_kb(int(tg_user_id)),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:users")
async def admin_users_panel(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    await _render_users_panel(cq, state=state)
    await cq.answer()


@router.callback_query(F.data == "admin:users:help")
async def admin_users_help(cq: CallbackQuery, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    text = panel(
        "📘 راهنمای جستجو کاربر",
        "نمونه ورودی‌ها:\n"
        "• TG ID: <code>6171256645</code>\n"
        "• Username: <code>@peymoon</code>\n"
        "• بازی: <code>gid:16</code>\n"
        "• واریز: <code>dep:14</code>\n"
        "• برداشت: <code>wdr:9</code>\n\n"
        "برای عملیات حساس، دلیل شفاف ثبت کن تا در تاپیک مدیریت کاربران گزارش کامل ثبت شود.",
    )
    await safe_edit_or_send(cq.message, text, reply_markup=admin_users_menu_kb(), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "admin:users:search")
async def admin_users_search_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminUsersSG.search_input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "🔎 جستجوی کاربر",
            "یکی از ورودی‌های جستجو را بفرست.\n\n"
            "نمونه:\n"
            "<code>6171256645</code>\n"
            "<code>@peymoon</code>\n"
            "<code>gid:16</code>\n"
            "<code>dep:14</code>\n"
            "<code>wdr:9</code>",
        ),
        reply_markup=admin_users_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(AdminUsersSG.search_input)
async def admin_users_search_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer(panel("خطا", "اجازه دسترسی نداری."), parse_mode="HTML")
        return
    text = str(m.text or "").strip()
    if text.lower() in {"لغو", "/cancel", "cancel"}:
        await _render_users_panel(m, state=state)
        return

    query = _parse_search_input(text)
    if not query or not any(query.values()):
        await m.answer(
            panel("ورودی نامعتبر", "فرمت ورودی را درست وارد کن. برای نمونه‌ها روی «راهنمای ورودی» بزن."),
            parse_mode="HTML",
            reply_markup=admin_users_cancel_kb(),
        )
        return

    try:
        res = await api.admin_users_search(**query, limit=15)
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
        return

    items = res.get("items") or []
    if not items:
        await m.answer(
            panel("نتیجه جستجو", "کاربری با این فیلتر پیدا نشد."),
            parse_mode="HTML",
            reply_markup=admin_users_menu_kb(),
        )
        return

    lines: list[str] = [f"🔎 تعداد نتیجه: <b>{len(items)}</b>", ""]
    for it in items[:15]:
        matched = ", ".join(str(x) for x in (it.get("matched_by") or [])) or "-"
        display = str(it.get("display_name") or it.get("username") or it.get("tg_user_id"))
        lines.append(
            f"• <b>{h(display)}</b> | TG: <code>{_to_int(it.get('tg_user_id'))}</code> | matched_by: <code>{h(matched)}</code>"
        )


    await state.clear()
    await m.answer(
        panel("نتایج جستجوی کاربران", "\n".join(lines)),
        parse_mode="HTML",
        reply_markup=admin_users_search_results_kb(items),
    )


@router.callback_query(F.data.startswith("admin:users:open:"))
async def admin_users_open_profile(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:open:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    try:
        await _show_profile(cq, api=api, tg_user_id=uid)
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data.startswith("admin:users:profile:"))
async def admin_users_profile_refresh(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:profile:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    try:
        await _show_profile(cq, api=api, tg_user_id=uid)
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data.startswith("admin:users:fin:"))
async def admin_users_financial(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:fin:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    try:
        data = await api.admin_user_financial_history(uid, limit=20)
        await safe_edit_or_send(
            cq.message,
            _financial_text(data),
            reply_markup=admin_user_profile_kb(uid),
            parse_mode="HTML",
        )
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data.startswith("admin:users:games:"))
async def admin_users_games(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:games:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    try:
        data = await api.admin_user_games_history(uid, limit=20)
        await safe_edit_or_send(
            cq.message,
            _games_text(data),
            reply_markup=admin_user_profile_kb(uid),
            parse_mode="HTML",
        )
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data.startswith("admin:users:restrict:"))
async def admin_users_restrict_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:restrict:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    await state.clear()
    await state.update_data(target_tg_user_id=uid)
    await state.set_state(AdminUsersSG.restrict_input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "⛔ محدودسازی کاربر",
            f"TG ID: <code>{uid}</code>\n\n"
            "فرمت ورودی:\n"
            "<code>دلیل | دقیقه | اکشن‌ها</code>\n\n"
            "نمونه:\n"
            "<code>سوءاستفاده از خرید | 120 | BUY,DEPOSIT</code>\n"
            "اگر دقیقه ندهی، محدودیت بدون زمان می‌ماند تا رفع شود.",
        ),
        reply_markup=admin_users_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(AdminUsersSG.restrict_input)
async def admin_users_restrict_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer(panel("خطا", "اجازه دسترسی نداری."), parse_mode="HTML")
        return
    txt = str(m.text or "").strip()
    if txt.lower() in {"لغو", "/cancel", "cancel"}:
        await _render_users_panel(m, state=state)
        return

    st = await state.get_data()
    uid = _to_int(st.get("target_tg_user_id"), 0)
    if uid <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه کاربر نامعتبر است."), parse_mode="HTML")
        return

    parts = [p.strip() for p in txt.translate(_FA_TO_EN).split("|")]
    reason = parts[0] if parts else ""
    minutes = _to_int(parts[1], 0) if len(parts) > 1 and parts[1] else None
    actions = [x.strip().upper() for x in (parts[2].split(",") if len(parts) > 2 else []) if x.strip()]
    if len(reason) < 3:
        await m.answer(panel("ورودی نامعتبر", "دلیل باید حداقل ۳ کاراکتر باشد."), parse_mode="HTML")
        return

    try:
        res = await api.admin_user_restrict(uid, reason=reason, minutes=(minutes or None), actions=(actions or None))
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
        return

    restriction = (res.get("restriction") or {})
    await _notify_users_topic(
        m,
        action_title="محدودسازی کاربر",
        target_tg_user_id=uid,
        detail_lines=[
            f"⛔ وضعیت: <b>{'فعال' if bool(restriction.get('active')) else 'غیرفعال'}</b>",
            f"📝 دلیل: <code>{h(reason)}</code>",
            f"⏳ زمان: <code>{h(str(restriction.get('until') or 'بدون زمان'))}</code>",
            f"🎛 اکشن‌ها: <code>{h(', '.join(restriction.get('actions') or []))}</code>",
        ],
    )
    await state.clear()
    await m.answer(panel("محدودسازی انجام شد ✅", f"کاربر <code>{uid}</code> محدود شد."), parse_mode="HTML")
    try:
        await _show_profile(m, api=api, tg_user_id=uid)
    except ApiError:
        pass


@router.callback_query(F.data.startswith("admin:users:unrestrict:"))
async def admin_users_unrestrict_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:unrestrict:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    await state.clear()
    await state.update_data(target_tg_user_id=uid)
    await state.set_state(AdminUsersSG.unrestrict_input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "✅ رفع محدودیت",
            f"TG ID: <code>{uid}</code>\n\n"
            "علت رفع محدودیت را بنویس (اختیاری، اما توصیه می‌شود).\n"
            "نمونه: <code>بررسی انجام شد و مشکل رفع شد</code>",
        ),
        reply_markup=admin_users_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(AdminUsersSG.unrestrict_input)
async def admin_users_unrestrict_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer(panel("خطا", "اجازه دسترسی نداری."), parse_mode="HTML")
        return
    txt = str(m.text or "").strip()
    if txt.lower() in {"لغو", "/cancel", "cancel"}:
        await _render_users_panel(m, state=state)
        return
    st = await state.get_data()
    uid = _to_int(st.get("target_tg_user_id"), 0)
    if uid <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه کاربر نامعتبر است."), parse_mode="HTML")
        return
    try:
        await api.admin_user_unrestrict(uid, reason=txt or None)
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
        return

    await _notify_users_topic(
        m,
        action_title="رفع محدودیت کاربر",
        target_tg_user_id=uid,
        detail_lines=[
            "✅ وضعیت: <b>رفع محدودیت شد</b>",
            f"📝 علت: <code>{h(txt or 'ثبت نشد')}</code>",
        ],
    )
    await state.clear()
    await _show_profile(m, api=api, tg_user_id=uid)


@router.callback_query(F.data.startswith("admin:users:adjust:"))
async def admin_users_adjust_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:adjust:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    await state.clear()
    await state.update_data(target_tg_user_id=uid)
    await state.set_state(AdminUsersSG.adjust_input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "💳 اصلاح کیف پول",
            f"TG ID: <code>{uid}</code>\n\n"
            "فرمت ورودی:\n"
            "<code>+50000 | علت</code>\n"
            "<code>-20000 | علت</code>",
        ),
        reply_markup=admin_users_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(AdminUsersSG.adjust_input)
async def admin_users_adjust_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer(panel("خطا", "اجازه دسترسی نداری."), parse_mode="HTML")
        return
    txt = str(m.text or "").strip().translate(_FA_TO_EN)
    if txt.lower() in {"لغو", "/cancel", "cancel"}:
        await _render_users_panel(m, state=state)
        return
    st = await state.get_data()
    uid = _to_int(st.get("target_tg_user_id"), 0)
    if uid <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه کاربر نامعتبر است."), parse_mode="HTML")
        return

    parts = [p.strip() for p in txt.split("|")]
    amount_raw = parts[0] if parts else ""
    reason = parts[1] if len(parts) > 1 else ""
    amount = _to_int(amount_raw.replace("+", ""), 0)
    if amount_raw.strip().startswith("-"):
        amount = -abs(amount)
    elif amount_raw.strip().startswith("+"):
        amount = abs(amount)
    if amount == 0 or len(reason.strip()) < 3:
        await m.answer(panel("ورودی نامعتبر", "مبلغ صفر نباشد و علت حداقل ۳ کاراکتر باشد."), parse_mode="HTML")
        return

    try:
        res = await api.admin_user_wallet_adjust(uid, amount=amount, reason=reason, notify_user=True)
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
        return

    await _notify_users_topic(
        m,
        action_title="اصلاح کیف پول کاربر",
        target_tg_user_id=uid,
        detail_lines=[
            f"💵 مبلغ اصلاح: <b>{h(_fmt_toman(amount))}</b>",
            f"📉 قبل: <b>{h(_fmt_toman(res.get('wallet_before')))}</b>",
            f"📈 بعد: <b>{h(_fmt_toman(res.get('wallet_after')))}</b>",
            f"📝 علت: <code>{h(reason)}</code>",
            f"🔐 idem: <code>{h(str(res.get('idempotency_key') or '-'))}</code>",
        ],
    )
    await state.clear()
    await _show_profile(m, api=api, tg_user_id=uid)


@router.callback_query(F.data.startswith("admin:users:compose:pick:"))
async def admin_users_compose_pick(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid, kind = _parse_compose_pick_cb(cq.data or "")
    if uid <= 0 or kind not in _COMPOSE_KIND_LABEL:
        await cq.answer("گزینه پیام آماده نامعتبر است.", show_alert=True)
        return

    reason = _COMPOSE_KIND_DEFAULT_REASON.get(kind) or _COMPOSE_KIND_DEFAULT_REASON["generic"]
    try:
        composed = await api.admin_user_compose_message(uid, kind=kind, reason=reason)
        text = str(composed.get("text") or "").strip()
        if not text:
            raise ApiError(500, "empty composed message")
        await api.admin_user_notify(uid, text=text, parse_mode="HTML", disable_notification=False)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"),
            reply_markup=admin_users_compose_templates_kb(uid),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    preview = text[:400]
    label = _COMPOSE_KIND_LABEL.get(kind, kind)
    await _notify_users_topic(
        cq,
        action_title="ارسال پیام آماده",
        target_tg_user_id=uid,
        detail_lines=[
            f"🧩 نوع: <b>{h(label)}</b>",
            f"📝 متن: <code>{h(preview)}</code>",
        ],
    )

    await safe_edit_or_send(
        cq.message,
        panel(
            "پیام آماده ارسال شد ✅",
            f"TG ID: <code>{uid}</code>\n"
            f"نوع پیام: <b>{h(label)}</b>\n\n"
            f"پیش‌نمایش:\n<code>{h(preview)}</code>",
        ),
        reply_markup=admin_users_compose_templates_kb(uid),
        parse_mode="HTML",
    )
    await cq.answer("ارسال شد")


@router.callback_query(F.data.startswith("admin:users:compose:"))
async def admin_users_compose_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:compose:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    await state.clear()
    await safe_edit_or_send(
        cq.message,
        panel(
            "🧩 پیام آماده به کاربر",
            f"TG ID: <code>{uid}</code>\n\n"
            "یکی از پیام‌های آماده را انتخاب کن تا مستقیم برای کاربر ارسال شود.\n"
            "اگر متن سفارشی می‌خواهی، گزینه «ورود پیام دستی» را بزن.",
        ),
        reply_markup=admin_users_compose_templates_kb(uid),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:users:notify:"))
async def admin_users_notify_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    uid = _parse_uid_from_cb(cq.data or "", "admin:users:notify:")
    if uid <= 0:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return
    await state.clear()
    await state.update_data(target_tg_user_id=uid)
    await state.set_state(AdminUsersSG.notify_input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "✉️ پیام خصوصی به کاربر",
            f"TG ID: <code>{uid}</code>\n\n"
            "متن پیام را بفرست.\n"
            "این پیام مستقیم در PV کاربر ارسال می‌شود.",
        ),
        reply_markup=admin_users_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(AdminUsersSG.notify_input)
async def admin_users_notify_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer(panel("خطا", "اجازه دسترسی نداری."), parse_mode="HTML")
        return
    txt = str(m.text or "").strip()
    if txt.lower() in {"لغو", "/cancel", "cancel"}:
        await _render_users_panel(m, state=state)
        return
    st = await state.get_data()
    uid = _to_int(st.get("target_tg_user_id"), 0)
    if uid <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه کاربر نامعتبر است."), parse_mode="HTML")
        return
    if len(txt) < 2:
        await m.answer(panel("ورودی نامعتبر", "متن پیام خیلی کوتاه است."), parse_mode="HTML")
        return
    try:
        await api.admin_user_notify(uid, text=txt, parse_mode="HTML", disable_notification=False)
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{h(e.detail)}</code>"), parse_mode="HTML")
        return

    await _notify_users_topic(
        m,
        action_title="ارسال پیام خصوصی",
        target_tg_user_id=uid,
        detail_lines=[
            "📨 وضعیت: <b>ارسال شد</b>",
            f"📝 متن: <code>{h(txt[:400])}</code>",
        ],
    )
    await state.clear()
    await _show_profile(m, api=api, tg_user_id=uid)


@router.callback_query(F.data == "admin:users:cancel")
async def admin_users_cancel(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    await _render_users_panel(cq, state=state)
    await cq.answer("لغو شد")
