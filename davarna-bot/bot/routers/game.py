from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.keyboards.active_games import active_game_detail_kb, active_games_list_kb
from bot.keyboards.common import back_to_menu_kb
from bot.keyboards.join_gate import join_gate_action_kb
from bot.services.api_client import ApiClient, ApiError
from bot.services.tg_membership import is_member
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel

router = Router()

ACTIVE_GAMES_PAGE_LIMIT = 8
RECENT_NUMBERS_LIMIT = 10
STATE_LAST_N = 200


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


def _fa_status(status: str | None) -> str:
    raw = (status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ACTIVE": "در حال اجرا",
        "ENDED": "پایان‌یافته",
    }
    return mapping.get(raw, "نامشخص")


def _fmt_int(value: int | str | None) -> str:
    try:
        return f"{int(value or 0):,}"
    except Exception:
        return str(value or 0)


def _as_int_list(values: object) -> list[int]:
    if not isinstance(values, list):
        return []
    out: list[int] = []
    for x in values:
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _recent_numbers_text(called_numbers: list[int], *, limit: int = RECENT_NUMBERS_LIMIT) -> str:
    if not called_numbers:
        return "—"
    tail = called_numbers[-limit:]
    if len(tail) == 1:
        return f"<b>{tail[0]}</b>"
    head = "، ".join(str(n) for n in tail[:-1])
    return f"{head}، <b>{tail[-1]}</b>"


def _winner_snapshot(state: dict) -> dict[str, int]:
    col_users = set(_as_int_list(state.get("col_winner_user_ids") or []))
    row_users = set(_as_int_list(state.get("row_winner_user_ids") or []))
    col_cards = set(_as_int_list(state.get("col_winner_card_ids") or []))
    row_cards = set(_as_int_list(state.get("row_winner_card_ids") or []))

    return {
        "col_users": len(col_users),
        "row_users": len(row_users),
        "users_total": len(col_users | row_users),
        "col_cards": len(col_cards),
        "row_cards": len(row_cards),
        "cards_total": len(col_cards | row_cards),
    }


def _build_game_flow_body(game_id: int, state: dict) -> str:
    status_raw = str(state.get("status") or "").upper()
    status_fa = _fa_status(status_raw)

    called_numbers = _as_int_list(state.get("called_numbers") or [])
    last_number = state.get("last_number")
    if last_number is None and called_numbers:
        last_number = called_numbers[-1]

    winners = _winner_snapshot(state)
    buy_state = "باز" if status_raw == "LOBBY" else "بسته"
    col_paid = bool(int(state.get("col_paid") or 0))
    row_paid = bool(int(state.get("row_paid") or 0))

    lines = [
        f"🎮 بازی: <b>#{game_id}</b>",
        f"وضعیت بازی: <b>{status_fa}</b>",
        f"👥 تعداد برندگان: <b>{winners['users_total']}</b> نفر",
        f"🪪 کارت‌های برنده: <b>{winners['cards_total']}</b>",
        f"تورنا: <b>{winners['col_users']}</b> نفر | تمام: <b>{winners['row_users']}</b> نفر",
        "",
        f"💳 قیمت کارت: <b>{_fmt_int(state.get('card_price'))}</b>",
        f"🎁 جایزه کل: <b>{_fmt_int(state.get('prize_pool'))}</b>",
        f"💵 فروش کارت: <b>{_fmt_int(state.get('sold_amount'))}</b>",
        "",
        f"🔢 آخرین عدد: <b>{last_number if last_number is not None else '—'}</b>",
        f"🧾 اعداد اخیر (تا ۱۰ عدد): {_recent_numbers_text(called_numbers)}",
        f"📊 تعداد اعداد اعلام‌شده: <b>{len(called_numbers)}</b>",
        "",
        f"🧭 وضعیت خرید کارت: <b>{buy_state}</b>",
        f"🏁 وضعیت پرداخت: تورنا {'✅' if col_paid else '❌'} | تمام {'✅' if row_paid else '❌'}",
    ]

    if status_raw == "ENDED":
        lines += ["", "🛑 این بازی پایان‌یافته است."]

    return "\n".join(lines)


def _parse_offset(data: str | None, default: int = 0) -> int:
    try:
        return max(0, int((data or "").split(":")[-1]))
    except Exception:
        return default


async def _render_active_games_list(
    cq: CallbackQuery,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None,
    *,
    offset: int,
) -> None:
    res = await api.bot_list_games(
        tg_user_id,
        tg_username,
        status="LOBBY|ACTIVE",
        limit=ACTIVE_GAMES_PAGE_LIMIT + 1,
        offset=offset,
    )
    items = res.get("items") or []
    has_more = len(items) > ACTIVE_GAMES_PAGE_LIMIT
    shown = items[:ACTIVE_GAMES_PAGE_LIMIT]

    if not shown:
        await safe_edit_or_send(
            cq.message,
            panel("بازی‌های فعال", "فعلاً بازی فعالی پیدا نشد."),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        return

    await safe_edit_or_send(
        cq.message,
        panel("بازی‌های فعال", "یکی از بازی‌ها را بزن تا جریانات بازی را ببینی 👇\n💳 قیمت هر کارت کنار هر بازی نمایش داده شده است."),
        reply_markup=active_games_list_kb(
            shown,
            offset=offset,
            limit=ACTIVE_GAMES_PAGE_LIMIT,
            has_more=has_more,
        ),
        parse_mode="HTML",
    )


async def _render_game_flow(cq: CallbackQuery, api: ApiClient, *, game_id: int, offset: int) -> None:
    state = await api.get_game_state(game_id, last_n=STATE_LAST_N)
    await safe_edit_or_send(
        cq.message,
        panel("جریانات بازی", _build_game_flow_body(game_id, state)),
        reply_markup=active_game_detail_kb(game_id=game_id, offset=offset),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:games")
async def games_entry(
    cq: CallbackQuery,
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
                        "برای مشاهده بازی‌های فعال ابتدا باید عضو گروه بازی باشید.\n"
                        "بعد از عضویت، روی «✅ عضو شدم» بزن.",
                    ),
                    reply_markup=join_gate_action_kb(
                        "games",
                        required_group_id,
                        invite_link=_join_invite_link(),
                    ),
                    parse_mode="HTML",
                )
                await cq.answer("ابتدا عضو گروه بازی شوید.", show_alert=True)
                return

    try:
        await _render_active_games_list(cq, api, tg_user_id, tg_username, offset=0)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("games:list:"))
async def games_list_page(
    cq: CallbackQuery,
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None = None,
):
    offset = _parse_offset(cq.data, default=0)
    try:
        await _render_active_games_list(cq, api, tg_user_id, tg_username, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("games:view:"))
async def games_view(cq: CallbackQuery, api: ApiClient):
    parts = (cq.data or "").split(":")
    if len(parts) < 4:
        await cq.answer("داده نامعتبر است.", show_alert=False)
        return

    try:
        game_id = int(parts[2])
        offset = max(0, int(parts[3]))
    except Exception:
        await cq.answer("داده نامعتبر است.", show_alert=False)
        return

    try:
        await _render_game_flow(cq, api, game_id=game_id, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
    await cq.answer()


@router.callback_query(F.data.startswith("games:refresh:"))
async def games_refresh(cq: CallbackQuery, api: ApiClient):
    parts = (cq.data or "").split(":")
    if len(parts) < 4:
        await cq.answer("داده نامعتبر است.", show_alert=False)
        return

    try:
        game_id = int(parts[2])
        offset = max(0, int(parts[3]))
    except Exception:
        await cq.answer("داده نامعتبر است.", show_alert=False)
        return

    try:
        await _render_game_flow(cq, api, game_id=game_id, offset=offset)
        await cq.answer("به‌روز شد ✅", show_alert=False)
        return
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
    await cq.answer()


@router.message(Command("game"))
async def cmd_game(m: Message, api: ApiClient):
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer(panel("راهنما", "روش درست استفاده:\nشناسه بازی را بعد از دستور ارسال کن.\nنمونه: <b>۸</b>"), parse_mode="HTML")
        return

    game_id = int(parts[1])
    try:
        state = await api.get_game_state(game_id, last_n=STATE_LAST_N)
        await m.answer(
            panel("جریانات بازی", _build_game_flow_body(game_id, state)),
            parse_mode="HTML",
            reply_markup=active_game_detail_kb(game_id=game_id, offset=0),
        )
    except ApiError as e:
        await m.answer(panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")

