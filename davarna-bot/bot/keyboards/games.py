from aiogram.utils.keyboard import InlineKeyboardBuilder


def _fmt_int(n: int | str | None) -> str:
    try:
        return f"{int(n or 0):,}"
    except Exception:
        return str(n or 0)


def games_select_kb(
    game_counts: list[dict],
    *,
    page: int = 1,
    page_size: int = 5,
):
    kb = InlineKeyboardBuilder()

    if page_size < 1:
        page_size = 5

    total = len(game_counts)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start = (page - 1) * page_size
    end = start + page_size

    for item in game_counts[start:end]:
        game_id = int(item.get("game_id") or item.get("id") or 0)
        cnt = int(item.get("count") or 0)
        price = _fmt_int(item.get("card_price"))
        kb.button(text=f"🎮 بازی {game_id} | 💳 {price} | ({cnt} کارت)", callback_data=f"mycards:game:{game_id}")

    if total_pages > 1:
        if page > 1:
            kb.button(text="⬅️ قبلی", callback_data=f"mycards:games:page:{page-1}")
        if page < total_pages:
            kb.button(text="بعدی ➡️", callback_data=f"mycards:games:page:{page+1}")

    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)

    return kb.as_markup()
