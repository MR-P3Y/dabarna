from aiogram.utils.keyboard import InlineKeyboardBuilder

QTY_CHOICES = (1, 2, 5, 10)


def _fa_status(status: str | None) -> str:
    raw = (status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ACTIVE": "در حال اجرا",
        "ENDED": "پایان‌یافته",
    }
    return mapping.get(raw, "نامشخص")


def _fmt_int(n: int) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def games_list_kb(
    items: list[dict],
    *,
    offset: int,
    limit: int,
    has_more: bool,
    is_on_map: dict[int, bool] | None = None,
    show_notify_button: bool = True,
):
    kb = InlineKeyboardBuilder()
    shown_items = items[:10]
    is_on_map = is_on_map or {}

    for g in shown_items:
        gid = int(g.get("id"))
        price = int(g.get("card_price") or 0)
        status = _fa_status(str(g.get("status") or ""))

        kb.button(
            text=f"🎮 بازی #{gid} | 💳 {_fmt_int(price)} تومان | {status}",
            callback_data=f"buy:game:{gid}",
        )

        if show_notify_button:
            is_on = bool(is_on_map.get(gid))
            if is_on:
                kb.button(text=f"🔕 نوتیف بازی #{gid} خاموش", callback_data=f"notif:off:{gid}")
            else:
                kb.button(text=f"🔔 نوتیف بازی #{gid} روشن", callback_data=f"notif:on:{gid}")

    nav: list[tuple[str, str]] = []
    if offset > 0:
        nav.append(("⬅️ قبلی", f"buy:games:o:{max(0, offset - limit)}"))
    if has_more:
        nav.append(("بعدی ➡️", f"buy:games:o:{offset + limit}"))

    for t, cb in nav:
        kb.button(text=t, callback_data=cb)
    kb.button(text="⬅️ منو", callback_data="nav:menu")

    sizes: list[int] = []
    for _ in shown_items:
        sizes.append(1)
        if show_notify_button:
            sizes.append(1)
    if nav:
        sizes.append(len(nav))
    sizes.append(1)
    kb.adjust(*sizes)

    return kb.as_markup()


def qty_kb(game_id: int):
    kb = InlineKeyboardBuilder()
    for q in QTY_CHOICES:
        kb.button(text=f"🃏 {q} کارت", callback_data=f"buy:qty:{game_id}:{q}")
    kb.button(text="⬅️ بازگشت", callback_data="buy:games:o:0")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def confirm_kb(game_id: int, qty: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید خرید", callback_data=f"buy:confirm:{game_id}:{qty}")
    kb.button(text="⬅️ تغییر تعداد", callback_data=f"buy:game:{game_id}")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


def after_purchase_kb(game_id: int, *, is_notif_on: bool = False):
    kb = InlineKeyboardBuilder()
    if is_notif_on:
        notif_label = f"🔕 نوتیف بازی #{game_id} خاموش"
        notif_cb = f"notif:off:{game_id}"
    else:
        notif_label = f"🔔 نوتیف بازی #{game_id} روشن"
        notif_cb = f"notif:on:{game_id}"

    kb.button(text="🃏 کارت‌های من", callback_data="menu:mycards")
    kb.button(text=notif_label, callback_data=notif_cb)
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(2, 1)
    return kb.as_markup()
