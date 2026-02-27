from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
import uuid

from bot.config import settings
from bot.keyboards.admin_finance import withdraw_admin_alert_kb
from bot.keyboards.join_gate import join_gate_action_kb
from bot.states.withdraw import WithdrawSG
from bot.services.ui import panel
from bot.keyboards.withdraw import withdraw_cancel_kb, withdraw_confirm_kb
from bot.services.validators import (
    parse_amount,
    normalize_iban,
    normalize_card,
    normalize_account,
    normalize_name,
)
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


def _withdraw_status_fa(status: str | None) -> str:
    s = str(status or "").upper()
    if s == "PENDING":
        return "در انتظار بررسی"
    if s == "APPROVED":
        return "تایید شده"
    if s == "PAID":
        return "پرداخت شده"
    if s == "REJECTED":
        return "رد شده"
    return "نامشخص"


def _friendly_withdraw_error(e: ApiError) -> str:
    detail_raw = str(getattr(e, "raw_detail", "") or e.detail or "")
    detail = detail_raw.lower()

    if "insufficient available balance" in detail or "insufficient balance" in detail:
        return "مبلغ درخواست از موجودی قابل برداشت کیف پول شما بیشتر است. لطفا مبلغ را کمتر وارد کن."
    if "invalid iban" in detail:
        return "شماره شبا نامعتبر است. فرمت صحیح: پیشوند IR + ۲۴ رقم."
    if "invalid card_number" in detail:
        return "شماره کارت نامعتبر است. شماره کارت باید 16 رقم باشد."
    if "invalid account_number" in detail:
        return "شماره حساب نامعتبر است. شماره حساب باید بین 6 تا 20 رقم باشد."
    if "invalid full_name" in detail:
        return "نام و نام خانوادگی نامعتبر است."
    if e.status >= 500:
        return "سرویس برداشت موقتا در دسترس نیست. چند دقیقه بعد دوباره تلاش کن."

    return (
        "ثبت درخواست برداشت ناموفق بود.\n"
        f"کد خطا: <code>{e.status}</code>\n"
        f"جزئیات: <code>{h(str(e.detail or 'خطای نامشخص'))}</code>"
    )


def summary_html(data: dict) -> str:
    return (
        "لطفا اطلاعات برداشت را بررسی کن:\n\n"
        f"💵 مبلغ: <b>{_fmt_toman(data.get('amount'))}</b>\n"
        f"👤 نام: <b>{h(str(data.get('full_name') or '—'))}</b>\n"
        f"💳 کارت: <code>{h(str(data.get('card_number') or '—'))}</code>\n"
        f"🏦 شبا: <code>{h(str(data.get('iban') or '—'))}</code>\n"
        f"🏧 حساب: <code>{h(str(data.get('account_number') or '—'))}</code>\n"
    )


def _is_skip_optional(text: str | None) -> bool:
    raw = str(text or "").strip().lower()
    return raw in {"", "-", "ندارم", "خالی", "رد", "skip", "none", "no"}


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


async def _notify_admins_new_withdraw(
    cq: CallbackQuery,
    api: ApiClient,
    *,
    tg_user_id: int,
    tg_username: str | None,
    withdraw_id: int,
    amount: int,
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
    created_at = h(now_stamp())

    text = panel(
        "درخواست برداشت جدید",
        "#برداشت #درخواست_جدید\n"
        f"🕒 زمان: <code>{created_at}</code>\n"
        f"🧾 شماره درخواست: <b>{withdraw_id}</b>\n"
        f"👤 کاربر: {user_text}\n"
        f"💵 مبلغ برداشت: <b>{_fmt_toman(amount)}</b>\n"
        f"👛 موجودی لحظه‌ای کیف پول: <b>{balance_text}</b>\n\n"
        "وضعیت درخواست: <b>در انتظار بررسی</b>\n\n"
        "برای کنترل دقیق، با دکمه زیر موجودی را تازه‌سازی کن.",
    )

    kb = withdraw_admin_alert_kb(withdraw_id=withdraw_id, tg_user_id=tg_user_id)
    sent_to_topic = await send_to_topic(
        cq.bot,
        name="withdraw",
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


@router.callback_query(F.data == "menu:withdraw")
async def start_withdraw(
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
                        "برای ورود به بخش برداشت، ابتدا باید عضو گروه بازی باشید.\n"
                        "بعد از عضویت، روی «✅ عضو شدم» بزن.",
                    ),
                    reply_markup=join_gate_action_kb(
                        "withdraw",
                        required_group_id,
                        invite_link=_join_invite_link(),
                    ),
                    parse_mode="HTML",
                )
                await cq.answer("ابتدا عضو گروه بازی شوید.", show_alert=True)
                return

    await state.clear()
    await state.set_state(WithdrawSG.amount)

    balance_line = ""
    try:
        w = await api.bot_get_wallet(tg_user_id=tg_user_id, tg_username=tg_username, limit=1, offset=0)
        balance_line = f"👛 موجودی فعلی شما: <b>{_fmt_toman(w.get('balance'))}</b>\n\n"
    except Exception:
        balance_line = ""

    await safe_edit_or_send(
        cq.message,
        panel(
            "برداشت",
            "⏳ واریز برداشت‌ها در ساعات مشخص بانکی انجام می‌شود.\n"
            "از صبر و شکیبایی شما متشکریم 🙏\n\n"
            "💡 برای مبالغ بالا بهتر است شماره شبا و شماره حساب را هم وارد کنید (اختیاری).\n\n"
            f"{balance_line}"
            "💵 مبلغ برداشت را به <b>تومان</b> وارد کن (فقط عدد):\n"
            "مثال: <code>50000</code>",
        ),
        reply_markup=withdraw_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(WithdrawSG.amount)
async def step_amount(m: Message, state: FSMContext):
    amount = parse_amount(m.text)
    if amount is None:
        await m.answer(
            panel("برداشت", "❌ مبلغ نامعتبر است. فقط عدد مثبت بفرست.\nمثال: <code>50000</code>"),
            reply_markup=withdraw_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(WithdrawSG.full_name)
    await m.answer(
        panel("برداشت", f"💵 مبلغ انتخابی: <b>{_fmt_toman(amount)}</b>\n\nنام و نام خانوادگی صاحب حساب را وارد کن:"),
        reply_markup=withdraw_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(WithdrawSG.full_name)
async def step_name(m: Message, state: FSMContext):
    name = normalize_name(m.text)
    if name is None:
        await m.answer(
            panel("برداشت", "❌ نام نامعتبر است. حداقل 3 کاراکتر وارد کن."),
            reply_markup=withdraw_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(full_name=name)
    await state.set_state(WithdrawSG.card_number)
    await m.answer(
        panel("برداشت", "شماره کارت 16 رقمی را وارد کن:"),
        reply_markup=withdraw_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(WithdrawSG.card_number)
async def step_card(m: Message, state: FSMContext):
    card = normalize_card(m.text)
    if card is None:
        await m.answer(
            panel("برداشت", "❌ شماره کارت نامعتبر است. باید 16 رقم باشد."),
            reply_markup=withdraw_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(card_number=card)
    await state.set_state(WithdrawSG.iban)
    await m.answer(
        panel(
            "برداشت",
            "شماره شبا را وارد کن (اختیاری):\n"
            "فرمت: <code>IR + 24 رقم</code>\n"
            "مثال: <code>IR062960000000100324200001</code>\n\n"
            "اگر نمی‌خواهی وارد کنی، بنویس: <code>ندارم</code>",
        ),
        reply_markup=withdraw_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(WithdrawSG.iban)
async def step_iban(m: Message, state: FSMContext):
    if _is_skip_optional(m.text):
        await state.update_data(iban="")
        await state.set_state(WithdrawSG.account_number)
        await m.answer(
            panel(
                "برداشت",
                "شماره حساب را وارد کن (اختیاری - فقط رقم):\n"
                "مثال: <code>1234567890</code>\n\n"
                "اگر نمی‌خواهی وارد کنی، بنویس: <code>ندارم</code>",
            ),
            reply_markup=withdraw_cancel_kb(),
            parse_mode="HTML",
        )
        return

    iban = normalize_iban(m.text)
    if iban is None:
        await m.answer(
            panel(
                "برداشت",
                "❌ شبا نامعتبر است.\n"
                "فرمت درست: <code>IR + 24 رقم</code>\n"
                "مثال: <code>IR062960000000100324200001</code>\n\n"
                "اگر نمی‌خواهی وارد کنی، بنویس: <code>ندارم</code>",
            ),
            reply_markup=withdraw_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(iban=iban)
    await state.set_state(WithdrawSG.account_number)
    await m.answer(
        panel(
            "برداشت",
            "شماره حساب را وارد کن (اختیاری - فقط رقم):\n"
            "مثال: <code>1234567890</code>\n\n"
            "اگر نمی‌خواهی وارد کنی، بنویس: <code>ندارم</code>",
        ),
        reply_markup=withdraw_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(WithdrawSG.account_number)
async def step_account(m: Message, state: FSMContext):
    if _is_skip_optional(m.text):
        await state.update_data(account_number="")
        data = await state.get_data()
        await state.set_state(WithdrawSG.confirm)
        text = panel("تایید برداشت", summary_html(data))
        await m.answer(text, reply_markup=withdraw_confirm_kb(), parse_mode="HTML")
        return

    acc = normalize_account(m.text)
    if acc is None:
        await m.answer(
            panel(
                "برداشت",
                "❌ شماره حساب نامعتبر است. فقط رقم (6 تا 20 رقم).\n"
                "اگر نمی‌خواهی وارد کنی، بنویس: <code>ندارم</code>",
            ),
            reply_markup=withdraw_cancel_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(account_number=acc)
    data = await state.get_data()
    await state.set_state(WithdrawSG.confirm)

    text = panel("تایید برداشت", summary_html(data))
    await m.answer(text, reply_markup=withdraw_confirm_kb(), parse_mode="HTML")


@router.callback_query(F.data == "withdraw:cancel")
async def cancel_withdraw(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_or_send(cq.message, panel("برداشت", "لغو شد. از منو ادامه بده."), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data == "withdraw:edit")
async def edit_withdraw(cq: CallbackQuery, state: FSMContext):
    await state.set_state(WithdrawSG.amount)
    await safe_edit_or_send(
        cq.message,
        panel("برداشت", "اوکی، از اول شروع می‌کنیم.\nمبلغ برداشت را به تومان وارد کن:"),
        reply_markup=withdraw_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "withdraw:confirm")
async def confirm_withdraw(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    data = await state.get_data()
    idem = f"WDR:{tg_user_id}:{uuid.uuid4().hex[:12]}"

    try:
        await retry_async(lambda: api.bot_sync_user(tg_user_id, tg_username), attempts=3, delay_sec=1.2)

        amount = int(data["amount"])
        res = await retry_async(
            lambda: api.bot_create_withdraw_request(
                tg_user_id,
                tg_username,
                amount=amount,
                full_name=str(data["full_name"]),
                iban=str(data.get("iban") or ""),
                card_number=str(data["card_number"]),
                account_number=str(data.get("account_number") or ""),
                idempotency_key=idem,
            ),
            attempts=3,
            delay_sec=1.2,
        )
        req_id = int(res.get("id") or 0)
        status = _withdraw_status_fa(res.get("status"))

        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel(
                "ثبت شد ✅",
                f"درخواست برداشت ثبت شد.\n"
                f"🧾 شماره: <b>{req_id}</b>\n"
                f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                f"وضعیت: <b>{status}</b>\n\n"
                "⏳ واریزها در ساعات مشخص بانکی انجام می‌شود.\n"
                "از صبر و شکیبایی شما متشکریم 🙏",
            ),
            parse_mode="HTML",
        )

        if req_id > 0:
            await _notify_admins_new_withdraw(
                cq,
                api,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                withdraw_id=req_id,
                amount=amount,
            )

        await cq.answer()
    except ApiError as e:
        await cq.answer()
        await safe_edit_or_send(
            cq.message,
            panel("خطا", _friendly_withdraw_error(e)),
            parse_mode="HTML",
        )
