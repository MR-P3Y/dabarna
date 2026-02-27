from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.common import back_to_menu_kb


def _fa_status(status: str | None) -> str:
    raw = (status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ENDED": "پایان‌یافته",
        "ACTIVE": "در حال اجرا",
    }
    return mapping.get(raw, "نامشخص")


def _fmt_int(n: int | str | None) -> str:
    try:
        return f"{int(n or 0):,}"
    except Exception:
        return str(n or 0)


def admin_games_list_kb(items: list[dict], *, status: str, offset: int, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    for g in items:
        gid = int(g.get("id"))
        st = _fa_status(str(g.get("status") or ""))
        price = _fmt_int(g.get("card_price"))
        topic_id = g.get("tg_topic_id")
        topic_tag = f" | 🧵{topic_id}" if topic_id is not None else ""
        kb.button(text=f"🎮 #{gid}{topic_tag} | {st} | 💳 {price}", callback_data=f"admin:games:view:{gid}:{status}:{offset}")

    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:list:{status}:{offset}")
    kb.button(text="🏆 کارت‌های برنده", callback_data="admin:games:winners:archive:0")
    kb.button(text="🆕 ایجاد/فعال‌سازی بازی گروه", callback_data=f"admin:games:ensure:{status}:{offset}")

    row: list[tuple[str, str]] = []
    if offset > 0:
        row.append(("⬅️ قبلی", f"admin:games:list:{status}:{max(0, offset - 5)}"))
    if has_next:
        row.append(("بعدی ➡️", f"admin:games:list:{status}:{offset + 5}"))
    for text, cb in row:
        kb.button(text=text, callback_data=cb)

    rows: list[int] = []
    if items:
        rows.extend([1] * len(items))
    rows.append(2)
    rows.append(1)
    if row:
        rows.append(len(row))
    kb.adjust(*rows)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_game_create_price_kb(*, status: str, offset: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو ایجاد بازی", callback_data=f"admin:games:create:cancel:{status}:{offset}")
    kb.button(text="⬅️ بازگشت به لیست", callback_data=f"admin:games:list:{status}:{offset}")
    kb.adjust(1, 1)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_game_create_topic_kb(*, status: str, offset: int, topics: list[tuple[str, int]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for title, topic_id in topics:
        kb.button(text=title, callback_data=f"admin:games:ensure:topic:{int(topic_id)}:{status}:{offset}")
    kb.button(text="⬅️ بازگشت به لیست", callback_data=f"admin:games:list:{status}:{offset}")
    rows = [1] * len(topics)
    rows.append(1)
    kb.adjust(*rows)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_game_close_reason_kb(*, game_id: int, status: str, offset: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="❌ لغو بستن بازی", callback_data="admin:games:close-lobby:cancel")
    kb.adjust(1)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_game_item_kb(
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
    if normalized == "RUNNING":
        kb.button(
            text="✅ در حال اجرا",
            callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}",
        )
    else:
        kb.button(
            text="▶️ شروع بازی",
            callback_data=f"admin:games:start:{int(game_id)}:{status}:{offset}",
        )
        if normalized == "LOBBY" and allow_close_lobby:
            kb.button(
                text="🛑 بستن بازی لابی",
                callback_data=f"admin:games:close-lobby:{int(game_id)}:{status}:{offset}",
            )

    kb.button(text="🔢 اعلام عدد", callback_data=f"admin:games:call:{int(game_id)}:{status}:{offset}")
    kb.button(text="↩️ بازگردانی آخرین شماره", callback_data=f"admin:games:undo:{int(game_id)}:{status}:{offset}")
    kb.button(text="🧾 گزارش بازی", callback_data=f"admin:games:report:{int(game_id)}:{status}:{offset}")
    kb.button(text="🏆 کارت‌های برنده", callback_data=f"admin:games:winners:{int(game_id)}:{status}:{offset}")
    kb.button(text="📡 مانیتور زنده", callback_data=f"admin:games:monitor:{int(game_id)}:{status}:{offset}")
    kb.button(text="🎥 تنظیم لینک لایو", callback_data=f"admin:games:live:set:{int(game_id)}:{status}:{offset}")
    kb.button(text="📣 ارسال لینک لایو", callback_data=f"admin:games:live:send:{int(game_id)}:{status}:{offset}")
    kb.button(text="🧹 حذف لینک لایو", callback_data=f"admin:games:live:clear:{int(game_id)}:{status}:{offset}")
    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:view:{int(game_id)}:{status}:{offset}")
    kb.button(text="⬅️ برگشت", callback_data=f"admin:games:list:{status}:{offset}")
    if normalized == "LOBBY" and allow_close_lobby:
        kb.adjust(2, 2, 2, 2, 2, 1, 1)
    else:
        kb.adjust(1, 2, 2, 2, 2, 1, 1)

    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_monitor_kb(*, game_id: int, status: str, offset: int, auto_on: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:monitor:refresh:{game_id}:{status}:{offset}")

    if auto_on:
        kb.button(text="⛔ توقف خودکار", callback_data=f"admin:games:monitor:auto:off:{game_id}:{status}:{offset}")
    else:
        kb.button(text="⏱ شروع خودکار", callback_data=f"admin:games:monitor:auto:on:{game_id}:{status}:{offset}")

    kb.button(text="⬅️ برگشت", callback_data=f"admin:games:view:{game_id}:{status}:{offset}")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def admin_winners_kb(*, game_id: int, status: str, offset: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:winners:{game_id}:{status}:{offset}")
    kb.button(text="⬅️ برگشت", callback_data=f"admin:games:view:{game_id}:{status}:{offset}")
    kb.adjust(1, 1)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()


def admin_winners_archive_kb(items: list[dict], *, offset: int, has_next: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    for g in items:
        gid = int(g.get("id"))
        col_count = int(g.get("col_count", 0) or 0)
        row_count = int(g.get("row_count", 0) or 0)
        price = _fmt_int(g.get("card_price"))
        badge = f"تورنا:{col_count} | تمام:{row_count}"
        kb.button(text=f"🏆 بازی #{gid} | 💳 {price} | {badge}", callback_data=f"admin:games:winners:{gid}:ENDED:{offset}")

    kb.button(text="🔄 تازه‌سازی", callback_data=f"admin:games:winners:archive:{offset}")

    nav_count = 0
    if offset > 0:
        kb.button(text="⬅️ قبلی", callback_data=f"admin:games:winners:archive:{max(0, offset - 5)}")
        nav_count += 1
    if has_next:
        kb.button(text="بعدی ➡️", callback_data=f"admin:games:winners:archive:{offset + 5}")
        nav_count += 1

    kb.button(text="⬅️ ادمین بازی", callback_data="admin:games")

    rows: list[int] = []
    if items:
        rows.extend([1] * len(items))
    rows.append(1)
    if nav_count > 0:
        rows.append(nav_count)
    rows.append(1)
    kb.adjust(*rows)
    kb.attach(InlineKeyboardBuilder.from_markup(back_to_menu_kb()))
    return kb.as_markup()
