from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def _fa_status(status: str | None) -> str:
    raw = (status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ACTIVE": "در حال اجرا",
        "ENDED": "پایان‌یافته",
    }
    return mapping.get(raw, "نامشخص")


def _fmt_int(n: int | str | None) -> str:
    try:
        return f"{int(n or 0):,}"
    except Exception:
        return str(n or 0)


def active_games_list_kb(
    items: list[dict],
    *,
    offset: int,
    limit: int,
    has_more: bool,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    for g in items:
        gid = int(g.get("id"))
        status_fa = _fa_status(str(g.get("status") or ""))
        price = _fmt_int(g.get("card_price"))
        kb.button(
            text=f"🎮 بازی #{gid} | {status_fa} | 💳 {price}",
            callback_data=f"games:view:{gid}:{offset}",
        )

    if offset > 0:
        kb.button(text="⬅️ قبلی", callback_data=f"games:list:{max(0, offset - limit)}")
    if has_more:
        kb.button(text="بعدی ➡️", callback_data=f"games:list:{offset + limit}")

    kb.button(text="🔄 تازه‌سازی", callback_data=f"games:list:{offset}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


def active_game_detail_kb(*, game_id: int, offset: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 تازه‌سازی", callback_data=f"games:refresh:{game_id}:{offset}")
    kb.button(text="🃏 کارت‌های من در این بازی", callback_data=f"mycards:game:{game_id}")
    kb.button(text="⬅️ لیست بازی‌ها", callback_data=f"games:list:{offset}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()
