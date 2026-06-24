from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.crypto import (
    admin_crypto_item_kb,
    admin_crypto_list_kb,
    crypto_cancel_kb,
    crypto_invoice_kb,
    crypto_network_kb,
)
from bot.services.api_client import ApiClient, ApiError
from bot.services.jalali import format_jalali_datetime
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel
from bot.states.crypto import CryptoAdminSG, CryptoDepositSG

router = Router()

_FA_DIGITS_TRANS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_FA_TO_EN_TRANS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)


def _fa(value: object) -> str:
    return str(value).translate(_FA_DIGITS_TRANS)


def _fmt_toman(value: object) -> str:
    try:
        number = int(value or 0)
    except Exception:
        number = 0
    return f"{_fa(f'{number:,}'.replace(',', '٬'))} تومان"


def _crypto_amount(value: object, asset: object) -> str:
    text = str(value or "0")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{escape(text or '0')} {escape(str(asset or ''))}"


def _status_fa(value: object) -> str:
    mapping = {
        "WAITING_PAYMENT": "در انتظار پرداخت",
        "CONFIRMING": "در حال تایید شبکه",
        "CREDITED": "واریز و شارژ کیف پول انجام شد",
        "EXPIRED": "منقضی‌شده",
        "NEEDS_REVIEW": "نیازمند بررسی ادمین",
        "REJECTED": "ردشده",
    }
    return mapping.get(str(value or "").upper(), "نامشخص")


def _invoice_text(item: dict, *, title: str = "فاکتور واریز رمزارز") -> str:
    memo = str(item.get("memo") or "").strip()
    tx_hash = str(item.get("tx_hash") or "").strip()
    reason = str(item.get("failure_reason") or "").strip()
    variance = str(item.get("payment_variance") or "").upper()
    lines = [
        f"🧾 شماره فاکتور: <b>{_fa(item.get('id'))}</b>",
        f"وضعیت: <b>{escape(_status_fa(item.get('status')))}</b>",
        f"💵 شارژ کیف پول: <b>{_fmt_toman(item.get('amount_toman'))}</b>",
        f"💎 مبلغ پرداخت: <code>{_crypto_amount(item.get('amount_crypto'), item.get('asset'))}</code>",
        f"🌐 شبکه: <b>{escape(str(item.get('network') or '—'))}</b>",
        f"📥 آدرس مقصد:\n<code>{escape(str(item.get('destination_address') or '—'))}</code>",
    ]
    if memo:
        lines.append(f"📝 کامنت/Memo الزامی:\n<code>{escape(memo)}</code>")
    if tx_hash:
        lines.append(f"🔗 هش تراکنش:\n<code>{escape(tx_hash)}</code>")
    lines.append(f"⏳ مهلت پرداخت: <code>{escape(format_jalali_datetime(item.get('expires_at'), default='—'))}</code>")
    if reason:
        lines.append(f"⚠️ توضیح: {escape(reason)}")
    if variance == "OVERPAID":
        lines.append("⚠️ مبلغ اضافه دریافت شده و برای بررسی ادمین ثبت شده است.")
    elif variance == "UNDERPAID":
        lines.append("⚠️ مبلغ دریافتی کمتر از فاکتور است و نیازمند بررسی ادمین است.")
    if str(item.get("status") or "").upper() == "WAITING_PAYMENT":
        lines.append("\nمبلغ، شبکه و آدرس را دقیق ارسال کن. پرداخت کمتر از مبلغ فاکتور خودکار تایید نمی‌شود.")
    return panel(title, "\n".join(lines))


def _parse_amount(text: str | None) -> int:
    normalized = str(text or "").translate(_FA_TO_EN_TRANS)
    digits = "".join(ch for ch in normalized if ch.isdigit())
    return int(digits) if digits else 0


@router.callback_query(F.data == "menu:crypto")
async def crypto_start(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    await state.clear()
    try:
        payload = await api.bot_crypto_options(tg_user_id, tg_username)
    except ApiError as exc:
        await safe_edit_or_send(cq.message, panel("واریز رمزارز", escape(exc.detail)), parse_mode="HTML")
        await cq.answer()
        return
    options = payload.get("options") if isinstance(payload, dict) else []
    if not payload.get("enabled") or not isinstance(options, list) or not options:
        await safe_edit_or_send(
            cq.message,
            panel("واریز رمزارز", "این روش پرداخت در حال حاضر فعال نیست."),
            reply_markup=crypto_cancel_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return
    await state.update_data(crypto_options=options)
    await safe_edit_or_send(
        cq.message,
        panel(
            "واریز رمزارز",
            f"شبکه پرداخت را انتخاب کن.\n"
            f"حداقل: <b>{_fmt_toman(payload.get('min_toman_amount'))}</b>\n"
            f"حداکثر: <b>{_fmt_toman(payload.get('max_toman_amount'))}</b>\n"
            f"سقف روزانه: <b>{_fa(payload.get('daily_user_max_count') or 0)}</b> فاکتور | "
            f"<b>{_fmt_toman(payload.get('daily_user_max_toman'))}</b>",
        ),
        reply_markup=crypto_network_kb(options),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("crypto:network:"))
async def crypto_choose_network(cq: CallbackQuery, state: FSMContext):
    network = str(cq.data or "").split(":")[-1].upper()
    data = await state.get_data()
    options = data.get("crypto_options") if isinstance(data, dict) else []
    if not any(str(item.get("network") or "").upper() == network for item in (options or [])):
        await cq.answer("شبکه انتخابی فعال نیست.", show_alert=True)
        return
    await state.update_data(crypto_network=network)
    await state.set_state(CryptoDepositSG.amount)
    await safe_edit_or_send(
        cq.message,
        panel(
            "مبلغ شارژ",
            f"شبکه: <b>{escape(network)}</b>\n"
            "مبلغی که باید به کیف پول تومانی اضافه شود را فقط به تومان بفرست.\n"
            "مثال: <code>500000</code>",
        ),
        reply_markup=crypto_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(CryptoDepositSG.amount)
async def crypto_create_invoice(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    amount = _parse_amount(message.text)
    data = await state.get_data()
    network = str(data.get("crypto_network") or "").upper()
    if amount <= 0 or not network:
        await message.answer(panel("واریز رمزارز", "مبلغ معتبر وارد کن."), reply_markup=crypto_cancel_kb())
        return
    try:
        invoice = await api.bot_create_crypto_deposit(
            tg_user_id,
            tg_username,
            amount_toman=amount,
            network=network,
        )
    except ApiError as exc:
        await message.answer(panel("واریز رمزارز", escape(exc.detail)), reply_markup=crypto_cancel_kb())
        return
    await state.clear()
    await message.answer(
        _invoice_text(invoice),
        reply_markup=crypto_invoice_kb(
            int(invoice.get("id") or 0),
            str(invoice.get("status") or ""),
            str(invoice.get("explorer_url") or "") or None,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("crypto:status:"))
async def crypto_refresh_status(
    cq: CallbackQuery,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    invoice_id = int(str(cq.data or "").split(":")[-1])
    try:
        invoice = await api.bot_get_crypto_deposit(
            tg_user_id,
            tg_username,
            invoice_id=invoice_id,
        )
    except ApiError as exc:
        await cq.answer(exc.detail, show_alert=True)
        return
    await safe_edit_or_send(
        cq.message,
        _invoice_text(invoice, title="وضعیت واریز رمزارز"),
        reply_markup=crypto_invoice_kb(
            invoice_id,
            str(invoice.get("status") or ""),
            str(invoice.get("explorer_url") or "") or None,
        ),
        parse_mode="HTML",
    )
    await cq.answer("وضعیت بروزرسانی شد.")


@router.callback_query(F.data.startswith("crypto:tx:"))
async def crypto_tx_hash_start(cq: CallbackQuery, state: FSMContext):
    invoice_id = int(str(cq.data or "").split(":")[-1])
    await state.update_data(crypto_invoice_id=invoice_id)
    await state.set_state(CryptoDepositSG.tx_hash)
    await safe_edit_or_send(
        cq.message,
        panel("ثبت هش تراکنش", "هش تراکنش را کامل و بدون فاصله ارسال کن."),
        reply_markup=crypto_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(CryptoDepositSG.tx_hash)
async def crypto_tx_hash_submit(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    data = await state.get_data()
    invoice_id = int(data.get("crypto_invoice_id") or 0)
    tx_hash = str(message.text or "").strip()
    try:
        invoice = await api.bot_claim_crypto_tx_hash(
            tg_user_id,
            tg_username,
            invoice_id=invoice_id,
            tx_hash=tx_hash,
        )
    except ApiError as exc:
        await message.answer(panel("ثبت هش تراکنش", escape(exc.detail)), reply_markup=crypto_cancel_kb())
        return
    await state.clear()
    await message.answer(
        _invoice_text(invoice, title="هش تراکنش ثبت شد"),
        reply_markup=crypto_invoice_kb(
            invoice_id,
            str(invoice.get("status") or ""),
            str(invoice.get("explorer_url") or "") or None,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "crypto:cancel")
async def crypto_cancel(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_or_send(
        cq.message,
        panel("واریز رمزارز", "عملیات لغو شد."),
        reply_markup=crypto_cancel_kb(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data == "admin:crypto:pending")
async def admin_crypto_pending(
    cq: CallbackQuery,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        await cq.answer("دسترسی ندارید.", show_alert=True)
        return
    payload = await api.admin_list_crypto_deposits(status="NEEDS_REVIEW", limit=30)
    items = payload.get("items") or []
    text = "موردی برای بررسی وجود ندارد." if not items else f"{_fa(len(items))} واریز نیازمند بررسی است."
    await safe_edit_or_send(
        cq.message,
        panel("واریزهای رمزارزی", text),
        reply_markup=admin_crypto_list_kb(items),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:crypto:view:"))
async def admin_crypto_view(
    cq: CallbackQuery,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        await cq.answer("دسترسی ندارید.", show_alert=True)
        return
    invoice_id = int(str(cq.data or "").split(":")[-1])
    try:
        item = await api.admin_get_crypto_deposit(invoice_id)
    except ApiError as exc:
        await cq.answer(exc.detail, show_alert=True)
        return
    await safe_edit_or_send(
        cq.message,
        _invoice_text(item, title="بررسی واریز رمزارز"),
        reply_markup=admin_crypto_item_kb(
            invoice_id=invoice_id,
            status=str(item.get("status") or ""),
            tg_user_id=int(item.get("tg_user_id") or 0),
        ),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:crypto:approve:"))
async def admin_crypto_approve(
    cq: CallbackQuery,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        await cq.answer("دسترسی ندارید.", show_alert=True)
        return
    invoice_id = int(str(cq.data or "").split(":")[-1])
    try:
        invoice = await api.admin_approve_crypto_deposit(invoice_id)
    except ApiError as exc:
        await cq.answer(exc.detail, show_alert=True)
        return
    await safe_edit_or_send(
        cq.message,
        _invoice_text(invoice, title="واریز رمزارز تایید شد"),
        reply_markup=admin_crypto_item_kb(invoice_id=invoice_id, status="CREDITED"),
        parse_mode="HTML",
    )
    await cq.answer("کیف پول شارژ شد.")


@router.callback_query(F.data.startswith("admin:crypto:reject:"))
async def admin_crypto_reject_start(
    cq: CallbackQuery,
    state: FSMContext,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        await cq.answer("دسترسی ندارید.", show_alert=True)
        return
    invoice_id = int(str(cq.data or "").split(":")[-1])
    await state.update_data(crypto_admin_invoice_id=invoice_id)
    await state.set_state(CryptoAdminSG.reject_reason)
    await safe_edit_or_send(
        cq.message,
        panel("رد واریز رمزارز", "علت رد را ارسال کن."),
        reply_markup=admin_crypto_item_kb(invoice_id=invoice_id, status="NEEDS_REVIEW"),
        parse_mode="HTML",
    )
    await cq.answer()


@router.message(CryptoAdminSG.reject_reason)
async def admin_crypto_reject_submit(
    message: Message,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        await state.clear()
        return
    data = await state.get_data()
    invoice_id = int(data.get("crypto_admin_invoice_id") or 0)
    reason = str(message.text or "").strip()
    if not reason:
        await message.answer(panel("رد واریز رمزارز", "علت رد الزامی است."))
        return
    try:
        invoice = await api.admin_reject_crypto_deposit(invoice_id, reason=reason)
    except ApiError as exc:
        await message.answer(panel("رد واریز رمزارز", escape(exc.detail)))
        return
    await state.clear()
    await message.answer(
        _invoice_text(invoice, title="واریز رمزارز رد شد"),
        reply_markup=admin_crypto_item_kb(invoice_id=invoice_id, status="REJECTED"),
        parse_mode="HTML",
    )
