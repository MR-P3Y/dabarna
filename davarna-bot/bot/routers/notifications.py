from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.purchase import after_purchase_kb
from bot.services.api_client import ApiClient, ApiError
from bot.services.notify_store import (
    get_subscribers,
    set_last_seen_count,
    subscribe,
    unsubscribe,
)

router = Router()


def _parse_game_id(data: str | None) -> int | None:
    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def _is_after_purchase_keyboard(cq: CallbackQuery) -> bool:
    msg = cq.message
    if not msg or not msg.reply_markup:
        return False
    rows = getattr(msg.reply_markup, "inline_keyboard", None) or []
    for row in rows:
        for btn in row:
            if getattr(btn, "callback_data", None) == "menu:mycards":
                return True
    return False


async def _toggle_list_notif_button(cq: CallbackQuery, game_id: int, *, is_on: bool) -> None:
    msg = cq.message
    if not msg or not msg.reply_markup:
        return

    rows = getattr(msg.reply_markup, "inline_keyboard", None) or []
    changed = False
    new_rows: list[list[InlineKeyboardButton]] = []

    for row in rows:
        new_row: list[InlineKeyboardButton] = []
        for btn in row:
            cb = getattr(btn, "callback_data", None)
            if cb in (f"notif:on:{game_id}", f"notif:off:{game_id}"):
                changed = True
                if is_on:
                    new_row.append(
                        InlineKeyboardButton(
                            text=f"🔕 نوتیف بازی #{game_id} خاموش",
                            callback_data=f"notif:off:{game_id}",
                        )
                    )
                else:
                    new_row.append(
                        InlineKeyboardButton(
                            text=f"🔔 نوتیف بازی #{game_id} روشن",
                            callback_data=f"notif:on:{game_id}",
                        )
                    )
            else:
                new_row.append(btn)
        new_rows.append(new_row)

    if changed:
        try:
            await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_rows))
        except Exception:
            pass


@router.callback_query(F.data.startswith("notif:on:"))
async def notif_on(cq: CallbackQuery, api: ApiClient, tg_user_id: int):
    game_id = _parse_game_id(cq.data)
    if game_id is None:
        await cq.answer("شناسه بازی نامعتبره 😕", show_alert=True)
        return

    try:
        st = await api.get_game_state(game_id, last_n=200)
    except ApiError as e:
        await cq.answer(f"خطا در دریافت وضعیت بازی:\n{e.detail}", show_alert=True)
        return

    subs_before = get_subscribers(game_id)
    already = int(tg_user_id) in set(subs_before)
    subscribe(tg_user_id=int(tg_user_id), game_id=game_id)

    if not subs_before:
        called = st.get("called_numbers") or []
        set_last_seen_count(game_id, len(called))

    if _is_after_purchase_keyboard(cq) and cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=after_purchase_kb(game_id, is_notif_on=True))
        except Exception:
            pass
    else:
        await _toggle_list_notif_button(cq, game_id, is_on=True)

    if already:
        await cq.answer("نوتیف این بازی از قبل روشن بود 🔔")
    else:
        await cq.answer("نوتیف این بازی روشن شد ✅\nاز این به بعد عددهای جدید رو خبر می‌دم 😉")


@router.callback_query(F.data.startswith("notif:off:"))
async def notif_off(cq: CallbackQuery, tg_user_id: int):
    game_id = _parse_game_id(cq.data)
    if game_id is None:
        await cq.answer("شناسه بازی نامعتبره 😕", show_alert=True)
        return

    unsubscribe(tg_user_id=int(tg_user_id), game_id=game_id)

    if _is_after_purchase_keyboard(cq) and cq.message:
        try:
            await cq.message.edit_reply_markup(reply_markup=after_purchase_kb(game_id, is_notif_on=False))
        except Exception:
            pass
    else:
        await _toggle_list_notif_button(cq, game_id, is_on=False)

    await cq.answer("نوتیف این بازی خاموش شد 🔕")
