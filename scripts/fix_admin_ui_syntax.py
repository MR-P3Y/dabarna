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


def replace_block(text: str, pattern: str, replacement_lf: str, label: str) -> str:
    m = re.search(pattern, text, flags=re.S)
    if not m:
        raise SystemExit(f"{label}: target block not found")
    nl = local_nl(m.group(0))
    replacement = replacement_lf.replace("\n", nl)
    return text[:m.start()] + replacement + text[m.end():]


# 1) Repair draw panel string escapes without touching the rest of the file.
path = Path("davarna-bot/bot/routers/admin_draw_mode.py")
text, bom = load_exact(path)
new_panel = r'''def _draw_panel(state: dict) -> str:
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
text = replace_block(
    text,
    r"def _draw_panel\(state: dict\) -> str:.*?def _draw_keyboard",
    new_panel,
    "_draw_panel",
)
save_exact(path, text, bom)
print("fixed", path)


# 2) Repair live-management handler string escapes.
path = Path("davarna-bot/bot/routers/admin_games.py")
text, bom = load_exact(path)
new_handler = r'''@router.callback_query(F.data.startswith("admin:games:live:menu:"))
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


@router.callback_query(F.data.startswith("admin:games:live:set:"))'''
text = replace_block(
    text,
    r'@router\.callback_query\(F\.data\.startswith\("admin:games:live:menu:"\)\).*?@router\.callback_query\(F\.data\.startswith\("admin:games:live:set:"\)\)',
    new_handler,
    "admin_games_live_menu",
)
save_exact(path, text, bom)
print("fixed", path)
