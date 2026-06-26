from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.super_admin import (
    super_admin_admin_detail_kb,
    super_admin_admins_list_kb,
    super_admin_cancel_kb,
    super_admin_deposit_card_cancel_kb,
    super_admin_deposit_card_delete_confirm_kb,
    super_admin_deposit_card_item_kb,
    super_admin_deposit_cards_kb,
    super_admin_panel_kb,
    super_admin_bank_deposit_settings_kb,
    super_admin_crypto_settings_kb,
    super_admin_remove_confirm_kb,
)
from bot.services.admin_acl import (
    get_admin_label,
    grant_dynamic_admin,
    revoke_dynamic_admin,
    set_admin_label,
    sync_dynamic_admin_ids,
)
from bot.services.api_client import ApiClient, ApiError
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel
from bot.states.super_admin import SuperAdminManageSG

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

_FA_TO_EN_DIGITS_TRANS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _require_super_admin(is_super_admin: bool) -> bool:
    return bool(is_super_admin)


def _normalize_digits(raw: str) -> str:
    return (raw or "").translate(_FA_TO_EN_DIGITS_TRANS)


def _parse_tg_user_id(raw: str) -> int | None:
    text = _normalize_digits(raw).strip()
    if not text.isdigit():
        return None
    value = int(text)
    if value <= 0:
        return None
    return value


def _role_fa(role: str) -> str:
    s = (role or "").strip().upper()
    if s == "SUPER_ADMIN":
        return "سوپرادمین"
    if s == "ADMIN":
        return "ادمین"
    return s or "نامشخص"


def _normalize_admin_items(raw_items: list[dict]) -> list[dict]:
    items: list[dict] = []
    for it in raw_items:
        tg_user_id = int(it.get("tg_user_id") or 0)
        user_id = int(it.get("user_id") or 0)
        username = str(it.get("username") or "").strip()
        first_name = str(it.get("first_name") or "").strip()
        last_name = str(it.get("last_name") or "").strip()
        roles = [str(x or "").strip().upper() for x in (it.get("roles") or []) if str(x or "").strip()]
        roles_fa = " | ".join(_role_fa(x) for x in roles) if roles else "بدون نقش"

        full_name = " ".join(x for x in [first_name, last_name] if x).strip()
        manual_label = get_admin_label(tg_user_id)
        display_name = manual_label or full_name or (f"@{username}" if username else f"کاربر ناشناس | {tg_user_id}")

        items.append(
            {
                "tg_user_id": tg_user_id,
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "roles": roles,
                "roles_fa": roles_fa,
                "manual_label": manual_label,
                "display_name": display_name,
                "full_name": full_name,
            }
        )

    def _sort_key(x: dict) -> tuple[int, int]:
        is_super = 0 if "SUPER_ADMIN" in (x.get("roles") or []) else 1
        return (is_super, int(x.get("tg_user_id") or 0))

    return sorted(items, key=_sort_key)


def _find_admin(items: list[dict], tg_user_id: int) -> dict | None:
    uid = int(tg_user_id)
    for it in items:
        if int(it.get("tg_user_id") or 0) == uid:
            return it
    return None


def _parse_destination_id(raw: str) -> str | None:
    did = str(raw or "").strip()
    if not did:
        return None
    if len(did) > 64:
        return None
    return did


def _normalize_destination_items(raw_items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        did = str(item.get("id") or "").strip()
        if not did:
            continue
        out.append(
            {
                "id": did,
                "title": str(item.get("title") or "").strip(),
                "account_name": str(item.get("account_name") or "").strip(),
                "bank_name": str(item.get("bank_name") or "").strip(),
                "card_number": str(item.get("card_number") or "").strip(),
                "iban": str(item.get("iban") or "").strip(),
                "account_number": str(item.get("account_number") or "").strip(),
                "is_active": bool(item.get("is_active", True)),
            }
        )
    return out


def _find_destination(items: list[dict], destination_id: str) -> dict | None:
    did = str(destination_id or "").strip()
    for item in items:
        if str(item.get("id") or "").strip() == did:
            return item
    return None


def _render_destination_detail(item: dict) -> str:
    title = str(item.get("title") or "کارت")
    bank = str(item.get("bank_name") or "—")
    account_name = str(item.get("account_name") or "—")
    card = str(item.get("card_number") or "—")
    iban = str(item.get("iban") or "—")
    account_number = str(item.get("account_number") or "—")
    is_active = "فعال 🟢" if bool(item.get("is_active", True)) else "غیرفعال 🔴"
    did = str(item.get("id") or "—")
    return (
        f"🏷 عنوان: <b>{title}</b>\n"
        f"🆔 شناسه کارت: <code>{did}</code>\n"
        f"وضعیت: <b>{is_active}</b>\n"
        f"🏦 بانک: <b>{bank}</b>\n"
        f"👤 نام صاحب کارت: <b>{account_name}</b>\n"
        f"💳 شماره کارت: <code>{card}</code>\n"
        f"🧾 شبا: <code>{iban or '—'}</code>\n"
        f"🏛 شماره حساب: <code>{account_number or '—'}</code>"
    )


def _parse_destination_payload(raw_text: str) -> tuple[dict, str | None]:
    txt = str(raw_text or "").strip()
    parts = [p.strip() for p in txt.split("|")]
    if len(parts) < 4:
        return {}, "فرمت ورودی کامل نیست. فرمت درست:\nعنوان | نام بانک | شماره کارت | نام صاحب کارت | شبا(اختیاری) | شماره حساب(اختیاری)"

    title = parts[0]
    bank_name = parts[1]
    card_number = "".join(ch for ch in parts[2] if ch.isdigit())
    account_name = parts[3]
    iban = parts[4] if len(parts) > 4 else ""
    account_number = "".join(ch for ch in (parts[5] if len(parts) > 5 else "") if ch.isdigit())

    if len(title) < 2 or len(bank_name) < 2 or len(account_name) < 2:
        return {}, "عنوان، نام بانک و نام صاحب کارت باید حداقل ۲ کاراکتر باشند."
    if len(card_number) < 16 or len(card_number) > 19:
        return {}, "شماره کارت نامعتبر است. باید ۱۶ تا ۱۹ رقم باشد."
    if iban and not iban.upper().startswith("IR"):
        return {}, "شماره شبا باید با IR شروع شود."

    out = {
        "title": title,
        "bank_name": bank_name,
        "card_number": card_number,
        "account_name": account_name,
        "iban": iban.upper(),
        "account_number": account_number,
        "is_active": True,
    }
    return out, None


def _render_admin_detail(item: dict) -> str:
    display_name = str(item.get("display_name") or "—")
    manual_label = str(item.get("manual_label") or "").strip()
    username = str(item.get("username") or "").strip()
    username_txt = f"@{username}" if username else "ندارد"
    tg_user_id = int(item.get("tg_user_id") or 0)
    user_id = int(item.get("user_id") or 0)
    roles_fa = str(item.get("roles_fa") or "بدون نقش")

    lines = [
        f"👤 نام نمایشی: <b>{display_name}</b>",
        f"🎛 نقش: <b>{roles_fa}</b>",
        f"🆔 آیدی تلگرام: <b>{username_txt}</b>",
        f"🧾 شناسه کاربر داخلی: <code>{user_id}</code>",
    ]
    if manual_label:
        lines.append(f"✍️ نام ثبت‌شده دستی: <b>{manual_label}</b>")
    return "\n".join(lines)


async def _fetch_admin_items(api: ApiClient) -> list[dict]:
    out = await api.super_admin_list_admins()
    raw_items = out.get("items") if isinstance(out, dict) else []
    if not isinstance(raw_items, list):
        raw_items = []
    items = _normalize_admin_items(raw_items)
    sync_dynamic_admin_ids({int(it.get("tg_user_id") or 0) for it in items})
    return items


async def _fetch_deposit_destination_items(api: ApiClient) -> list[dict]:
    out = await api.super_admin_list_deposit_destinations()
    raw_items = out.get("items") if isinstance(out, dict) else []
    if not isinstance(raw_items, list):
        raw_items = []
    return _normalize_destination_items(raw_items)


async def _show_admin_list(cq: CallbackQuery, api: ApiClient, *, mode: str, notice: str = "") -> None:
    try:
        items = await _fetch_admin_items(api)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("👑 سوپرادمین", f"خطا در دریافت لیست ادمین‌ها:\n{e.detail}"),
            reply_markup=super_admin_panel_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    normalized_mode = "remove" if str(mode).lower() == "remove" else "list"
    title = "👑 سوپرادمین | حذف ادمین" if normalized_mode == "remove" else "👑 سوپرادمین | لیست ادمین‌ها"
    helper = "روی ادمین موردنظر بزن تا جزئیات/حذف نمایش داده شود."
    if normalized_mode == "remove":
        helper = "برای حذف، ادمین را انتخاب کن و سپس تایید حذف را بزن."
    body = f"تعداد ادمین‌ها: <b>{len(items)}</b>\n\n{helper}"
    if notice:
        body = f"{notice}\n\n{body}"
    await safe_edit_or_send(
        cq.message,
        panel(title, body),
        reply_markup=super_admin_admins_list_kb(items, mode=normalized_mode),
        parse_mode="HTML",
    )
    await cq.answer()


async def _show_panel(target: CallbackQuery | Message, api: ApiClient) -> None:
    try:
        items = await _fetch_admin_items(api)
    except ApiError as e:
        text = panel("👑 سوپرادمین", f"خطا در دریافت اطلاعات:\n{e.detail}")
    else:
        text = panel(
            "👑 سوپرادمین",
            f"تعداد ادمین‌ها: <b>{len(items)}</b>\n\nاز دکمه‌های زیر برای مدیریت ادمین‌ها استفاده کن.",
        )

    if isinstance(target, CallbackQuery):
        await safe_edit_or_send(
            target.message,
            text,
            reply_markup=super_admin_panel_kb(),
            parse_mode="HTML",
        )
        await target.answer()
        return
    await target.answer(text, reply_markup=super_admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "super:admin:panel")
async def super_admin_panel(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    await _show_panel(cq, api)


@router.callback_query(F.data == "super:admin:list")
async def super_admin_list(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_super_admin: bool = False,
):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    await _show_admin_list(cq, api, mode="list")


@router.callback_query(F.data == "super:admin:add")
async def super_admin_add_start(cq: CallbackQuery, state: FSMContext, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.set_state(SuperAdminManageSG.waiting_for_tg_user_id)
    await state.update_data(action="grant")
    await safe_edit_or_send(
        cq.message,
        panel(
            "👑 سوپرادمین | افزودن ادمین",
            "شناسه تلگرام کاربر را ارسال کن.\n\nمثال: <code>6171256645</code>",
        ),
        reply_markup=super_admin_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "super:admin:remove")
async def super_admin_remove_start(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_super_admin: bool = False,
):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    await _show_admin_list(cq, api, mode="remove")


@router.callback_query(F.data.startswith("super:admin:view:"))
async def super_admin_view_item(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return

    parts = (cq.data or "").split(":")
    if len(parts) < 5:
        await cq.answer("درخواست نامعتبر است.", show_alert=True)
        return
    tg_user_id = _parse_tg_user_id(parts[3])
    source = str(parts[4] or "list")
    if tg_user_id is None:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return

    try:
        items = await _fetch_admin_items(api)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("👑 سوپرادمین", f"خطا در دریافت اطلاعات:\n{e.detail}"),
            reply_markup=super_admin_panel_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    item = _find_admin(items, tg_user_id)
    if not item:
        await cq.answer("ادمین موردنظر پیدا نشد.", show_alert=True)
        return

    await safe_edit_or_send(
        cq.message,
        panel("👑 سوپرادمین | جزئیات ادمین", _render_admin_detail(item)),
        reply_markup=super_admin_admin_detail_kb(tg_user_id=tg_user_id, source=source),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("super:admin:remove:pick:"))
async def super_admin_remove_pick(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return

    parts = (cq.data or "").split(":")
    if len(parts) < 5:
        await cq.answer("درخواست نامعتبر است.", show_alert=True)
        return
    tg_user_id = _parse_tg_user_id(parts[4])
    if tg_user_id is None:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return

    try:
        items = await _fetch_admin_items(api)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("👑 سوپرادمین", f"خطا در دریافت اطلاعات:\n{e.detail}"),
            reply_markup=super_admin_panel_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    item = _find_admin(items, tg_user_id)
    if not item:
        await cq.answer("ادمین موردنظر پیدا نشد.", show_alert=True)
        return

    await safe_edit_or_send(
        cq.message,
        panel(
            "👑 سوپرادمین | تایید حذف ادمین",
            f"{_render_admin_detail(item)}\n\n⚠️ آیا از حذف دسترسی ادمینی این کاربر مطمئن هستی؟",
        ),
        reply_markup=super_admin_remove_confirm_kb(tg_user_id=tg_user_id),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("super:admin:remove:confirm:"))
async def super_admin_remove_confirm(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return

    parts = (cq.data or "").split(":")
    if len(parts) < 5:
        await cq.answer("درخواست نامعتبر است.", show_alert=True)
        return
    tg_user_id = _parse_tg_user_id(parts[4])
    if tg_user_id is None:
        await cq.answer("شناسه نامعتبر است.", show_alert=True)
        return

    try:
        await api.super_admin_revoke_admin(tg_user_id=tg_user_id, role="ALL")
        revoke_dynamic_admin(tg_user_id)
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return

    await _show_admin_list(
        cq,
        api,
        mode="remove",
        notice="✅ ادمین با موفقیت حذف شد.",
    )


@router.message(SuperAdminManageSG.waiting_for_tg_user_id)
async def super_admin_add_receive_tg_user_id(m: Message, state: FSMContext, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await m.answer(panel("خطا", "فقط سوپرادمین دسترسی دارد."), parse_mode="HTML")
        await state.clear()
        return

    tg_user_id = _parse_tg_user_id(m.text or "")
    if tg_user_id is None:
        await m.answer(
            panel("خطا", "شناسه تلگرام نامعتبر است.\nفقط عدد معتبر ارسال کن."),
            reply_markup=super_admin_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(action="grant", tg_user_id=tg_user_id)
    await state.set_state(SuperAdminManageSG.waiting_for_display_name)
    await m.answer(
        panel(
            "👑 سوپرادمین | نام ادمین",
            "نام نمایشی ادمین را وارد کن.\n\nمثال: <code>پیمون - ادمین شیفت شب</code>",
        ),
        reply_markup=super_admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(SuperAdminManageSG.waiting_for_display_name)
async def super_admin_add_receive_name(m: Message, state: FSMContext, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await m.answer(panel("خطا", "فقط سوپرادمین دسترسی دارد."), parse_mode="HTML")
        await state.clear()
        return

    display_name = str(m.text or "").strip()
    if len(display_name) < 2:
        await m.answer(
            panel("خطا", "نام خیلی کوتاه است. حداقل ۲ کاراکتر وارد کن."),
            reply_markup=super_admin_cancel_kb(),
            parse_mode="HTML",
        )
        return
    if len(display_name) > 64:
        await m.answer(
            panel("خطا", "نام خیلی طولانی است. حداکثر ۶۴ کاراکتر وارد کن."),
            reply_markup=super_admin_cancel_kb(),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    tg_user_id = int(data.get("tg_user_id") or 0)
    if tg_user_id <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه ادمین در حافظه پیدا نشد. دوباره تلاش کن."), parse_mode="HTML")
        return

    try:
        await api.super_admin_grant_admin(tg_user_id=tg_user_id, role="ADMIN")
        grant_dynamic_admin(tg_user_id)
        set_admin_label(tg_user_id, display_name)
    except ApiError as e:
        await m.answer(
            panel("خطا", f"عملیات انجام نشد:\n{e.detail}"),
            reply_markup=super_admin_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await m.answer(
        panel(
            "👑 سوپرادمین",
            f"✅ ادمین جدید ثبت شد 🎉\n\nنام: <b>{display_name}</b>",
        ),
        parse_mode="HTML",
    )
    await _show_panel(m, api)


async def _show_deposit_cards_panel(target: CallbackQuery | Message, api: ApiClient, *, notice: str = "") -> None:
    try:
        items = await _fetch_deposit_destination_items(api)
    except ApiError as e:
        text = panel("👑 سوپرادمین | کارت‌های واریز", f"خطا در دریافت کارت‌ها:\n{e.detail}")
        kb = super_admin_panel_kb()
    else:
        lines = [f"تعداد کارت‌ها: <b>{len(items)}</b>", "", "کارت موردنظر را برای مشاهده/ویرایش انتخاب کن."]
        if notice:
            lines.insert(0, notice)
            lines.insert(1, "")
        text = panel("👑 سوپرادمین | کارت‌های واریز", "\n".join(lines))
        kb = super_admin_deposit_cards_kb(items)

    if isinstance(target, CallbackQuery):
        await safe_edit_or_send(target.message, text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "super:deposit:cards")
async def super_deposit_cards_panel(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    await _show_deposit_cards_panel(cq, api)


@router.callback_query(F.data.startswith("super:deposit:card:view:"))
async def super_deposit_card_view(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    did = _parse_destination_id((cq.data or "").split(":")[-1])
    if not did:
        await cq.answer("شناسه کارت نامعتبر است.", show_alert=True)
        return
    try:
        items = await _fetch_deposit_destination_items(api)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("👑 سوپرادمین | کارت‌های واریز", f"خطا در دریافت کارت‌ها:\n{e.detail}"),
            reply_markup=super_admin_panel_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return
    item = _find_destination(items, did)
    if not item:
        await cq.answer("کارت پیدا نشد.", show_alert=True)
        return
    await safe_edit_or_send(
        cq.message,
        panel("👑 سوپرادمین | جزئیات کارت", _render_destination_detail(item)),
        reply_markup=super_admin_deposit_card_item_kb(did),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "super:deposit:card:add")
async def super_deposit_card_add_start(cq: CallbackQuery, state: FSMContext, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.set_state(SuperAdminManageSG.waiting_for_deposit_card_payload)
    await state.update_data(deposit_card_mode="add")
    await safe_edit_or_send(
        cq.message,
        panel(
            "👑 سوپرادمین | افزودن کارت واریز",
            "اطلاعات را در یک خط با جداکننده | بفرست:\n\n"
            "<code>عنوان | نام بانک | شماره کارت | نام صاحب کارت | شبا(اختیاری) | شماره حساب(اختیاری)</code>\n\n"
            "نمونه:\n"
            "<code>کارت ملت ۱ | بانک ملت | 6219861234567890 | پیمان قویدل | IR123... | 1234567890</code>",
        ),
        reply_markup=super_admin_deposit_card_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("super:deposit:card:edit:"))
async def super_deposit_card_edit_start(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    did = _parse_destination_id((cq.data or "").split(":")[-1])
    if not did:
        await cq.answer("شناسه کارت نامعتبر است.", show_alert=True)
        return
    try:
        items = await _fetch_deposit_destination_items(api)
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return
    item = _find_destination(items, did)
    if not item:
        await cq.answer("کارت پیدا نشد.", show_alert=True)
        return
    await state.set_state(SuperAdminManageSG.waiting_for_deposit_card_payload)
    await state.update_data(deposit_card_mode="edit", destination_id=did)
    await safe_edit_or_send(
        cq.message,
        panel(
            "👑 سوپرادمین | ویرایش کارت واریز",
            f"{_render_destination_detail(item)}\n\n"
            "نسخه جدید را با همین فرمت ارسال کن:\n"
            "<code>عنوان | نام بانک | شماره کارت | نام صاحب کارت | شبا(اختیاری) | شماره حساب(اختیاری)</code>",
        ),
        reply_markup=super_admin_deposit_card_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("super:deposit:card:delete:confirm:"))
async def super_deposit_card_delete_confirm(cq: CallbackQuery, api: ApiClient, state: FSMContext, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    did = _parse_destination_id((cq.data or "").split(":")[-1])
    if not did:
        await cq.answer("شناسه کارت نامعتبر است.", show_alert=True)
        return
    try:
        await api.super_admin_delete_deposit_destination(did)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("👑 سوپرادمین | کارت‌های واریز", f"حذف انجام نشد:\n{e.detail}"),
            reply_markup=super_admin_panel_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return
    await _show_deposit_cards_panel(cq, api, notice="✅ کارت با موفقیت حذف شد.")


@router.callback_query(F.data.startswith("super:deposit:card:delete:"))
async def super_deposit_card_delete_ask(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    did = _parse_destination_id((cq.data or "").split(":")[-1])
    if not did:
        await cq.answer("شناسه کارت نامعتبر است.", show_alert=True)
        return
    try:
        items = await _fetch_deposit_destination_items(api)
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return
    item = _find_destination(items, did)
    if not item:
        await cq.answer("کارت پیدا نشد.", show_alert=True)
        return
    await safe_edit_or_send(
        cq.message,
        panel(
            "👑 سوپرادمین | تایید حذف کارت",
            f"{_render_destination_detail(item)}\n\n⚠️ آیا از حذف این کارت مطمئن هستی؟",
        ),
        reply_markup=super_admin_deposit_card_delete_confirm_kb(did),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(SuperAdminManageSG.waiting_for_deposit_card_payload)
async def super_deposit_card_payload_submit(
    m: Message,
    state: FSMContext,
    api: ApiClient,
    is_super_admin: bool = False,
):
    if not _require_super_admin(is_super_admin):
        await m.answer(panel("خطا", "فقط سوپرادمین دسترسی دارد."), parse_mode="HTML")
        await state.clear()
        return

    payload, err = _parse_destination_payload(m.text or "")
    if err:
        await m.answer(
            panel("خطا", err),
            reply_markup=super_admin_deposit_card_cancel_kb(),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    mode = str(data.get("deposit_card_mode") or "add").lower()
    destination_id = _parse_destination_id(str(data.get("destination_id") or ""))

    try:
        if mode == "edit":
            if not destination_id:
                await m.answer(panel("خطا", "شناسه کارت برای ویرایش پیدا نشد."), parse_mode="HTML")
                await state.clear()
                return
            await api.super_admin_update_deposit_destination(destination_id, **payload)
            notice = "✅ کارت واریز با موفقیت ویرایش شد."
        else:
            await api.super_admin_add_deposit_destination(**payload)
            notice = "✅ کارت واریز جدید با موفقیت اضافه شد."
    except ApiError as e:
        await m.answer(
            panel("خطا", f"عملیات انجام نشد:\n{e.detail}"),
            reply_markup=super_admin_deposit_card_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await _show_deposit_cards_panel(m, api, notice=notice)



def _onoff(value: object) -> str:
    return "فعال 🟢" if bool(value) else "غیرفعال 🔴"


async def _show_bank_deposit_settings(target: CallbackQuery | Message, api: ApiClient, *, notice: str = "") -> None:
    try:
        out = await api.super_admin_get_bank_deposit_settings()
    except ApiError as e:
        text = panel("👑 سوپرادمین | کارت‌به‌کارت", f"خطا در دریافت وضعیت:\n{e.detail}")
        kb = super_admin_panel_kb()
    else:
        runtime_enabled = bool(out.get("runtime_enabled"))
        active = int(out.get("active_destinations_count") or 0)
        total = int(out.get("total_destinations_count") or 0)
        lines = [
            f"وضعیت نمایش برای کاربران: <b>{_onoff(out.get('enabled'))}</b>",
            f"کلید مدیریتی: <b>{_onoff(runtime_enabled)}</b>",
            f"کارت‌های فعال: <b>{active}</b> از <b>{total}</b>",
        ]
        if notice:
            lines.insert(0, notice)
            lines.insert(1, "")
        text = panel("👑 سوپرادمین | کارت‌به‌کارت", "\n".join(lines))
        kb = super_admin_bank_deposit_settings_kb(runtime_enabled=runtime_enabled, can_enable=active > 0)
    if isinstance(target, CallbackQuery):
        await safe_edit_or_send(target.message, text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "super:deposit:settings")
async def super_bank_deposit_settings_panel(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    await _show_bank_deposit_settings(cq, api)


@router.callback_query(F.data == "super:deposit:settings:toggle")
async def super_bank_deposit_settings_toggle(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    try:
        current = await api.super_admin_get_bank_deposit_settings()
        next_enabled = not bool(current.get("runtime_enabled"))
        await api.super_admin_set_bank_deposit_settings(enabled=next_enabled)
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return
    notice = "✅ کارت‌به‌کارت برای کاربران روشن شد." if next_enabled else "✅ کارت‌به‌کارت برای کاربران خاموش شد."
    await _show_bank_deposit_settings(cq, api, notice=notice)


def _crypto_networks_text(items: object) -> str:
    if not isinstance(items, list) or not items:
        return "-"
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset") or "").strip()
        network = str(item.get("network") or "").strip()
        label = " / ".join(x for x in [asset, network] if x)
        if label:
            out.append(label)
    return "، ".join(out) or "-"


async def _show_crypto_settings(target: CallbackQuery | Message, api: ApiClient, *, notice: str = "") -> None:
    try:
        out = await api.super_admin_get_crypto_settings()
    except ApiError as e:
        text = panel("👑 سوپرادمین | پرداخت رمزارزی", f"خطا در دریافت وضعیت:\n{e.detail}")
        kb = super_admin_panel_kb()
    else:
        runtime_enabled = bool(out.get("runtime_enabled"))
        master_enabled = bool(out.get("master_enabled"))
        configured = bool(out.get("configured"))
        lines = [
            f"وضعیت نمایش برای کاربران: <b>{_onoff(out.get('enabled'))}</b>",
            f"کلید مدیریتی: <b>{_onoff(runtime_enabled)}</b>",
            f"کلید اصلی سرور: <b>{_onoff(master_enabled)}</b>",
            f"تنظیم شبکه/آدرس: <b>{_onoff(configured)}</b>",
            f"شبکه‌ها: <b>{_crypto_networks_text(out.get('networks'))}</b>",
        ]
        warnings = out.get("config_warnings")
        if isinstance(warnings, list) and warnings:
            lines.append(f"هشدار تنظیمات: <code>{' | '.join(str(x) for x in warnings[:4])}</code>")
        if notice:
            lines.insert(0, notice)
            lines.insert(1, "")
        text = panel("👑 سوپرادمین | پرداخت رمزارزی", "\n".join(lines))
        kb = super_admin_crypto_settings_kb(
            runtime_enabled=runtime_enabled,
            can_enable=master_enabled and configured,
        )
    if isinstance(target, CallbackQuery):
        await safe_edit_or_send(target.message, text, reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "super:crypto:settings")
async def super_crypto_settings_panel(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    await state.clear()
    await _show_crypto_settings(cq, api)


@router.callback_query(F.data == "super:crypto:settings:toggle")
async def super_crypto_settings_toggle(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    try:
        current = await api.super_admin_get_crypto_settings()
        next_enabled = not bool(current.get("runtime_enabled"))
        await api.super_admin_set_crypto_settings(enabled=next_enabled)
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return
    notice = "✅ پرداخت رمزارزی برای کاربران روشن شد." if next_enabled else "✅ پرداخت رمزارزی برای کاربران خاموش شد."
    await _show_crypto_settings(cq, api, notice=notice)


@router.callback_query(F.data == "super:crypto:health")
async def super_crypto_health(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    try:
        out = await api.super_admin_crypto_health()
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return
    text = panel(
        "👑 سوپرادمین | سلامت رمزارز",
        "\n".join(
            [
                f"وضعیت کلی: <b>{_onoff(out.get('ok'))}</b>",
                f"نرخ‌ها: <b>{_onoff(out.get('rates_ok'))}</b>",
                f"شبکه‌ها: <b>{_onoff(out.get('chains_ok'))}</b>",
                f"حالت کاهش افزونگی: <b>{'بله' if out.get('degraded') else 'خیر'}</b>",
            ]
        ),
    )
    await safe_edit_or_send(cq.message, text, reply_markup=super_admin_crypto_settings_kb(runtime_enabled=True, can_enable=True), parse_mode="HTML")
    await cq.answer("بررسی انجام شد.")


@router.callback_query(F.data == "super:crypto:reconcile")
async def super_crypto_reconcile(cq: CallbackQuery, api: ApiClient, is_super_admin: bool = False):
    if not _require_super_admin(is_super_admin):
        await cq.answer("فقط سوپرادمین دسترسی دارد.", show_alert=True)
        return
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    try:
        out = await api.super_admin_crypto_reconciliation(from_at=start.isoformat(), to_at=end.isoformat())
    except ApiError as e:
        await cq.answer(e.detail, show_alert=True)
        return
    text = panel(
        "👑 سوپرادمین | تطبیق رمزارز",
        "\n".join(
            [
                f"وضعیت کلی: <b>{_onoff(out.get('ok'))}</b>",
                f"فاکتور شارژشده: <b>{int(out.get('credited_invoices_count') or 0)}</b>",
                f"مجموع شارژ: <b>{int(out.get('credited_toman_total') or 0):,}</b> تومان",
                f"تراکنش بدون فاکتور: <b>{int(out.get('unmatched_onchain_count') or 0)}</b>",
                f"فاکتور بدون مشاهده زنجیره: <b>{int(out.get('missing_onchain_count') or 0)}</b>",
                f"مغایرت کیف پول: <b>{int(out.get('ledger_mismatch_count') or 0)}</b>",
            ]
        ),
    )
    await safe_edit_or_send(cq.message, text, reply_markup=super_admin_crypto_settings_kb(runtime_enabled=True, can_enable=True), parse_mode="HTML")
    await cq.answer("تطبیق انجام شد.")
