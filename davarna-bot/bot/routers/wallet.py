from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.api_client import ApiClient, ApiError
from bot.services.jalali import format_jalali_datetime
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel

router = Router()

WALLET_TX_LIMIT = 10
_FA_DIGITS_TRANS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _to_fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS_TRANS)


def _fmt_amount(value: object) -> str:
    try:
        n = int(value or 0)
    except Exception:
        n = 0
    return _to_fa_digits(f"{n:,}".replace(",", "٬")) + " تومان"


def _fmt_datetime(value: object) -> str:
    return format_jalali_datetime(value, default="نامشخص")


def _tx_direction_meta(direction: object) -> tuple[str, str, str]:
    d = str(direction or "").upper()
    if d == "DEBIT":
        return "برداشت", "−", "🔴"
    return "واریز", "+", "🟢"


def _tx_reason_fa(
    reason: object,
    *,
    idempotency_key: object = None,
    ref_type: object = None,
    ref_id: object = None,
    game_rule: object = None,
) -> str:
    raw = str(reason or "").strip()
    up = raw.upper()
    rule = str(game_rule or "UNKNOWN").strip().upper()
    idem = str(idempotency_key or "").strip().upper()
    ref_t = str(ref_type or "").strip().upper()
    try:
        ref_id_int = int(ref_id or 0)
    except Exception:
        ref_id_int = 0

    mapping = {
        "DEPOSIT_MANUAL": "واریز دستی تاییدشده",
        "DEPOSIT_GATEWAY": "واریز از درگاه پرداخت",
        "DEPOSIT_CRYPTO": "واریز تاییدشده رمزارز",
        "BUY_CARDS": "خرید کارت بازی",

        "WITHDRAW": "برداشت از کیف پول",
        "ADJUST": "اصلاح حساب توسط سیستم/ادمین",
    }

    if up in {"PRIZE_COL", "PRIZE_ROW"} and rule not in {"LINE", "LEGACY", "FULL_CARD"}:
        return "جایزه بازی؛ قانون ذخیره‌شده قابل تأیید نیست"

    if up == "PRIZE_COL":
        if rule == "LINE":
            return "دریافت جایزه تورنا (۳ عدد یک ردیف)"
        if rule == "FULL_CARD":
            return "تراکنش جایزه با قانون پرکردنی ناسازگار است"
        return "دریافت جایزه برد ستونی (تورنا)"
    if up == "PRIZE_ROW":
        if rule == "FULL_CARD":
            return "دریافت جایزه پرکردنی (۱۵ عدد)"
        if rule == "LINE":
            return "دریافت جایزه خطی (۵ عدد یک ردیف)"
        return "دریافت جایزه برد ردیفی (تمام)"

    if up == "ADJUST":
        if idem.startswith("LOBBY_REFUND:GAME:"):
            if ref_t == "GAME" and ref_id_int > 0:
                return f"بازگشت وجه خرید کارت (کنسل بازی #{_to_fa_digits(ref_id_int)})"
            return "بازگشت وجه خرید کارت (کنسل بازی)"
        if idem.startswith("UNDO_PRIZE_ROW:GAME:"):
            return "اصلاح جایزه نهایی بازی (بازگردانی اعلام عدد)"
        if idem.startswith("UNDO_PRIZE_COL:GAME:"):
            return "اصلاح جایزه برد تورنا (بازگردانی اعلام عدد)"

    if up in mapping:
        return mapping[up]

    if raw.lower().startswith("admin_charge:"):
        tag = raw.split(":", 1)[1].strip()
        if tag:
            return f"شارژ دستی توسط ادمین ({escape(tag)})"
        return "شارژ دستی توسط ادمین"

    if raw:
        return f"تراکنش سیستمی ({escape(raw)})"
    return "نامشخص"


def _wallet_kb(*, bank_enabled: bool = False, crypto_enabled: bool = False):
    kb = InlineKeyboardBuilder()
    if bank_enabled:
        kb.button(text="📥 واریز کارت‌به‌کارت", callback_data="menu:deposit")
    if crypto_enabled:
        kb.button(text="💎 واریز رمزارز", callback_data="menu:crypto")
    kb.button(text="📤 برداشت", callback_data="menu:withdraw")
    kb.button(text="🔄 تازه‌سازی", callback_data="menu:wallet")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


async def _deposit_method_visibility(api: ApiClient, tg_user_id: int, tg_username: str | None) -> tuple[bool, bool]:
    # Read the same user-facing endpoints used when starting a deposit.
    # If either status cannot be verified, do not advertise that method.
    async def bank_available() -> bool:
        try:
            result = await asyncio.wait_for(api.bot_list_deposit_destinations(tg_user_id, tg_username), timeout=6)
            return bool(isinstance(result, dict) and result.get("items"))
        except Exception:
            return False

    async def crypto_available() -> bool:
        try:
            result = await asyncio.wait_for(api.bot_crypto_options(tg_user_id, tg_username), timeout=6)
            return bool(isinstance(result, dict) and result.get("enabled") and result.get("options"))
        except Exception:
            return False

    return await asyncio.gather(bank_available(), crypto_available())


@router.callback_query(F.data == "menu:wallet")
async def wallet(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    # Start availability calls while wallet history loads to keep the menu responsive.
    availability_task = asyncio.create_task(_deposit_method_visibility(api, tg_user_id, tg_username))
    try:
        w = await api.bot_get_wallet(
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            limit=WALLET_TX_LIMIT,
            offset=0,
        )
        balance = w.get("balance", 0)
        txs = w.get("transactions") or []
        shown = txs[:WALLET_TX_LIMIT]

        total_credit = 0
        total_debit = 0
        for t in shown:
            amt = int(t.get("amount") or 0)
            if str(t.get("direction") or "").upper() == "DEBIT":
                total_debit += amt
            else:
                total_credit += amt

        lines = [
            f"💳 موجودی فعلی: <b>{_fmt_amount(balance)}</b>",
            "",
            f"📘 جمع واریزها در این لیست: <b>{_fmt_amount(total_credit)}</b>",
            f"📕 جمع برداشت‌ها در این لیست: <b>{_fmt_amount(total_debit)}</b>",
            "",
            f"<b>آخرین {_to_fa_digits(WALLET_TX_LIMIT)} تراکنش:</b>",
            "راهنما: 🟢 واریز | 🔴 برداشت",
        ]

        if shown:
            for idx, t in enumerate(shown, start=1):
                direction_fa, sign, badge = _tx_direction_meta(t.get("direction"))
                amount = _fmt_amount(t.get("amount"))
                reason_fa = _tx_reason_fa(
                    t.get("reason"),
                    idempotency_key=t.get("idempotency_key"),
                    ref_type=t.get("ref_type"),
                    ref_id=t.get("ref_id"),
                    game_rule=t.get("game_rule"),
                )
                at = _fmt_datetime(t.get("created_at"))
                lines += [
                    "",
                    f"{_to_fa_digits(idx)}. {badge} <b>{direction_fa}</b> {sign}<b>{amount}</b>",
                    f"علت: <b>{reason_fa}</b>",
                    f"زمان: <code>{escape(at)}</code>",
                ]
        else:
            lines += ["", "هنوز تراکنشی ثبت نشده است."]

        text = panel("کیف پول", "\n".join(lines))
    except ApiError as e:
        text = panel("خطا", f"دریافت اطلاعات کیف پول ناموفق بود.\n<code>{e.status}</code>\n<code>{escape(e.detail)}</code>")

    try:
        bank_enabled, crypto_enabled = await availability_task
    except Exception:
        bank_enabled, crypto_enabled = False, False
    if not bank_enabled and not crypto_enabled:
        text += "\n\nℹ️ روش واریز جدید فعلاً در دسترس نیست؛ تاریخچه کیف پول همچنان قابل مشاهده است."
    await safe_edit_or_send(
        cq.message, text,
        reply_markup=_wallet_kb(bank_enabled=bank_enabled, crypto_enabled=crypto_enabled),
        parse_mode="HTML",
    )
    await cq.answer()
