from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_DRAW = ROOT / "davarna-bot/bot/routers/admin_draw_mode.py"
NOTIFIER = ROOT / "davarna-bot/bot/workers/notifier.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)


admin = ADMIN_DRAW.read_text(encoding="utf-8")
admin = admin.replace("from bot.services.user_topics import send_to_game_topic\n", "")

start = admin.find("\nasync def _announce_selection(")
end = admin.find('\n@router.callback_query(F.data.startswith("admin:games:draw:"))', start)
if start < 0 or end < 0:
    raise SystemExit("admin announcement block markers not found")
admin = admin[:start] + "\n" + admin[end:]

admin = replace_once(
    admin,
    '    await _announce_selection(cq, state)\n',
    '',
    'selection announcement call',
)
admin = replace_once(
    admin,
    '    await _announce_locked(cq, state)\n',
    '',
    'locked announcement call',
)
ADMIN_DRAW.write_text(admin, encoding="utf-8")

notifier = NOTIFIER.read_text(encoding="utf-8")

user_fn = notifier.find("async def _send_user_game_started_notice(")
if user_fn < 0:
    raise SystemExit("user game started function not found")

helper = '''def _game_start_draw_line(event: dict | None) -> str:\n    payload = _event_payload(event)\n    mode = str(payload.get("draw_mode") or "").upper()\n    interval = _to_int(payload.get("draw_interval_seconds"), 0)\n    if mode == "AUTO":\n        if interval > 0:\n            return f"⚡ اعلام اعداد: <b>خودکار</b> • هر <b>{interval} ثانیه</b>"\n        return "⚡ اعلام اعداد: <b>خودکار</b>"\n    if mode == "MANUAL":\n        return "🔢 اعلام اعداد: <b>دستی</b> • توسط ادمین"\n    return "🔢 اعلام اعداد: <b>ثبت نشده</b>"\n\n\n'''
if "def _game_start_draw_line(" not in notifier:
    notifier = notifier[:user_fn] + helper + notifier[user_fn:]

notifier = replace_once(
    notifier,
    "async def _send_user_game_started_notice(bot: Bot, *, game_id: int, report: dict) -> None:",
    "async def _send_user_game_started_notice(bot: Bot, *, game_id: int, report: dict, event: dict | None = None) -> None:",
    "user start notice signature",
)

user_fn = notifier.find("async def _send_user_game_started_notice(")
user_end = notifier.find("\n\nasync def ", user_fn + 1)
if user_end < 0:
    raise SystemExit("user start notice end not found")
user_seg = notifier[user_fn:user_end]
user_seg = replace_once(
    user_seg,
    '        f"🎮 بازی: <b>#{game_id}</b>\\n"\n',
    '        f"🎮 بازی: <b>#{game_id}</b>\\n"\n        f"{_game_start_draw_line(event)}\\n"\n',
    "public start draw line",
)
notifier = notifier[:user_fn] + user_seg + notifier[user_end:]

report_fn = notifier.find("async def _send_game_started_report(")
if report_fn < 0:
    raise SystemExit("game started report function not found")
report_end = notifier.find("\n\nasync def ", report_fn + 1)
if report_end < 0:
    raise SystemExit("game started report end not found")
report_seg = notifier[report_fn:report_end]
report_seg = replace_once(
    report_seg,
    '        f"🎮 بازی: <b>#{game_id}</b>\\n"\n',
    '        f"🎮 بازی: <b>#{game_id}</b>\\n"\n        f"{_game_start_draw_line(event)}\\n"\n',
    "admin report draw line",
)
report_seg = replace_once(
    report_seg,
    '        await _send_user_game_started_notice(bot, game_id=game_id, report=report)\n',
    '        await _send_user_game_started_notice(bot, game_id=game_id, report=report, event=event)\n',
    "public start event forwarding",
)
notifier = notifier[:report_fn] + report_seg + notifier[report_end:]

NOTIFIER.write_text(notifier, encoding="utf-8")
print("UNIFIED_GAME_START_ANNOUNCEMENTS_APPLIED")
