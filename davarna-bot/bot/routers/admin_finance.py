from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
import time
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from bot.keyboards.admin_finance import (
    admin_cancel_kb,
    deposit_admin_alert_kb,
    admin_deposits_list_kb,
    deposit_filter_quick_kb,
    admin_finance_menu_kb,
    admin_finance_sales_range_kb,
    admin_reject_reason_kb,
    admin_withdraws_list_kb,
    deposit_item_kb,
    withdraw_filter_quick_kb,
    withdraw_admin_alert_kb,
    withdraw_receipt_prompt_kb,
    withdraw_item_kb,
)
from bot.services.api_client import ApiClient, ApiError
from bot.services.admin_topics import forum_enabled, send_to_topic
from bot.services.html import h
from bot.services.jalali import format_jalali_datetime, jalali_date_to_gregorian_text
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.tg_display import resolve_tg_identity
from bot.services.ui import panel
from bot.states.admin_reject import AdminRejectSG

router = Router()

ADMIN_PAGE_SIZE = 5
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_FA_DIGITS_TRANS = str.maketrans("0123456789", _FA_DIGITS)
_FA_TO_EN_DIGITS_TRANS = str.maketrans(_FA_DIGITS + _AR_DIGITS, "0123456789" * 2)


@dataclass
class DepositFilter:
    created_from: str | None = None
    created_to: str | None = None
    min_amount: int | None = None
    max_amount: int | None = None


class AdminDepositFilterSG(StatesGroup):
    input = State()


class AdminWithdrawFilterSG(StatesGroup):
    input = State()


class AdminWithdrawReceiptSG(StatesGroup):
    payload = State()


class AdminFinanceSalesRangeSG(StatesGroup):
    input = State()


ADMIN_DEPOSIT_FILTERS: dict[int, DepositFilter] = {}
ADMIN_WITHDRAW_FILTERS: dict[int, DepositFilter] = {}


def require_admin(is_admin: bool) -> bool:
    return bool(is_admin)


def _to_int(raw: str | None, default: int = 0) -> int:
    try:
        return int(raw or "")
    except (TypeError, ValueError):
        return default


def _to_fa_digits(value: object) -> str:
    return str(value).translate(_FA_DIGITS_TRANS)


def _fmt_toman(value: object) -> str:
    try:
        n = int(value or 0)
    except Exception:
        n = 0
    return f"{_to_fa_digits(f'{n:,}'.replace(',', '٬'))} تومان"


def _fmt_count(value: object) -> str:
    try:
        n = int(value or 0)
    except Exception:
        n = 0
    return _to_fa_digits(f"{n:,}".replace(",", "٬"))


async def _display_name(
    target: CallbackQuery | Message,
    *,
    tg_user_id: object = None,
    tg_username: object = None,
    full_name: object = None,
) -> str:
    return await resolve_tg_identity(
        target.bot,
        _to_int(str(tg_user_id or ""), 0),
        username=str(tg_username or "").strip() or None,
        full_name=str(full_name or "").strip() or None,
    )


def _deposit_destination_text(item: dict) -> str:
    d = item.get("destination") or {}
    slot = _to_int(str(item.get("destination_slot") or ""), 0)
    count = _to_int(str(item.get("destination_count") or ""), 0)
    slot_line = ""
    if slot > 0 and count > 0:
        slot_line = f"🧩 کارت تخصیصی: <b>{slot} از {count}</b>\n"
    title_line = ""
    title = str(d.get("title") or "").strip()
    if title:
        title_line = f"🏷 عنوان: <b>{h(title)}</b>\n"
    return (
        f"{slot_line}"
        f"{title_line}"
        f"💳 کارت مقصد: <code>{h(str(d.get('card_number') or '—'))}</code>\n"
        f"👤 صاحب کارت: <b>{h(str(d.get('account_name') or '—'))}</b>\n"
        f"🏦 بانک: <b>{h(str(d.get('bank_name') or '—'))}</b>\n"
    )


def _normalize_digits_en(raw: str) -> str:
    return (raw or "").translate(_FA_TO_EN_DIGITS_TRANS)


def _chat_id_from_target(target: CallbackQuery | Message) -> int:
    if isinstance(target, CallbackQuery):
        return int(target.message.chat.id)
    return int(target.chat.id)


def _get_deposit_filter(chat_id: int) -> DepositFilter:
    return ADMIN_DEPOSIT_FILTERS.get(int(chat_id), DepositFilter())


def _get_withdraw_filter(chat_id: int) -> DepositFilter:
    return ADMIN_WITHDRAW_FILTERS.get(int(chat_id), DepositFilter())


def _is_deposit_filter_active(flt: DepositFilter) -> bool:
    return any([flt.created_from, flt.created_to, flt.min_amount is not None, flt.max_amount is not None])


def _deposit_filter_summary(flt: DepositFilter) -> str:
    if not _is_deposit_filter_active(flt):
        return "فیلتر: <b>بدون فیلتر</b>"

    created_from = h(format_jalali_datetime(flt.created_from, default="—"))
    created_to = h(format_jalali_datetime(flt.created_to, default="—"))
    min_amount = _fmt_toman(flt.min_amount) if flt.min_amount is not None else "—"
    max_amount = _fmt_toman(flt.max_amount) if flt.max_amount is not None else "—"
    return (
        "فیلتر فعال:\n"
        f"🗓 از: <code>{created_from}</code>\n"
        f"🗓 تا: <code>{created_to}</code>\n"
        f"💵 حداقل: <b>{min_amount}</b>\n"
        f"💵 حداکثر: <b>{max_amount}</b>"
    )


def _withdraw_filter_summary(flt: DepositFilter) -> str:
    if not _is_deposit_filter_active(flt):
        return "فیلتر برداشت: <b>بدون فیلتر</b>"

    created_from = h(format_jalali_datetime(flt.created_from, default="—"))
    created_to = h(format_jalali_datetime(flt.created_to, default="—"))
    min_amount = _fmt_toman(flt.min_amount) if flt.min_amount is not None else "—"
    max_amount = _fmt_toman(flt.max_amount) if flt.max_amount is not None else "—"
    return (
        "فیلتر برداشت فعال:\n"
        f"🗓 از: <code>{created_from}</code>\n"
        f"🗓 تا: <code>{created_to}</code>\n"
        f"💵 حداقل: <b>{min_amount}</b>\n"
        f"💵 حداکثر: <b>{max_amount}</b>"
    )


def _parse_deposit_filter_text(raw_text: str) -> DepositFilter | None:
    txt = _normalize_digits_en(raw_text or "").replace("/", "-").strip()
    if not txt:
        return None

    from_match = re.search(r"(?:از|from)\s*[:=]?\s*(\d{4}-\d{2}-\d{2})", txt, flags=re.IGNORECASE)
    to_match = re.search(r"(?:تا|to)\s*[:=]?\s*(\d{4}-\d{2}-\d{2})", txt, flags=re.IGNORECASE)
    min_match = re.search(r"(?:حداقل|min)\s*[:=]?\s*([0-9,]+)", txt, flags=re.IGNORECASE)
    max_match = re.search(r"(?:حداکثر|max)\s*[:=]?\s*([0-9,]+)", txt, flags=re.IGNORECASE)

    created_from = jalali_date_to_gregorian_text(from_match.group(1)) if from_match else None
    created_to = jalali_date_to_gregorian_text(to_match.group(1)) if to_match else None

    min_amount = None
    if min_match:
        try:
            min_amount = int(min_match.group(1).replace(",", "").replace("٬", ""))
        except Exception:
            min_amount = None

    max_amount = None
    if max_match:
        try:
            max_amount = int(max_match.group(1).replace(",", "").replace("٬", ""))
        except Exception:
            max_amount = None

    if created_from and created_to and created_from > created_to:
        return None
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        return None
    if not any([created_from, created_to, min_amount is not None, max_amount is not None]):
        return None

    return DepositFilter(
        created_from=created_from,
        created_to=created_to,
        min_amount=min_amount,
        max_amount=max_amount,
    )


def _build_quick_deposit_filter(kind: str) -> DepositFilter | None:
    today = datetime.now().date()
    k = (kind or "").strip().lower()
    if k == "today":
        d = today.isoformat()
        return DepositFilter(created_from=d, created_to=d)
    if k == "yesterday":
        d = (today - timedelta(days=1)).isoformat()
        return DepositFilter(created_from=d, created_to=d)
    if k == "7d":
        start = (today - timedelta(days=6)).isoformat()
        end = today.isoformat()
        return DepositFilter(created_from=start, created_to=end)
    if k == "high500":
        return DepositFilter(min_amount=500000)
    if k == "high1m":
        return DepositFilter(min_amount=1000000)
    return None


def _parse_admin_datetime_text(raw: str, *, end_of_day_if_date_only: bool) -> datetime | None:
    txt = _normalize_digits_en(raw or "").strip()
    if not txt:
        return None

    normalized = txt.replace("/", "-").replace("T", " ").strip()
    normalized = re.sub(r"\s+", " ", normalized)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        d = datetime.strptime(jalali_date_to_gregorian_text(normalized), "%Y-%m-%d")
        if end_of_day_if_date_only:
            return d.replace(hour=23, minute=59, second=59)
        return d.replace(hour=0, minute=0, second=0)

    if " " in normalized:
        date_part, time_part = normalized.split(" ", 1)
        normalized = f"{jalali_date_to_gregorian_text(date_part)} {time_part}"

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt)
        except Exception:
            continue
    return None


def _parse_sales_range_input(text: str | None) -> tuple[datetime, datetime] | None:
    raw = _normalize_digits_en(text or "").strip()
    if not raw:
        return None

    from_match = re.search(
        r"(?mi)^\s*(?:از|from)\s*[:=]?\s*([0-9/\-:T ]+)\s*$",
        raw,
    )
    to_match = re.search(
        r"(?mi)^\s*(?:تا|to)\s*[:=]?\s*([0-9/\-:T ]+)\s*$",
        raw,
    )
    if from_match and to_match:
        start = _parse_admin_datetime_text(from_match.group(1), end_of_day_if_date_only=False)
        end = _parse_admin_datetime_text(to_match.group(1), end_of_day_if_date_only=True)
        if start is None or end is None:
            return None
        return start, end

    one_line_match = re.match(r"^\s*([0-9/\-:T ]+?)\s+(?:تا|to)\s+([0-9/\-:T ]+)\s*$", raw, flags=re.IGNORECASE)
    if one_line_match:
        start = _parse_admin_datetime_text(one_line_match.group(1), end_of_day_if_date_only=False)
        end = _parse_admin_datetime_text(one_line_match.group(2), end_of_day_if_date_only=True)
        if start is None or end is None:
            return None
        return start, end

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) >= 2:
        first = re.sub(r"^(?:از|from)\s*[:=]?\s*", "", lines[0], flags=re.IGNORECASE)
        second = re.sub(r"^(?:تا|to)\s*[:=]?\s*", "", lines[1], flags=re.IGNORECASE)
        start = _parse_admin_datetime_text(first, end_of_day_if_date_only=False)
        end = _parse_admin_datetime_text(second, end_of_day_if_date_only=True)
        if start is None or end is None:
            return None
        return start, end

    return None


def _parse_deposit_action(data: str) -> tuple[int, int]:
    parts = data.split(":")
    deposit_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    if len(parts) >= 6 and parts[4] == "o":
        return deposit_id, max(0, _to_int(parts[5], 0))
    if len(parts) == 5:
        # Backward compatibility:
        # old callbacks were `...:reject:{deposit_id}:{tg_user_id}`
        # new callbacks should always include `:o:{offset}`.
        return deposit_id, 0
    if len(parts) >= 7:
        return deposit_id, max(0, _to_int(parts[6], 0))
    return deposit_id, 0


def _withdraw_status_fa(status: str | None) -> str:
    s = (status or "").upper()
    if s == "APPROVED":
        return "تاییدشده"
    if s == "PAID":
        return "پرداخت‌شده"
    if s == "REJECTED":
        return "ردشده"
    return "در انتظار"


def _deposit_status_fa(status: str | None) -> str:
    s = (status or "").upper()
    if s == "AWAITING_RECEIPT":
        return "در انتظار رسید"
    if s == "PENDING_REVIEW":
        return "در انتظار بررسی"
    if s == "APPROVED":
        return "تاییدشده"
    if s == "REJECTED":
        return "ردشده"
    return "نامشخص"


def _parse_withdraw_page_ctx(data: str) -> tuple[str, int]:
    # New: admin:withdraws:page:{status}:{offset}
    # Old: admin:withdraws:page:{offset}
    parts = data.split(":")
    if len(parts) >= 6:
        return (parts[4] or "PENDING").upper(), max(0, _to_int(parts[5], 0))
    return "PENDING", max(0, _to_int(parts[-1], 0))


def _parse_withdraw_view_ctx(data: str) -> tuple[int, str, int]:
    # New: admin:withdraws:view:{withdraw_id}:{status}:{offset}
    # Old: admin:withdraws:view:{withdraw_id}:{offset}
    parts = data.split(":")
    withdraw_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    if len(parts) >= 6:
        status = (parts[4] or "PENDING").upper()
        back_offset = max(0, _to_int(parts[5], 0))
        return withdraw_id, status, back_offset
    back_offset = _to_int(parts[4] if len(parts) > 4 else None, 0)
    return withdraw_id, "PENDING", back_offset


def _parse_withdraw_action_ctx(data: str) -> tuple[str, int, str, int]:
    # admin:withdraw:{approve|reject|send-receipt}:{withdraw_id}:{status}:{offset}
    parts = data.split(":")
    action = parts[2] if len(parts) > 2 else ""
    withdraw_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = (parts[4] if len(parts) > 4 else "PENDING").upper()
    offset = max(0, _to_int(parts[5] if len(parts) > 5 else None, 0))
    return action, withdraw_id, status, offset


def _parse_withdraw_live_ctx(data: str) -> tuple[int, int]:
    # admin:withdraw:live:{withdraw_id}:{tg_user_id}
    parts = data.split(":")
    withdraw_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    tg_user_id = _to_int(parts[4] if len(parts) > 4 else None, -1)
    return withdraw_id, tg_user_id


def _parse_deposit_live_ctx(data: str) -> tuple[int, int]:
    # admin:deposit:live:{deposit_id}:{tg_user_id}
    parts = data.split(":")
    deposit_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    tg_user_id = _to_int(parts[4] if len(parts) > 4 else None, -1)
    return deposit_id, tg_user_id


def _quick_reject_reason(kind: str, code: str) -> str | None:
    k = (kind or "").strip().lower()
    c = (code or "").strip().lower()
    if k == "withdraw":
        mapping = {
            "no_balance": "عدم موجودی برای انجام پرداخت در این لحظه. لطفا کمی بعد دوباره درخواست ثبت کنید.",
            "bank_issue": "به دلیل اختلال موقت شبکه بانکی، درخواست فعلا قابل انجام نیست. لطفا مجددا تلاش کنید.",
        }
        return mapping.get(c)
    if k == "deposit":
        mapping = {
            "invalid_receipt": "رسید ارسالی نامعتبر یا ناخوانا بود.",
            "amount_mismatch": "مبلغ رسید با مبلغ درخواست ثبت‌شده مطابقت ندارد.",
        }
        return mapping.get(c)
    return None


async def _withdraw_wallet_status_note(api: ApiClient, wr: dict) -> str:
    tg_user_id = _to_int(wr.get("tg_user_id"), 0)
    if tg_user_id <= 0:
        return "👛 موجودی فعلی کیف پول: <b>نامشخص</b>\n"

    tg_username_raw = wr.get("tg_username")
    tg_username = str(tg_username_raw).strip() if tg_username_raw is not None else None
    if tg_username == "":
        tg_username = None

    try:
        wallet = await api.bot_get_wallet(tg_user_id, tg_username)
    except Exception:
        return "👛 موجودی فعلی کیف پول: <b>خطا در دریافت</b>\n"

    balance_raw = (
        wallet.get("balance")
        if isinstance(wallet, dict)
        else None
    )
    if balance_raw is None and isinstance(wallet, dict):
        balance_raw = wallet.get("wallet_balance")
    if balance_raw is None and isinstance(wallet, dict):
        balance_raw = wallet.get("amount")

    return f"👛 موجودی فعلی کیف پول: <b>{_fmt_toman(balance_raw)}</b>\n"


def _withdraw_detail_panel_text(
    *,
    withdraw_id: int,
    wr: dict,
    status: str,
    user_display_name: str = "—",
    extra_note: str = "",
) -> str:
    text = panel(
        f"برداشت {_withdraw_status_fa(status)}",
        f"🧾 شماره: <b>{withdraw_id}</b>\n"
        f"وضعیت: <b>{_withdraw_status_fa(status)}</b>\n"
        f"👤 کاربر: <b>{h(user_display_name)}</b>\n"
        f"🧾 شناسه داخلی: <code>{wr.get('user_id')}</code>\n"
        f"💵 مبلغ: <b>{_fmt_toman(wr.get('amount'))}</b>\n"
        f"🙍 نام: <b>{h(str(wr.get('full_name') or '—'))}</b>\n"
        f"💳 کارت: <code>{h(str(wr.get('card_number') or '—'))}</code>\n"
        f"🏦 شبا: <code>{h(str(wr.get('iban') or '—'))}</code>\n"
        f"🏛 حساب: <code>{h(str(wr.get('account_number') or '—'))}</code>\n"
        f"🔖 پیگیری پرداخت: <code>{h(str(wr.get('paid_tracking') or '—'))}</code>\n"
        f"⏱ {h(format_jalali_datetime(wr.get('created_at'), default='—'))}\n",
    )
    if extra_note:
        text += f"\n{extra_note}"
    return text


async def _render_deposits_page(cq: CallbackQuery, api: ApiClient, *, offset: int):
    chat_id = int(cq.message.chat.id)
    flt = _get_deposit_filter(chat_id)
    filter_active = _is_deposit_filter_active(flt)

    offset = max(0, offset)
    res = await api.admin_list_deposits(
        status="PENDING_REVIEW",
        limit=ADMIN_PAGE_SIZE + 1,
        offset=offset,
        created_from=flt.created_from,
        created_to=flt.created_to,
        min_amount=flt.min_amount,
        max_amount=flt.max_amount,
    )
    raw_items = res.get("items") or []
    has_next = len(raw_items) > ADMIN_PAGE_SIZE
    items = raw_items[:ADMIN_PAGE_SIZE]

    if not items and offset > 0:
        offset = max(0, offset - ADMIN_PAGE_SIZE)
        res = await api.admin_list_deposits(
            status="PENDING_REVIEW",
            limit=ADMIN_PAGE_SIZE + 1,
            offset=offset,
            created_from=flt.created_from,
            created_to=flt.created_to,
            min_amount=flt.min_amount,
            max_amount=flt.max_amount,
        )
        raw_items = res.get("items") or []
        has_next = len(raw_items) > ADMIN_PAGE_SIZE
        items = raw_items[:ADMIN_PAGE_SIZE]

    if not items:
        empty_reason = "هیچ موردی وجود ندارد."
        if filter_active:
            empty_reason = "با فیلتر فعلی موردی پیدا نشد.\n\n" + _deposit_filter_summary(flt)
        w_flt = _get_withdraw_filter(chat_id)
        await safe_edit_or_send(
            cq.message,
            panel("واریزهای در انتظار", empty_reason),
            reply_markup=admin_finance_menu_kb(
                deposit_filter_active=filter_active,
                withdraw_filter_active=_is_deposit_filter_active(w_flt),
            ),
            parse_mode="HTML",
        )
        return

    page_no = (offset // ADMIN_PAGE_SIZE) + 1
    lines = [f"صفحه: <b>{page_no}</b>", _deposit_filter_summary(flt), "", "برای مشاهده جزئیات، روی یکی از موارد زیر بزن:"]
    for it in items:
        amount = _fmt_toman(it.get("amount"))
        dup_badge = " | ⚠️ رسید تکراری" if bool(it.get("is_duplicate_receipt")) else ""
        display_name = await _display_name(
            cq,
            tg_user_id=it.get("tg_user_id"),
            tg_username=it.get("tg_username"),
            full_name=it.get("full_name"),
        )
        lines.append(
            f"#{it.get('id')} | کاربر:{it.get('user_id')} | مبلغ: <b>{amount}</b> | "
            f"👤 <b>{h(display_name)}</b>{dup_badge}"
        )

    await safe_edit_or_send(
        cq.message,
        panel("صف واریزهای در انتظار", "\n".join(lines)),
        reply_markup=admin_deposits_list_kb(items, offset=offset, has_next=has_next),
        parse_mode="HTML",
    )


async def _render_withdraws_page(cq: CallbackQuery, api: ApiClient, *, status: str, offset: int):
    chat_id = int(cq.message.chat.id)
    d_flt = _get_deposit_filter(chat_id)
    w_flt = _get_withdraw_filter(chat_id)
    withdraw_filter_active = _is_deposit_filter_active(w_flt)

    status_u = (status or "PENDING").upper()
    status_fa = _withdraw_status_fa(status_u)
    offset = max(0, offset)
    res = await api.admin_list_withdraws(
        status=status_u,
        limit=ADMIN_PAGE_SIZE + 1,
        offset=offset,
        created_from=w_flt.created_from,
        created_to=w_flt.created_to,
        min_amount=w_flt.min_amount,
        max_amount=w_flt.max_amount,
    )
    raw_items = res.get("items") or []
    has_next = len(raw_items) > ADMIN_PAGE_SIZE
    items = raw_items[:ADMIN_PAGE_SIZE]

    if not items and offset > 0:
        offset = max(0, offset - ADMIN_PAGE_SIZE)
        res = await api.admin_list_withdraws(
            status=status_u,
            limit=ADMIN_PAGE_SIZE + 1,
            offset=offset,
            created_from=w_flt.created_from,
            created_to=w_flt.created_to,
            min_amount=w_flt.min_amount,
            max_amount=w_flt.max_amount,
        )
        raw_items = res.get("items") or []
        has_next = len(raw_items) > ADMIN_PAGE_SIZE
        items = raw_items[:ADMIN_PAGE_SIZE]

    if not items:
        empty_reason = "هیچ موردی وجود ندارد."
        if withdraw_filter_active:
            empty_reason = "با فیلتر فعلی موردی پیدا نشد.\n\n" + _withdraw_filter_summary(w_flt)
        await safe_edit_or_send(
            cq.message,
            panel(f"برداشت‌های {status_fa}", empty_reason),
            reply_markup=admin_finance_menu_kb(
                deposit_filter_active=_is_deposit_filter_active(d_flt),
                withdraw_filter_active=withdraw_filter_active,
            ),
            parse_mode="HTML",
        )
        return

    page_no = (offset // ADMIN_PAGE_SIZE) + 1
    lines = [f"صفحه: <b>{page_no}</b>", _withdraw_filter_summary(w_flt), "", "برای مشاهده جزئیات، روی یکی از موارد زیر بزن:"]
    for it in items:
        amount = _fmt_toman(it.get("amount"))
        display_name = await _display_name(
            cq,
            tg_user_id=it.get("tg_user_id"),
            tg_username=it.get("tg_username"),
            full_name=it.get("full_name"),
        )
        lines.append(
            f"#{it.get('id')} | کاربر:{it.get('user_id')} | مبلغ: <b>{amount}</b> | "
            f"👤 <b>{h(display_name)}</b> | وضعیت: <b>{_withdraw_status_fa(it.get('status'))}</b>"
        )

    await safe_edit_or_send(
        cq.message,
        panel(f"صف برداشت‌های {status_fa}", "\n".join(lines)),
        reply_markup=admin_withdraws_list_kb(items, status=status_u, offset=offset, has_next=has_next),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:finance")
async def admin_finance_home(cq: CallbackQuery, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    chat_id = int(cq.message.chat.id)
    d_flt = _get_deposit_filter(chat_id)
    w_flt = _get_withdraw_filter(chat_id)
    await safe_edit_or_send(
        cq.message,
        panel("ادمین مالی", "یکی از گزینه‌ها را انتخاب کن:"),
        reply_markup=admin_finance_menu_kb(
            deposit_filter_active=_is_deposit_filter_active(d_flt),
            withdraw_filter_active=_is_deposit_filter_active(w_flt),
        ),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "admin:finance:sales:range")
async def admin_finance_sales_range_open(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminFinanceSalesRangeSG.input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "📊 گزارش فروش بازه‌ای",
            "بازه زمانی را دستی وارد کن.\n\n"
            "فرمت پیشنهادی:\n"
            "<code>از: 1405/04/01 00:00\n"
            "تا: 1405/04/01 23:59</code>\n\n"
            "یا یک‌خطی:\n"
            "<code>1405/04/01 00:00 تا 1405/04/01 23:59</code>\n\n"
            "نکته:\n"
            "اگر فقط تاریخ وارد شود،\n"
            "برای «از» ساعت <b>00:00</b> و برای «تا» ساعت <b>23:59:59</b> در نظر گرفته می‌شود.",
        ),
        reply_markup=admin_finance_sales_range_kb(),
        parse_mode="HTML",
    )
    await cq.answer("بازه را وارد کن", show_alert=False)


@router.message(AdminFinanceSalesRangeSG.input)
async def admin_finance_sales_range_submit(
    m: Message,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await m.answer("اجازه دسترسی نداری.")
        await state.clear()
        return

    raw_text = (m.text or "").strip()
    if raw_text.lower() in {"cancel", "/cancel", "لغو"}:
        await state.clear()
        await m.answer(
            panel("گزارش فروش بازه‌ای", "لغو شد."),
            reply_markup=admin_finance_menu_kb(
                deposit_filter_active=_is_deposit_filter_active(_get_deposit_filter(int(m.chat.id))),
                withdraw_filter_active=_is_deposit_filter_active(_get_withdraw_filter(int(m.chat.id))),
            ),
            parse_mode="HTML",
        )
        return

    parsed = _parse_sales_range_input(raw_text)
    if parsed is None:
        await m.answer(
            panel(
                "گزارش فروش بازه‌ای",
                "فرمت ورودی نامعتبر است.\n\n"
                "نمونه درست:\n"
                "<code>از: 1405/04/01 00:00\n"
                "تا: 1405/04/01 23:59</code>\n\n"
                "یا:\n"
                "<code>1405/04/01 00:00 تا 1405/04/01 23:59</code>",
            ),
            reply_markup=admin_finance_sales_range_kb(),
            parse_mode="HTML",
        )
        return

    from_dt, to_dt = parsed
    if from_dt > to_dt:
        await m.answer(
            panel("گزارش فروش بازه‌ای", "زمان شروع نباید بعد از زمان پایان باشد."),
            reply_markup=admin_finance_sales_range_kb(),
            parse_mode="HTML",
        )
        return

    from_at = from_dt.strftime("%Y-%m-%d %H:%M:%S")
    to_at = to_dt.strftime("%Y-%m-%d %H:%M:%S")

    try:
        summary = await api.admin_get_games_sales_summary(from_at=from_at, to_at=to_at)
    except ApiError as e:
        await m.answer(
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=admin_finance_sales_range_kb(),
            parse_mode="HTML",
        )
        return

    await state.clear()

    games_count = _to_int(str(summary.get("games_count") or ""), 0)
    purchases_count = _to_int(str(summary.get("purchases_count") or ""), 0)
    cards_sold = _to_int(str(summary.get("cards_sold") or ""), 0)
    sales_total = _to_int(str(summary.get("sales_total") or ""), 0)
    commission_total = _to_int(str(summary.get("commission_total") or ""), 0)
    prize_pool_total = _to_int(str(summary.get("prize_pool_total") or ""), 0)
    row_users = _to_int(str(summary.get("row_winner_users_count") or ""), 0)
    row_cards = _to_int(str(summary.get("row_winner_cards_count") or ""), 0)
    row_events = _to_int(str(summary.get("row_win_events_count") or ""), 0)
    col_users = _to_int(str(summary.get("col_winner_users_count") or ""), 0)
    col_cards = _to_int(str(summary.get("col_winner_cards_count") or ""), 0)
    col_events = _to_int(str(summary.get("col_win_events_count") or ""), 0)

    report_body = (
        f"🗓 از: <code>{h(format_jalali_datetime(from_at, seconds=True))}</code>\n"
        f"🗓 تا: <code>{h(format_jalali_datetime(to_at, seconds=True))}</code>\n\n"
        f"🎮 تعداد بازی‌های بازه: <b>{_fmt_count(games_count)}</b>\n"
        f"🧾 تعداد خرید کارت: <b>{_fmt_count(purchases_count)}</b>\n"
        f"🎫 تعداد کارت فروخته‌شده: <b>{_fmt_count(cards_sold)}</b>\n"
        f"💰 مبلغ فروش کارت: <b>{_fmt_toman(sales_total)}</b>\n"
        f"🤖 کمیسیون ربات: <b>{_fmt_toman(commission_total)}</b>\n"
        f"🎁 مجموع جایزه (پس از کسر کمیسیون): <b>{_fmt_toman(prize_pool_total)}</b>\n\n"
        f"🏁 برندگان تمام: <b>{_fmt_count(row_users)}</b> کاربر | "
        f"<b>{_fmt_count(row_cards)}</b> کارت | <b>{_fmt_count(row_events)}</b> رویداد\n"
        f"🏆 برندگان تورنا: <b>{_fmt_count(col_users)}</b> کاربر | "
        f"<b>{_fmt_count(col_cards)}</b> کارت | <b>{_fmt_count(col_events)}</b> رویداد"
    )
    await m.answer(
        panel("📊 گزارش فروش بازه‌ای", report_body),
        reply_markup=admin_finance_sales_range_kb(),
        parse_mode="HTML",
    )
    if forum_enabled():
        try:
            await send_to_topic(
                m.bot,
                name="income",
                text=panel("📊 گزارش فروش بازه‌ای (درخواستی)", report_body),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.callback_query(F.data == "admin:deposits:pending")
async def admin_deposits_pending(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    try:
        await _render_deposits_page(cq, api, offset=0)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data == "admin:deposits:filter")
async def admin_deposits_filter_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    chat_id = int(cq.message.chat.id)
    flt = _get_deposit_filter(chat_id)
    await safe_edit_or_send(
        cq.message,
        panel(
            "فیلتر واریز",
            f"{_deposit_filter_summary(flt)}\n\n"
            "می‌تونی از فیلتر سریع استفاده کنی یا فیلتر دستی وارد کنی.",
        ),
        reply_markup=deposit_filter_quick_kb(filter_active=_is_deposit_filter_active(flt)),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "admin:deposits:filter:manual")
async def admin_deposits_filter_manual(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminDepositFilterSG.input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "فیلتر دستی واریز",
            "فرمت ورودی:\n"
            "<code>از=1405/04/01 تا=1405/04/15 حداقل=100000 حداکثر=800000</code>\n\n"
            "هر بخشی اختیاری است. مثال:\n"
            "<code>از=1405/04/10 حداقل=50000</code>",
        ),
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:deposits:filter:quick:"))
async def admin_deposits_filter_quick(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    kind = (cq.data or "").split(":")[-1]
    parsed = _build_quick_deposit_filter(kind)
    if parsed is None:
        await cq.answer("فیلتر سریع نامعتبر است.", show_alert=True)
        return

    chat_id = int(cq.message.chat.id)
    ADMIN_DEPOSIT_FILTERS[chat_id] = parsed
    await state.clear()
    try:
        await _render_deposits_page(cq, api, offset=0)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    await cq.answer("فیلتر سریع اعمال شد ✅", show_alert=False)


@router.message(AdminDepositFilterSG.input)
async def admin_deposits_filter_apply(
    m: Message,
    state: FSMContext,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await m.answer("اجازه دسترسی نداری.")
        return

    parsed = _parse_deposit_filter_text(m.text or "")
    if parsed is None:
        await m.answer(
            panel(
                "فیلتر واریز",
                "ورودی نامعتبر است.\n"
                "مثال درست:\n"
                "<code>از=1405/04/01 تا=1405/04/15 حداقل=100000 حداکثر=800000</code>",
            ),
            reply_markup=admin_cancel_kb(),
            parse_mode="HTML",
        )
        return

    chat_id = int(m.chat.id)
    ADMIN_DEPOSIT_FILTERS[chat_id] = parsed
    await state.clear()
    w_flt = _get_withdraw_filter(chat_id)
    await m.answer(
        panel("فیلتر واریز ثبت شد ✅", _deposit_filter_summary(parsed)),
        reply_markup=admin_finance_menu_kb(
            deposit_filter_active=True,
            withdraw_filter_active=_is_deposit_filter_active(w_flt),
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:deposits:filter:clear")
async def admin_deposits_filter_clear(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    chat_id = int(cq.message.chat.id)
    ADMIN_DEPOSIT_FILTERS.pop(chat_id, None)
    await state.clear()
    w_flt = _get_withdraw_filter(chat_id)
    await safe_edit_or_send(
        cq.message,
        panel("فیلتر واریز", "فیلتر واریز پاک شد."),
        reply_markup=admin_finance_menu_kb(
            deposit_filter_active=False,
            withdraw_filter_active=_is_deposit_filter_active(w_flt),
        ),
        parse_mode="HTML",
    )
    await cq.answer("فیلتر پاک شد ✅", show_alert=False)


@router.callback_query(F.data == "admin:withdraws:filter")
async def admin_withdraws_filter_start(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    chat_id = int(cq.message.chat.id)
    flt = _get_withdraw_filter(chat_id)
    await safe_edit_or_send(
        cq.message,
        panel(
            "فیلتر برداشت",
            f"{_withdraw_filter_summary(flt)}\n\n"
            "می‌تونی از فیلتر سریع استفاده کنی یا فیلتر دستی وارد کنی.",
        ),
        reply_markup=withdraw_filter_quick_kb(filter_active=_is_deposit_filter_active(flt)),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "admin:withdraws:filter:manual")
async def admin_withdraws_filter_manual(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    await state.set_state(AdminWithdrawFilterSG.input)
    await safe_edit_or_send(
        cq.message,
        panel(
            "فیلتر دستی برداشت",
            "فرمت ورودی:\n"
            "<code>از=1405/04/01 تا=1405/04/15 حداقل=100000 حداکثر=800000</code>\n\n"
            "هر بخشی اختیاری است. مثال:\n"
            "<code>از=1405/04/10 حداقل=50000</code>",
        ),
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:withdraws:filter:quick:"))
async def admin_withdraws_filter_quick(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    kind = (cq.data or "").split(":")[-1]
    parsed = _build_quick_deposit_filter(kind)
    if parsed is None:
        await cq.answer("فیلتر سریع نامعتبر است.", show_alert=True)
        return

    chat_id = int(cq.message.chat.id)
    ADMIN_WITHDRAW_FILTERS[chat_id] = parsed
    await state.clear()
    try:
        await _render_withdraws_page(cq, api, status="PENDING", offset=0)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    await cq.answer("فیلتر سریع اعمال شد ✅", show_alert=False)


@router.message(AdminWithdrawFilterSG.input)
async def admin_withdraws_filter_apply(
    m: Message,
    state: FSMContext,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await m.answer("اجازه دسترسی نداری.")
        return

    parsed = _parse_deposit_filter_text(m.text or "")
    if parsed is None:
        await m.answer(
            panel(
                "فیلتر برداشت",
                "ورودی نامعتبر است.\n"
                "مثال درست:\n"
                "<code>از=1405/04/01 تا=1405/04/15 حداقل=100000 حداکثر=800000</code>",
            ),
            reply_markup=admin_cancel_kb(),
            parse_mode="HTML",
        )
        return

    chat_id = int(m.chat.id)
    ADMIN_WITHDRAW_FILTERS[chat_id] = parsed
    await state.clear()
    d_flt = _get_deposit_filter(chat_id)
    await m.answer(
        panel("فیلتر برداشت ثبت شد ✅", _withdraw_filter_summary(parsed)),
        reply_markup=admin_finance_menu_kb(
            deposit_filter_active=_is_deposit_filter_active(d_flt),
            withdraw_filter_active=True,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin:withdraws:filter:clear")
async def admin_withdraws_filter_clear(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    chat_id = int(cq.message.chat.id)
    ADMIN_WITHDRAW_FILTERS.pop(chat_id, None)
    await state.clear()
    d_flt = _get_deposit_filter(chat_id)
    await safe_edit_or_send(
        cq.message,
        panel("فیلتر برداشت", "فیلتر برداشت پاک شد."),
        reply_markup=admin_finance_menu_kb(
            deposit_filter_active=_is_deposit_filter_active(d_flt),
            withdraw_filter_active=False,
        ),
        parse_mode="HTML",
    )
    await cq.answer("فیلتر پاک شد ✅", show_alert=False)


@router.callback_query(F.data.startswith("admin:deposits:page:"))
async def admin_deposits_page(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    offset = _to_int(cq.data.split(":")[-1], 0)
    try:
        await _render_deposits_page(cq, api, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:deposits:view:"))
async def admin_deposit_view(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    parts = cq.data.split(":")
    deposit_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    back_offset = _to_int(parts[4] if len(parts) > 4 else None, 0)
    if deposit_id <= 0:
        await cq.answer("شناسه واریز نامعتبر است.", show_alert=True)
        return

    try:
        it = await api.admin_get_deposit(deposit_id)
        display_name = await _display_name(
            cq,
            tg_user_id=it.get("tg_user_id"),
            tg_username=it.get("tg_username"),
            full_name=it.get("full_name"),
        )
        duplicate_ids = [int(x) for x in (it.get("duplicate_of_ids") or []) if str(x).isdigit()]
        duplicate_note = ""
        destination_block = _deposit_destination_text(it)
        if duplicate_ids:
            show_ids = ", ".join(str(x) for x in duplicate_ids[:8])
            duplicate_note = f"\n⚠️ <b>رسید تکراری مشکوک</b>\nهمسان با درخواست(ها): <code>{show_ids}</code>\n"
        caption = panel(
            "واریز در انتظار",
            f"🧾 شماره: <b>{deposit_id}</b>\n"
            f"وضعیت: <b>{_deposit_status_fa(it.get('status'))}</b>\n"
            f"👤 کاربر: <b>{h(display_name)}</b>\n"
            f"🧾 شناسه داخلی: <code>{it.get('user_id')}</code>\n"
            f"💵 مبلغ: <b>{_fmt_toman(it.get('amount'))}</b>\n"
            f"{destination_block}"
            f"🔐 هش رسید: <code>{h(str(it.get('receipt_hash') or '—'))}</code>\n"
            f"{duplicate_note}"
            f"⏱ {h(format_jalali_datetime(it.get('created_at'), default='—'))}\n",
        )
        item_kb = deposit_item_kb(deposit_id, back_offset=back_offset)
        try:
            b = await api.admin_get_deposit_receipt_bytes(deposit_id)
            file = BufferedInputFile(b, filename=f"receipt_{deposit_id}.jpg")
            await cq.message.answer_document(
                file,
                caption=caption,
                reply_markup=item_kb,
                parse_mode="HTML",
            )
        except ApiError:
            await safe_edit_or_send(
                cq.message,
                caption + "\n\n⚠️ دریافت تصویر رسید ممکن نشد.",
                reply_markup=item_kb,
                parse_mode="HTML",
            )
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )

    await cq.answer()


@router.callback_query(F.data.startswith("admin:deposit:receipt:"))
async def admin_deposit_receipt(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    deposit_id = _to_int(cq.data.split(":")[-1], -1)
    if deposit_id <= 0:
        await cq.answer("شناسه واریز نامعتبر است.", show_alert=True)
        return

    try:
        b = await api.admin_get_deposit_receipt_bytes(deposit_id)
        file = BufferedInputFile(b, filename=f"receipt_{deposit_id}.jpg")
        await cq.message.answer_document(file, caption=f"رسید واریز #{deposit_id}")
        await cq.answer("ارسال شد ✅")
    except Exception:
        await cq.answer("خطا در دریافت رسید", show_alert=True)


@router.callback_query(F.data.startswith("admin:deposit:live:"))
async def admin_deposit_live_refresh(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    deposit_id, tg_user_id = _parse_deposit_live_ctx(cq.data or "")
    if deposit_id <= 0 or tg_user_id <= 0:
        await cq.answer("اطلاعات درخواست نامعتبر است.", show_alert=True)
        return

    try:
        it = await api.admin_get_deposit(deposit_id)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    display_name = await _display_name(
        cq,
        tg_user_id=it.get("tg_user_id") or tg_user_id,
        tg_username=it.get("tg_username"),
        full_name=it.get("full_name"),
    )
    wallet_balance_text = "نامشخص"
    try:
        wallet = await api.bot_get_wallet(tg_user_id=tg_user_id, tg_username=None, limit=1, offset=0)
        wallet_balance_text = _fmt_toman(wallet.get("balance"))
    except ApiError:
        pass

    duplicate_ids = [int(x) for x in (it.get("duplicate_of_ids") or []) if str(x).isdigit()]
    duplicate_line = ""
    destination_block = _deposit_destination_text(it)
    if duplicate_ids:
        show_ids = ", ".join(str(x) for x in duplicate_ids[:8])
        duplicate_line = f"⚠️ رسید تکراری مشکوک: <code>{show_ids}</code>\n"

    text = panel(
        "درخواست واریز جدید",
        f"🧾 شماره درخواست: <b>{deposit_id}</b>\n"
        f"👤 کاربر: <b>{h(display_name)}</b>\n"
        f"🧾 شناسه داخلی: <code>{it.get('user_id')}</code>\n"
        f"💵 مبلغ واریزی: <b>{_fmt_toman(it.get('amount'))}</b>\n"
        f"{destination_block}"
        f"👛 موجودی لحظه‌ای کیف پول: <b>{wallet_balance_text}</b>\n"
        f"🔐 هش رسید: <code>{h(str(it.get('receipt_hash') or '—'))}</code>\n"
        f"{duplicate_line}"
        f"وضعیت درخواست: <b>{_deposit_status_fa(it.get('status'))}</b>\n\n"
        "برای کنترل دقیق، می‌توانی دوباره تازه‌سازی کنی.",
    )
    await safe_edit_or_send(
        cq.message,
        text,
        reply_markup=deposit_admin_alert_kb(deposit_id=deposit_id, tg_user_id=tg_user_id),
        parse_mode="HTML",
    )
    await cq.answer("تازه‌سازی شد ✅", show_alert=False)


@router.callback_query(F.data.startswith("admin:deposit:approve:"))
async def admin_deposit_approve(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    deposit_id, back_offset = _parse_deposit_action(cq.data)
    if deposit_id <= 0:
        await cq.answer("شناسه واریز نامعتبر است.", show_alert=True)
        return

    tg_user_id = None
    amount = None
    try:
        before = await api.admin_get_deposit(deposit_id)
        tg_user_id = before.get("tg_user_id")
        amount = before.get("amount")
    except ApiError:
        pass

    try:
        await api.admin_approve_deposit(deposit_id, idempotency_key=f"DEP_APPROVE:{deposit_id}")
        if tg_user_id is not None:
            amount_text = _fmt_toman(amount) if amount is not None else "نامشخص"
            try:
                await cq.bot.send_message(
                    chat_id=int(tg_user_id),
                    text=panel(
                        "واریز تایید شد ✅",
                        f"واریز شما تایید شد.\n💵 مبلغ: <b>{amount_text}</b>\nکیف پول شما شارژ شد.",
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await _render_deposits_page(cq, api, offset=back_offset)
        await cq.answer("تایید شد ✅")
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer()


@router.callback_query(F.data.startswith("admin:deposit:reject:"))
async def admin_deposit_reject_start(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    deposit_id, back_offset = _parse_deposit_action(cq.data)
    if deposit_id <= 0:
        await cq.answer("شناسه واریز نامعتبر است.", show_alert=True)
        return

    tg_user_id = None
    amount = None
    try:
        before = await api.admin_get_deposit(deposit_id)
        tg_user_id = before.get("tg_user_id")
        amount = before.get("amount")
    except ApiError:
        pass

    await state.clear()
    await state.update_data(
        reject_kind="deposit",
        deposit_id=deposit_id,
        tg_user_id=tg_user_id,
        amount=amount,
        list_status="PENDING_REVIEW",
        back_offset=back_offset,
    )
    await state.set_state(AdminRejectSG.reason)

    await safe_edit_or_send(
        cq.message,
        panel(
            "رد واریز",
            f"علت رد واریز <b>#{deposit_id}</b> را بنویس.\n"
            "یا از دکمه‌های آماده استفاده کن.",
        ),
        reply_markup=admin_reject_reason_kb(kind="deposit"),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(AdminRejectSG.reason, F.data.startswith("admin:reject:quick:"))
async def admin_reject_reason_quick(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    st = await state.get_data()
    kind = str(st.get("reject_kind") or "").strip().lower()
    if kind not in {"deposit", "withdraw"}:
        await state.clear()
        await cq.answer("جلسه رد درخواست منقضی شده است.", show_alert=True)
        return

    code = (cq.data or "").split(":")[-1]
    reason = _quick_reject_reason(kind, code)
    if not reason:
        await cq.answer("دلیل آماده نامعتبر است.", show_alert=True)
        return

    if kind == "deposit":
        deposit_id = _to_int(st.get("deposit_id"), -1)
        tg_user_id = _to_int(st.get("tg_user_id"), 0) or None
        if deposit_id <= 0:
            await state.clear()
            await cq.answer("شناسه واریز نامعتبر است.", show_alert=True)
            return

        try:
            res = await api.admin_reject_deposit(deposit_id, reason=reason)
            await state.clear()
            await safe_edit_or_send(
                cq.message,
                panel(
                    "رد شد ❌",
                    f"واریز #{deposit_id} رد شد.\n"
                    f"وضعیت: <b>{_deposit_status_fa(res.get('status'))}</b>\n\n"
                    f"دلیل: {h(reason)}",
                ),
                parse_mode="HTML",
                reply_markup=admin_finance_menu_kb(
                    deposit_filter_active=_is_deposit_filter_active(_get_deposit_filter(int(cq.message.chat.id))),
                    withdraw_filter_active=_is_deposit_filter_active(_get_withdraw_filter(int(cq.message.chat.id))),
                ),
            )

            if tg_user_id is not None:
                try:
                    await cq.bot.send_message(
                        chat_id=int(tg_user_id),
                        text=panel(
                            "واریز رد شد ❌",
                            f"درخواست واریز شما رد شد.\n"
                            f"🧾 شماره درخواست: <b>{deposit_id}</b>\n"
                            f"📌 دلیل رد: {h(reason)}\n\n"
                            "در صورت نیاز، با اصلاح اطلاعات و ثبت رسید معتبر دوباره درخواست ثبت کنید.",
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            await cq.answer("رد شد ❌", show_alert=False)
        except ApiError as e:
            await safe_edit_or_send(
                cq.message,
                panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
                parse_mode="HTML",
            )
            await cq.answer("خطا", show_alert=False)
        return

    withdraw_id = _to_int(st.get("withdraw_id"), -1)
    list_status = str(st.get("list_status") or "PENDING").upper()
    back_offset = max(0, _to_int(st.get("back_offset"), 0))
    tg_user_id = _to_int(st.get("tg_user_id"), 0) or None
    amount = _to_int(st.get("amount"), 0)
    if withdraw_id <= 0:
        await state.clear()
        await cq.answer("شناسه برداشت نامعتبر است.", show_alert=True)
        return

    try:
        await api.admin_reject_withdraw(withdraw_id, reason=reason)
        await state.clear()

        await safe_edit_or_send(
            cq.message,
            panel(
                "برداشت رد شد ❌",
                f"برداشت <b>#{withdraw_id}</b> رد شد.\n"
                f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                f"📌 دلیل: {h(reason)}",
            ),
            parse_mode="HTML",
            reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status="REJECTED", back_offset=back_offset),
        )

        if tg_user_id is not None:
            try:
                await cq.bot.send_message(
                    chat_id=int(tg_user_id),
                    text=panel(
                        "برداشت رد شد ❌",
                        f"درخواست برداشت شما رد شد.\n"
                        f"🧾 شماره درخواست: <b>{withdraw_id}</b>\n"
                        f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                        f"📌 دلیل رد: {h(reason)}\n\n"
                        "در صورت نیاز می‌تونی اطلاعات را اصلاح کنی و دوباره درخواست ثبت کنی.",
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await cq.answer("رد شد ❌", show_alert=False)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer("خطا", show_alert=False)


@router.message(AdminRejectSG.reason)
async def admin_reject_reason_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer("اجازه دسترسی نداری.")
        return

    st = await state.get_data()
    kind = str(st.get("reject_kind") or "").strip().lower()
    if kind not in {"deposit", "withdraw"}:
        await state.clear()
        await m.answer(panel("خطا", "جلسه رد درخواست منقضی شده است. دوباره از منوی ادمین مالی اقدام کن."), parse_mode="HTML")
        return

    reason = (m.text or "").strip()
    if len(reason) < 3:
        title = "رد برداشت" if kind == "withdraw" else "رد واریز"
        await m.answer(
            panel(title, "دلیل خیلی کوتاهه. حداقل ۳ کاراکتر بنویس یا از دکمه آماده استفاده کن."),
            reply_markup=admin_reject_reason_kb(kind=kind),
            parse_mode="HTML",
        )
        return

    if kind == "deposit":
        deposit_id = _to_int(st.get("deposit_id"), -1)
        tg_user_id = _to_int(st.get("tg_user_id"), 0) or None
        if deposit_id <= 0:
            await state.clear()
            await m.answer(panel("خطا", "شناسه واریز نامعتبر است."), parse_mode="HTML")
            return

        try:
            res = await api.admin_reject_deposit(deposit_id, reason=reason)
            await state.clear()
            await m.answer(
                panel(
                    "رد شد ❌",
                    f"واریز #{deposit_id} رد شد.\n"
                    f"وضعیت: <b>{_deposit_status_fa(res.get('status'))}</b>\n\n"
                    f"دلیل: {h(reason)}",
                ),
                parse_mode="HTML",
                reply_markup=admin_finance_menu_kb(
                    deposit_filter_active=_is_deposit_filter_active(_get_deposit_filter(int(m.chat.id))),
                    withdraw_filter_active=_is_deposit_filter_active(_get_withdraw_filter(int(m.chat.id))),
                ),
            )

            if tg_user_id is not None:
                try:
                    await m.bot.send_message(
                        chat_id=int(tg_user_id),
                        text=panel(
                            "واریز رد شد ❌",
                            f"درخواست واریز شما رد شد.\n"
                            f"🧾 شماره درخواست: <b>{deposit_id}</b>\n"
                            f"📌 دلیل رد: {h(reason)}\n\n"
                            "در صورت نیاز، با اصلاح اطلاعات و ثبت رسید معتبر دوباره درخواست ثبت کنید.",
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        except ApiError as e:
            await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
        return

    withdraw_id = _to_int(st.get("withdraw_id"), -1)
    list_status = str(st.get("list_status") or "PENDING").upper()
    back_offset = max(0, _to_int(st.get("back_offset"), 0))
    tg_user_id = _to_int(st.get("tg_user_id"), 0) or None
    amount = _to_int(st.get("amount"), 0)
    if withdraw_id <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه برداشت نامعتبر است."), parse_mode="HTML")
        return

    try:
        await api.admin_reject_withdraw(withdraw_id, reason=reason)
        await state.clear()

        await m.answer(
            panel(
                "برداشت رد شد ❌",
                f"برداشت <b>#{withdraw_id}</b> رد شد.\n"
                f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                f"📌 دلیل: {h(reason)}",
            ),
            parse_mode="HTML",
            reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status="REJECTED", back_offset=back_offset),
        )

        if tg_user_id is not None:
            try:
                await m.bot.send_message(
                    chat_id=int(tg_user_id),
                    text=panel(
                        "برداشت رد شد ❌",
                        f"درخواست برداشت شما رد شد.\n"
                        f"🧾 شماره درخواست: <b>{withdraw_id}</b>\n"
                        f"💵 مبلغ: <b>{_fmt_toman(amount)}</b>\n"
                        f"📌 دلیل رد: {h(reason)}\n\n"
                        "در صورت نیاز می‌تونی اطلاعات را اصلاح کنی و دوباره درخواست ثبت کنی.",
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")

@router.callback_query(F.data == "admin:withdraws:pending")
async def admin_withdraws_pending(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    try:
        await _render_withdraws_page(cq, api, status="PENDING", offset=0)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data == "admin:withdraws:approved")
async def admin_withdraws_approved(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    try:
        await _render_withdraws_page(cq, api, status="APPROVED", offset=0)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:withdraws:page:"))
async def admin_withdraws_page(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    status, offset = _parse_withdraw_page_ctx(cq.data)
    try:
        await _render_withdraws_page(cq, api, status=status, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:withdraws:view:"))
async def admin_withdraw_view(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    withdraw_id, list_status, back_offset = _parse_withdraw_view_ctx(cq.data)
    if withdraw_id <= 0:
        await cq.answer("شناسه برداشت نامعتبر است.", show_alert=True)
        return

    try:
        wr = await api.admin_get_withdraw(withdraw_id)
        status = str(wr.get("status") or list_status or "PENDING").upper()
        display_name = await _display_name(
            cq,
            tg_user_id=wr.get("tg_user_id"),
            tg_username=wr.get("tg_username"),
            full_name=wr.get("full_name"),
        )
        wallet_note = await _withdraw_wallet_status_note(api, wr)
        text = panel(
            f"برداشت {_withdraw_status_fa(status)}",
            f"🧾 شماره: <b>{withdraw_id}</b>\n"
            f"وضعیت: <b>{_withdraw_status_fa(status)}</b>\n"
            f"👤 کاربر: <b>{h(display_name)}</b>\n"
            f"🧾 شناسه داخلی: <code>{wr.get('user_id')}</code>\n"
            f"{wallet_note}"
            f"💵 مبلغ: <b>{_fmt_toman(wr.get('amount'))}</b>\n"
            f"🙍 نام: <b>{h(str(wr.get('full_name') or '—'))}</b>\n"
            f"💳 کارت: <code>{h(str(wr.get('card_number') or '—'))}</code>\n"
            f"🏦 شبا: <code>{h(str(wr.get('iban') or '—'))}</code>\n"
            f"🏛 حساب: <code>{h(str(wr.get('account_number') or '—'))}</code>\n"
            f"🔖 پیگیری پرداخت: <code>{h(str(wr.get('paid_tracking') or '—'))}</code>\n"
            f"⏱ {h(format_jalali_datetime(wr.get('created_at'), default='—'))}\n",
        )
        await safe_edit_or_send(
            cq.message,
            text,
            reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status=status, back_offset=back_offset, tg_user_id=_to_int(wr.get("tg_user_id"), 0)),
            parse_mode="HTML",
        )
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:withdraw:live:"))
async def admin_withdraw_live_refresh(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    withdraw_id, tg_user_id = _parse_withdraw_live_ctx(cq.data or "")
    if withdraw_id <= 0 or tg_user_id <= 0:
        await cq.answer("اطلاعات درخواست نامعتبر است.", show_alert=True)
        return

    try:
        wr = await api.admin_get_withdraw(withdraw_id)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    display_name = await _display_name(
        cq,
        tg_user_id=wr.get("tg_user_id") or tg_user_id,
        tg_username=wr.get("tg_username"),
        full_name=wr.get("full_name"),
    )
    wallet_balance_text = "نامشخص"
    try:
        wallet = await api.bot_get_wallet(tg_user_id=tg_user_id, tg_username=None, limit=1, offset=0)
        wallet_balance_text = _fmt_toman(wallet.get("balance"))
    except ApiError:
        pass

    text = panel(
        "درخواست برداشت جدید",
        f"🧾 شماره درخواست: <b>{withdraw_id}</b>\n"
        f"👤 کاربر: <b>{h(display_name)}</b>\n"
        f"🧾 شناسه داخلی: <code>{wr.get('user_id')}</code>\n"
        f"💵 مبلغ برداشت: <b>{_fmt_toman(wr.get('amount'))}</b>\n"
        f"👛 موجودی لحظه‌ای کیف پول: <b>{wallet_balance_text}</b>\n"
        f"وضعیت درخواست: <b>{_withdraw_status_fa(wr.get('status'))}</b>\n\n"
        "برای کنترل دقیق، می‌توانی دوباره تازه‌سازی کنی.",
    )
    await safe_edit_or_send(
        cq.message,
        text,
        reply_markup=withdraw_admin_alert_kb(withdraw_id=withdraw_id, tg_user_id=tg_user_id),
        parse_mode="HTML",
    )
    await cq.answer("تازه‌سازی شد ✅", show_alert=False)


@router.callback_query(F.data.startswith("admin:withdraw:approve:"))
async def admin_withdraw_approve(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    action, withdraw_id, _list_status, back_offset = _parse_withdraw_action_ctx(cq.data or "")
    if action != "approve" or withdraw_id <= 0:
        await cq.answer("درخواست نامعتبر است.", show_alert=True)
        return

    tg_user_id = None
    amount = None
    try:
        before = await api.admin_get_withdraw(withdraw_id)
        tg_user_id = _to_int(before.get("tg_user_id"), 0) or None
        amount = _to_int(before.get("amount"), 0)
    except ApiError:
        pass

    try:
        await api.admin_approve_withdraw(withdraw_id, idempotency_key=f"WDR_APPROVE:{withdraw_id}")
        wr: dict = {}
        status_u = "APPROVED"
        try:
            wr = await api.admin_get_withdraw(withdraw_id)
            status_u = str(wr.get("status") or "APPROVED").upper()
        except ApiError:
            wr = {
                "user_id": "—",
                "tg_user_id": tg_user_id,
                "tg_username": "—",
                "amount": amount,
                "full_name": "—",
                "card_number": "—",
                "iban": "—",
                "account_number": "—",
                "paid_tracking": "—",
                "created_at": "—",
            }
        display_name = await _display_name(
            cq,
            tg_user_id=wr.get("tg_user_id"),
            tg_username=wr.get("tg_username"),
            full_name=wr.get("full_name"),
        )

        await safe_edit_or_send(
            cq.message,
            _withdraw_detail_panel_text(
                withdraw_id=withdraw_id,
                wr=wr,
                status=status_u,
                user_display_name=display_name,
                extra_note="✅ برداشت تایید شد. هنوز پیامی برای کاربر ارسال نشده؛ پیام کاربر فقط در مرحله پرداخت نهایی یا رد ارسال می‌شود.",
            ),
            reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status=status_u, back_offset=back_offset, tg_user_id=_to_int(wr.get("tg_user_id"), 0)),
            parse_mode="HTML",
        )
        await cq.answer("برداشت تایید شد ✅", show_alert=False)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer("خطا", show_alert=False)

@router.callback_query(F.data.startswith("admin:withdraw:reject:"))
async def admin_withdraw_reject_start(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    action, withdraw_id, list_status, back_offset = _parse_withdraw_action_ctx(cq.data or "")
    if action != "reject" or withdraw_id <= 0:
        await cq.answer("درخواست نامعتبر است.", show_alert=True)
        return

    tg_user_id = None
    amount = None
    try:
        before = await api.admin_get_withdraw(withdraw_id)
        tg_user_id = _to_int(before.get("tg_user_id"), 0) or None
        amount = _to_int(before.get("amount"), 0)
    except ApiError:
        pass

    await state.clear()
    await state.update_data(
        reject_kind="withdraw",
        withdraw_id=withdraw_id,
        list_status=(list_status or "PENDING").upper(),
        back_offset=max(0, back_offset),
        tg_user_id=tg_user_id,
        amount=amount,
    )
    await state.set_state(AdminRejectSG.reason)

    await safe_edit_or_send(
        cq.message,
        panel(
            "رد برداشت",
            f"علت رد برداشت <b>#{withdraw_id}</b> را بنویس.\n"
            "یا از دکمه آماده «عدم موجودی» استفاده کن.",
        ),
        reply_markup=admin_reject_reason_kb(kind="withdraw"),
        parse_mode="HTML",
    )
    await cq.answer()

@router.callback_query(F.data.startswith("admin:withdraw:send-receipt:"))
async def admin_withdraw_send_receipt_start(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    action, withdraw_id, list_status, back_offset = _parse_withdraw_action_ctx(cq.data or "")
    if action != "send-receipt" or withdraw_id <= 0:
        await cq.answer("درخواست نامعتبر است.", show_alert=True)
        return

    try:
        wr = await api.admin_get_withdraw(withdraw_id)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
        )
        await cq.answer("خطا", show_alert=False)
        return

    tg_user_id = _to_int(wr.get("tg_user_id"), 0)
    if tg_user_id <= 0:
        await cq.answer("اطلاعات کاربر در دسترس نیست.", show_alert=True)
        return

    status_u = str(wr.get("status") or list_status or "APPROVED").upper()
    amount = _to_int(wr.get("amount"), 0)

    await state.clear()
    await state.set_state(AdminWithdrawReceiptSG.payload)
    await state.update_data(
        receipt_withdraw_id=withdraw_id,
        receipt_status=status_u,
        receipt_back_offset=max(0, back_offset),
        receipt_tg_user_id=tg_user_id,
        receipt_amount=amount,
    )

    await safe_edit_or_send(
        cq.message,
        panel(
            "پرداخت نهایی برداشت",
            f"برای برداشت <b>#{withdraw_id}</b> رسید نهایی را بفرست.\n"
            "با ارسال متن یا عکس، برداشت PAID می‌شود و فقط یک پیام نهایی برای کاربر ارسال می‌شود.\n\n"
            "برای لغو: <code>لغو</code> یا <code>/cancel</code>",
        ),
        reply_markup=withdraw_receipt_prompt_kb(withdraw_id=withdraw_id, status=status_u, back_offset=back_offset),
        parse_mode="HTML",
    )
    await cq.answer("منتظر ارسال رسید هستم…", show_alert=False)


@router.message(AdminWithdrawReceiptSG.payload)
async def admin_withdraw_send_receipt_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await m.answer("اجازه دسترسی نداری.")
        return

    st = await state.get_data()
    withdraw_id = _to_int(st.get("receipt_withdraw_id"), -1)
    status_u = str(st.get("receipt_status") or "APPROVED").upper()
    back_offset = max(0, _to_int(st.get("receipt_back_offset"), 0))
    tg_user_id = _to_int(st.get("receipt_tg_user_id"), 0)
    amount = _to_int(st.get("receipt_amount"), 0)

    if withdraw_id <= 0 or tg_user_id <= 0:
        await state.clear()
        await m.answer(panel("خطا", "شناسه درخواست/کاربر نامعتبر است. دوباره از منوی ادمین مالی اقدام کن."), parse_mode="HTML")
        return

    text_raw = (m.text or "").strip()
    if text_raw.lower() in {"cancel", "/cancel", "لغو"}:
        await state.clear()
        await m.answer(
            panel("ارسال رسید برداشت", "ارسال رسید لغو شد."),
            parse_mode="HTML",
            reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status=status_u, back_offset=back_offset),
        )
        return

    tracking = f"BOT-{withdraw_id}-{int(time.time())}"
    if status_u != "PAID":
        try:
            await api.admin_mark_withdraw_paid(withdraw_id, paid_tracking=tracking)
            status_u = "PAID"
        except ApiError as e:
            await m.answer(
                panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
                parse_mode="HTML",
                reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status=status_u, back_offset=back_offset),
            )
            return

    amount_text = _fmt_toman(amount)
    base_caption = (
        f"🧾 شماره برداشت: <b>{withdraw_id}</b>\n"
        f"💵 مبلغ: <b>{amount_text}</b>\n"
        f"🔖 کد پیگیری: <code>{h(tracking)}</code>\n"
        "✅ برداشت شما پرداخت شد."
    )

    try:
        if m.photo:
            note = (m.caption or "").strip()
            caption = panel("رسید پرداخت برداشت", base_caption + (f"\n\n📌 توضیح: {h(note)}" if note else ""))
            await m.bot.send_photo(
                chat_id=tg_user_id,
                photo=m.photo[-1].file_id,
                caption=caption,
                parse_mode="HTML",
            )
        elif m.document and str(getattr(m.document, "mime_type", "")).lower().startswith("image/"):
            note = (m.caption or "").strip()
            caption = panel("رسید پرداخت برداشت", base_caption + (f"\n\n📌 توضیح: {h(note)}" if note else ""))
            await m.bot.send_document(
                chat_id=tg_user_id,
                document=m.document.file_id,
                caption=caption,
                parse_mode="HTML",
            )
        elif text_raw:
            await m.bot.send_message(
                chat_id=tg_user_id,
                text=panel(
                    "رسید پرداخت برداشت",
                    base_caption + f"\n\n📌 جزئیات رسید:\n{h(text_raw)}",
                ),
                parse_mode="HTML",
            )
        else:
            await m.answer(
                panel("ارسال رسید برداشت", "فقط متن یا عکس رسید بفرست."),
                parse_mode="HTML",
                reply_markup=withdraw_receipt_prompt_kb(withdraw_id=withdraw_id, status=status_u, back_offset=back_offset),
            )
            return
    except Exception:
        await m.answer(
            panel("خطا", "ارسال رسید به کاربر انجام نشد. دوباره تلاش کن."),
            parse_mode="HTML",
            reply_markup=withdraw_receipt_prompt_kb(withdraw_id=withdraw_id, status=status_u, back_offset=back_offset),
        )
        return

    await state.clear()
    await m.answer(
        panel("پرداخت نهایی شد ✅", f"برداشت <b>#{withdraw_id}</b> پرداخت شد و فقط پیام نهایی برای کاربر ارسال شد."),
        parse_mode="HTML",
        reply_markup=withdraw_item_kb(withdraw_id=withdraw_id, status="PAID", back_offset=back_offset),
    )

@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    await safe_edit_or_send(
        cq.message,
        panel("ادمین مالی", "لغو شد."),
        reply_markup=admin_finance_menu_kb(
            deposit_filter_active=_is_deposit_filter_active(_get_deposit_filter(int(cq.message.chat.id))),
            withdraw_filter_active=_is_deposit_filter_active(_get_withdraw_filter(int(cq.message.chat.id))),
        ),
        parse_mode="HTML",
    )
    await cq.answer()
