from __future__ import annotations

import re
from pathlib import Path


def replace_block(text: str, pattern: str, replacement: str, *, label: str) -> str:
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 replacement, got {count}")
    return new_text


# ---------------------------------------------------------------------------
# 1) Admin game keyboard: fewer top-level buttons + live submenu
# ---------------------------------------------------------------------------
kb_path = Path("davarna-bot/bot/keyboards/admin_games.py")
kb = kb_path.read_text(encoding="utf-8-sig")

new_item = '''def admin_game_item_kb(
    *,
    game_id: int,
    status: str,
    offset: int,
    game_status: str | None = None,
    has_winners: bool = True,
    allow_close_lobby: bool = False,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    normalized = (game_status or "").strip().upper()
    rows: list[int] = []

    if normalized == "LOBBY":
        kb.button(
            text="🎛 تنظیم روش شماره‌خوانی و شروع",
            callback_data=f"admin:games:draw:{int(game_id)}:{status}:{offset}",
        )
        rows.append(1)
        if allow_close_lobby:
            kb.button(
                text="🛑 بستن بازی لابی",
                callback_data=f"admin:games:close-lobby:{int(game_id)}:{status}:{offset}",
            )
            rows.append(1)
        kb.button(text="🧾 گزارش بازی", callback_data=f"admin:games:report:{int(game_id)}:{status}:{offset}")
        kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}")
        rows.append(2)

    elif normalized == "RUNNING":
        kb.button(
            text="🎛 کنترل بازی و شماره‌ها",
            callback_data=f"admin:games:draw:{int(game_id)}:{status}:{offset}",
        )
        rows.append(1)
        kb.button(text="📡 مانیتور زنده", callback_data=f"admin:games:monitor:{int(game_id)}:{status}:{offset}")
        kb.button(text="🧾 گزارش بازی", callback_data=f"admin:games:report:{int(game_id)}:{status}:{offset}")
        rows.append(2)
        if has_winners:
            kb.button(text="🏆 برنده‌ها", callback_data=f"admin:games:winners:{int(game_id)}:{status}:{offset}")
            kb.button(text="🎥 مدیریت لایو", callback_data=f"admin:games:live:menu:{int(game_id)}:{status}:{offset}")
            rows.append(2)
        else:
            kb.button(text="🎥 مدیریت لایو", callback_data=f"admin:games:live:menu:{int(game_id)}:{status}:{offset}")
            rows.append(1)
        kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}")
        rows.append(1)

    else:
        kb.button(
            text="🏁 بازی پایان یافته",
            callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}",
        )
        rows.append(1)
        kb.button(text="🧾 گزارش نهایی", callback_data=f"admin:games:report:{int(game_id)}:{status}:{offset}")
        if has_winners:
            kb.button(text="🏆 برنده‌ها", callback_data=f"admin:games:winners:{int(game_id)}:{status}:{offset}")
            rows.append(2)
        else:
            rows.append(1)
        kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}")
        rows.append(1)

    kb.button(text="⬅️ برگشت به لیست بازی‌ها", callback_data=f"admin:games:list:{status}:{offset}")
    rows.append(1)
    kb.adjust(*rows)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_live_kb(*, game_id: int, status: str, offset: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔗 تنظیم / تغییر لینک", callback_data=f"admin:games:live:set:{game_id}:{status}:{offset}")
    kb.button(text="📣 ارسال برای بازیکنان", callback_data=f"admin:games:live:send:{game_id}:{status}:{offset}")
    kb.button(text="🧹 حذف لینک", callback_data=f"admin:games:live:clear:{game_id}:{status}:{offset}")
    kb.button(text="⬅️ برگشت به بازی", callback_data=f"admin:games:view:{game_id}:{status}:{offset}")
    kb.adjust(1, 2, 1)
    return kb.as_markup()
'''

kb = replace_block(
    kb,
    r"def admin_game_item_kb\(.*?\n\ndef admin_monitor_kb",
    new_item + "\n\ndef admin_monitor_kb",
    label="admin_game_item_kb",
)
kb_path.write_text(kb, encoding="utf-8")


# ---------------------------------------------------------------------------
# 2) Draw-mode panel: clearer state, highlighted selection, fewer clicks
# ---------------------------------------------------------------------------
draw_path = Path("davarna-bot/bot/routers/admin_draw_mode.py")
draw = draw_path.read_text(encoding="utf-8-sig")

new_panel = '''def _draw_panel(state: dict) -> str:
    gid = _to_int(state.get("game_id"), 0)
    game_status = str(state.get("game_status") or "").upper()
    mode = str(state.get("draw_mode") or "").upper() or None
    interval = _to_int(state.get("interval_seconds"), 0)
    locked = bool(state.get("locked"))
    commitment = str(state.get("sequence_commitment") or "").strip()
    auto_status = str(state.get("auto_status") or "").upper()
    remaining = _to_int(state.get("remaining_count"), 0)

    status_label = {
        "LOBBY": "🟡 آماده شروع",
        "RUNNING": "🟢 در حال اجرا",
        "ENDED": "⚫ پایان یافته",
    }.get(game_status, "⚪ نامشخص")

    body = (
        f"🎮 بازی <b>#{gid}</b>\n"
        f"📍 وضعیت: <b>{status_label}</b>\n"
        f"🎛 روش: <b>{_mode_label(mode)}</b>\n"
    )

    if game_status == "LOBBY":
        if mode == "AUTO":
            body += f"⏱ فاصله انتخاب‌شده: <b>{interval} ثانیه</b>\n"
        body += "🔓 تا قبل از شروع، انتخاب قابل تغییر است.\n"
        if mode in {"MANUAL", "AUTO"}:
            body += "\n✅ آماده شروع؛ با زدن دکمه شروع، این قانون برای همان بازی قفل می‌شود."
        else:
            body += "\n👇 ابتدا روش شماره‌خوانی را انتخاب کنید."

    elif game_status == "RUNNING":
        body += "🔒 قانون این بازی قفل شده است.\n"
        if mode == "MANUAL":
            body += "🔢 اعلام اعداد فقط توسط ادمین انجام می‌شود."
        elif mode == "AUTO":
            body += f"⏱ فاصله ثابت: <b>{interval} ثانیه</b>\n"
            body += f"🤖 وضعیت: <b>{_auto_status_label(auto_status)}</b>\n"
            body += f"🔢 اعداد باقی‌مانده در ترتیب: <b>{remaining}</b>"

    else:
        body += f"🔒 وضعیت قانون: <b>{'قفل‌شده' if locked else 'ثبت‌شده'}</b>"

    if mode == "AUTO" and commitment:
        short_commitment = commitment[:16] + "…" if len(commitment) > 16 else commitment
        body += f"\n🔐 شناسه ترتیب: <code>{short_commitment}</code>"

    return panel("🎛 کنترل بازی و شماره‌ها", body)
'''

draw = replace_block(
    draw,
    r"def _draw_panel\(state: dict\) -> str:.*?\n\ndef _draw_keyboard",
    new_panel + "\n\ndef _draw_keyboard",
    label="_draw_panel",
)

new_keyboard = '''def _draw_keyboard(state: dict, *, status: str, offset: int):
    kb = InlineKeyboardBuilder()
    gid = _to_int(state.get("game_id"), 0)
    game_status = str(state.get("game_status") or "").upper()
    mode = str(state.get("draw_mode") or "").upper()
    interval = _to_int(state.get("interval_seconds"), 0)
    auto_status = str(state.get("auto_status") or "").upper()
    rows: list[int] = []

    if game_status == "LOBBY":
        manual_text = "✅ دستی" if mode == "MANUAL" else "👤 دستی"
        kb.button(text=manual_text, callback_data=f"drawmode:set:manual:{gid}:{status}:{offset}")
        rows.append(1)

        for sec in (5, 8, 10, 15):
            selected = mode == "AUTO" and interval == sec
            label = f"✅ خودکار {sec}ث" if selected else f"🤖 خودکار {sec}ث"
            kb.button(text=label, callback_data=f"drawmode:set:auto{sec}:{gid}:{status}:{offset}")
        rows.extend([2, 2])

        if mode == "MANUAL":
            kb.button(text="🚀 شروع بازی با حالت دستی", callback_data=f"drawmode:start:{gid}:{status}:{offset}")
            rows.append(1)
        elif mode == "AUTO":
            kb.button(text=f"🚀 شروع خودکار • هر {interval} ثانیه", callback_data=f"drawmode:start:{gid}:{status}:{offset}")
            rows.append(1)

    elif game_status == "RUNNING" and mode == "MANUAL":
        kb.button(text="🔢 اعلام عدد جدید", callback_data=f"admin:games:call:{gid}:{status}:{offset}")
        kb.button(text="↩️ بازگردانی آخرین عدد", callback_data=f"admin:games:undo:{gid}:{status}:{offset}")
        rows.extend([1, 1])
        kb.button(text="📡 مانیتور", callback_data=f"admin:games:monitor:{gid}:{status}:{offset}")
        kb.button(text="🧾 گزارش", callback_data=f"admin:games:report:{gid}:{status}:{offset}")
        rows.append(2)

    elif game_status == "RUNNING" and mode == "AUTO":
        if auto_status == "RUNNING":
            kb.button(text="⏸ مکث شماره‌خوان", callback_data=f"drawmode:pause:{gid}:{status}:{offset}")
            rows.append(1)
        elif auto_status == "PAUSED":
            kb.button(text="▶️ ادامه همان ترتیب", callback_data=f"drawmode:resume:{gid}:{status}:{offset}")
            rows.append(1)
        kb.button(text="📡 مانیتور", callback_data=f"admin:games:monitor:{gid}:{status}:{offset}")
        kb.button(text="🧾 گزارش", callback_data=f"admin:games:report:{gid}:{status}:{offset}")
        rows.append(2)

    kb.button(text="🔄 به‌روزرسانی", callback_data=f"admin:games:draw:{gid}:{status}:{offset}")
    kb.button(text="⬅️ برگشت به بازی", callback_data=f"admin:games:view:{gid}:{status}:{offset}")
    rows.append(2)
    kb.adjust(*rows)
    return kb.as_markup()
'''

draw = replace_block(
    draw,
    r"def _draw_keyboard\(state: dict, \*, status: str, offset: int\):.*?\n\n\nasync def _show",
    new_keyboard + "\n\n\nasync def _show",
    label="_draw_keyboard",
)
draw_path.write_text(draw, encoding="utf-8")


# ---------------------------------------------------------------------------
# 3) Admin router: one live-management entry instead of three top-level buttons
# ---------------------------------------------------------------------------
router_path = Path("davarna-bot/bot/routers/admin_games.py")
router = router_path.read_text(encoding="utf-8-sig")

if "    admin_live_kb,\n" not in router:
    anchor = "    admin_game_item_kb,\n"
    if anchor not in router:
        raise SystemExit("admin_games import anchor not found")
    router = router.replace(anchor, anchor + "    admin_live_kb,\n", 1)

if 'F.data.startswith("admin:games:live:menu:")' not in router:
    live_set_marker = '@router.callback_query(F.data.startswith("admin:games:live:set:"))\n'
    if live_set_marker not in router:
        raise SystemExit("live set handler marker not found")
    live_menu_handler = '''@router.callback_query(F.data.startswith("admin:games:live:menu:"))
async def admin_games_live_menu(cq: CallbackQuery, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    if not cq.message:
        return
    _, game_id, status, offset = _parse_live_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return
    await cq.answer()
    await safe_edit_or_send(
        cq.message,
        panel(
            "🎥 مدیریت لایو",
            f"🎮 بازی <b>#{game_id}</b>\n\n"
            "از این بخش لینک لایو را تنظیم، برای بازیکنان ارسال یا حذف کنید.",
        ),
        parse_mode="HTML",
        reply_markup=admin_live_kb(game_id=game_id, status=status, offset=offset),
    )


'''
    router = router.replace(live_set_marker, live_menu_handler + live_set_marker, 1)

router_path.write_text(router, encoding="utf-8")

print("patched", kb_path)
print("patched", draw_path)
print("patched", router_path)
