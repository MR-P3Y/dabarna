from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.config import settings
from bot.states.deposit import DepositSG
from bot.keyboards.admin_finance import deposit_admin_alert_kb
from bot.keyboards.join_gate import join_gate_action_kb
from bot.keyboards.deposit import (
    deposit_cancel_kb,
    deposit_confirm_kb,
    deposit_destination_kb,
    deposit_pending_kb,
)
from bot.keyboards.common import back_to_menu_kb
from bot.services.ui import panel
from bot.services.validators import parse_amount
from bot.services.api_client import ApiClient, ApiError
from bot.services.admin_topics import now_stamp, send_to_topic
from bot.services.html import h
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.retry import retry_async
from bot.services.tg_display import resolve_tg_identity
from bot.services.tg_membership import is_member

router = Router()

_FA_DIGITS_TRANS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _to_fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS_TRANS)


def _fmt_toman(value: object) -> str:
    try:
        n = int(value or 0)
    except Exception:
        n = 0
    return f"{_to_fa_digits(f'{n:,}'.replace(',', '٬'))} تومان"


def _mask_card(card_number: object) -> str:
    digits = "".join(ch for ch in str(card_number or "") if ch.isdigit())
    if len(digits) < 4:
        return "----"
    return f"****{digits[-4:]}"


def _destination_title(destination: dict | None) -> str:
    d = destination or {}
    title = str(d.get("title") or "").strip()
    bank = str(d.get("bank_name") or "").strip()
    card_tail = _mask_card(d.get("card_number"))
    if title:
        return title
    if bank:
        return f"{bank} ({card_tail})"
    return f"کارت {card_tail}"


def _destination_text(destination: dict | None, *, slot: int | None = None, count: int | None = None) -> str:
    d = destination or {}
    slot_text = ""
    if slot is not None and count is not None and count > 0:
        slot_text = f"🧩 کارت تخصیصی: <b>{slot} از {count}</b>\n"
    return (
        f"{slot_text}"
        f"🏷 عنوان کارت: <b>{h(_destination_title(d))}</b>\n"
        f"💳 شماره کارت مقصد:\n<code>{h(str(d.get('card_number') or '—'))}</code>\n\n"
        f"👤 نام صاحب کارت: <b>{h(str(d.get('account_name') or '—'))}</b>\n"
        f"🏦 بانک: <b>{h(str(d.get('bank_name') or '—'))}</b>\n"
    )


def _deposit_status_fa(status: str | None) -> str:
    s = str(status or "").upper()
    if s == "AWAITING_RECEIPT":
        return "در انتظار ارسال رسید"
    if s == "PENDING_REVIEW":
        return "در حال بررسی ادمین"
    if s == "APPROVED":
        return "تایید شد ✅"
    if s == "REJECTED":
        return "رد شد ❌"
    return "نامشخص"


def _friendly_deposit_error(e: ApiError) -> str:
    detail_raw = str(getattr(e, "raw_detail", "") or e.detail or "")
    detail = detail_raw.lower()

    if "deposit destination is not configured" in detail:
        return "در حال حاضر کارت مقصد واریز تنظیم نشده است. لطفا با پشتیبانی تماس بگیر."
    if "destination_id is required" in detail:
        return "لطفا ابتدا یکی از کارت‌های مقصد را انتخاب کن."
    if "invalid destination_id" in detail:
        return "کارت انتخاب‌شده معتبر نیست. لطفا دوباره از لیست انتخاب کن."
    if "deposit_request not found" in detail:
        return "درخواست واریز پیدا نشد یا به شما تعلق ندارد."
    if "deposit_request not awaiting receipt" in detail:
        return "این درخواست دیگر در انتظار رسید نیست."
    if "amount" in detail and "positive" in detail:
        return "مبلغ نامعتبر است. لطفا فقط عدد مثبت وارد کن."
    if "receipt" in detail:
        return "ثبت یا دریافت رسید ناموفق بود. لطفا دوباره تلاش کن."
    if e.status >= 500:
        return "سرویس واریز موقتا در دسترس نیست. چند دقیقه بعد دوباره تلاش کن."

    return (
        "درخواست واریز ناموفق بود.\n"
        f"کد خطا: <code>{e.status}</code>\n"
        f"جزئیات: <code>{h(str(e.detail or 'خطای نامشخص'))}</code>"
    )


def _render_destination_choices(items: list[dict]) -> str:
    lines = ["کارت مقصد واریز را انتخاب کن:"]
    for idx, item in enumerate(items, start=1):
        lines.append(
            f"{_to_fa_digits(idx)}. <b>{h(_destination_title(item))}</b>\n"
            f"   🏦 {h(str(item.get('bank_name') or '—'))} | 💳 <code>{h(str(item.get('card_number') or '—'))}</code>"
        )
    return "\n".join(lines)


def _required_group_id() -> int | None:
    raw = settings.BOT_JOIN_GROUP_ID
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _join_invite_link() -> str | None:
    raw = str(settings.BOT_JOIN_GROUP_INVITE_LINK or "").strip()
    return raw or None


async def _notify_admins_new_deposit(
    cq: CallbackQuery,
    api: ApiClient,
    *,
    tg_user_id: int,
    tg_username: str | None,
    deposit_id: int,
    amount: int,
    destination: dict | None = None,
    destination_slot: int | None = None,
    destination_count: int | None = None,
    receipt_hash: str | None = None,
    duplicate_of_ids: list[int] | None = None,
) -> None:
    wallet_balance: int | None = None
    try:
        w = await retry_async(
            lambda: api.bot_get_wallet(tg_user_id=tg_user_id, tg_username=tg_username, limit=1, offset=0),
            attempts=2,
            delay_sec=0.8,
        )
        wallet_balance = int(w.get("balance") or 0)
    except Exception:
        wallet_balance = None

    display_name = await resolve_tg_identity(cq.bot, tg_user_id, username=tg_username)
    user_text = f"<b>{h(display_name)}</b>"
    balance_text = _fmt_toman(wallet_balance) if wallet_balance is not None else "نامشخص"
    dup_ids = [int(x) for x in (duplicate_of_ids or []) if str(x).isdigit()]
    duplicate_line = ""
    if dup_ids:
        show_ids = ", ".join(str(x) for x in dup_ids[:8])
        duplicate_line = f"⚠️ رسید تکراری مشکوک: <code>{show_ids}</code>\n"
    receipt_hash_line = f"🔐 هش رسید: <code>{h(str(receipt_hash or '—'))}</code>\n"
    destination_block = _destination_text(destination, slot=destination_slot, count=destination_count)
    created_at = h(now_stamp())

    text = panel(
        "درخواست واریز جدید",
        "#واریز #درخواست_جدید\n"
        f"🕒 زمان: <code>{created_at}</code>\n"
        f"🧾 شماره درخواست: <b>{deposit_id}</b>\n"
        f"👤 کاربر: {user_text}\n"
        f"💵 مبلغ واریزی: <b>{_fmt_toman(amount)}</b>\n"
        f"👛 موجودی لحظه‌ای کیف پول: <b>{balance_text}</b>\n\n"
        f"{destination_block}\n"
        f"{receipt_hash_line}"
        f"{duplicate_line}"
        "وضعیت درخواست: <b>در حال بررسی ادمین</b>\n\n"
        "برای بررسی سریع‌تر، درخواست را باز کن.",
    )

    kb = deposit_admin_alert_kb(deposit_id=deposit_id, tg_user_id=tg_user_id)

    if dup_ids:
        antifraud_text = panel(
            "هشدار ضدتقلب: رسید تکراری",
            "#ضدتقلب #رسید_تکراری\n"
            f"🕒 زمان: <code>{created_at}</code>\n"
            f"🧾 شماره درخواست: <b>{deposit_id}</b>\n"
            f"👤 کاربر: {user_text}\n"
            f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
            f"{destination_block}\n"
            f"🔐 هش رسید: <code>{h(str(receipt_hash or '—'))}</code>\n"
            f"📌 درخواست(های) مشابه: <code>{show_ids}</code>\n"
            "لطفا قبل از تایید، بررسی ضدتقلب انجام شود.",
        )
        sent_af = await send_to_topic(
            cq.bot,
            name="antifraud",
            text=antifraud_text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_notification=False,
        )
        if (not sent_af) and bool(settings.ADMIN_TOPIC_ENABLE_DM_FALLBACK):
            admin_ids = sorted(int(uid) for uid in settings.admin_ids if int(uid) > 0)
            for admin_tg_id in admin_ids:
                try:
                    await cq.bot.send_message(
                        chat_id=int(admin_tg_id),
                        text=antifraud_text,
                        parse_mode="HTML",
                        reply_markup=kb,
                    )
                except Exception:
                    continue

    sent_to_topic = await send_to_topic(
        cq.bot,
        name="deposit",
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    if sent_to_topic:
        return

    if not bool(settings.ADMIN_TOPIC_ENABLE_DM_FALLBACK):
        return

    admin_ids = sorted(int(uid) for uid in settings.admin_ids if int(uid) > 0)
    if not admin_ids:
        return

    for admin_tg_id in admin_ids:
        try:
            await cq.bot.send_message(
                chat_id=int(admin_tg_id),
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            continue


@router.callback_query(F.data == "menu:deposit")
async def deposit_start(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        required_group_id = _required_group_id()
        if required_group_id is not None:
            member_ok = await is_member(cq.bot, required_group_id, tg_user_id)
            if not member_ok:
                await safe_edit_or_send(
                    cq.message,
                    panel(
                        "عضویت اجباری",
                        "برای ورود به بخش واریز، ابتدا باید عضو گروه بازی باشید.\n"
                        "بعد از عضویت، روی «✅ عضو شدم» بزن.",
                    ),
                    reply_markup=join_gate_action_kb(
                        "deposit",
                        required_group_id,
                        invite_link=_join_invite_link(),
                    ),
                    parse_mode="HTML",
                )
                await cq.answer("ابتدا عضو گروه بازی شوید.", show_alert=True)
                return

    await state.clear()
    try:
        res = await api.bot_list_deposit_destinations(tg_user_id, tg_username)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("واریز", _friendly_deposit_error(e)),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    items = res.get("items") if isinstance(res, dict) else []
    if not isinstance(items, list):
        items = []
    cleaned_items: list[dict] = [it for it in items if isinstance(it, dict) and str(it.get("id") or "").strip()]
    if not cleaned_items:
        await safe_edit_or_send(
            cq.message,
            panel("واریز", "در حال حاضر کارت مقصد فعالی برای واریز ثبت نشده است. لطفا بعدا تلاش کن."),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    await state.update_data(deposit_destinations=cleaned_items)
    await state.set_state(DepositSG.destination)

    text = panel(
        "واریز (کارت‌به‌کارت)",
        "⏳ بررسی واریزها در ساعات مشخص انجام می‌شود.\n"
        "از صبر و شکیبایی شما متشکریم 🙏\n\n"
        + _render_destination_choices(cleaned_items),
    )
    await safe_edit_or_send(
        cq.message,
        text,
        reply_markup=deposit_destination_kb(cleaned_items),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("deposit:dest:"))
async def deposit_choose_destination(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    dest_id = (cq.data or "").split(":", 2)[-1].strip()
    data = await state.get_data()
    items = data.get("deposit_destinations") if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []

    selected = None
    for item in items:
        if isinstance(item, dict) and str(item.get("id") or "").strip() == dest_id:
            selected = item
            break

    if selected is None:
        try:
            res = await api.bot_list_deposit_destinations(tg_user_id, tg_username)
            items = res.get("items") if isinstance(res, dict) else []
        except ApiError as e:
            await safe_edit_or_send(
                cq.message,
                panel("واریز", _friendly_deposit_error(e)),
                reply_markup=back_to_menu_kb(),
                parse_mode="HTML",
            )
            await cq.answer()
            return
        if not isinstance(items, list):
            items = []
        for item in items:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == dest_id:
                selected = item
                break

    if selected is None:
        await cq.answer("کارت انتخاب‌شده معتبر نیست.", show_alert=True)
        return

    await state.update_data(
        deposit_destinations=[it for it in items if isinstance(it, dict)] if items else data.get("deposit_destinations", []),
        selected_destination_id=dest_id,
        selected_destination=selected,
    )
    await state.set_state(DepositSG.amount)
    await safe_edit_or_send(
        cq.message,
        panel(
            "واریز",
            "کارت مقصد انتخاب شد ✅\n\n"
            f"{_destination_text(selected)}\n"
            "💵 حالا مبلغ را به <b>تومان</b> وارد کن (فقط عدد):\n"
            "مثال: <code>200000</code>",
        ),
        reply_markup=deposit_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(DepositSG.amount)
async def deposit_amount(
    m: Message,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    data = await state.get_data()
    selected_destination_id = str(data.get("selected_destination_id") or "").strip()
    if not selected_destination_id:
        items = data.get("deposit_destinations") if isinstance(data, dict) else []
        if isinstance(items, list) and items:
            await state.set_state(DepositSG.destination)
            await m.answer(
                panel("واریز", "ابتدا کارت مقصد را انتخاب کن."),
                reply_markup=deposit_destination_kb([it for it in items if isinstance(it, dict)]),
                parse_mode="HTML",
            )
        else:
            await state.clear()
            await m.answer(
                panel("واریز", "جلسه واریز منقضی شد. دوباره از منو وارد بخش واریز شو."),
                reply_markup=back_to_menu_kb(),
                parse_mode="HTML",
            )
        return

    amount = parse_amount(m.text)
    if amount is None:
        await m.answer(
            panel("واریز", "❌ مبلغ نامعتبر است. فقط عدد مثبت بفرست.\nمثال: <code>200000</code>"),
            reply_markup=deposit_cancel_kb(),
            parse_mode="HTML",
        )
        return

    try:
        dr = await api.bot_create_deposit_request(
            tg_user_id,
            tg_username,
            amount=amount,
            destination_id=selected_destination_id,
        )
    except ApiError as e:
        await m.answer(
            panel("واریز", _friendly_deposit_error(e)),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await state.clear()
        return

    deposit_id = int(dr.get("id") or 0)
    if deposit_id <= 0:
        await m.answer(
            panel("واریز", "خطا در ایجاد درخواست واریز. لطفا دوباره تلاش کن."),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await state.clear()
        return
    destination = dr.get("destination") or {}
    destination_slot = dr.get("destination_slot")
    destination_count = dr.get("destination_count")

    await state.update_data(
        amount=amount,
        deposit_id=deposit_id,
        destination=destination,
        destination_slot=destination_slot,
        destination_count=destination_count,
    )
    await state.set_state(DepositSG.receipt)
    await m.answer(
        panel(
            "واریز",
            f"🧾 شماره درخواست: <b>{deposit_id}</b>\n"
            f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n\n"
            f"{_destination_text(destination, slot=destination_slot, count=destination_count)}\n"
            "این کارت فقط برای همین درخواست معتبر است.\n\n"
            "حالا عکس رسید را ارسال کن 📷",
        ),
        reply_markup=deposit_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(DepositSG.receipt)
async def deposit_receipt(m: Message, state: FSMContext):
    if not m.photo:
        await m.answer(
            panel("واریز", "❌ لطفا فقط عکس رسید را ارسال کن."),
            reply_markup=deposit_cancel_kb(),
            parse_mode="HTML",
        )
        return

    file_id = m.photo[-1].file_id
    await state.update_data(receipt_file_id=file_id)
    data = await state.get_data()
    destination = data.get("destination") or {}
    destination_slot = data.get("destination_slot")
    destination_count = data.get("destination_count")

    text = panel(
        "تایید واریز",
        f"🧾 شماره درخواست: <b>{int(data.get('deposit_id') or 0)}</b>\n"
        f"💵 مبلغ: <b>{_fmt_toman(data.get('amount'))}</b>\n"
        "📷 رسید دریافت شد.\n\n"
        f"{_destination_text(destination, slot=destination_slot, count=destination_count)}\n"
        "اگر اطلاعات درست است، تایید کن.",
    )
    await state.set_state(DepositSG.confirm)
    await m.answer(text, reply_markup=deposit_confirm_kb(), parse_mode="HTML")


@router.callback_query(F.data == "deposit:cancel")
async def deposit_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_or_send(
        cq.message,
        panel("واریز", "لغو شد. از منو ادامه بده."),
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "deposit:confirm")
async def deposit_confirm(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    data = await state.get_data()

    try:
        deposit_id = int(data["deposit_id"])
        res = await api.bot_upload_deposit_receipt(
            tg_user_id,
            tg_username,
            deposit_id=deposit_id,
            receipt_file_id=str(data["receipt_file_id"]),
        )
        amount = int(res.get("amount") or data.get("amount") or 0)
        destination = res.get("destination") or data.get("destination") or {}
        destination_slot = res.get("destination_slot") or data.get("destination_slot")
        destination_count = res.get("destination_count") or data.get("destination_count")

        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel(
                "ثبت شد ✅",
                f"درخواست واریز ثبت شد.\n"
                f"🧾 شماره: <b>{deposit_id}</b>\n"
                f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                f"{_destination_text(destination, slot=destination_slot, count=destination_count)}\n"
                f"وضعیت: <b>{_deposit_status_fa(res.get('status'))}</b>\n\n"
                "⏳ رسید شما در ساعات مشخص بررسی می‌شود.\n"
                "از صبر و شکیبایی شما متشکریم 🙏",
            ),
            reply_markup=deposit_pending_kb(deposit_id),
            parse_mode="HTML",
        )

        duplicate_ids = [int(x) for x in (res.get("duplicate_of_ids") or []) if str(x).isdigit()]
        if duplicate_ids:
            show_ids = ", ".join(str(x) for x in duplicate_ids[:8])
            await cq.message.answer(
                panel(
                    "هشدار رسید تکراری ⚠️",
                    "رسید ارسالی با یک/چند رسید قبلی هش یکسان دارد.\n"
                    f"درخواست(های) مشابه: <code>{show_ids}</code>\n"
                    "اگر این مورد عمدی نیست، لطفا به پشتیبانی اطلاع بده.",
                ),
                parse_mode="HTML",
            )

        await _notify_admins_new_deposit(
            cq,
            api,
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            deposit_id=deposit_id,
            amount=amount,
            destination=destination,
            destination_slot=destination_slot,
            destination_count=destination_count,
            receipt_hash=str(res.get("receipt_hash") or ""),
            duplicate_of_ids=duplicate_ids,
        )
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", _friendly_deposit_error(e)),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
    except (TypeError, ValueError, KeyError):
        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel("خطا", "اطلاعات درخواست ناقص بود. لطفا دوباره از بخش واریز اقدام کن."),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )

    await cq.answer()


@router.callback_query(F.data.startswith("deposit:status:"))
@router.callback_query(F.data.startswith("deposit:refresh:"))
async def deposit_status(
    cq: CallbackQuery,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    try:
        deposit_id = int(cq.data.split(":")[-1])
    except (TypeError, ValueError):
        await cq.answer("شناسه واریز نامعتبر است.", show_alert=True)
        return

    try:
        dr = await api.bot_get_deposit_request(tg_user_id, tg_username, deposit_id=deposit_id)
        status = str(dr.get("status", "UNKNOWN"))
        amount = dr.get("amount", 0)
        destination = dr.get("destination") or {}
        destination_slot = dr.get("destination_slot")
        destination_count = dr.get("destination_count")

        status_text = _deposit_status_fa(status)

        extra = ""
        if status.upper() == "APPROVED":
            extra = "\n\n✅ مبلغ به کیف پول شما اضافه شد."
        elif status.upper() == "REJECTED":
            extra = "\n\nدر صورت نیاز با پشتیبانی هماهنگ کن."

        reply_markup = deposit_pending_kb(deposit_id) if status.upper() in {"AWAITING_RECEIPT", "PENDING_REVIEW"} else back_to_menu_kb()
        await safe_edit_or_send(
            cq.message,
            panel(
                "وضعیت واریز",
                f"🧾 شماره: <b>{deposit_id}</b>\n"
                f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                f"{_destination_text(destination, slot=destination_slot, count=destination_count)}\n"
                f"وضعیت: <b>{status_text}</b>{extra}",
            ),
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        await cq.answer("تازه‌سازی شد ✅")
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", _friendly_deposit_error(e)),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
