from __future__ import annotations

import uuid
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import settings
from bot.keyboards.join_gate import join_gate_action_kb, join_gate_kb
from bot.keyboards.purchase import after_purchase_kb, confirm_kb, games_list_kb, qty_kb
from bot.services.api_client import ApiClient, ApiError
from bot.services.notify_store import get_user_subscription_map, is_subscribed
from bot.services.tg_membership import is_member
from bot.services.ui import panel
from bot.states.purchase import PurchaseSG

router = Router()

DEFAULT_LIMIT = 10


def _fmt_int(n: int) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _fa_status(status: str | None) -> str:
    raw = (status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ACTIVE": "در حال اجرا",
        "ENDED": "پایان‌یافته",
    }
    return mapping.get(raw, "نامشخص")


def _effective_group_id(game_group_id: int | None) -> int | None:
    if settings.BOT_JOIN_GROUP_ID is not None:
        return int(settings.BOT_JOIN_GROUP_ID)
    return game_group_id


def _join_invite_link() -> str | None:
    raw = str(settings.BOT_JOIN_GROUP_INVITE_LINK or "").strip()
    return raw or None


@router.callback_query(F.data == "menu:buy")
async def buy_entry(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
    is_admin: bool = False,
    is_super_admin: bool = False,
):
    if not (is_admin or is_super_admin):
        required_group_id = _effective_group_id(None)
        if required_group_id is not None:
            member_ok = await is_member(cq.bot, required_group_id, tg_user_id)
            if not member_ok:
                await cq.message.edit_text(
                    panel(
                        "عضویت اجباری",
                        "برای ورود به بخش خرید کارت، ابتدا باید عضو گروه بازی باشید.\n"
                        "بعد از عضویت، روی «✅ عضو شدم» بزن.",
                    ),
                    parse_mode="HTML",
                    reply_markup=join_gate_action_kb(
                        "buy",
                        required_group_id,
                        invite_link=_join_invite_link(),
                    ),
                )
                await cq.answer("ابتدا عضو گروه بازی شوید.", show_alert=True)
                return

    await state.clear()
    await state.set_state(PurchaseSG.select_game)
    await _render_games_list(cq, api, tg_user_id, tg_username, offset=0)
    await cq.answer()


@router.callback_query(F.data.startswith("buy:games:o:"))
async def buy_games_page(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    offset = int(cq.data.split(":")[-1])
    await _render_games_list(cq, api, tg_user_id, tg_username, offset=offset)
    await cq.answer()


async def _render_games_list(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None, *, offset: int):
    res = await api.bot_list_games(
        tg_user_id,
        tg_username,
        status="LOBBY",
        limit=DEFAULT_LIMIT,
        offset=offset,
    )
    items = res.get("items") or []
    has_more = len(items) >= DEFAULT_LIMIT
    game_ids = [int(x.get("id")) for x in items if x.get("id") is not None]
    is_on_map = get_user_subscription_map(game_ids, tg_user_id)

    if not items:
        await cq.message.edit_text(
            panel("خرید کارت", "فعلاً بازیِ آماده خرید پیدا نشد 😕\nیه کم بعد دوباره چک کن."),
            parse_mode="HTML",
            reply_markup=games_list_kb([], offset=offset, limit=DEFAULT_LIMIT, has_more=False, is_on_map={}),
        )
        return

    text = panel("خرید کارت", "یک بازی را انتخاب کن 👇")
    await cq.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=games_list_kb(items, offset=offset, limit=DEFAULT_LIMIT, has_more=has_more, is_on_map=is_on_map),
    )


@router.callback_query(F.data.startswith("buy:game:"))
async def buy_select_game(cq: CallbackQuery, state: FSMContext, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    game_id = int(cq.data.split(":")[-1])

    # برای نمایش قیمت/عنوان، دوباره از لیست بازی‌ها می‌گیریم.
    res = await api.bot_list_games(tg_user_id, tg_username, status="LOBBY", limit=50, offset=0)
    games = res.get("items") or []
    g = next((x for x in games if int(x.get("id")) == game_id), None)

    if not g:
        await cq.answer("این بازی پیدا نشد 😕\nیه‌بار دیگه از لیست انتخاب کن.", show_alert=True)
        return

    game_title = str(g.get("title") or f"بازی {game_id}")
    card_price = int(g.get("card_price") or 0)
    game_status = str(g.get("status") or "")
    game_status_fa = _fa_status(game_status)
    tg_group_id_raw = g.get("tg_group_id")
    try:
        game_group_id = int(tg_group_id_raw) if tg_group_id_raw is not None else None
    except (TypeError, ValueError):
        game_group_id = None

    tg_group_id = _effective_group_id(game_group_id)

    await state.update_data(
        game_id=game_id,
        game_title=game_title,
        card_price=card_price,
        game_status=game_status_fa,
        tg_group_id=tg_group_id,
    )
    await state.set_state(PurchaseSG.select_qty)

    # اگر بازی group-bound باشد، قبل از انتخاب تعداد عضویت را enforce کن.
    if tg_group_id is not None:
        ok = await is_member(cq.bot, tg_group_id, tg_user_id)
        if not ok:
            group_title: str | None = None
            invite_link: str | None = None

            try:
                chat = await cq.bot.get_chat(tg_group_id)
                raw_title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
                if raw_title:
                    group_title = str(raw_title)

                raw_invite = getattr(chat, "invite_link", None)
                if isinstance(raw_invite, str) and raw_invite.strip():
                    invite_link = raw_invite.strip()
                else:
                    username = getattr(chat, "username", None)
                    if isinstance(username, str) and username.strip():
                        invite_link = f"https://t.me/{username.strip()}"
            except Exception:
                invite_link = None

            if not invite_link and settings.BOT_JOIN_GROUP_INVITE_LINK:
                link = settings.BOT_JOIN_GROUP_INVITE_LINK.strip()
                if link:
                    invite_link = link

            if not invite_link:
                try:
                    # Works when bot has permission to export invite links.
                    generated = await cq.bot.export_chat_invite_link(tg_group_id)
                    if isinstance(generated, str) and generated.strip():
                        invite_link = generated.strip()
                except Exception:
                    pass

            body = "برای خرید کارت این بازی باید عضو گروه مربوطه باشی."
            if group_title:
                body += f"\n👥 نام گروه: <b>{escape(group_title)}</b>"
            if invite_link:
                body += f"\n🆔 شناسه گروه: <a href=\"{escape(invite_link)}\"><code>{tg_group_id}</code></a>"
                body += "\nبرای عضویت مستقیم، روی دکمه «🔗 عضویت در گروه» بزن."
            else:
                body += f"\n🆔 شناسه گروه: <code>{tg_group_id}</code>"
                body += "\nلینک مستقیم گروه در دسترس نیست؛ از ادمین گروه لینک دعوت بگیر."
            body += "\nبعد از عضویت، روی «✅ عضو شدم» بزن."

            await cq.message.edit_text(
                panel("عضویت الزامی", body),
                parse_mode="HTML",
                reply_markup=join_gate_kb(game_id, tg_group_id, invite_link=invite_link),
            )
            await cq.answer("ابتدا عضو گروه شو.", show_alert=True)
            return

    text = panel(
        "خرید کارت 🛒",
        f"🎮 بازی: <b>{game_title}</b>\n"
        f"وضعیت: <b>{game_status_fa}</b>\n"
        f"💳 قیمت هر کارت: <b>{_fmt_int(card_price)}</b>\n\n"
        "حالا تعداد کارت رو انتخاب کن 👇",
    )
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=qty_kb(game_id))
    await cq.answer()


@router.callback_query(F.data.startswith("buy:qty:"))
async def buy_select_qty(cq: CallbackQuery, state: FSMContext, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    _, _, gid_s, qty_s = cq.data.split(":")
    game_id = int(gid_s)
    qty = int(qty_s)

    data = await state.get_data()
    price = int(data.get("card_price") or 0)
    title = str(data.get("game_title") or f"بازی {game_id}")
    total = price * qty

    wallet = await api.bot_get_wallet(tg_user_id, tg_username, limit=1, offset=0)
    balance = int(wallet.get("balance") or 0)

    await state.update_data(quantity=qty, total_amount=total, wallet_balance=balance)
    await state.set_state(PurchaseSG.confirm)

    hint = ""
    if balance < total:
        hint = "\n\n⚠️ موجودی کافی نیست؛ اول یه واریز انجام بده تا خریدت تکمیل بشه."

    text = panel(
        "تایید خرید",
        f"🎮 بازی: <b>{title}</b>\n"
        f"🃏 تعداد: <b>{qty}</b>\n"
        f"💳 قیمت هر کارت: <b>{_fmt_int(price)}</b>\n"
        f"💰 مبلغ کل: <b>{_fmt_int(total)}</b>\n"
        f"👛 موجودی: <b>{_fmt_int(balance)}</b>" + hint,
    )
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=confirm_kb(game_id, qty))
    await cq.answer()


@router.callback_query(F.data.startswith("buy:confirm:"))
async def buy_confirm(cq: CallbackQuery, state: FSMContext, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    _, _, gid_s, qty_s = cq.data.split(":")
    game_id = int(gid_s)
    qty = int(qty_s)

    data = await state.get_data()
    total = int(data.get("total_amount") or 0)
    balance = int(data.get("wallet_balance") or 0)

    if balance < total:
        await cq.answer("موجودی کافی نیست 😕", show_alert=True)
        return

    idem = f"BUY:{tg_user_id}:{game_id}:{uuid.uuid4().hex[:10]}"

    try:
        out = await api.bot_purchase_cards(
            tg_user_id,
            tg_username,
            game_id=game_id,
            quantity=qty,
            idempotency_key=idem,
        )
        await state.clear()

        text = panel(
            "خرید با موفقیت انجام شد ✅",
            f"🎮 بازی: <b>{out.get('game_id')}</b>\n"
            f"🧾 سفارش: <b>{out.get('order_id')}</b>\n"
            f"🃏 کارت ساخته شد: <b>{out.get('cards_created')}</b>\n"
            f"💰 مبلغ: <b>{_fmt_int(out.get('total_amount') or 0)}</b>\n"
            f"👛 موجودی جدید: <b>{_fmt_int(out.get('wallet_balance') or 0)}</b>\n"
            f"💳 شناسه تراکنش کیف پول: <code>{out.get('wallet_tx_id')}</code>",
        )
        out_game_id = int(out.get("game_id") or game_id)
        notif_on = is_subscribed(tg_user_id, out_game_id)
        await cq.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=after_purchase_kb(out_game_id, is_notif_on=notif_on),
        )
        await cq.answer()
    except ApiError as e:
        await cq.message.edit_text(panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
        await cq.answer()
