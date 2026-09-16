from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.api_client import ApiClient, ApiError
from bot.services.draw_mode_api import get_draw_mode, pause_auto_draw, resume_auto_draw, set_draw_mode
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel
from bot.services.user_topics import send_to_game_topic


router = Router()


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _ctx(data: str, prefix_parts: int) -> tuple[int, str, int]:
    parts = str(data or "").split(":")
    game_id = _to_int(parts[prefix_parts] if len(parts) > prefix_parts else None, 0)
    status = parts[prefix_parts + 1] if len(parts) > prefix_parts + 1 and parts[prefix_parts + 1] else "LOBBY|RUNNING"
    offset = _to_int(parts[prefix_parts + 2] if len(parts) > prefix_parts + 2 else None, 0)
    return game_id, status, max(0, offset)


def _mode_label(mode: str | None) -> str:
    return "🤖 خودکار" if str(mode or "").upper() == "AUTO" else "👤 دستی" if str(mode or "").upper() == "MANUAL" else "انتخاب نشده"


def _auto_status_label(status: str | None) -> str:
    raw = str(status or "").upper()
    return {
        "ARMED": "آماده شروع",
        "RUNNING": "در حال اجرا",
        "PAUSED": "متوقف موقت",
        "STOPPED": "متوقف",
    }.get(raw, raw or "—")


def _draw_panel(state: dict) -> str:
    gid = _to_int(state.get("game_id"), 0)
    game_status = str(state.get("game_status") or "").upper()
    mode = str(state.get("draw_mode") or "").upper() or None
    interval = state.get("interval_seconds")
    locked = bool(state.get("locked"))
    commitment = str(state.get("sequence_commitment") or "").strip()
    auto_status = str(state.get("auto_status") or "").upper()

    body = (
        f"🎮 بازی: <b>#{gid}</b>\n"
        f"🎛 روش شماره‌خوانی: <b>{_mode_label(mode)}</b>\n"
        f"🔒 وضعیت قانون: <b>{'قفل‌شده' if locked else 'قابل انتخاب تا قبل از شروع'}</b>\n"
    )
    if mode == "AUTO":
        body += f"⏱ فاصله اعلام: <b>{_to_int(interval, 0)} ثانیه</b>\n"
        body += f"🤖 وضعیت شماره‌خوان: <b>{_auto_status_label(auto_status)}</b>\n"
        if commitment:
            body += f"🔐 تعهد ترتیب اعداد:\n<code>{commitment}</code>\n"
    if game_status == "LOBBY":
        body += "\n⚠️ روش انتخاب‌شده با شروع بازی برای همیشه قفل می‌شود."
    elif game_status == "RUNNING":
        body += "\n✅ در این بازی تغییر بین دستی و خودکار امکان‌پذیر نیست."
    return panel("کنترل شماره‌خوانی", body)


def _draw_keyboard(state: dict, *, status: str, offset: int):
    kb = InlineKeyboardBuilder()
    gid = _to_int(state.get("game_id"), 0)
    game_status = str(state.get("game_status") or "").upper()
    mode = str(state.get("draw_mode") or "").upper()
    auto_status = str(state.get("auto_status") or "").upper()

    if game_status == "LOBBY":
        kb.button(text="👤 دستی", callback_data=f"drawmode:set:manual:{gid}:{status}:{offset}")
        kb.button(text="🤖 خودکار ۵ث", callback_data=f"drawmode:set:auto5:{gid}:{status}:{offset}")
        kb.button(text="🤖 خودکار ۸ث", callback_data=f"drawmode:set:auto8:{gid}:{status}:{offset}")
        kb.button(text="🤖 خودکار ۱۰ث", callback_data=f"drawmode:set:auto10:{gid}:{status}:{offset}")
        kb.button(text="🤖 خودکار ۱۵ث", callback_data=f"drawmode:set:auto15:{gid}:{status}:{offset}")
        if mode in {"MANUAL", "AUTO"}:
            kb.button(text="▶️ تأیید و شروع بازی", callback_data=f"drawmode:start:{gid}:{status}:{offset}")
        kb.adjust(1, 2, 2, 1)
    elif game_status == "RUNNING" and mode == "MANUAL":
        kb.button(text="🔢 اعلام عدد دستی", callback_data=f"admin:games:call:{gid}:{status}:{offset}")
        kb.button(text="↩️ بازگردانی آخرین شماره", callback_data=f"admin:games:undo:{gid}:{status}:{offset}")
        kb.adjust(1, 1)
    elif game_status == "RUNNING" and mode == "AUTO":
        if auto_status == "RUNNING":
            kb.button(text="⏸ توقف موقت", callback_data=f"drawmode:pause:{gid}:{status}:{offset}")
        elif auto_status == "PAUSED":
            kb.button(text="▶️ ادامه همان ترتیب", callback_data=f"drawmode:resume:{gid}:{status}:{offset}")
        kb.adjust(1)

    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:draw:{gid}:{status}:{offset}")
    kb.button(text="⬅️ برگشت به بازی", callback_data=f"admin:games:view:{gid}:{status}:{offset}")
    kb.adjust(1, 1)
    return kb.as_markup()


async def _show(cq: CallbackQuery, api: ApiClient, *, game_id: int, status: str, offset: int) -> None:
    if not cq.message:
        return
    try:
        state = await get_draw_mode(api, game_id)
    except ApiError as exc:
        await cq.answer(str(exc.detail)[:180], show_alert=True)
        return
    await safe_edit_or_send(
        cq.message,
        _draw_panel(state),
        reply_markup=_draw_keyboard(state, status=status, offset=offset),
    )


async def _announce_selection(cq: CallbackQuery, state: dict) -> None:
    topic_id = state.get("tg_topic_id")
    if topic_id is None:
        return
    gid = _to_int(state.get("game_id"), 0)
    mode = str(state.get("draw_mode") or "").upper()
    interval = _to_int(state.get("interval_seconds"), 0)
    commitment = str(state.get("sequence_commitment") or "").strip()
    body = (
        "#شرایط_بازی #شماره_خوانی\n"
        f"🎮 بازی: <b>#{gid}</b>\n"
        f"🎛 روش اعلام اعداد: <b>{_mode_label(mode)}</b>\n"
    )
    if mode == "AUTO":
        body += f"⏱ فاصله اعلام: <b>{interval} ثانیه</b>\n"
        if commitment:
            body += f"🔐 تعهد ترتیب اعداد:\n<code>{commitment}</code>\n"
    body += "\n⚖️ این روش با شروع بازی قفل می‌شود و در طول بازی قابل تغییر نیست."
    await send_to_game_topic(
        cq.bot,
        game_topic_id=int(topic_id),
        text=panel("شرایط شماره‌خوانی بازی", body),
        parse_mode="HTML",
        disable_notification=False,
    )


async def _announce_locked(cq: CallbackQuery, state: dict) -> None:
    topic_id = state.get("tg_topic_id")
    if topic_id is None:
        return
    gid = _to_int(state.get("game_id"), 0)
    mode = str(state.get("draw_mode") or "").upper()
    interval = _to_int(state.get("interval_seconds"), 0)
    body = (
        "#شروع_بازی #قانون_ثابت\n"
        f"🎮 بازی: <b>#{gid}</b>\n"
        f"🔒 روش شماره‌خوانی قفل شد: <b>{_mode_label(mode)}</b>\n"
    )
    if mode == "AUTO":
        body += f"⏱ فاصله ثابت: <b>{interval} ثانیه</b>\n"
    body += "\nتغییر روش شماره‌خوانی تا پایان این بازی امکان‌پذیر نیست."
    await send_to_game_topic(
        cq.bot,
        game_topic_id=int(topic_id),
        text=panel("شروع رسمی بازی", body),
        parse_mode="HTML",
        disable_notification=False,
    )


@router.callback_query(F.data.startswith("admin:games:draw:"))
async def open_draw_mode(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not is_admin:
        await cq.answer("دسترسی ادمین لازم است.", show_alert=True)
        return
    game_id, status, offset = _ctx(cq.data or "", 3)
    await cq.answer()
    await _show(cq, api, game_id=game_id, status=status, offset=offset)


@router.callback_query(F.data.startswith("drawmode:set:"))
async def select_draw_mode(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not is_admin:
        await cq.answer("دسترسی ادمین لازم است.", show_alert=True)
        return
    parts = str(cq.data or "").split(":")
    choice = parts[2] if len(parts) > 2 else ""
    game_id = _to_int(parts[3] if len(parts) > 3 else None, 0)
    status = parts[4] if len(parts) > 4 else "LOBBY|RUNNING"
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    try:
        if choice == "manual":
            state = await set_draw_mode(api, game_id, draw_mode="MANUAL")
        elif choice.startswith("auto"):
            interval = _to_int(choice.replace("auto", ""), 0)
            state = await set_draw_mode(api, game_id, draw_mode="AUTO", interval_seconds=interval)
        else:
            await cq.answer("انتخاب نامعتبر است.", show_alert=True)
            return
    except ApiError as exc:
        await cq.answer(str(exc.detail)[:180], show_alert=True)
        return

    await cq.answer("روش شماره‌خوانی ثبت شد.")
    await _announce_selection(cq, state)
    if cq.message:
        await safe_edit_or_send(
            cq.message,
            _draw_panel(state),
            reply_markup=_draw_keyboard(state, status=status, offset=offset),
        )


@router.callback_query(F.data.startswith("drawmode:start:"))
async def start_locked_game(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not is_admin:
        await cq.answer("دسترسی ادمین لازم است.", show_alert=True)
        return
    game_id, status, offset = _ctx(cq.data or "", 2)
    try:
        before = await get_draw_mode(api, game_id)
        if str(before.get("draw_mode") or "").upper() not in {"MANUAL", "AUTO"}:
            await cq.answer("ابتدا روش شماره‌خوانی را انتخاب کنید.", show_alert=True)
            return
        await api.admin_start_game(game_id, idempotency_key=f"BOT_DRAW_START:{game_id}")
        state = await get_draw_mode(api, game_id)
    except ApiError as exc:
        await cq.answer(str(exc.detail)[:180], show_alert=True)
        return

    if not bool(state.get("locked")) or str(state.get("game_status") or "").upper() != "RUNNING":
        await cq.answer("شروع بازی تأیید نشد؛ وضعیت را بررسی کنید.", show_alert=True)
        return
    if str(state.get("draw_mode") or "").upper() == "AUTO" and str(state.get("auto_status") or "").upper() != "RUNNING":
        await cq.answer("بازی شروع شد اما شماره‌خوان خودکار فعال نشد؛ عملیات متوقف و باید بررسی شود.", show_alert=True)
        return

    await cq.answer("بازی با قانون شماره‌خوانی قفل‌شده شروع شد.", show_alert=True)
    await _announce_locked(cq, state)
    if cq.message:
        await safe_edit_or_send(
            cq.message,
            _draw_panel(state),
            reply_markup=_draw_keyboard(state, status=status, offset=offset),
        )


@router.callback_query(F.data.startswith("drawmode:pause:"))
async def pause_locked_auto(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not is_admin:
        await cq.answer("دسترسی ادمین لازم است.", show_alert=True)
        return
    game_id, status, offset = _ctx(cq.data or "", 2)
    try:
        await pause_auto_draw(api, game_id)
    except ApiError as exc:
        await cq.answer(str(exc.detail)[:180], show_alert=True)
        return
    await cq.answer("شماره‌خوان موقتاً متوقف شد. روش بازی همچنان خودکار و قفل است.")
    await _show(cq, api, game_id=game_id, status=status, offset=offset)


@router.callback_query(F.data.startswith("drawmode:resume:"))
async def resume_locked_auto(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not is_admin:
        await cq.answer("دسترسی ادمین لازم است.", show_alert=True)
        return
    game_id, status, offset = _ctx(cq.data or "", 2)
    try:
        await resume_auto_draw(api, game_id)
    except ApiError as exc:
        await cq.answer(str(exc.detail)[:180], show_alert=True)
        return
    await cq.answer("شماره‌خوان با همان ترتیب اولیه ادامه یافت.")
    await _show(cq, api, game_id=game_id, status=status, offset=offset)
