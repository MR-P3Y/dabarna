from __future__ import annotations

import re
from pathlib import Path


def load_exact(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    return raw.decode("utf-8"), bom


def save_exact(path: Path, text: str, bom: bool) -> None:
    raw = text.encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw
    path.write_bytes(raw)


def local_nl(block: str) -> str:
    return "\r\n" if "\r\n" in block else "\n"


def replace_func(text: str, start_pat: str, end_pat: str, replacement_lf: str, label: str) -> str:
    pat = re.compile(start_pat + r".*?" + end_pat, re.S)
    m = pat.search(text)
    if not m:
        raise SystemExit(f"{label}: target block not found")
    block = m.group(0)
    nl = local_nl(block)
    replacement = replacement_lf.replace("\n", nl)
    return text[:m.start()] + replacement + text[m.end():]


# 1) keyboard ---------------------------------------------------------------
path = Path("davarna-bot/bot/keyboards/admin_games.py")
text, bom = load_exact(path)
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
        kb.button(text="🎛 تنظیم روش شماره‌خوانی و شروع", callback_data=f"admin:games:draw:{int(game_id)}:{status}:{offset}")
        rows.append(1)
        if allow_close_lobby:
            kb.button(text="🛑 بستن بازی لابی", callback_data=f"admin:games:close-lobby:{int(game_id)}:{status}:{offset}")
            rows.append(1)
        kb.button(text="🧾 گزارش بازی", callback_data=f"admin:games:report:{int(game_id)}:{status}:{offset}")
        kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}")
        rows.append(2)
    elif normalized == "RUNNING":
        kb.button(text="🎛 کنترل بازی و شماره‌ها", callback_data=f"admin:games:draw:{int(game_id)}:{status}:{offset}")
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
        kb.button(text="🏁 بازی پایان یافته", callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}")
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


def admin_monitor_kb'''
text = replace_func(text, r"def admin_game_item_kb\(", r"def admin_monitor_kb", new_item, "admin_game_item_kb")
save_exact(path, text, bom)
print("patched", path)


# 2) draw mode panel ---------------------------------------------------------
path = Path("davarna-bot/bot/routers/admin_draw_mode.py")
text, bom = load_exact(path)
new_panel = '''def _draw_panel(state: dict) -> str:
    gid = _to_int(state.get("game_id"), 0)
    game_status = str(state.get("game_status") or "").upper()
    mode = str(state.get("draw_mode") or "").upper() or None
    interval = _to_int(state.get("interval_seconds"), 0)
    locked = bool(state.get("locked"))
    commitment = str(state.get("sequence_commitment") or "").strip()
    auto_status = str(state.get("auto_status") or "").upper()
    remaining = _to_int(state.get("remaining_count"), 0)

    status_label = {"LOBBY": "🟡 آماده شروع", "RUNNING": "🟢 در حال اجرا", "ENDED": "⚫ پایان یافته"}.get(game_status, "⚪ نامشخص")
    body = f"🎮 بازی <b>#{gid}</b>\n📍 وضعیت: <b>{status_label}</b>\n🎛 روش: <b>{_mode_label(mode)}</b>\n"

    if game_status == "LOBBY":
        if mode == "AUTO":
            body += f"⏱ فاصله انتخاب‌شده: <b>{interval} ثانیه</b>\n"
        body += "🔓 تا قبل از شروع، انتخاب قابل تغییر است.\n"
        body += "\n✅ آماده شروع؛ با شروع بازی این قانون قفل می‌شود." if mode in {"MANUAL", "AUTO"} else "\n👇 ابتدا روش شماره‌خوانی را انتخاب کنید."
    elif game_status == "RUNNING":
        body += "🔒 قانون این بازی قفل شده است.\n"
        if mode == "MANUAL":
            body += "🔢 اعلام اعداد فقط توسط ادمین انجام می‌شود."
        elif mode == "AUTO":
            body += f"⏱ فاصله ثابت: <b>{interval} ثانیه</b>\n🤖 وضعیت: <b>{_auto_status_label(auto_status)}</b>\n🔢 اعداد باقی‌مانده: <b>{remaining}</b>"
    else:
        body += f"🔒 وضعیت قانون: <b>{'قفل‌شده' if locked else 'ثبت‌شده'}</b>"

    if mode == "AUTO" and commitment:
        short_commitment = commitment[:16] + "…" if len(commitment) > 16 else commitment
        body += f"\n🔐 شناسه ترتیب: <code>{short_commitment}</code>"
    return panel("🎛 کنترل بازی و شماره‌ها", body)


def _draw_keyboard'''
text = replace_func(text, r"def _draw_panel\(state: dict\) -> str:", r"def _draw_keyboard", new_panel, "_draw_panel")
new_keyboard = '''def _draw_keyboard(state: dict, *, status: str, offset: int):
    kb = InlineKeyboardBuilder()
    gid = _to_int(state.get("game_id"), 0)
    game_status = str(state.get("game_status") or "").upper()
    mode = str(state.get("draw_mode") or "").upper()
    interval = _to_int(state.get("interval_seconds"), 0)
    auto_status = str(state.get("auto_status") or "").upper()
    rows: list[int] = []

    if game_status == "LOBBY":
        kb.button(text="✅ دستی" if mode == "MANUAL" else "👤 دستی", callback_data=f"drawmode:set:manual:{gid}:{status}:{offset}")
        rows.append(1)
        for sec in (5, 8, 10, 15):
            selected = mode == "AUTO" and interval == sec
            kb.button(text=f"✅ خودکار {sec}ث" if selected else f"🤖 خودکار {sec}ث", callback_data=f"drawmode:set:auto{sec}:{gid}:{status}:{offset}")
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


async def _show'''
text = replace_func(text, r"def _draw_keyboard\(state: dict, \*, status: str, offset: int\):", r"async def _show", new_keyboard, "_draw_keyboard")
save_exact(path, text, bom)
print("patched", path)


# 3) router: import live keyboard + submenu handler -------------------------
path = Path("davarna-bot/bot/routers/admin_games.py")
text, bom = load_exact(path)

if "    admin_live_kb," not in text:
    m = re.search(r"([ \t]*admin_game_item_kb,)(\r?\n)", text)
    if not m:
        raise SystemExit("admin_live_kb import anchor not found")
    text = text[:m.end()] + m.group(1).split("admin_game_item_kb")[0] + "admin_live_kb," + m.group(2) + text[m.end():]

if 'F.data.startswith("admin:games:live:menu:")' not in text:
    marker = re.search(r'@router\.callback_query\(F\.data\.startswith\("admin:games:live:set:"\)\)(\r?\n)', text)
    if not marker:
        raise SystemExit("live:set marker not found")
    nl = marker.group(1)
    handler = '''@router.callback_query(F.data.startswith("admin:games:live:menu:"))
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
        panel("🎥 مدیریت لایو", f"🎮 بازی <b>#{game_id}</b>\n\nاز این بخش لینک لایو را تنظیم، برای بازیکنان ارسال یا حذف کنید."),
        parse_mode="HTML",
        reply_markup=admin_live_kb(game_id=game_id, status=status, offset=offset),
    )


'''.replace("\n", nl)
    text = text[:marker.start()] + handler + text[marker.start():]

save_exact(path, text, bom)
print("patched", path)
