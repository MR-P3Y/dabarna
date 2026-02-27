from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest
import asyncio

from bot.services.ui import panel
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.api_client import ApiClient, ApiError
from bot.services.retry import retry_async
from bot.services.card_cache import put_card, get_card
from bot.services.card_render import build_grid_text_from_numbers, render_grid_with_marks
from bot.services.game_cards_messages_cache import set_game_card_messages, CardMsgRef
from bot.keyboards.game_cards_control import game_cards_control_kb
from bot.keyboards.common import back_to_menu_kb
from bot.keyboards.games import games_select_kb
from bot.keyboards.card_detail import card_detail_kb
from bot.services.game_cards_messages_cache import get_game_card_messages

router = Router()
MYCARDS_GAMES_PAGE_SIZE = 5
MYCARDS_SCAN_PAGE_SIZE = 100
MYCARDS_SCAN_MAX_PAGES = 50
MYCARDS_ENDED_RETENTION_HOURS = 48


# --------------------------
# Keyboard: cards list + pagination
# --------------------------
def cards_list_kb(cards, page, total_pages, game_id: int):
    kb = InlineKeyboardBuilder()

    for c in cards[:8]:
        kb.button(
            text=f"🃏 کارت {c.get('id')} (بازی {c.get('game_id')})",
            callback_data=f"card:open:{c.get('id')}",
        )

    if page > 1:
        kb.button(text="⬅️ قبلی", callback_data=f"mycards:page:{page-1}:{game_id}")
    if page < total_pages:
        kb.button(text="بعدی ➡️", callback_data=f"mycards:page:{page+1}:{game_id}")

    kb.button(text="⬅️ انتخاب بازی", callback_data="menu:mycards")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


# --------------------------
# Helper: render list page
# --------------------------
def render_cards_list(game_id: int, data: dict) -> tuple[str, list[dict], int, int]:
    cards = data.get("cards") or []
    pg = data.get("pagination") or {}
    page = int(pg.get("page", 1))
    total_pages = int(pg.get("total_pages", 1))

    if not cards:
        return panel("کارت‌های من", f"برای بازی <b>{game_id}</b> هیچ کارتی پیدا نشد."), [], page, total_pages

    text = panel("کارت‌های من", f"بازی <b>{game_id}</b>\nبرای دیدن کارت، روی یکی از دکمه‌ها بزن 👇")
    return text, cards, page, total_pages


async def _collect_user_game_counts(
    api: ApiClient,
    tg_user_id: int,
    tg_username: str | None,
) -> list[dict]:
    counts: Counter[int] = Counter()
    latest_created_at: dict[int, datetime] = {}
    page = 1
    total_pages = 1

    while page <= total_pages and page <= MYCARDS_SCAN_MAX_PAGES:
        data = await api.bot_get_my_cards(
            tg_user_id,
            tg_username,
            page=page,
            page_size=MYCARDS_SCAN_PAGE_SIZE,
            game_id=None,
        )
        cards = data.get("cards") or []

        for c in cards:
            put_card(tg_user_id, c)
            gid = c.get("game_id")
            if gid is None:
                continue
            try:
                game_id = int(gid)
            except Exception:
                continue

            counts[game_id] += 1
            created_at = _parse_ts_utc(c.get("created_at"))
            if created_at is None:
                continue
            prev = latest_created_at.get(game_id)
            if prev is None or created_at > prev:
                latest_created_at[game_id] = created_at

        pg = data.get("pagination") or {}
        try:
            total_pages = max(1, int(pg.get("total_pages", total_pages)))
        except Exception:
            total_pages = max(total_pages, page)

        if not cards:
            break
        page += 1

    meta_cache: dict[int, dict[str, object]] = {}
    filtered: list[dict] = []
    for game_id, cnt in sorted(counts.items(), key=lambda x: x[0], reverse=True):
        if await _is_ended_game_expired(
            api=api,
            game_id=game_id,
            latest_card_created_at=latest_created_at.get(game_id),
            meta_cache=meta_cache,
        ):
            continue
        meta = await _get_game_meta_cached(api, game_id, meta_cache)
        card_price = 0
        if meta is not None:
            try:
                card_price = int(meta.get("card_price") or 0)
            except Exception:
                card_price = 0
        filtered.append({"game_id": game_id, "count": cnt, "card_price": card_price})

    return filtered


def _parse_ts_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except Exception:
            return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _get_game_meta_cached(
    api: ApiClient,
    game_id: int,
    meta_cache: dict[int, dict[str, object]],
) -> dict[str, object] | None:
    cached = meta_cache.get(game_id)
    if cached is not None:
        return cached

    try:
        game = await api.get_game(game_id)
    except ApiError:
        return None

    status = str((game or {}).get("status") or "").upper() or None
    try:
        card_price = int((game or {}).get("card_price") or 0)
    except Exception:
        card_price = 0

    meta: dict[str, object] = {"status": status, "card_price": card_price}
    meta_cache[game_id] = meta
    return meta


async def _is_ended_game_expired(
    *,
    api: ApiClient,
    game_id: int,
    latest_card_created_at: datetime | None,
    meta_cache: dict[int, dict[str, object]],
) -> bool:
    if latest_card_created_at is None:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(hours=MYCARDS_ENDED_RETENTION_HOURS)
    if latest_card_created_at >= cutoff:
        return False

    meta = await _get_game_meta_cached(api, game_id, meta_cache)
    status = str((meta or {}).get("status") or "").upper()
    return status == "ENDED"


def _mycards_games_text(page: int, total_pages: int, total_games: int) -> str:
    body = "اول بازی را انتخاب کن 👇\n\n"
    body += f"نمایش: <b>{MYCARDS_GAMES_PAGE_SIZE}</b> بازی آخر"
    body += "\n💳 قیمت هر کارت کنار هر بازی نمایش داده شده است."
    if total_games > MYCARDS_GAMES_PAGE_SIZE:
        body += f"\nصفحه: <b>{page}</b>/<b>{total_pages}</b> | کل بازی‌ها: <b>{total_games}</b>"
    body += f"\nبازی‌های پایان‌یافته بعد از <b>{MYCARDS_ENDED_RETENTION_HOURS}</b> ساعت بایگانی می‌شوند."
    return panel("کارت‌های من", body)


async def _show_mycards_games_selector(
    cq: CallbackQuery,
    game_counts: list[dict],
    *,
    page: int,
) -> None:
    total_games = len(game_counts)
    total_pages = max(1, (total_games + MYCARDS_GAMES_PAGE_SIZE - 1) // MYCARDS_GAMES_PAGE_SIZE)
    page = max(1, min(page, total_pages))

    await safe_edit_or_send(
        cq.message,
        _mycards_games_text(page, total_pages, total_games),
        reply_markup=games_select_kb(
            game_counts,
            page=page,
            page_size=MYCARDS_GAMES_PAGE_SIZE,
        ),
        parse_mode="HTML",
    )


def _mycards_archived_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ انتخاب بازی", callback_data="menu:mycards")
    kb.button(text="⬅️ منو", callback_data="nav:menu")
    kb.adjust(1)
    return kb.as_markup()


# ============================================================
# 1) entry: menu:mycards  ->  select game (only games user has cards in)
# ============================================================
@router.callback_query(F.data == "menu:mycards")
async def mycards_entry(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    try:
        game_counts = await _collect_user_game_counts(api, tg_user_id, tg_username)

        if not game_counts:
            await safe_edit_or_send(
                cq.message,
                panel("کارت‌های من", "هیچ کارتی پیدا نشد."),
                reply_markup=back_to_menu_kb(),
                parse_mode="HTML",
            )
            await cq.answer()
            return

        await _show_mycards_games_selector(cq, game_counts, page=1)
        await cq.answer()

    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()


# ============================================================
# 2) choose game -> show first page of cards for that game
# ============================================================
@router.callback_query(F.data.startswith("mycards:game:"))
async def mycards_by_game(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    game_id = int(cq.data.split(":")[-1])

    # 1) اول یک پیام کوتاه بده که “دارم کارت‌ها رو می‌فرستم”
    await safe_edit_or_send(
        cq.message,
        panel("کارت‌های من", f"بازی <b>{game_id}</b>\nدر حال ارسال کارت‌ها…"),
        parse_mode="HTML",
    )

    # 2) همه کارت‌های این بازی را بگیر (حداکثر 100)
    try:
        data = await api.bot_get_my_cards(tg_user_id, tg_username, page=1, page_size=100, game_id=game_id)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    cards = data.get("cards") or []

    if not cards:
        await cq.message.answer(panel("کارت‌های من", f"برای بازی <b>{game_id}</b> کارتی پیدا نشد."), parse_mode="HTML")
        await cq.answer()
        return

    latest_card_created_at = max(
        (ts for ts in (_parse_ts_utc(c.get("created_at")) for c in cards) if ts is not None),
        default=None,
    )
    if await _is_ended_game_expired(
        api=api,
        game_id=game_id,
        latest_card_created_at=latest_card_created_at,
        meta_cache={},
    ):
        await safe_edit_or_send(
            cq.message,
            panel(
                "کارت‌های من",
                f"بازی <b>{game_id}</b> بیش از <b>{MYCARDS_ENDED_RETENTION_HOURS}</b> ساعت از پایانش گذشته و کارت‌ها بایگانی شده‌اند.",
            ),
            reply_markup=_mycards_archived_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    # 3) فقط یک بار state را بگیر تا برای همه کارت‌ها ✅ درست شود
    called_numbers = []
    try:
        st = await api.get_game_state(game_id, last_n=200)
        called_numbers = st.get("called_numbers") or []
    except Exception:
        called_numbers = []

    # 4) هر کارت = یک پیام جدا + ذخیره message_id
    refs: list[CardMsgRef] = []
    for c in cards:
        put_card(tg_user_id, c)  # برای PV/refresh single اگر خواستی

        card_id = int(c.get("id"))
        numbers = c.get("numbers_json") or []
        grid_text = c.get("grid_text") or build_grid_text_from_numbers(numbers, cols=5)
        grid_html = render_grid_with_marks(grid_text, called_numbers)

        text = panel(
            f"کارت {card_id}",
            f"بازی: <b>{game_id}</b>\n"
            f"اثر انگشت کارت: <code>{c.get('fingerprint','—')[:12]}…</code>\n\n"
            f"<pre>{grid_html}</pre>\n"
            "✅ عددهای خوانده‌شده مشخص شده‌اند."
        )

        msg = await cq.message.answer(text, parse_mode="HTML")
        refs.append(CardMsgRef(card_id=card_id, message_id=msg.message_id))

    set_game_card_messages(tg_user_id, game_id, refs)

    # 5) پیام کنترل آخر
    await cq.message.answer(
        panel("بازی", f"بازی <b>{game_id}</b>\nکنترل‌ها 👇"),
        reply_markup=game_cards_control_kb(game_id),
        parse_mode="HTML"
    )
    await cq.answer()


@router.callback_query(F.data.startswith("mycards:games:page:"))
async def mycards_games_page(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    try:
        page = int((cq.data or "").split(":")[3])
    except Exception:
        await cq.answer("صفحه نامعتبر است.", show_alert=False)
        return

    try:
        game_counts = await _collect_user_game_counts(api, tg_user_id, tg_username)
        if not game_counts:
            await safe_edit_or_send(
                cq.message,
                panel("کارت‌های من", "هیچ کارتی پیدا نشد."),
                reply_markup=back_to_menu_kb(),
                parse_mode="HTML",
            )
            await cq.answer()
            return

        await _show_mycards_games_selector(cq, game_counts, page=page)
        await cq.answer()

    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()

# ============================================================
# 3) pagination within a selected game
# ============================================================
@router.callback_query(F.data.startswith("mycards:page:"))
async def mycards_page(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    _, _, page_s, gid_s = cq.data.split(":", 3)
    page = int(page_s)
    game_id = int(gid_s)

    try:
        data = await api.bot_get_my_cards(tg_user_id, tg_username, page=page, page_size=12, game_id=game_id)
        cards_raw = data.get("cards") or []
        latest_card_created_at = max(
            (ts for ts in (_parse_ts_utc(c.get("created_at")) for c in cards_raw) if ts is not None),
            default=None,
        )
        if cards_raw and await _is_ended_game_expired(
            api=api,
            game_id=game_id,
            latest_card_created_at=latest_card_created_at,
            meta_cache={},
        ):
            await safe_edit_or_send(
                cq.message,
                panel(
                    "کارت‌های من",
                    f"بازی <b>{game_id}</b> بیش از <b>{MYCARDS_ENDED_RETENTION_HOURS}</b> ساعت از پایانش گذشته و کارت‌ها بایگانی شده‌اند.",
                ),
                reply_markup=_mycards_archived_kb(),
                parse_mode="HTML",
            )
            await cq.answer()
            return

        text, cards, page, total_pages = render_cards_list(game_id, data)

        for c in cards:
            put_card(tg_user_id, c)

        await safe_edit_or_send(
            cq.message,
            text,
            reply_markup=cards_list_kb(cards, page, total_pages, game_id),
            parse_mode="HTML",
        )
        await cq.answer()

    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()


# ============================================================
# 4) open a card -> show grid with ✅ marks + actions
# ============================================================
@router.callback_query(F.data.startswith("card:open:"))
async def card_open(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    card_id = int(cq.data.split(":")[-1])
    card = get_card(tg_user_id, card_id)

    if not card:
        await safe_edit_or_send(
            cq.message,
            panel("کارت", "این کارت در کش نبود. لطفاً دوباره از لیست کارت‌ها انتخاب کن."),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    game_id = int(card.get("game_id"))
    numbers = card.get("numbers_json") or []
    grid_text = card.get("grid_text") or build_grid_text_from_numbers(numbers, cols=5)
    if not grid_text:
        await safe_edit_or_send(
            cq.message,
            panel("کارت", "این کارت داده کافی برای نمایش ندارد."),
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await cq.answer()
        return

    called_numbers: list[int] = []
    try:
        st = await api.get_game_state(game_id, last_n=200)
        called_numbers = st.get("called_numbers") or []
    except Exception:
        called_numbers = []

    grid_html = render_grid_with_marks(grid_text, called_numbers)

    text = panel(
        f"کارت {card_id}",
        f"بازی: <b>{game_id}</b>\n"
        f"اثر انگشت کارت: <code>{card.get('fingerprint','—')[:12]}…</code>\n\n"
        f"<pre>{grid_html}</pre>\n"
        "راهنما: عددهای خوانده‌شده با ✅ مشخص شده‌اند.",
    )

    await safe_edit_or_send(cq.message, text, reply_markup=card_detail_kb(card_id), parse_mode="HTML")
    await cq.answer()


# ============================================================
# 5) refresh card -> only update ✅ marks
# ============================================================
@router.callback_query(F.data.startswith("card:refresh:"))
async def card_refresh(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    card_id = int(cq.data.split(":")[-1])
    card = get_card(tg_user_id, card_id)

    if not card:
        await cq.answer("کارت پیدا نشد. از کارت‌های من دوباره وارد شو.", show_alert=False)
        return

    game_id = int(card.get("game_id"))
    numbers = card.get("numbers_json") or []
    grid_text = card.get("grid_text") or build_grid_text_from_numbers(numbers, cols=5)
    if not grid_text:
        await cq.answer("داده کافی برای نمایش کارت نیست.", show_alert=False)
        return

    called_numbers: list[int] = []
    try:
        st = await api.get_game_state(game_id, last_n=200)
        called_numbers = st.get("called_numbers") or []
    except Exception:
        called_numbers = []

    grid_html = render_grid_with_marks(grid_text, called_numbers)

    text = panel(
        f"کارت {card_id}",
        f"بازی: <b>{game_id}</b>\n"
        f"اثر انگشت کارت: <code>{card.get('fingerprint','—')[:12]}…</code>\n\n"
        f"<pre>{grid_html}</pre>\n"
        "راهنما: عددهای خوانده‌شده با ✅ مشخص شده‌اند.",
    )

    await safe_edit_or_send(cq.message, text, reply_markup=card_detail_kb(card_id), parse_mode="HTML")
    await cq.answer("به‌روزرسانی شد ✅", show_alert=False)


# ============================================================
# 6) send card to PV (safe + retry)
# ============================================================
@router.callback_query(F.data.startswith("card:pv:"))
async def card_send_pv(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    card_id = int(cq.data.split(":")[-1])
    card = get_card(tg_user_id, card_id)

    if not card:
        await cq.answer("کارت پیدا نشد.", show_alert=False)
        return

    game_id = int(card.get("game_id"))
    numbers = card.get("numbers_json") or []
    grid_text = card.get("grid_text") or build_grid_text_from_numbers(numbers, cols=5)
    if not grid_text:
        await cq.answer("داده کافی برای نمایش کارت نیست.", show_alert=False)
        return

    called_numbers: list[int] = []
    try:
        st = await api.get_game_state(game_id, last_n=200)
        called_numbers = st.get("called_numbers") or []
    except Exception:
        called_numbers = []

    grid_html = render_grid_with_marks(grid_text, called_numbers)
    text = panel(
        f"کارت {card_id}",
        f"بازی: <b>{game_id}</b>\n\n"
        f"<pre>{grid_html}</pre>\n"
        "✅ عددهای خوانده‌شده مشخص شده‌اند.",
    )

    try:
        await retry_async(
            lambda: cq.bot.send_message(chat_id=tg_user_id, text=text, parse_mode="HTML"),
            attempts=3,
            delay_sec=1.0,
        )
        await cq.answer("به پیام خصوصی ارسال شد ✅", show_alert=False)
    except TelegramNetworkError:
        await cq.answer("اینترنت قطع شد؛ دوباره تلاش کن.", show_alert=False)
    except Exception:
        await cq.answer("خطا در ارسال پیام خصوصی.", show_alert=False)


@router.callback_query(F.data.startswith("mycards:refresh_all:"))
async def mycards_refresh_all(cq: CallbackQuery, api: ApiClient, tg_user_id: int, tg_username: str | None = None):
    game_id = int(cq.data.split(":")[-1])

    refs = get_game_card_messages(tg_user_id, game_id)
    if not refs:
        await cq.answer("چیزی برای به‌روزرسانی پیدا نشد. دوباره بازی را انتخاب کن.", show_alert=False)
        return

    # جواب بدی تا کاربر دوباره نزنه
    await cq.answer("دارم کارت‌ها رو تازه می‌کنم ⏳", show_alert=False)

    # state فقط یک بار
    called_numbers = []
    try:
        st = await api.get_game_state(game_id, last_n=200)
        called_numbers = st.get("called_numbers") or []
    except Exception:
        called_numbers = []

    # هر پیام کارت را edit کن با rate limiting
    updated = 0
    for ref in refs:
        card = get_card(tg_user_id, ref.card_id)
        if not card:
            continue

        numbers = card.get("numbers_json") or []
        grid_text = card.get("grid_text") or build_grid_text_from_numbers(numbers, cols=5)
        grid_html = render_grid_with_marks(grid_text, called_numbers)

        text = panel(
            f"کارت {ref.card_id}",
            f"بازی: <b>{game_id}</b>\n"
            f"اثر انگشت کارت: <code>{card.get('fingerprint','—')[:12]}…</code>\n\n"
            f"<pre>{grid_html}</pre>\n"
            "✅ عددهای خوانده‌شده مشخص شده‌اند."
        )

        try:
            await cq.bot.edit_message_text(
                chat_id=tg_user_id,
                message_id=ref.message_id,
                text=text,
                parse_mode="HTML",
            )
            updated += 1
            # Rate limiting: 0.2 ثانیه بین هر پیام (تا 5 بروزرسانی در ثانیه)
            await asyncio.sleep(0.2)
        except TelegramBadRequest:
            # مثلا "message is not modified"
            pass
        except TelegramNetworkError:
            pass
        except Exception:
            pass

    # پیام نهایی
    try:
        await cq.bot.send_message(
            chat_id=tg_user_id,
            text=f"به‌روزرسانی شد ✅ ({updated} کارت)",
        )
    except Exception:
        pass
