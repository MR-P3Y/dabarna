from __future__ import annotations

import asyncio
import logging
import time
from html import escape as html_escape
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from bot.config import settings
from bot.services.api_client import ApiClient
from bot.services.admin_topics import ensure_topic_rules, forum_enabled, now_stamp, send_to_topic
from bot.services.user_topics import (
    game_topic_title as user_game_topic_title,
    send_to_game_topic as send_to_user_game_topic,
    send_to_topic as send_to_user_topic,
)
from bot.services.notify_store import (
    get_event_marker,
    get_last_seen_count,
    get_meta_marker,
    get_subscribers,
    list_tracked_game_ids,
    set_event_marker,
    set_last_seen_count,
    set_meta_marker,
    unsubscribe,
)
from bot.services.tg_display import resolve_tg_identity
from bot.services.ui import panel

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SendJob:
    game_id: int
    user_id: int
    text: str


@dataclass(slots=True)
class _SendStats:
    processed: int = 0
    ok: int = 0
    dead_fail: int = 0
    transient_fail: int = 0
    retry_after_hits: int = 0


def _fmt_last(nums: list[int], n: int = 10) -> str:
    tail = nums[-n:] if len(nums) > n else nums
    return "، ".join(str(x) for x in tail)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    out: list[int] = []
    for v in values:
        try:
            out.append(int(v))
        except Exception:
            continue
    return out


def _latest_event(events: list[dict], kind: str) -> dict | None:
    for ev in events or []:
        if str((ev or {}).get("kind") or "").strip().upper() == kind:
            return ev
    return None


def _event_payload(event: dict | None) -> dict[str, Any]:
    payload = (event or {}).get("payload_json")
    return payload if isinstance(payload, dict) else {}


def _event_created_ts(event: dict | None) -> float | None:
    raw = str((event or {}).get("created_at") or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return float(dt.timestamp())


def _is_recent_event_for_runtime(event: dict | None, runtime_started_ts: float, *, skew_sec: float = 3.0) -> bool:
    created_ts = _event_created_ts(event)
    if created_ts is None:
        return False
    return created_ts >= (runtime_started_ts - float(skew_sec))


def _group_cards_by_tg_user(
    tg_user_ids: list[int],
    card_ids: list[int],
    amounts_by_card: list[int],
) -> dict[int, list[tuple[int, int]]]:
    out: dict[int, list[tuple[int, int]]] = {}
    if not tg_user_ids:
        return out

    for idx, tg_uid in enumerate(tg_user_ids):
        if tg_uid <= 0:
            continue
        card_id = card_ids[idx] if idx < len(card_ids) else 0
        amount = amounts_by_card[idx] if idx < len(amounts_by_card) else 0
        out.setdefault(int(tg_uid), []).append((int(card_id), int(amount)))
    return out


def _fmt_cards(items: list[tuple[int, int]]) -> str:
    cards = [str(card_id) for card_id, _ in items if card_id > 0]
    return ", ".join(cards) if cards else "—"


async def _fmt_winner_rows(bot: Bot, grouped: dict[int, list[tuple[int, int]]]) -> str:
    if not grouped:
        return "—"

    lines: list[str] = []
    for tg_uid in sorted(grouped):
        cards = grouped.get(tg_uid) or []
        amount = sum(max(0, amt) for _, amt in cards)
        amount_txt = str(amount) if amount > 0 else "—"
        display_name = await resolve_tg_identity(bot, int(tg_uid))
        lines.append(
            f"• <b>{html_escape(display_name)}</b> | کارت: <code>{_fmt_cards(cards)}</code> | مبلغ: <b>{amount_txt}</b>"
        )
    return "\n".join(lines)


def _winners_topic_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 آرشیو کارت‌های برنده", callback_data="admin:games:winners:archive:0")
    kb.button(text="🛠 ادمین بازی", callback_data="admin:games")
    kb.adjust(1)
    return kb.as_markup()


def _games_topic_kb(game_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 ادمین بازی", callback_data="admin:games")
    kb.button(text="📡 مانیتور بازی", callback_data=f"admin:games:monitor:{int(game_id)}:LOBBY|RUNNING|ENDED:0")
    kb.button(text="🏆 آرشیو کارت‌های برنده", callback_data="admin:games:winners:archive:0")
    kb.adjust(1)
    return kb.as_markup()


def _event_time_text(event: dict | None) -> str:
    dt = _parse_dt((event or {}).get("created_at"))
    if dt is None:
        return now_stamp()
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def _called_numbers_from_report(report: dict) -> list[int]:
    out: list[int] = []
    for item in (report.get("called_numbers") or []):
        if isinstance(item, dict):
            n = _to_int(item.get("number"), 0)
        else:
            n = _to_int(item, 0)
        if n > 0:
            out.append(n)
    return out


def _purchase_card_ids_from_events(events: list[dict]) -> list[int]:
    card_ids: set[int] = set()
    for ev in events or []:
        if str((ev or {}).get("kind") or "").strip().upper() != "CARDS_PURCHASED":
            continue
        payload = _event_payload(ev)
        for x in payload.get("card_ids") or []:
            n = _to_int(x, 0)
            if n > 0:
                card_ids.add(n)
    return sorted(card_ids)


def _fmt_int_list(values: list[int], *, max_items: int = 120) -> str:
    if not values:
        return "—"
    if len(values) <= max_items:
        return ", ".join(str(x) for x in values)
    head = ", ".join(str(x) for x in values[:max_items])
    return f"{head}, ... (مابقی حذف شد)"


def _fa_game_status(status: str | None) -> str:
    raw = str(status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ACTIVE": "در حال اجرا",
        "ENDED": "پایان‌یافته",
    }
    return mapping.get(raw, "نامشخص")


def _end_reason_fa(reason: str | None) -> str:
    raw = str(reason or "").strip().upper()
    mapping = {
        "ROW_WIN": "برد تمام",
        "COL_WIN": "برد تورنا",
        "MANUAL_END": "پایان دستی",
        "LOBBY_CLOSED": "بسته شدن لابی",
    }
    return mapping.get(raw, "نامشخص")


def _meta_int(key: str, default: int = 0) -> int:
    try:
        return int(get_meta_marker(key, str(int(default))) or default)
    except Exception:
        return int(default)


def _set_meta_int(key: str, value: int) -> None:
    set_meta_marker(key, str(int(value)))


def _throttle_alert(meta_key: str, *, window_sec: int = 180) -> bool:
    now_ts = int(time.time())
    prev = _meta_int(meta_key, 0)
    if prev > 0 and (now_ts - prev) < int(window_sec):
        return False
    _set_meta_int(meta_key, now_ts)
    return True


async def _send_operational_alert(bot: Bot, *, title: str, detail: str, throttle_key: str) -> None:
    if not _throttle_alert(throttle_key):
        return
    text = panel(
        "هشدار فوری",
        "#فوری #پایش_عملیاتی\n"
        f"🕒 زمان: <code>{now_stamp()}</code>\n"
        f"🔎 نوع: <b>{title}</b>\n"
        f"جزئیات: <code>{detail}</code>",
    )
    await send_to_topic(bot, name="alerts", text=text, parse_mode="HTML", disable_notification=False)


def _is_user_forum_game(report: dict) -> bool:
    target_group_id = settings.USER_FORUM_CHAT_ID or settings.BOT_JOIN_GROUP_ID
    if target_group_id is None:
        return False
    game = report.get("game") or {}
    game_group_id = _to_int(game.get("tg_group_id"), 0)
    return game_group_id != 0 and game_group_id == int(target_group_id)


async def _send_user_game_started_notice(bot: Bot, *, game_id: int, report: dict) -> None:
    if not _is_user_forum_game(report):
        return
    game = report.get("game") or {}
    purchases = report.get("purchases") or {}
    game_topic_id = _to_int(game.get("tg_topic_id"), 0)
    topic_label = user_game_topic_title(game_topic_id if game_topic_id > 0 else None)

    text = panel(
        "اطلاعیه شروع بازی",
        "#اطلاعیه #شروع_بازی\n"
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"🧵 دسته بازی: <b>{topic_label}</b>\n"
        f"💳 قیمت هر کارت: <b>{_fmt_amount(_to_int(game.get('card_price'), 0))}</b>\n"
        f"🃏 کارت‌های فروخته‌شده: <b>{_fmt_amount(_to_int(purchases.get('cards_sold'), 0))}</b>\n"
        f"🎁 جایزه کل فعلی: <b>{_fmt_amount(_to_int(game.get('prize_pool'), 0))}</b>\n"
        "🔔 بازی شروع شد؛ اعداد زنده در تاپیک «اعداد اعلام‌شده (زنده)» اعلام می‌شود.",
    )

    await send_to_user_topic(bot, name="announce", text=text, parse_mode="HTML", disable_notification=False)
    await send_to_user_game_topic(
        bot,
        game_topic_id=game_topic_id if game_topic_id > 0 else None,
        text=text,
        parse_mode="HTML",
        disable_notification=False,
    )


async def _send_user_game_created_notice(bot: Bot, *, game_id: int, report: dict, event: dict) -> None:
    if not _is_user_forum_game(report):
        return
    game = report.get("game") or {}
    game_topic_id = _to_int(game.get("tg_topic_id"), 0)
    topic_label = user_game_topic_title(game_topic_id if game_topic_id > 0 else None)

    text = panel(
        "بازی جدید آماده خرید",
        "#اطلاعیه #بازی_جدید\n"
        f"🕒 زمان ایجاد: <code>{_event_time_text(event)}</code>\n"
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"🧵 دسته بازی: <b>{topic_label}</b>\n"
        f"💳 قیمت هر کارت: <b>{_fmt_amount(_to_int(game.get('card_price'), 0))}</b>\n"
        "🛒 خرید کارت برای این بازی باز است.",
    )

    await send_to_user_topic(bot, name="announce", text=text, parse_mode="HTML", disable_notification=False)
    await send_to_user_game_topic(
        bot,
        game_topic_id=game_topic_id if game_topic_id > 0 else None,
        text=text,
        parse_mode="HTML",
        disable_notification=False,
    )


async def _send_user_game_ended_notice(bot: Bot, *, game_id: int, report: dict, end_reason: str | None) -> None:
    if not _is_user_forum_game(report):
        return
    game = report.get("game") or {}
    called = _called_numbers_from_report(report)
    last = called[-1] if called else None
    game_topic_id = _to_int(game.get("tg_topic_id"), 0)
    topic_label = user_game_topic_title(game_topic_id if game_topic_id > 0 else None)

    text = panel(
        "نتیجه نهایی بازی",
        "#نتایج #پایان_بازی\n"
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"🧵 دسته بازی: <b>{topic_label}</b>\n"
        f"📌 دلیل پایان: <b>{_end_reason_fa(end_reason)}</b>\n"
        f"🔢 تعداد اعداد خوانده‌شده: <b>{_fmt_amount(len(called))}</b>\n"
        f"📍 آخرین عدد: <b>{last if last is not None else '—'}</b>\n"
        f"💳 قیمت کارت: <b>{_fmt_amount(_to_int(game.get('card_price'), 0))}</b>\n"
        f"🎁 جایزه کل: <b>{_fmt_amount(_to_int(game.get('prize_pool'), 0))}</b>",
    )

    await send_to_user_topic(bot, name="results", text=text, parse_mode="HTML", disable_notification=False)
    await send_to_user_game_topic(
        bot,
        game_topic_id=game_topic_id if game_topic_id > 0 else None,
        text=text,
        parse_mode="HTML",
        disable_notification=True,
    )


async def _send_user_live_number_notice(
    bot: Bot,
    *,
    game_id: int,
    game_topic_id: int | None,
    number: int,
    called_numbers: list[int],
) -> None:
    tail = _fmt_last(called_numbers, 10)
    text = panel(
        "اعداد اعلام‌شده (زنده)",
        "#اعداد_زنده\n"
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"🧵 دسته بازی: <b>{user_game_topic_title(game_topic_id)}</b>\n"
        f"🔢 عدد جدید: <b>{number}</b>\n"
        f"🧾 آخرین ۱۰ عدد: {tail}",
    )
    await send_to_user_topic(bot, name="live", text=text, parse_mode="HTML", disable_notification=True)


async def _send_game_report_topic(
    bot: Bot,
    *,
    game_id: int,
    text: str,
) -> None:
    sent_to_topic = await send_to_topic(
        bot,
        name="game_audit",
        text=text,
        reply_markup=_games_topic_kb(game_id),
        parse_mode="HTML",
    )
    if sent_to_topic:
        return

    if not bool(settings.ADMIN_TOPIC_ENABLE_DM_FALLBACK):
        return

    admin_receivers = sorted(int(uid) for uid in settings.admin_ids if int(uid) > 0)
    for admin_uid in admin_receivers:
        try:
            await bot.send_message(
                chat_id=int(admin_uid),
                text=text,
                parse_mode="HTML",
                reply_markup=_games_topic_kb(game_id),
            )
        except Exception:
            continue


async def _send_game_started_report(bot: Bot, *, game_id: int, report: dict, event: dict) -> None:
    g = report.get("game") or {}
    purchases = report.get("purchases") or {}
    events = report.get("events") or []

    cards_sold = _to_int(purchases.get("cards_sold"), 0)
    purchases_count = _to_int(purchases.get("purchases_count"), 0)
    sales_total = _to_int(purchases.get("sales_total"), 0)
    sold_amount = _to_int(g.get("sold_amount"), 0)
    prize_pool = _to_int(g.get("prize_pool"), 0)
    col_prize = _to_int(g.get("col_prize_amount"), 0)
    row_prize = _to_int(g.get("row_prize_amount"), 0)
    card_price = _to_int(g.get("card_price"), 0)

    sold_card_ids = _purchase_card_ids_from_events(events)
    sold_cards_text = _fmt_int_list(sold_card_ids, max_items=160)
    coverage_note = ""
    if cards_sold > 0 and len(sold_card_ids) < cards_sold:
        coverage_note = (
            "\nℹ️ نمایش شناسه کارت‌ها بر اساس رخدادهای ثبت‌شده است و ممکن است بخشی از کارت‌های خیلی قدیمی در این گزارش نباشند."
        )

    text = panel(
        "شروع بازی",
        "#گزارش_بازی #شروع_بازی\n"
        f"🕒 زمان شروع: <code>{_event_time_text(event)}</code>\n"
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"وضعیت: <b>{_fa_game_status(str(g.get('status') or 'RUNNING'))}</b>\n\n"
        f"💳 قیمت هر کارت: <b>{_fmt_amount(card_price)}</b>\n"
        f"🧾 تعداد خریدها: <b>{_fmt_amount(purchases_count)}</b>\n"
        f"🃏 تعداد کارت فروخته‌شده: <b>{_fmt_amount(cards_sold)}</b>\n"
        f"💰 مبلغ فروش: <b>{_fmt_amount(max(sales_total, sold_amount))}</b>\n"
        f"🎁 جایزه کل: <b>{_fmt_amount(prize_pool)}</b>\n"
        f"🏆 جایزه برد تورنا: <b>{_fmt_amount(col_prize)}</b>\n"
        f"🏁 جایزه برد تمام: <b>{_fmt_amount(row_prize)}</b>\n\n"
        f"🪪 کارت‌های فروخته‌شده: <code>{sold_cards_text}</code>"
        f"{coverage_note}",
    )
    await _send_game_report_topic(bot, game_id=game_id, text=text)
    with suppress(Exception):
        await _send_user_game_started_notice(bot, game_id=game_id, report=report)


async def _send_game_ended_report(bot: Bot, *, game_id: int, report: dict, event: dict) -> None:
    g = report.get("game") or {}
    purchases = report.get("purchases") or {}
    events = report.get("events") or []
    payload = _event_payload(event)

    called = _called_numbers_from_report(report)
    last_number = called[-1] if called else None

    col_users = _as_int_list(g.get("col_winner_user_ids"))
    row_users = _as_int_list(g.get("row_winner_user_ids"))
    col_cards = _as_int_list(g.get("col_winner_card_ids"))
    row_cards = _as_int_list(g.get("row_winner_card_ids"))

    col_event = _latest_event(events, "PRIZE_COL")
    row_event = _latest_event(events, "PRIZE_ROW")
    col_paid_total = _to_int(_event_payload(col_event).get("amount_total"), 0)
    row_paid_total = _to_int(_event_payload(row_event).get("amount_total"), 0)

    text = panel(
        "پایان بازی",
        "#گزارش_بازی #پایان_بازی\n"
        f"🕒 زمان پایان: <code>{_event_time_text(event)}</code>\n"
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"📌 دلیل پایان: <b>{_end_reason_fa(payload.get('end_reason'))}</b>\n\n"
        f"💳 قیمت هر کارت: <b>{_fmt_amount(_to_int(g.get('card_price'), 0))}</b>\n"
        f"🧾 تعداد خریدها: <b>{_fmt_amount(_to_int(purchases.get('purchases_count'), 0))}</b>\n"
        f"🃏 تعداد کارت فروخته‌شده: <b>{_fmt_amount(_to_int(purchases.get('cards_sold'), 0))}</b>\n"
        f"💰 مبلغ بازی (فروش): <b>{_fmt_amount(_to_int(g.get('sold_amount'), 0))}</b>\n"
        f"🎁 جایزه کل: <b>{_fmt_amount(_to_int(g.get('prize_pool'), 0))}</b>\n"
        f"🏆 جایزه تورنا (تعریف‌شده/پرداخت): <b>{_fmt_amount(_to_int(g.get('col_prize_amount'), 0))}</b> / <b>{_fmt_amount(col_paid_total)}</b>\n"
        f"🏁 جایزه تمام (تعریف‌شده/پرداخت): <b>{_fmt_amount(_to_int(g.get('row_prize_amount'), 0))}</b> / <b>{_fmt_amount(row_paid_total)}</b>\n\n"
        f"👥 برندگان تورنا: <b>{_fmt_amount(len(set(col_users)))}</b> | کارت: <b>{_fmt_amount(len(set(col_cards)))}</b>\n"
        f"👥 برندگان تمام: <b>{_fmt_amount(len(set(row_users)))}</b> | کارت: <b>{_fmt_amount(len(set(row_cards)))}</b>\n"
        f"🔢 تعداد اعداد خوانده‌شده: <b>{_fmt_amount(len(called))}</b>\n"
        f"📍 آخرین عدد: <b>{last_number if last_number is not None else '—'}</b>\n\n"
        f"🧾 اعداد خوانده‌شده به ترتیب نوبت:\n<code>{_fmt_int_list(called, max_items=200)}</code>",
    )
    await _send_game_report_topic(bot, game_id=game_id, text=text)
    with suppress(Exception):
        await _send_user_game_ended_notice(
            bot,
            game_id=game_id,
            report=report,
            end_reason=str(payload.get("end_reason") or ""),
        )

def _fmt_amount(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except Exception:
        return str(value or 0)


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _oldest_pending_info(items: list[dict]) -> tuple[int, int]:
    oldest_dt: datetime | None = None
    oldest_id = 0
    for it in items:
        dt = _parse_dt(it.get("created_at"))
        if dt is None:
            continue
        if oldest_dt is None or dt < oldest_dt:
            oldest_dt = dt
            oldest_id = _to_int(it.get("id"), 0)
    if oldest_dt is None:
        return 0, 0
    minutes = int((datetime.now(timezone.utc) - oldest_dt).total_seconds() // 60)
    return oldest_id, max(0, minutes)


async def _send_admin_sla_alert(
    bot: Bot,
    *,
    kind: str,
    count: int,
    oldest_id: int,
    oldest_minutes: int,
    threshold_minutes: int,
) -> None:
    if not forum_enabled():
        return

    kind_title = "واریز" if kind == "deposit" else "برداشت"
    tag = "#واریز" if kind == "deposit" else "#برداشت"
    text = panel(
        "هشدار تاخیر بررسی",
        "#فوری #تاخیر_بررسی " + tag + "\n"
        f"🕒 زمان: <code>{now_stamp()}</code>\n"
        f"نوع درخواست: <b>{kind_title}</b>\n"
        f"تعداد در انتظار: <b>{count}</b>\n"
        f"قدیمی‌ترین شناسه: <b>{oldest_id if oldest_id > 0 else '—'}</b>\n"
        f"زمان انتظار قدیمی‌ترین: <b>{oldest_minutes}</b> دقیقه\n"
        f"حد مجاز تنظیم‌شده: <b>{threshold_minutes}</b> دقیقه\n\n"
        "لطفا بررسی را در اولویت قرار دهید.",
    )
    await send_to_topic(bot, name="alerts", text=text, parse_mode="HTML", disable_notification=False)


async def _send_admin_summary(
    bot: Bot,
    *,
    title: str,
    tag: str,
    pending_deposits: list[dict],
    pending_withdraws: list[dict],
    active_games_count: int,
    lobby_games_count: int,
) -> None:
    if not forum_enabled():
        return

    dep_total = sum(max(0, _to_int(it.get("amount"), 0)) for it in pending_deposits)
    wdr_total = sum(max(0, _to_int(it.get("amount"), 0)) for it in pending_withdraws)
    dep_old_id, dep_old_min = _oldest_pending_info(pending_deposits)
    wdr_old_id, wdr_old_min = _oldest_pending_info(pending_withdraws)

    text = panel(
        title,
        f"{tag} #ادمین\n"
        f"🕒 زمان: <code>{now_stamp()}</code>\n\n"
        f"📥 واریزهای در انتظار: <b>{len(pending_deposits)}</b>\n"
        f"💵 مجموع مبلغ واریزهای در انتظار: <b>{_fmt_amount(dep_total)}</b>\n"
        f"قدیمی‌ترین واریز: <b>{dep_old_id if dep_old_id > 0 else '—'}</b> | <b>{dep_old_min}</b> دقیقه\n\n"
        f"📤 برداشت‌های در انتظار: <b>{len(pending_withdraws)}</b>\n"
        f"💵 مجموع مبلغ برداشت‌های در انتظار: <b>{_fmt_amount(wdr_total)}</b>\n"
        f"قدیمی‌ترین برداشت: <b>{wdr_old_id if wdr_old_id > 0 else '—'}</b> | <b>{wdr_old_min}</b> دقیقه\n\n"
        f"🎮 بازی‌های در حال اجرا: <b>{active_games_count}</b>\n"
        f"🕹 بازی‌های در انتظار شروع: <b>{lobby_games_count}</b>",
    )
    await send_to_topic(bot, name="general", text=text, parse_mode="HTML")


def _admin_local_now() -> datetime:
    tz_name = str(settings.ADMIN_TOPIC_TIMEZONE or "Asia/Tehran").strip() or "Asia/Tehran"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def _daily_revenue_window(now_local: datetime) -> tuple[datetime, datetime]:
    trigger_hour = max(0, min(23, int(settings.ADMIN_TOPIC_DAILY_REVENUE_HOUR_LOCAL or 15)))
    end_local = now_local.replace(hour=trigger_hour, minute=0, second=0, microsecond=0)
    if now_local < end_local:
        end_local -= timedelta(days=1)
    start_local = end_local - timedelta(days=1)
    return start_local, end_local


async def _send_income_daily_summary(bot: Bot, api: ApiClient, *, now_local: datetime) -> None:
    if not forum_enabled():
        return

    start_local, end_local = _daily_revenue_window(now_local)
    range_to = end_local - timedelta(seconds=1)
    from_at = start_local.strftime("%Y-%m-%d %H:%M:%S")
    to_at = range_to.strftime("%Y-%m-%d %H:%M:%S")

    try:
        summary = await api.admin_get_games_sales_summary(from_at=from_at, to_at=to_at)
    except Exception:
        return

    games_count = _to_int(summary.get("games_count"), 0)
    purchases_count = _to_int(summary.get("purchases_count"), 0)
    cards_sold = _to_int(summary.get("cards_sold"), 0)
    sales_total = _to_int(summary.get("sales_total"), 0)
    commission_total = _to_int(summary.get("commission_total"), 0)
    prize_pool_total = _to_int(summary.get("prize_pool_total"), 0)
    row_users = _to_int(summary.get("row_winner_users_count"), 0)
    row_cards = _to_int(summary.get("row_winner_cards_count"), 0)
    col_users = _to_int(summary.get("col_winner_users_count"), 0)
    col_cards = _to_int(summary.get("col_winner_cards_count"), 0)

    text = panel(
        "گزارش درآمد روزانه",
        "#درآمد #گزارش_روزانه\n"
        f"🕒 زمان ارسال: <code>{now_local.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        f"🗓 از: <code>{from_at}</code>\n"
        f"🗓 تا: <code>{to_at}</code>\n\n"
        f"🎮 تعداد بازی‌های بازه: <b>{_fmt_amount(games_count)}</b>\n"
        f"🧾 تعداد خرید کارت: <b>{_fmt_amount(purchases_count)}</b>\n"
        f"🎫 تعداد کارت فروخته‌شده: <b>{_fmt_amount(cards_sold)}</b>\n"
        f"💰 فروش کارت: <b>{_fmt_amount(sales_total)}</b>\n"
        f"🤖 کمیسیون ربات: <b>{_fmt_amount(commission_total)}</b>\n"
        f"🎁 مجموع جایزه (بعد از کمیسیون): <b>{_fmt_amount(prize_pool_total)}</b>\n\n"
        f"🏁 برندگان تمام: <b>{_fmt_amount(row_users)}</b> کاربر | <b>{_fmt_amount(row_cards)}</b> کارت\n"
        f"🏆 برندگان تورنا: <b>{_fmt_amount(col_users)}</b> کاربر | <b>{_fmt_amount(col_cards)}</b> کارت",
    )
    await send_to_topic(bot, name="income", text=text, parse_mode="HTML")


async def _admin_forum_audit(bot: Bot, api: ApiClient) -> None:
    if not forum_enabled():
        return

    try:
        dep = await api.admin_list_deposits(status="PENDING_REVIEW", limit=200, offset=0)
        pending_deposits = dep.get("items") or []
    except Exception:
        pending_deposits = []

    try:
        wdr = await api.admin_list_withdraws(status="PENDING", limit=200, offset=0)
        pending_withdraws = wdr.get("items") or []
    except Exception:
        pending_withdraws = []

    active_games_count = 0
    lobby_games_count = 0
    try:
        active = await api.admin_list_games(status="RUNNING", limit=200, offset=0)
        active_games_count = len(active.get("items") or active.get("games") or [])
    except Exception:
        active_games_count = 0
    try:
        lobby = await api.admin_list_games(status="LOBBY", limit=200, offset=0)
        lobby_games_count = len(lobby.get("items") or lobby.get("games") or [])
    except Exception:
        lobby_games_count = 0

    threshold_minutes = max(1, int(settings.ADMIN_TOPIC_SLA_MINUTES or 30))
    dep_old_id, dep_old_min = _oldest_pending_info(pending_deposits)
    wdr_old_id, wdr_old_min = _oldest_pending_info(pending_withdraws)

    if pending_deposits and dep_old_min >= threshold_minutes:
        marker = f"{dep_old_id}:{dep_old_min // threshold_minutes}"
        prev = get_meta_marker("admin_sla_deposit_marker", "")
        if marker != prev:
            await _send_admin_sla_alert(
                bot,
                kind="deposit",
                count=len(pending_deposits),
                oldest_id=dep_old_id,
                oldest_minutes=dep_old_min,
                threshold_minutes=threshold_minutes,
            )
            set_meta_marker("admin_sla_deposit_marker", marker)
    else:
        set_meta_marker("admin_sla_deposit_marker", "")

    if pending_withdraws and wdr_old_min >= threshold_minutes:
        marker = f"{wdr_old_id}:{wdr_old_min // threshold_minutes}"
        prev = get_meta_marker("admin_sla_withdraw_marker", "")
        if marker != prev:
            await _send_admin_sla_alert(
                bot,
                kind="withdraw",
                count=len(pending_withdraws),
                oldest_id=wdr_old_id,
                oldest_minutes=wdr_old_min,
                threshold_minutes=threshold_minutes,
            )
            set_meta_marker("admin_sla_withdraw_marker", marker)
    else:
        set_meta_marker("admin_sla_withdraw_marker", "")

    now_utc = datetime.now(timezone.utc)
    hour_key = now_utc.strftime("%Y%m%d%H")
    if get_meta_marker("admin_hourly_summary_key", "") != hour_key:
        await _send_admin_summary(
            bot,
            title="گزارش ساعتی مدیریت",
            tag="#گزارش_ساعتی",
            pending_deposits=pending_deposits,
            pending_withdraws=pending_withdraws,
            active_games_count=active_games_count,
            lobby_games_count=lobby_games_count,
        )
        set_meta_marker("admin_hourly_summary_key", hour_key)

    daily_hour = max(0, min(23, int(settings.ADMIN_TOPIC_DAILY_SUMMARY_HOUR_UTC or 18)))
    day_key = now_utc.strftime("%Y%m%d")
    if now_utc.hour >= daily_hour and get_meta_marker("admin_daily_summary_key", "") != day_key:
        await _send_admin_summary(
            bot,
            title="گزارش روزانه مدیریت",
            tag="#گزارش_روزانه",
            pending_deposits=pending_deposits,
            pending_withdraws=pending_withdraws,
            active_games_count=active_games_count,
            lobby_games_count=lobby_games_count,
        )
        set_meta_marker("admin_daily_summary_key", day_key)
    now_local = _admin_local_now()
    income_hour = max(0, min(23, int(settings.ADMIN_TOPIC_DAILY_REVENUE_HOUR_LOCAL or 15)))
    income_day_key = now_local.strftime("%Y%m%d")
    if now_local.hour >= income_hour and get_meta_marker("admin_income_daily_summary_key", "") != income_day_key:
        await _send_income_daily_summary(bot, api, now_local=now_local)
        set_meta_marker("admin_income_daily_summary_key", income_day_key)


async def _queue_prize_notifications(
    queue: asyncio.Queue[_SendJob],
    bot: Bot,
    *,
    game_id: int,
    report: dict,
    kind: str,
    event: dict,
) -> None:
    game = report.get("game") or {}
    payload = _event_payload(event)
    call_number = _to_int(payload.get("call_number"), 0)
    amount_total = _to_int(payload.get("amount_total"), 0)
    amounts_by_card = _as_int_list(payload.get("amounts_by_card"))
    admin_tg_user_id = _to_int(game.get("admin_tg_user_id"), 0)
    game_topic_id = _to_int(game.get("tg_topic_id"), 0)
    kind_title = "تورنا" if kind == "PRIZE_COL" else "تمام"

    if kind == "PRIZE_COL":
        winner_tg_user_ids = _as_int_list(game.get("col_winner_tg_user_ids"))
        winner_card_ids = _as_int_list(game.get("col_winner_card_ids"))
    else:
        winner_tg_user_ids = _as_int_list(game.get("row_winner_tg_user_ids"))
        winner_card_ids = _as_int_list(game.get("row_winner_card_ids"))

    grouped = _group_cards_by_tg_user(winner_tg_user_ids, winner_card_ids, amounts_by_card)
    winners_rows = await _fmt_winner_rows(bot, grouped)
    if _is_user_forum_game(report):
        public_text = panel(
            "اعلان برنده",
            "#نتایج #برنده\n"
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"🧵 دسته بازی: <b>{user_game_topic_title(game_topic_id if game_topic_id > 0 else None)}</b>\n"
            f"🏆 نوع برد: <b>{kind_title}</b>\n"
            f"👥 تعداد برنده‌ها: <b>{len([x for x in winner_tg_user_ids if x > 0])}</b>\n"
            f"🪪 کارت‌های برنده: <code>{', '.join(str(x) for x in winner_card_ids) if winner_card_ids else '—'}</code>\n"
            f"💰 مجموع پرداخت: <b>{amount_total if amount_total > 0 else '—'}</b>\n"
            f"{f'🔢 عدد برنده: <b>{call_number}</b>' if call_number > 0 else ''}\n\n"
            f"جزئیات:\n{winners_rows}",
        )
        await send_to_user_topic(
            bot,
            name="results",
            text=public_text,
            parse_mode="HTML",
            disable_notification=False,
        )
        await send_to_user_game_topic(
            bot,
            game_topic_id=game_topic_id if game_topic_id > 0 else None,
            text=public_text,
            parse_mode="HTML",
            disable_notification=True,
        )

    for tg_uid, cards in grouped.items():
        user_amount = sum(max(0, amt) for _, amt in cards)
        text = (
            f"🏆 <b>تبریک!</b>\n"
            f"تو در بازی <b>#{game_id}</b> برنده {kind_title} شدی.\n"
            f"🪪 کارت(ها): <code>{_fmt_cards(cards)}</code>\n"
            f"💰 مبلغ: <b>{user_amount if user_amount > 0 else amount_total}</b>\n"
            f"{f'🔢 عدد برنده: <b>{call_number}</b>' if call_number > 0 else ''}"
        ).strip()
        await queue.put(_SendJob(game_id=game_id, user_id=int(tg_uid), text=text))

    admin_receivers: set[int] = set()
    if admin_tg_user_id > 0:
        admin_receivers.add(int(admin_tg_user_id))
    elif settings.admin_ids:
        admin_receivers.update(int(uid) for uid in settings.admin_ids if int(uid) > 0)

    if admin_receivers:
        cards_txt = ", ".join(str(x) for x in winner_card_ids) if winner_card_ids else "—"
        winners_count = len([x for x in winner_tg_user_ids if x > 0])
        admin_text = panel(
            "گزارش برنده حین بازی",
            "#برنده #حین_بازی\n"
            f"🕒 زمان: <code>{now_stamp()}</code>\n"
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"نوع برد: <b>{kind_title}</b>\n"
            f"👥 تعداد برنده‌ها: <b>{winners_count}</b>\n"
            f"🪪 کارت(های) برنده: <code>{cards_txt}</code>\n"
            f"💰 مجموع پرداخت: <b>{amount_total if amount_total > 0 else '—'}</b>\n"
            f"{f'🔢 عدد برنده: <b>{call_number}</b>' if call_number > 0 else ''}\n\n"
            f"جزئیات برنده‌ها:\n{winners_rows}",
        )

        sent_to_topic = await send_to_topic(
            bot,
            name="winners",
            text=admin_text,
            reply_markup=_winners_topic_kb(),
            parse_mode="HTML",
        )
        if sent_to_topic:
            return

        if not bool(settings.ADMIN_TOPIC_ENABLE_DM_FALLBACK):
            return

        for admin_uid in sorted(admin_receivers):
            await queue.put(_SendJob(game_id=game_id, user_id=int(admin_uid), text=admin_text))


async def _process_game_lifecycle_reports(
    bot: Bot,
    *,
    game_id: int,
    report: dict,
    runtime_started_ts: float,
    is_first_seen: bool,
) -> None:
    events = report.get("events") or []

    created_event = _latest_event(events, "GAME_CREATED")
    created_event_id = _to_int((created_event or {}).get("id"), 0)
    prev_created_marker = get_event_marker(game_id, "GAME_CREATED_NOTICE")
    if created_event and created_event_id > prev_created_marker:
        created_payload = _event_payload(created_event)
        created_notice_sent_by_mini = bool(created_payload.get("mini_created_notice_sent"))
        should_send_created = True
        if is_first_seen and prev_created_marker <= 0:
            should_send_created = _is_recent_event_for_runtime(created_event, runtime_started_ts)
        if should_send_created and not created_notice_sent_by_mini:
            await _send_user_game_created_notice(
                bot,
                game_id=game_id,
                report=report,
                event=created_event,
            )
        set_event_marker(game_id, "GAME_CREATED_NOTICE", created_event_id)

    start_event = _latest_event(events, "GAME_STARTED")
    start_event_id = _to_int((start_event or {}).get("id"), 0)
    prev_start_marker = get_event_marker(game_id, "GAME_STARTED_NOTICE")
    if start_event and start_event_id > prev_start_marker:
        should_send_start = True
        if is_first_seen and prev_start_marker <= 0:
            should_send_start = _is_recent_event_for_runtime(start_event, runtime_started_ts)
        if should_send_start:
            await _send_game_started_report(bot, game_id=game_id, report=report, event=start_event)
        set_event_marker(game_id, "GAME_STARTED_NOTICE", start_event_id)

    end_event = _latest_event(events, "GAME_ENDED")
    end_event_id = _to_int((end_event or {}).get("id"), 0)
    prev_end_marker = get_event_marker(game_id, "GAME_ENDED_NOTICE")
    if end_event and end_event_id > prev_end_marker:
        should_send_end = True
        if is_first_seen and prev_end_marker <= 0:
            should_send_end = _is_recent_event_for_runtime(end_event, runtime_started_ts)
        if should_send_end:
            await _send_game_ended_report(bot, game_id=game_id, report=report, event=end_event)
        set_event_marker(game_id, "GAME_ENDED_NOTICE", end_event_id)


async def _send_with_retry(bot: Bot, user_id: int, text: str) -> tuple[bool, bool, int]:
    """
    Returns:
      - success
      - dead_subscriber (should be removed)
      - retry_after_hits (429/RetryAfter count in this send attempt)
    """
    retry_after_hits = 0
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
        return True, False, retry_after_hits
    except TelegramRetryAfter as e:
        retry_after_hits += 1
        retry_after = float(getattr(e, "retry_after", 1.0) or 1.0)
        if retry_after >= 2.0:
            with suppress(Exception):
                await _send_operational_alert(
                    bot,
                    title="RetryAfter بالا",
                    detail=f"retry_after={retry_after:.2f}s در ارسال پیام",
                    throttle_key="alerts:retry_after_high",
                )
        await asyncio.sleep(float(getattr(e, "retry_after", 1.0)) + 0.1)
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            return True, False, retry_after_hits
        except TelegramRetryAfter:
            retry_after_hits += 1
            return False, False, retry_after_hits
        except (TelegramForbiddenError, TelegramBadRequest):
            return False, True, retry_after_hits
        except TelegramNetworkError:
            with suppress(Exception):
                await _send_operational_alert(
                    bot,
                    title="اختلال شبکه تلگرام",
                    detail="ارسال پیام پس از RetryAfter نیز با خطای شبکه مواجه شد.",
                    throttle_key="alerts:telegram_network_after_retry",
                )
            return False, False, retry_after_hits
        except Exception:
            return False, False, retry_after_hits
    except (TelegramForbiddenError, TelegramBadRequest):
        return False, True, retry_after_hits
    except TelegramNetworkError:
        with suppress(Exception):
            await _send_operational_alert(
                bot,
                title="اختلال شبکه تلگرام",
                detail="ارسال پیام نوتیفایر با خطای شبکه مواجه شد.",
                throttle_key="alerts:telegram_network_send",
            )
        return False, False, retry_after_hits
    except Exception:
        return False, False, retry_after_hits


async def _sender_worker(
    bot: Bot,
    queue: asyncio.Queue[_SendJob],
    fail_counts: dict[tuple[int, int], int],
    stats_window: _SendStats,
    stats_total: _SendStats,
    stats_lock: asyncio.Lock,
    *,
    dead_fail_threshold: int,
    send_delay_sec: float,
) -> None:
    while True:
        job = await queue.get()
        try:
            success, dead, retry_after_hits = await _send_with_retry(bot, job.user_id, job.text)
            key = (job.game_id, job.user_id)

            async with stats_lock:
                stats_window.processed += 1
                stats_window.retry_after_hits += int(retry_after_hits)
                stats_total.processed += 1
                stats_total.retry_after_hits += int(retry_after_hits)
                if success:
                    stats_window.ok += 1
                    stats_total.ok += 1
                elif dead:
                    stats_window.dead_fail += 1
                    stats_total.dead_fail += 1
                else:
                    stats_window.transient_fail += 1
                    stats_total.transient_fail += 1

            if success:
                fail_counts.pop(key, None)
            else:
                if dead:
                    cnt = fail_counts.get(key, 0) + 1
                    if cnt >= dead_fail_threshold:
                        unsubscribe(job.user_id, job.game_id)
                        fail_counts.pop(key, None)
                    else:
                        fail_counts[key] = cnt
                else:
                    # transient failure
                    cnt = fail_counts.get(key, 0) + 1
                    fail_counts[key] = cnt
        finally:
            queue.task_done()
            if send_delay_sec > 0:
                await asyncio.sleep(send_delay_sec)


async def notifier_loop(
    bot: Bot,
    api: ApiClient,
    *,
    interval_sec: float = 2.0,
    last_n: int = 200,
    send_workers: int = 2,
    adaptive_max_workers: int = 3,
    send_delay_sec: float = 0.025,
    queue_maxsize: int = 5000,
    dead_fail_threshold: int = 3,
    fast_events_limit: int = 100,
    fast_games_limit: int = 120,
    slow_interval_sec: float = 30.0,
    slow_events_limit: int = 150,
    slow_games_limit: int = 80,
    hot_game_ttl_sec: float = 120.0,
    adaptive_check_sec: float = 180.0,
    adaptive_min_jobs: int = 120,
    metrics_report_sec: float = 60.0,
    mini_deposit_alert_interval_sec: float = 4.0,
):
    interval_sec = max(0.5, float(interval_sec))
    last_n = max(20, int(last_n))
    send_workers = max(1, int(send_workers))
    adaptive_max_workers = max(send_workers, int(adaptive_max_workers))
    send_delay_sec = max(0.0, float(send_delay_sec))
    queue_maxsize = max(500, int(queue_maxsize))
    dead_fail_threshold = max(1, int(dead_fail_threshold))
    fast_events_limit = max(20, int(fast_events_limit))
    fast_games_limit = max(20, int(fast_games_limit))
    slow_interval_sec = max(5.0, float(slow_interval_sec))
    slow_events_limit = max(20, int(slow_events_limit))
    slow_games_limit = max(10, int(slow_games_limit))
    hot_game_ttl_sec = max(15.0, float(hot_game_ttl_sec))
    adaptive_check_sec = max(30.0, float(adaptive_check_sec))
    adaptive_min_jobs = max(20, int(adaptive_min_jobs))
    metrics_report_sec = max(15.0, float(metrics_report_sec))
    mini_deposit_alert_interval_sec = max(2.0, float(mini_deposit_alert_interval_sec))

    def _ids_from_admin_games_payload(payload: dict | None) -> set[int]:
        out: set[int] = set()
        if not isinstance(payload, dict):
            return out
        items = payload.get("items") or payload.get("games") or []
        for item in items:
            gid = _to_int((item or {}).get("id"), 0)
            if gid > 0:
                out.add(int(gid))
        return out

    async def _fetch_game_ids_by_status(status: str, limit: int) -> set[int]:
        try:
            data = await api.admin_list_games(status=status, limit=int(limit), offset=0)
            return _ids_from_admin_games_payload(data if isinstance(data, dict) else {})
        except Exception:
            return set()

    async def _process_game_report_candidate(gid: int, *, events_limit: int) -> None:
        try:
            rep = await api.admin_get_game_report(gid, events_limit=events_limit)
        except Exception:
            return

        game = rep.get("game") or {}
        if _is_user_forum_game(rep):
            called_numbers = _called_numbers_from_report(rep)
            live_marker_key = f"user_live_count:{gid}"
            raw_live_marker = get_meta_marker(live_marker_key, "")
            if raw_live_marker == "":
                _set_meta_int(live_marker_key, len(called_numbers))
            else:
                prev_live_count = _meta_int(live_marker_key, 0)
                cur_live_count = len(called_numbers)
                if cur_live_count < prev_live_count:
                    _set_meta_int(live_marker_key, cur_live_count)
                elif cur_live_count > prev_live_count:
                    game_topic_id = _to_int(game.get("tg_topic_id"), 0)
                    for idx in range(prev_live_count, cur_live_count):
                        n = int(called_numbers[idx])
                        partial_called = called_numbers[: idx + 1]
                        with suppress(Exception):
                            await _send_user_live_number_notice(
                                bot,
                                game_id=gid,
                                game_topic_id=game_topic_id if game_topic_id > 0 else None,
                                number=int(n),
                                called_numbers=partial_called,
                            )
                    _set_meta_int(live_marker_key, cur_live_count)

        events = rep.get("events") or []
        col_event = _latest_event(events, "PRIZE_COL")
        row_event = _latest_event(events, "PRIZE_ROW")
        col_event_id = _to_int((col_event or {}).get("id"), 0)
        row_event_id = _to_int((row_event or {}).get("id"), 0)
        is_first_lifecycle_seen = gid not in warmed_lifecycle_games

        if gid not in warmed_prize_games:
            prev_col = get_event_marker(gid, "PRIZE_COL")
            if col_event and col_event_id > prev_col:
                if prev_col > 0 or _is_recent_event_for_runtime(col_event, runtime_started_ts):
                    await _queue_prize_notifications(
                        queue,
                        bot,
                        game_id=gid,
                        report=rep,
                        kind="PRIZE_COL",
                        event=col_event,
                    )
                set_event_marker(gid, "PRIZE_COL", col_event_id)

            prev_row = get_event_marker(gid, "PRIZE_ROW")
            if row_event and row_event_id > prev_row:
                if prev_row > 0 or _is_recent_event_for_runtime(row_event, runtime_started_ts):
                    await _queue_prize_notifications(
                        queue,
                        bot,
                        game_id=gid,
                        report=rep,
                        kind="PRIZE_ROW",
                        event=row_event,
                    )
                set_event_marker(gid, "PRIZE_ROW", row_event_id)

            warmed_prize_games.add(gid)
        else:
            prev_col = get_event_marker(gid, "PRIZE_COL")
            if col_event and col_event_id > prev_col:
                await _queue_prize_notifications(
                    queue,
                    bot,
                    game_id=gid,
                    report=rep,
                    kind="PRIZE_COL",
                    event=col_event,
                )
                set_event_marker(gid, "PRIZE_COL", col_event_id)

            prev_row = get_event_marker(gid, "PRIZE_ROW")
            if row_event and row_event_id > prev_row:
                await _queue_prize_notifications(
                    queue,
                    bot,
                    game_id=gid,
                    report=rep,
                    kind="PRIZE_ROW",
                    event=row_event,
                )
                set_event_marker(gid, "PRIZE_ROW", row_event_id)

        await _process_game_lifecycle_reports(
            bot,
            game_id=gid,
            report=rep,
            runtime_started_ts=runtime_started_ts,
            is_first_seen=is_first_lifecycle_seen,
        )
        warmed_lifecycle_games.add(gid)

    # Warm-up per process start: first time we see a game with last_seen_count<=0,
    # only align cursor and do not send historical numbers.
    warmed_games: set[int] = set()
    warmed_prize_games: set[int] = set()
    warmed_lifecycle_games: set[int] = set()
    hot_games_until_ts: dict[int, float] = {}
    runtime_started_ts = float(time.time())
    fail_counts: dict[tuple[int, int], int] = {}
    queue: asyncio.Queue[_SendJob] = asyncio.Queue(maxsize=queue_maxsize)
    stats_window = _SendStats()
    stats_total = _SendStats()
    stats_lock = asyncio.Lock()

    workers: list[asyncio.Task[Any]] = []

    def _spawn_worker() -> None:
        workers.append(
            asyncio.create_task(
                _sender_worker(
                    bot,
                    queue,
                    fail_counts,
                    stats_window,
                    stats_total,
                    stats_lock,
                    dead_fail_threshold=dead_fail_threshold,
                    send_delay_sec=send_delay_sec,
                )
            )
        )

    for _ in range(int(send_workers)):
        _spawn_worker()
    next_admin_audit_ts = 0.0
    next_slow_scan_ts = 0.0
    next_adaptive_check_ts = float(time.time()) + adaptive_check_sec
    next_metrics_report_ts = float(time.time()) + metrics_report_sec

    with suppress(Exception):
        await ensure_topic_rules(bot)

    logger.info(
        (
            "notifier: started interval=%.2fs workers=%d..%d send_delay=%.3fs "
            "fast_events=%d slow_events=%d adaptive_check=%.0fs metrics=%.0fs"
        ),
        interval_sec,
        send_workers,
        adaptive_max_workers,
        send_delay_sec,
        fast_events_limit,
        slow_events_limit,
        adaptive_check_sec,
        metrics_report_sec,
    )

    try:
        while True:
            try:
                now_ts = float(time.time())

                if now_ts >= next_metrics_report_ts:
                    next_metrics_report_ts = now_ts + metrics_report_sec
                    async with stats_lock:
                        window_processed = stats_window.processed
                        window_ok = stats_window.ok
                        window_dead = stats_window.dead_fail
                        window_transient = stats_window.transient_fail
                        window_retry_after = stats_window.retry_after_hits
                        total_processed = stats_total.processed
                        total_ok = stats_total.ok
                        total_dead = stats_total.dead_fail
                        total_transient = stats_total.transient_fail
                        total_retry_after = stats_total.retry_after_hits
                    logger.info(
                        (
                            "notifier: metrics workers=%d queue=%d "
                            "window[p=%d ok=%d dead=%d transient=%d retry_after=%d] "
                            "total[p=%d ok=%d dead=%d transient=%d retry_after=%d]"
                        ),
                        len(workers),
                        queue.qsize(),
                        window_processed,
                        window_ok,
                        window_dead,
                        window_transient,
                        window_retry_after,
                        total_processed,
                        total_ok,
                        total_dead,
                        total_transient,
                        total_retry_after,
                    )

                if now_ts >= next_adaptive_check_ts:
                    next_adaptive_check_ts = now_ts + adaptive_check_sec
                    async with stats_lock:
                        window_processed = stats_window.processed
                        window_retry_after = stats_window.retry_after_hits
                        stats_window.processed = 0
                        stats_window.ok = 0
                        stats_window.dead_fail = 0
                        stats_window.transient_fail = 0
                        stats_window.retry_after_hits = 0

                    if (
                        window_retry_after <= 0
                        and window_processed >= adaptive_min_jobs
                        and len(workers) < adaptive_max_workers
                    ):
                        _spawn_worker()
                        logger.info(
                            (
                                "notifier: adaptive scale up workers=%d "
                                "(processed=%d retry_after=%d threshold=%d)"
                            ),
                            len(workers),
                            window_processed,
                            window_retry_after,
                            adaptive_min_jobs,
                        )
                    elif window_retry_after > 0 and len(workers) > send_workers:
                        w = workers.pop()
                        w.cancel()
                        with suppress(asyncio.CancelledError):
                            await w
                        logger.warning(
                            (
                                "notifier: adaptive scale down workers=%d "
                                "(processed=%d retry_after=%d)"
                            ),
                            len(workers),
                            window_processed,
                            window_retry_after,
                        )

                game_ids = list_tracked_game_ids()
                for gid in game_ids:
                    subs = get_subscribers(gid)
                    if not subs:
                        continue

                    try:
                        st = await api.get_game_state(gid, last_n=last_n)
                    except Exception as exc:
                        status = getattr(exc, "status", None)
                        if status == 404:
                            # The tracked game no longer exists; prune stale subscriptions.
                            for uid in list(subs):
                                with suppress(Exception):
                                    unsubscribe(int(uid), int(gid))
                            with suppress(Exception):
                                set_last_seen_count(gid, 0)
                            logger.info("notifier: pruned stale game tracking for game_id=%s", gid)
                        else:
                            logger.warning("notifier: get_game_state failed for game_id=%s: %s", gid, exc)
                        continue

                    called = st.get("called_numbers") or []
                    called = [int(x) for x in called]
                    if not called:
                        continue

                    prev_count = get_last_seen_count(gid)
                    cur_count = len(called)

                    # Handle resets (e.g., game state reset): realign cursor.
                    if cur_count < prev_count:
                        set_last_seen_count(gid, cur_count)
                        prev_count = cur_count

                    # Warm-up on first poll of this process for games with empty cursor.
                    if gid not in warmed_games:
                        warmed_games.add(gid)
                        if prev_count <= 0:
                            set_last_seen_count(gid, cur_count)
                            continue

                    if cur_count <= prev_count:
                        continue

                    new_numbers = called[prev_count:cur_count]
                    set_last_seen_count(gid, cur_count)
                    hot_games_until_ts[int(gid)] = now_ts + hot_game_ttl_sec

                    for n in new_numbers:
                        text = (
                            f"📣 <b>عدد جدید</b>: <b>{n}</b>\n"
                            f"🎮 بازی: <b>{gid}</b>\n"
                            f"آخرین اعداد: {_fmt_last(called, 12)}"
                        )
                        for uid in subs:
                            await queue.put(_SendJob(game_id=gid, user_id=int(uid), text=text))

                # Fast path: only LOBBY/RUNNING + hot games.
                active_game_ids = await _fetch_game_ids_by_status("LOBBY|RUNNING", fast_games_limit)
                for gid in active_game_ids:
                    hot_games_until_ts[int(gid)] = now_ts + hot_game_ttl_sec
                for gid in game_ids:
                    hot_games_until_ts[int(gid)] = now_ts + hot_game_ttl_sec

                for gid, expire_ts in list(hot_games_until_ts.items()):
                    if expire_ts < now_ts:
                        hot_games_until_ts.pop(gid, None)

                hot_ids = {int(gid) for gid, expire_ts in hot_games_until_ts.items() if expire_ts >= now_ts}
                candidate_fast_ids = set(int(x) for x in game_ids) | set(active_game_ids) | hot_ids
                for gid in sorted(candidate_fast_ids):
                    await _process_game_report_candidate(gid, events_limit=fast_events_limit)

                # Slow path: scan ENDED separately with lower cadence.
                if now_ts >= next_slow_scan_ts:
                    next_slow_scan_ts = now_ts + max(slow_interval_sec, interval_sec)
                    ended_game_ids = await _fetch_game_ids_by_status("ENDED", slow_games_limit)
                    for gid in sorted(int(x) for x in ended_game_ids if int(x) not in candidate_fast_ids):
                        await _process_game_report_candidate(gid, events_limit=slow_events_limit)

                if now_ts >= next_admin_audit_ts:
                    next_admin_audit_ts = now_ts + max(30, int(settings.ADMIN_TOPIC_AUDIT_INTERVAL_SEC or 120))
                    with suppress(Exception):
                        await _admin_forum_audit(bot, api)

            except Exception:
                # Keep loop alive but do not swallow diagnostics.
                logger.exception("notifier: loop iteration failed")

            await asyncio.sleep(interval_sec)
    finally:
        for w in workers:
            w.cancel()
        for w in workers:
            with suppress(asyncio.CancelledError):
                await w
