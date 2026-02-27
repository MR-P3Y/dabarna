from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from html import escape as html_escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import settings
from bot.keyboards.admin_games import (
    admin_game_close_reason_kb,
    admin_game_create_price_kb,
    admin_game_create_topic_kb,
    admin_game_item_kb,
    admin_games_list_kb,
    admin_monitor_kb,
    admin_winners_archive_kb,
    admin_winners_kb,
)
from bot.services.api_client import ApiClient, ApiError
from bot.services.telegram_safe import safe_edit_or_send, safe_send
from bot.services.tg_display import resolve_tg_identity, resolve_tg_identities
from bot.services.ui import panel
from bot.states.admin_call import AdminCallSG
from bot.states.admin_game_close import AdminGameCloseSG
from bot.states.admin_game_create import AdminGameCreateSG
from bot.states.admin_game_live import AdminGameLiveSG

router = Router()

PAGE_SIZE = 5
DEFAULT_STATUS = "LOBBY|RUNNING"
MONITOR_INTERVAL_SEC = 3.0
DEFAULT_CARD_PRICE = 1000
PERSIAN_DIGITS_TRANSLATION = str.maketrans(
    {
        "\u06f0": "0",
        "\u06f1": "1",
        "\u06f2": "2",
        "\u06f3": "3",
        "\u06f4": "4",
        "\u06f5": "5",
        "\u06f6": "6",
        "\u06f7": "7",
        "\u06f8": "8",
        "\u06f9": "9",
        "\u0660": "0",
        "\u0661": "1",
        "\u0662": "2",
        "\u0663": "3",
        "\u0664": "4",
        "\u0665": "5",
        "\u0666": "6",
        "\u0667": "7",
        "\u0668": "8",
        "\u0669": "9",
    }
)


@dataclass
class MonitorJob:
    task: asyncio.Task
    message_id: int
    chat_id: int
    game_id: int


@dataclass
class LiveSendCacheItem:
    url: str
    failed_tg_ids: list[int]
    updated_at: float


# one active auto-monitor per admin chat
ADMIN_MONITORS: dict[int, MonitorJob] = {}
LIVE_SEND_CACHE: dict[tuple[int, int], LiveSendCacheItem] = {}
LIVE_SEND_CACHE_TTL_SEC = 3600.0


def require_admin(is_admin: bool) -> bool:
    return bool(is_admin)


def _to_int(x: str | None, default: int = 0) -> int:
    try:
        return int(x or "")
    except Exception:
        return default


def _fa_status(status: str | None) -> str:
    s = (status or "").strip().upper()
    mapping = {
        "LOBBY": "در انتظار شروع",
        "RUNNING": "در حال اجرا",
        "ENDED": "پایان‌یافته",
        "ACTIVE": "در حال اجرا",
    }
    return mapping.get(s, "نامشخص")


def _fa_status_filter(raw: str | None) -> str:
    parts = [p.strip() for p in (raw or "").upper().replace(",", "|").split("|") if p.strip()]
    if not parts:
        return _fa_status(DEFAULT_STATUS)
    return " | ".join(_fa_status(p) for p in parts)


def _parse_list_cb(data: str) -> tuple[str, int]:
    # admin:games:list:{status}:{offset}
    parts = data.split(":")
    status = parts[3] if len(parts) > 3 and parts[3] else DEFAULT_STATUS
    offset = _to_int(parts[4] if len(parts) > 4 else None, 0)
    return status, max(0, offset)


def _parse_winners_archive_cb(data: str) -> int:
    # admin:games:winners:archive:{offset}
    parts = data.split(":")
    offset = _to_int(parts[4] if len(parts) > 4 else None, 0)
    return max(0, offset)


def _parse_ensure_ctx(data: str) -> tuple[str, int]:
    # admin:games:ensure:{status}:{offset}
    parts = data.split(":")
    status = parts[3] if len(parts) > 3 and parts[3] else DEFAULT_STATUS
    offset = _to_int(parts[4] if len(parts) > 4 else None, 0)
    return status, max(0, offset)


def _parse_ensure_topic_ctx(data: str) -> tuple[int, str, int]:
    # admin:games:ensure:topic:{topic_id}:{status}:{offset}
    parts = data.split(":")
    topic_id = _to_int(parts[4] if len(parts) > 4 else None, 0)
    status = parts[5] if len(parts) > 5 and parts[5] else DEFAULT_STATUS
    offset = _to_int(parts[6] if len(parts) > 6 else None, 0)
    return topic_id, status, max(0, offset)


def _parse_create_cancel_ctx(data: str) -> tuple[str, int]:
    # admin:games:create:cancel:{status}:{offset}
    parts = data.split(":")
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return status, max(0, offset)


def _configured_game_topics() -> list[tuple[str, int]]:
    raw: list[tuple[str, int | None]] = [
        ("🎯 بازی ۱ (مبلغ پایین)", settings.USER_TOPIC_GAME_LOW_ID),
        ("🎯 بازی ۲ (مبلغ متوسط)", settings.USER_TOPIC_GAME_MEDIUM_ID),
        ("🎯 بازی ۳ (مبلغ بالا)", settings.USER_TOPIC_GAME_HIGH_ID),
    ]
    out: list[tuple[str, int]] = []
    seen: set[int] = set()
    for title, topic_id in raw:
        if topic_id is None:
            continue
        t = int(topic_id)
        if t in seen:
            continue
        seen.add(t)
        out.append((title, t))
    return out


def _topic_title(topic_id: int | None) -> str:
    if topic_id is None:
        return "عمومی"
    for title, t_id in _configured_game_topics():
        if int(t_id) == int(topic_id):
            return title
    return f"تاپیک {int(topic_id)}"


def _parse_card_price_input(text: str | None) -> int | None:
    raw = str(text or "").strip().translate(PERSIAN_DIGITS_TRANSLATION)
    cleaned = raw.replace(",", "").replace("٬", "").replace(" ", "")
    if not cleaned.isdigit():
        return None
    amount = int(cleaned)
    if amount <= 0:
        return None
    return amount


def _parse_game_ctx_from_start(data: str) -> tuple[int, str, int]:
    # admin:games:start:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return game_id, status, max(0, offset)


def _parse_game_ctx_from_close_lobby(data: str) -> tuple[int, str, int]:
    # admin:games:close-lobby:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return game_id, status, max(0, offset)


def _parse_view_cb(data: str) -> tuple[int, str, int]:
    # admin:games:view:{game_id}:{status}:{offset}
    parts = data.split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return game_id, status, max(0, offset)


def _parse_game_ctx(data: str) -> tuple[int, str, int]:
    # admin:games:call:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return game_id, status, max(0, offset)


def _parse_undo_ctx(data: str) -> tuple[int, str, int]:
    # admin:games:undo:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return game_id, status, max(0, offset)


def _parse_undo2_ctx(data: str) -> tuple[int, str, int, str]:
    # admin:games:undo2:{game_id}:{status}:{offset}:{nonce}
    parts = (data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    nonce = str(parts[6]) if len(parts) > 6 and parts[6] else uuid.uuid4().hex[:8]
    return game_id, status, max(0, offset), nonce


def _parse_monitor_open_ctx(data: str) -> tuple[int, str, int]:
    # admin:games:monitor:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    return game_id, status, max(0, offset)


def _parse_monitor_refresh_ctx(data: str) -> tuple[int, str, int]:
    # admin:games:monitor:refresh:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[4] if len(parts) > 4 else None, -1)
    status = parts[5] if len(parts) > 5 and parts[5] else DEFAULT_STATUS
    offset = _to_int(parts[6] if len(parts) > 6 else None, 0)
    return game_id, status, max(0, offset)


def _parse_monitor_auto_ctx(data: str) -> tuple[int, str, int]:
    # admin:games:monitor:auto:{on|off}:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    game_id = _to_int(parts[5] if len(parts) > 5 else None, -1)
    status = parts[6] if len(parts) > 6 and parts[6] else DEFAULT_STATUS
    offset = _to_int(parts[7] if len(parts) > 7 else None, 0)
    return game_id, status, max(0, offset)


def _parse_live_ctx(data: str) -> tuple[str, int, str, int]:
    # admin:games:live:{set|send|clear|resend}:{game_id}:{status}:{offset}
    parts = (data or "").split(":")
    action = parts[3] if len(parts) > 3 else ""
    game_id = _to_int(parts[4] if len(parts) > 4 else None, -1)
    status = parts[5] if len(parts) > 5 and parts[5] else DEFAULT_STATUS
    offset = _to_int(parts[6] if len(parts) > 6 else None, 0)
    return action, game_id, status, max(0, offset)


def _set_live_send_cache(chat_id: int, game_id: int, *, url: str, failed_tg_ids: list[int]) -> None:
    key = (int(chat_id), int(game_id))
    clean_ids = [int(x) for x in failed_tg_ids if _to_int(str(x), 0) > 0]
    if not clean_ids:
        LIVE_SEND_CACHE.pop(key, None)
        return
    LIVE_SEND_CACHE[key] = LiveSendCacheItem(
        url=str(url or "").strip(),
        failed_tg_ids=list(dict.fromkeys(clean_ids)),
        updated_at=time.time(),
    )


def _get_live_send_cache(chat_id: int, game_id: int) -> LiveSendCacheItem | None:
    key = (int(chat_id), int(game_id))
    item = LIVE_SEND_CACHE.get(key)
    if not item:
        return None
    if (time.time() - float(item.updated_at)) > LIVE_SEND_CACHE_TTL_SEC:
        LIVE_SEND_CACHE.pop(key, None)
        return None
    return item


def _single_game_status(status: str | None) -> str | None:
    raw = (status or "").strip().upper()
    if raw in {"LOBBY", "RUNNING", "ENDED"}:
        return raw
    return None


def _extract_numbers(called_numbers):
    # called_numbers ممکنه list[int] باشه یا list[dict]
    nums = []
    for x in called_numbers or []:
        if isinstance(x, int):
            nums.append(x)
        elif isinstance(x, dict) and "number" in x:
            try:
                nums.append(int(x["number"]))
            except Exception:
                pass
    return nums


def _extract_participant_items(payload: dict | list | None) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        raw = payload.get("items")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    return []


def _live_watch_kb(game_id: int, url: str):
    base = str(getattr(settings, "PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    watch_url = f"{base}/mini-api/live/{int(game_id)}" if base else str(url)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"▶️ ورود به لایو بازی #{game_id}", url=watch_url)
    kb.adjust(1)
    return kb.as_markup()

def _live_send_result_kb(*, game_id: int, status: str, offset: int, has_failed: bool):
    kb = InlineKeyboardBuilder()
    if has_failed:
        kb.button(text="🔁 ارسال مجدد ناموفق‌ها", callback_data=f"admin:games:live:resend:{game_id}:{status}:{offset}")
    kb.button(text="⬅️ بازگشت به بازی", callback_data=f"admin:games:view:{game_id}:{status}:{offset}")
    if has_failed:
        kb.adjust(1, 1)
    else:
        kb.adjust(1)
    return kb.as_markup()



async def _broadcast_live_link(
    cq: CallbackQuery,
    *,
    game_id: int,
    url: str,
    participants: list[dict],
) -> tuple[int, int, list[int]]:
    text = panel(
        "🎥 لینک پخش زنده",
        f"بازی <b>#{game_id}</b>\n"
        "برای مشاهده گردونه زنده و روند اعلام عدد، روی دکمه زیر بزن 👇",
    )
    markup = _live_watch_kb(game_id, url)

    sent = 0
    failed = 0
    failed_ids: list[int] = []

    for item in participants:
        tg_user_id = _to_int(str(item.get("tg_user_id") or ""), 0)
        if tg_user_id <= 0:
            failed += 1
            continue

        delivered = False
        for _ in range(3):
            try:
                await cq.bot.send_message(
                    chat_id=tg_user_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
                delivered = True
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(float(getattr(e, "retry_after", 2.0)) + 0.2)
            except (TelegramForbiddenError, TelegramBadRequest):
                delivered = False
                break
            except Exception:
                delivered = False
                break

        if delivered:
            sent += 1
        else:
            failed += 1
            if len(failed_ids) < 10:
                failed_ids.append(tg_user_id)

        # keep a small gap to stay far from Telegram flood limits
        await asyncio.sleep(0.12)

    return sent, failed, failed_ids


async def _notify_lobby_cancel_refunds(
    m: Message,
    *,
    game_id: int,
    card_price: int,
    cancel_reason: str,
    participants: list[dict],
) -> tuple[int, int, int, int, int]:
    notified_ok = 0
    notify_failed = 0
    no_tg_count = 0
    refund_total = 0
    refund_users_count = 0

    reason_html = html_escape(str(cancel_reason or "").strip())

    for item in participants:
        cards_count = _to_int(str(item.get("cards_count") or ""), 0)
        if cards_count <= 0:
            continue

        refund_users_count += 1
        amount = _to_int(str(item.get("total_paid") or ""), 0)
        if amount <= 0:
            amount = max(0, int(card_price)) * int(cards_count)
        refund_total += int(amount)

        tg_user_id = _to_int(str(item.get("tg_user_id") or ""), 0)
        if tg_user_id <= 0:
            no_tg_count += 1
            continue

        text = panel(
            "کنسل بازی و بازگشت وجه",
            "#کنسل_بازی #بازگشت_وجه\n"
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"📝 علت کنسل: <b>{reason_html}</b>\n"
            f"🃏 تعداد کارت شما: <b>{cards_count}</b>\n"
            f"💰 مبلغ برگشتی به کیف پول: <b>{amount:,}</b>\n\n"
            "✅ مبلغ به کیف پول شما برگشت داده شد.",
        )

        delivered = False
        for _ in range(3):
            try:
                await m.bot.send_message(chat_id=int(tg_user_id), text=text, parse_mode="HTML")
                delivered = True
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(float(getattr(e, "retry_after", 1.5)) + 0.2)
            except (TelegramForbiddenError, TelegramBadRequest):
                delivered = False
                break
            except Exception:
                delivered = False
                break

        if delivered:
            notified_ok += 1
        else:
            notify_failed += 1

        await asyncio.sleep(0.10)

    return notified_ok, notify_failed, no_tg_count, refund_total, refund_users_count


def _int_list(values) -> list[int]:
    out: list[int] = []
    for x in values or []:
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _render_card_grid(numbers: list[int], called_set: set[int]) -> str:
    rows: list[str] = []
    nums = [int(x) for x in numbers]
    for i in range(0, len(nums), 5):
        chunk = nums[i : i + 5]
        cells: list[str] = []
        for n in chunk:
            if n in called_set:
                cells.append(f"✅{n:02d}")
            else:
                cells.append(f"⬜️{n:02d}")
        rows.append("  ".join(cells))
    return "\n".join(rows)


def _has_winners(g: dict | None) -> bool:
    game = g or {}
    col_paid = int(game.get("col_paid", 0) or 0)
    row_paid = int(game.get("row_paid", 0) or 0)
    if col_paid == 1 or row_paid == 1:
        return True

    payout_state = game.get("payout_state_json") if isinstance(game.get("payout_state_json"), dict) else {}
    col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
    row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
    return bool(col_info or row_info)


def _winner_card_ids(game: dict | None) -> tuple[list[int], list[int]]:
    g = game or {}

    col_cards = _int_list(g.get("col_winner_card_ids") or [])
    row_cards = _int_list(g.get("row_winner_card_ids") or [])

    if not col_cards or not row_cards:
        payout_state = g.get("payout_state_json") if isinstance(g.get("payout_state_json"), dict) else {}
        col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
        row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
        if not col_cards:
            col_cards = _int_list(col_info.get("winner_card_ids") or [])
        if not row_cards:
            row_cards = _int_list(row_info.get("winner_card_ids") or [])

    col_cards = list(dict.fromkeys(col_cards))
    row_cards = list(dict.fromkeys(row_cards))
    return col_cards, row_cards


def _can_close_lobby(game: dict | None, *, purchases_count: int | None = None, called_count: int | None = None) -> bool:
    g = game or {}
    status = str(g.get("status") or "").strip().upper()
    if status != "LOBBY":
        return False
    if called_count is not None and int(called_count) > 0:
        return False
    return True


def _monitor_job(chat_id: int) -> MonitorJob | None:
    job = ADMIN_MONITORS.get(chat_id)
    if not job:
        return None
    if job.task.done():
        ADMIN_MONITORS.pop(chat_id, None)
        return None
    return job


def _monitor_is_on(chat_id: int, game_id: int) -> bool:
    job = _monitor_job(chat_id)
    return bool(job and job.game_id == game_id)


def _stop_monitor(chat_id: int) -> None:
    job = ADMIN_MONITORS.pop(chat_id, None)
    if job:
        job.task.cancel()


def _pop_monitor_if_current(chat_id: int, task: asyncio.Task | None) -> None:
    if task is None:
        return
    job = ADMIN_MONITORS.get(chat_id)
    if job and job.task is task:
        ADMIN_MONITORS.pop(chat_id, None)


def build_monitor_text(game_id: int, rep: dict) -> str:
    g = rep.get("game") or {}
    nums = _extract_numbers(rep.get("called_numbers") or [])
    last_num = nums[-1] if nums else None
    tail = nums[-12:] if nums else []

    status = str(g.get("status") or "—")
    card_price = g.get("card_price")
    sold_amount = g.get("sold_amount")
    prize_pool = g.get("prize_pool")

    row_paid = int(g.get("row_paid") or rep.get("row_paid") or 0)
    col_paid = int(g.get("col_paid") or rep.get("col_paid") or 0)

    lines = [
        f"📡 <b>مانیتور زنده</b> — بازی <b>#{game_id}</b>",
        f"وضعیت: <b>{_fa_status(status)}</b>",
        f"آخرین عدد: <b>{last_num if last_num is not None else '—'}</b>",
        f"تعداد اعداد: <b>{len(nums)}</b>",
        "",
        f"💳 قیمت کارت: <b>{card_price}</b>",
        f"💰 فروش: <b>{sold_amount}</b>",
        f"🎁 جایزه: <b>{prize_pool}</b>",
    ]

    if col_paid == 1:
        lines.append("🏆 <b>برد تورنا پرداخت شد</b>")
    if row_paid == 1:
        lines.append("🏁 <b>برد تمام پرداخت شد</b>")

    if tail:
        tail_head = "  •  ".join(str(n) for n in tail[:-1])
        tail_last = f"✅ <b>{tail[-1]}</b>"
        tail_str = f"{tail_head}  •  {tail_last}" if tail_head else tail_last
        lines += ["", "آخرین ۱۲ عدد:", tail_str]

    if status.strip().upper() == "ENDED":
        lines += ["", "🛑 <b>بازی تمام شد</b> — اعلام عدد متوقف است."]

    return "\n".join(lines)


async def _render_monitor_view(
    message: Message,
    api: ApiClient,
    *,
    game_id: int,
    status: str,
    offset: int,
    force_auto: bool | None = None,
) -> None:
    rep = await api.admin_get_game_report(game_id)
    auto_on = force_auto if force_auto is not None else _monitor_is_on(message.chat.id, game_id)
    await safe_edit_or_send(
        message,
        build_monitor_text(game_id, rep),
        parse_mode="HTML",
        reply_markup=admin_monitor_kb(game_id=game_id, status=status, offset=offset, auto_on=auto_on),
    )


async def _monitor_edit_text(message: Message, text: str, *, game_id: int, status: str, offset: int):
    try:
        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_monitor_kb(game_id=game_id, status=status, offset=offset, auto_on=True),
        )
    except TelegramBadRequest as e:
        # expected when report data is unchanged
        if "message is not modified" in str(e).lower():
            return
        raise


async def _monitor_loop(
    api: ApiClient,
    message: Message,
    *,
    game_id: int,
    status: str,
    offset: int,
    interval_sec: float = MONITOR_INTERVAL_SEC,
):
    chat_id = message.chat.id
    current_task = asyncio.current_task()

    while True:
        try:
            rep = await api.admin_get_game_report(game_id)
            text = build_monitor_text(game_id, rep)
            await _monitor_edit_text(message, text, game_id=game_id, status=status, offset=offset)
        except asyncio.CancelledError:
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 2)) + 0.3)
            continue
        except (TelegramForbiddenError, TelegramBadRequest):
            _pop_monitor_if_current(chat_id, current_task)
            return
        except ApiError:
            await asyncio.sleep(interval_sec)
            continue
        except Exception:
            await asyncio.sleep(interval_sec)
            continue

        await asyncio.sleep(interval_sec)


def _resolve_target_group_id(cq: CallbackQuery) -> int | None:
    chat = cq.message.chat
    if chat.type in ("group", "supergroup"):
        return int(chat.id)
    if settings.USER_FORUM_CHAT_ID is not None:
        return int(settings.USER_FORUM_CHAT_ID)
    if settings.BOT_JOIN_GROUP_ID is not None:
        return int(settings.BOT_JOIN_GROUP_ID)
    return None


def _default_games_group_id() -> int | None:
    if settings.USER_FORUM_CHAT_ID is not None:
        return int(settings.USER_FORUM_CHAT_ID)
    if settings.BOT_JOIN_GROUP_ID is not None:
        return int(settings.BOT_JOIN_GROUP_ID)
    return None


async def _suggest_card_price(api: ApiClient, *, group_id: int, topic_id: int | None = None) -> int:
    suggested = DEFAULT_CARD_PRICE
    try:
        recent = await api.admin_list_games(
            status="LOBBY|RUNNING|ENDED",
            limit=1,
            offset=0,
            tg_group_id=group_id,
            tg_topic_id=topic_id,
        )
        recent_items = recent.get("items") or recent.get("games") or []
        if recent_items:
            suggested = max(1, _to_int(str(recent_items[0].get("card_price") or ""), DEFAULT_CARD_PRICE))
    except ApiError:
        pass
    return suggested


async def _get_active_game_for_group(api: ApiClient, *, group_id: int, topic_id: int | None = None) -> dict | None:
    try:
        res = await api.admin_list_games(
            status="LOBBY|RUNNING",
            limit=1,
            offset=0,
            tg_group_id=group_id,
            tg_topic_id=topic_id,
        )
    except ApiError:
        return None
    items = res.get("items") or res.get("games") or []
    if not items:
        return None
    first = items[0]
    return first if isinstance(first, dict) else None


async def _open_create_price_step(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    *,
    status: str,
    offset: int,
    target_group_id: int,
    target_topic_id: int | None,
) -> None:
    suggested_price = await _suggest_card_price(api, group_id=target_group_id, topic_id=target_topic_id)
    await state.clear()
    await state.set_state(AdminGameCreateSG.waiting_card_price)
    await state.update_data(
        status=status,
        offset=offset,
        target_group_id=target_group_id,
        target_topic_id=target_topic_id,
    )

    topic_text = ""
    if target_topic_id is not None:
        topic_text = (
            f"🧵 تاپیک انتخابی: <b>{_topic_title(target_topic_id)}</b>\n"
            f"🧩 شناسه تاپیک: <code>{target_topic_id}</code>\n"
        )

    txt = (
        "مرحله <b>1 از 2</b>\n"
        "💳 مبلغ هر کارت را به <b>تومان</b> وارد کن.\n"
        "بدون وارد کردن مبلغ معتبر، بازی ایجاد نمی‌شود.\n\n"
        f"📌 پیشنهاد بر اساس آخرین بازی: <b>{suggested_price:,}</b> تومان\n"
        f"🧩 شناسه گروه: <code>{target_group_id}</code>\n"
        f"{topic_text}\n"
        "نمونه ورودی:\n"
        "<code>100000</code>"
    )
    await safe_edit_or_send(
        cq.message,
        panel("🕹️ ایجاد/فعال‌سازی بازی گروه", txt),
        parse_mode="HTML",
        reply_markup=admin_game_create_price_kb(status=status, offset=offset),
    )


async def _render_games_list(cq: CallbackQuery, api: ApiClient, *, status: str, offset: int):
    group_id = _default_games_group_id()
    res = await api.admin_list_games(status=status, limit=PAGE_SIZE + 1, offset=offset, tg_group_id=group_id)
    raw_items = res.get("items") or res.get("games") or []
    has_next = len(raw_items) > PAGE_SIZE
    items = raw_items[:PAGE_SIZE]

    if not items and offset > 0:
        offset = max(0, offset - PAGE_SIZE)
        res = await api.admin_list_games(status=status, limit=PAGE_SIZE + 1, offset=offset, tg_group_id=group_id)
        raw_items = res.get("items") or res.get("games") or []
        has_next = len(raw_items) > PAGE_SIZE
        items = raw_items[:PAGE_SIZE]

    if not items:
        await safe_edit_or_send(
            cq.message,
            panel("🎮 ادمین بازی", "فعلاً بازی‌ای برای نمایش نداریم 😴\nیه رفرش بزن، شاید تازه از راه رسیده باشه 😉"),
            reply_markup=admin_games_list_kb(items, status=status, offset=offset, has_next=has_next),
            parse_mode="HTML",
        )
        return

    page_no = (offset // PAGE_SIZE) + 1
    lines = [
        f"فیلتر وضعیت: <b>{_fa_status_filter(status)}</b>",
        f"صفحه: <b>{page_no}</b>",
        "",
        "روی بازی دلخواهت بزن تا جزئیاتش باز بشه 👇",
    ]

    for g in items:
        gid = g.get("id")
        title = g.get("title") or f"بازی {gid}"
        st_fa = _fa_status(str(g.get("status") or ""))
        price = _to_int(str(g.get("card_price") or ""), 0)
        pool = _to_int(str(g.get("prize_pool") or ""), 0)
        topic_id = g.get("tg_topic_id")
        topic_tag = f" | 🧵 {topic_id}" if topic_id is not None else ""
        lines.append(f"• 🎮 <b>#{gid}</b> | {title}{topic_tag} | <b>{st_fa}</b> | 💳 {price:,} | 🎁 {pool:,}")

    await safe_edit_or_send(
        cq.message,
        panel("🕹️ ادمین بازی | لیست", "\n".join(lines)),
        reply_markup=admin_games_list_kb(items, status=status, offset=offset, has_next=has_next),
        parse_mode="HTML",
    )


async def _render_winners_archive(cq: CallbackQuery, api: ApiClient, *, offset: int):
    group_id = _default_games_group_id()
    res = await api.admin_list_games(status="ENDED", limit=PAGE_SIZE + 1, offset=offset, tg_group_id=group_id)
    raw_items = res.get("items") or res.get("games") or []
    has_next = len(raw_items) > PAGE_SIZE
    items = raw_items[:PAGE_SIZE]

    if not items and offset > 0:
        offset = max(0, offset - PAGE_SIZE)
        res = await api.admin_list_games(status="ENDED", limit=PAGE_SIZE + 1, offset=offset, tg_group_id=group_id)
        raw_items = res.get("items") or res.get("games") or []
        has_next = len(raw_items) > PAGE_SIZE
        items = raw_items[:PAGE_SIZE]

    winner_items: list[dict] = []
    skipped = 0
    for g in items:
        gid = _to_int(str(g.get("id") or ""), -1)
        if gid <= 0:
            continue
        try:
            rep = await api.admin_get_game_report(gid)
            game = rep.get("game") or {}
            col_cards, row_cards = _winner_card_ids(game)
            payout_state = game.get("payout_state_json") if isinstance(game.get("payout_state_json"), dict) else {}
            col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
            col_absorbed_into_row = bool(col_info.get("absorbed_into_row", False))
        except ApiError:
            continue
        if not col_cards and not row_cards:
            skipped += 1
            continue
        winner_items.append(
            {
                "id": gid,
                "col_count": 0 if col_absorbed_into_row else len(col_cards),
                "row_count": len(row_cards),
                "card_price": int(game.get("card_price") or 0),
            }
        )

    page_no = (offset // PAGE_SIZE) + 1
    lines = [
        "این صفحه بازی‌های پایان‌یافته را برای بازبینی برنده‌ها نشان می‌دهد.",
        f"صفحه: <b>{page_no}</b>",
        "",
    ]

    if winner_items:
        lines.append("روی بازی بزن تا کارت‌های برنده تمام/تورنا با جزئیات نمایش داده شود 👇")
        lines.append("💳 قیمت هر کارت کنار هر بازی در دکمه‌ها نمایش داده شده است.")
    else:
        lines.append("در این صفحه بازی برنده‌دار پیدا نشد.")
        if skipped > 0:
            lines.append("بازی‌های بدون برنده فیلتر شدند؛ صفحه بعد را هم بررسی کن.")

    await safe_edit_or_send(
        cq.message,
        panel("🏆 آرشیو کارت‌های برنده", "\n".join(lines)),
        parse_mode="HTML",
        reply_markup=admin_winners_archive_kb(winner_items, offset=offset, has_next=has_next),
    )


@router.callback_query(F.data.startswith("admin:games:start:"))
async def admin_games_start(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_game_ctx_from_start(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    idem = f"START:{game_id}:{uuid.uuid4().hex[:12]}"
    prev_status = _single_game_status(status)

    try:
        await api.admin_start_game(game_id, idempotency_key=idem)
        rep = await api.admin_get_game_report(game_id)
        g = rep.get("game") or {}

        current_status = str(g.get("status") or "")
        current_status_fa = _fa_status(current_status)

        if current_status == "RUNNING" and prev_status == "RUNNING":
            action_text = "✅ بازی از قبل هم در حال اجرا بود؛ همه‌چیز رو رواله 😎"
        elif current_status == "RUNNING":
            action_text = "✅ بازی با موفقیت شروع شد؛ بریم برای اعلام عدد! 🚀"
        elif current_status == "ENDED":
            action_text = "ℹ️ این بازی پایان‌یافته‌ست و دوباره شروع نمی‌شه."
        else:
            action_text = f"ℹ️ وضعیت فعلی بازی: <b>{current_status_fa}</b>"

        topic_id = g.get("tg_topic_id")
        topic_info = ""
        if topic_id is not None:
            topic_num = _to_int(str(topic_id), 0)
            topic_info = (
                f"🧵 تاپیک: <b>{_topic_title(topic_num if topic_num > 0 else None)}</b>\n"
                f"🧩 شناسه تاپیک: <code>{topic_id}</code>\n"
            )

        txt = (
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"وضعیت: <b>{current_status_fa}</b>\n"
            f"گروه: <code>{g.get('tg_group_id')}</code>\n"
            f"{topic_info}"
            f"💳 قیمت کارت: <b>{g.get('card_price')}</b>\n"
            f"💰 فروش: <b>{g.get('sold_amount')}</b>\n"
            f"🎁 جایزه: <b>{g.get('prize_pool')}</b>\n\n"
            f"{action_text}"
        )

        await safe_edit_or_send(
            cq.message,
            panel("🕹️ ادمین بازی | شروع", txt),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=current_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
        await cq.answer("انجام شد ✅", show_alert=False)

    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)


@router.callback_query(F.data == "admin:games")
async def admin_games_home(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    try:
        await _render_games_list(cq, api, status=DEFAULT_STATUS, offset=0)
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(
    F.data.startswith("admin:games:close-lobby:")
    & ~F.data.startswith("admin:games:close-lobby:cancel")
)
async def admin_games_close_lobby(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_game_ctx_from_close_lobby(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        rep = await api.admin_get_game_report(game_id)
        g = rep.get("game") or {}
        purchases = rep.get("purchases") or {}
        called_numbers = _extract_numbers(rep.get("called_numbers") or [])
        game_status = str(g.get("status") or "")

        if not _can_close_lobby(
            g,
            purchases_count=int(purchases.get("purchases_count", 0) or 0),
            called_count=len(called_numbers),
        ):
            await safe_edit_or_send(
                cq.message,
                panel(
                    "بستن بازی لابی",
                    f"🎮 بازی: <b>#{game_id}</b>\n"
                    f"وضعیت فعلی: <b>{_fa_status(game_status)}</b>\n"
                    "در وضعیت فعلی امکان بستن لابی وجود ندارد.",
                ),
                parse_mode="HTML",
                reply_markup=admin_game_item_kb(
                    game_id=game_id,
                    status=status,
                    offset=offset,
                    game_status=game_status,
                    has_winners=_has_winners(g),
                    allow_close_lobby=False,
                ),
            )
            await state.clear()
            await cq.answer("امکان بستن نیست", show_alert=True)
            return

        await state.clear()
        await state.set_state(AdminGameCloseSG.waiting_reason)
        await state.update_data(game_id=game_id, status=status, offset=offset)

        await safe_edit_or_send(
            cq.message,
            panel(
                "علت کنسل بازی",
                f"🎮 بازی: <b>#{game_id}</b>\n"
                f"وضعیت: <b>{_fa_status(game_status)}</b>\n"
                f"💳 قیمت کارت: <b>{g.get('card_price')}</b>\n"
                f"🧾 تعداد خرید: <b>{purchases.get('purchases_count', 0)}</b>\n"
                f"🃏 تعداد کارت فروخته‌شده: <b>{purchases.get('cards_sold', 0)}</b>\n"
                f"💰 مبلغ فروش: <b>{g.get('sold_amount')}</b>\n\n"
                "علت کنسل بازی را در یک پیام بنویس.\n"
                "همین متن همراه مبلغ برگشتی برای خریداران ارسال می‌شود.",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_close_reason_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("علت کنسل را ارسال کن", show_alert=False)
    except ApiError as e:
        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel("خطا در بستن لابی", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)


@router.callback_query(F.data == "admin:games:close-lobby:cancel")
async def admin_games_close_lobby_cancel(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    data = await state.get_data()
    game_id = _to_int(str(data.get("game_id") or ""), -1)
    status = str(data.get("status") or DEFAULT_STATUS)
    offset = _to_int(str(data.get("offset") or "0"), 0)
    await state.clear()
    if game_id <= 0:
        await safe_edit_or_send(
            cq.message,
            panel("کنسل بستن بازی", "عملیات لغو شد."),
            parse_mode="HTML",
            reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
        )
        await cq.answer("لغو شد", show_alert=False)
        return
    try:
        rep = await api.admin_get_game_report(game_id)
        g = rep.get("game") or {}
        await safe_edit_or_send(
            cq.message,
            panel(
                "کنسل بستن بازی",
                f"عملیات بستن بازی <b>#{game_id}</b> لغو شد.\n"
                f"وضعیت فعلی: <b>{_fa_status(str(g.get('status') or ''))}</b>",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=str(g.get("status") or ""),
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
    except ApiError:
        await safe_edit_or_send(
            cq.message,
            panel("کنسل بستن بازی", "عملیات لغو شد."),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
    await cq.answer("لغو شد", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:list:"))
async def admin_games_list(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await state.clear()
    status, offset = _parse_list_cb(cq.data or "")
    try:
        await _render_games_list(cq, api, status=status, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data.startswith("admin:games:sales:range:"))
async def admin_games_sales_range_open(cq: CallbackQuery, state: FSMContext, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    parts = (cq.data or "").split(":")
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = max(0, _to_int(parts[5] if len(parts) > 5 else None, 0))
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 رفتن به گزارش مالی", callback_data="admin:finance:sales:range")
    kb.button(text="⬅️ بازگشت به لیست بازی‌ها", callback_data=f"admin:games:list:{status}:{offset}")
    kb.adjust(1)
    await safe_edit_or_send(
        cq.message,
        panel(
            "📊 انتقال گزارش فروش",
            "گزارش فروش بازه‌ای از بخش ادمین بازی به ادمین مالی منتقل شد.\n"
            "برای مشاهده گزارش، از دکمه زیر وارد ادمین مالی شو.",
        ),
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await cq.answer("به ادمین مالی منتقل شد", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:ensure:") & ~F.data.startswith("admin:games:ensure:topic:"))
async def admin_games_ensure_active(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    status, offset = _parse_ensure_ctx(cq.data or "")
    target_group_id = _resolve_target_group_id(cq)

    if target_group_id is None:
        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel(
                "ایجاد/فعال‌سازی بازی گروه",
                "شناسه گروه در این گفتگو مشخص نیست.\n"
                "این دکمه را داخل همان گروه بازی بزن، یا شناسه گروه پیش‌فرض را در تنظیمات ربات ثبت کن.",
            ),
            parse_mode="HTML",
            reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
        )
        await cq.answer("گروه مشخص نیست", show_alert=True)
        return

    topics = _configured_game_topics()
    if topics:
        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel(
                "🕹️ انتخاب تاپیک بازی",
                "مرحله <b>1 از 2</b>\n"
                "برای ساخت بازی جدید، ابتدا یکی از تاپیک‌های بازی را انتخاب کن.\n"
                "برای هر تاپیک فقط یک بازی فعال (در انتظار شروع/در حال اجرا) نگه داشته می‌شود.",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_create_topic_kb(status=status, offset=offset, topics=topics),
        )
        await cq.answer("تاپیک بازی را انتخاب کن", show_alert=False)
        return

    await _open_create_price_step(
        cq,
        state,
        api,
        status=status,
        offset=offset,
        target_group_id=target_group_id,
        target_topic_id=None,
    )
    await cq.answer("مبلغ کارت را ارسال کن", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:ensure:topic:"))
async def admin_games_ensure_topic(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    topic_id, status, offset = _parse_ensure_topic_ctx(cq.data or "")
    if topic_id <= 0:
        await cq.answer("شناسه تاپیک نامعتبر است.", show_alert=True)
        return

    allowed_topics = {topic for _, topic in _configured_game_topics()}
    if allowed_topics and topic_id not in allowed_topics:
        await cq.answer("این تاپیک برای بازی تعریف نشده است.", show_alert=True)
        return

    target_group_id = _resolve_target_group_id(cq)
    if target_group_id is None:
        await state.clear()
        await safe_edit_or_send(
            cq.message,
            panel(
                "ایجاد/فعال‌سازی بازی گروه",
                "شناسه گروه مشخص نیست.\n"
                "دوباره از منوی ادمین بازی اقدام کن.",
            ),
            parse_mode="HTML",
            reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
        )
        await cq.answer("گروه مشخص نیست", show_alert=True)
        return

    await _open_create_price_step(
        cq,
        state,
        api,
        status=status,
        offset=offset,
        target_group_id=target_group_id,
        target_topic_id=topic_id,
    )
    await cq.answer("مبلغ کارت را ارسال کن", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:create:cancel:"))
async def admin_games_create_cancel(
    cq: CallbackQuery,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    status, offset = _parse_create_cancel_ctx(cq.data or "")
    await state.clear()
    try:
        await _render_games_list(cq, api, status=status, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
    await cq.answer("لغو شد", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:winners:archive:"))
async def admin_games_winners_archive(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    offset = _parse_winners_archive_cb(cq.data or "")
    try:
        await _render_winners_archive(cq, api, offset=offset)
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
    await cq.answer()


@router.callback_query(F.data.startswith("admin:games:report:"))
async def admin_games_report(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    # admin:games:report:{game_id}:{status}:{offset}
    parts = (cq.data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        rep = await api.admin_get_game_report(game_id)

        g = rep.get("game") or {}
        purchases = rep.get("purchases") or {}
        called_numbers = rep.get("called_numbers") or []
        events = rep.get("events") or []
        game_status = str(g.get("status") or "")
        row_paid = int(g.get("row_paid", 0) or 0)
        col_paid = int(g.get("col_paid", 0) or 0)
        payout_state = g.get("payout_state_json") if isinstance(g.get("payout_state_json"), dict) else {}
        col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
        row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
        col_winner_users = list(dict.fromkeys(_int_list(col_info.get("winner_user_ids") or [])))
        col_winner_cards = list(dict.fromkeys(_int_list(col_info.get("winner_card_ids") or [])))
        row_winner_users = list(dict.fromkeys(_int_list(row_info.get("winner_user_ids") or [])))
        row_winner_cards = list(dict.fromkeys(_int_list(row_info.get("winner_card_ids") or [])))
        col_winner_tg_users = list(dict.fromkeys(_int_list(g.get("col_winner_tg_user_ids") or [])))
        row_winner_tg_users = list(dict.fromkeys(_int_list(g.get("row_winner_tg_user_ids") or [])))

        # Fallback: if tg_user_id list is missing, derive it from winner_cards payload.
        if (not col_winner_tg_users or not row_winner_tg_users) and isinstance(rep.get("winner_cards"), list):
            tg_by_card_id: dict[int, int] = {}
            for card in rep.get("winner_cards") or []:
                if not isinstance(card, dict):
                    continue
                card_id = _to_int(str(card.get("card_id") or ""), 0)
                tg_user_id = _to_int(str(card.get("tg_user_id") or ""), 0)
                if card_id > 0 and tg_user_id > 0 and card_id not in tg_by_card_id:
                    tg_by_card_id[card_id] = tg_user_id
            if not col_winner_tg_users and tg_by_card_id:
                col_winner_tg_users = list(dict.fromkeys([tg_by_card_id[cid] for cid in col_winner_cards if cid in tg_by_card_id]))
            if not row_winner_tg_users and tg_by_card_id:
                row_winner_tg_users = list(dict.fromkeys([tg_by_card_id[cid] for cid in row_winner_cards if cid in tg_by_card_id]))

        col_winner_names = await resolve_tg_identities(cq.bot, col_winner_tg_users)
        row_winner_names = await resolve_tg_identities(cq.bot, row_winner_tg_users)

        purchases_count = int(purchases.get("purchases_count", 0) or 0) if isinstance(purchases, dict) else len(purchases)
        nums = _extract_numbers(called_numbers)
        last_called = nums[-1] if nums else None

        topic_id = g.get("tg_topic_id")
        topic_info = ""
        if topic_id is not None:
            topic_num = _to_int(str(topic_id), 0)
            topic_info = (
                f"🧵 تاپیک: <b>{_topic_title(topic_num if topic_num > 0 else None)}</b>\n"
                f"🧩 شناسه تاپیک: <code>{topic_id}</code>\n"
            )

        txt = (
            f"🎮 بازی: <b>#{g.get('id', game_id)}</b>\n"
            f"وضعیت: <b>{_fa_status(game_status)}</b>\n"
            f"گروه: <code>{g.get('tg_group_id')}</code>\n"
            f"{topic_info}"
            f"💳 قیمت کارت: <b>{g.get('card_price')}</b>\n"
            f"💰 فروش: <b>{g.get('sold_amount')}</b>\n"
            f"🎁 جایزه: <b>{g.get('prize_pool')}</b>\n"
            f"🟡 آخرین عدد: <b>{last_called if last_called is not None else '—'}</b>\n"
            f"🧾 خریدها: <b>{purchases_count}</b>\n"
            f"🔢 تعداد اعداد خوانده‌شده: <b>{len(nums)}</b>\n"
            f"🗂 رویدادها: <b>{len(events)}</b>\n"
        )

        if nums:
            tail = nums[-12:]
            txt += "\n\nآخرین ۱۲ عدد:\n" + "  •  ".join(str(n) for n in tail)

        payout_lines: list[str] = []
        if col_paid == 1:
            payout_lines.append("✅ پرداخت برد تورنا انجام شد.")
            if col_winner_cards or col_winner_users or col_winner_tg_users:
                if col_winner_names:
                    payout_lines.append(
                        f"👤 برنده(های) تورنا: <b>{html_escape('، '.join(col_winner_names))}</b>"
                    )
                elif col_winner_users:
                    payout_lines.append(
                        f"👤 برنده(های) تورنا: <code>شناسه داخلی: {', '.join(str(x) for x in col_winner_users)}</code>"
                    )
                payout_lines.append(
                    f"🪪 کارت(های) تورنا: <code>{', '.join(str(x) for x in col_winner_cards) or '—'}</code>"
                )
        if row_paid == 1:
            payout_lines.append("🏁 پرداخت برد تمام انجام شد.")
            if row_winner_cards or row_winner_users or row_winner_tg_users:
                if row_winner_names:
                    payout_lines.append(
                        f"👤 برنده(های) تمام: <b>{html_escape('، '.join(row_winner_names))}</b>"
                    )
                elif row_winner_users:
                    payout_lines.append(
                        f"👤 برنده(های) تمام: <code>شناسه داخلی: {', '.join(str(x) for x in row_winner_users)}</code>"
                    )
                payout_lines.append(
                    f"🪪 کارت(های) تمام: <code>{', '.join(str(x) for x in row_winner_cards) or '—'}</code>"
                )
        if game_status.strip().upper() == "ENDED":
            payout_lines.append("⛔️ بازی تمام شده و اعلام عدد متوقف است.")
        if payout_lines:
            txt += "\n\n" + "\n".join(payout_lines)

        await safe_edit_or_send(
            cq.message,
            panel("🧾 گزارش بازی", txt),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g, purchases_count=purchases_count, called_count=len(nums)),
            ),
        )
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )

    await cq.answer()


@router.callback_query(
    F.data.startswith("admin:games:winners:")
    & ~F.data.startswith("admin:games:winners:archive:")
)
async def admin_games_winners(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    # admin:games:winners:{game_id}:{status}:{offset}
    parts = (cq.data or "").split(":")
    game_id = _to_int(parts[3] if len(parts) > 3 else None, -1)
    status = parts[4] if len(parts) > 4 and parts[4] else DEFAULT_STATUS
    offset = _to_int(parts[5] if len(parts) > 5 else None, 0)
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        rep = await api.admin_get_game_report(game_id)
        g = rep.get("game") or {}
        game_status = str(g.get("status") or "")
        called = _extract_numbers(rep.get("called_numbers") or [])
        called_set = set(called)
        col_winner_cards, row_winner_cards = _winner_card_ids(g)
        payout_state = g.get("payout_state_json") if isinstance(g.get("payout_state_json"), dict) else {}
        col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
        col_absorbed_into_row = bool(col_info.get("absorbed_into_row", False))

        cards_by_id: dict[int, dict] = {}
        for card in rep.get("winner_cards") or []:
            if not isinstance(card, dict):
                continue
            cid = _to_int(str(card.get("card_id") or ""), -1)
            if cid > 0:
                cards_by_id[cid] = card

        winner_tg_ids = sorted(
            {
                _to_int(str((card or {}).get("tg_user_id") or ""), 0)
                for card in cards_by_id.values()
                if _to_int(str((card or {}).get("tg_user_id") or ""), 0) > 0
            }
        )
        tg_name_map: dict[int, str] = {}
        for tg_uid in winner_tg_ids:
            tg_name_map[tg_uid] = await resolve_tg_identity(cq.bot, tg_uid)

        def _append_card_block(lines: list[str], card_id: int) -> None:
            card = cards_by_id.get(card_id) or {}
            user_id = _to_int(str(card.get("user_id") or ""), 0)
            tg_user_id = _to_int(str(card.get("tg_user_id") or ""), 0)
            numbers = _int_list(card.get("numbers") or [])
            grid = _render_card_grid(numbers, called_set) if numbers else "—"
            display_name = tg_name_map.get(tg_user_id, "—") if tg_user_id > 0 else "—"

            lines.append(
                f"🪪 <b>کارت #{card_id}</b> | کاربر: <b>{html_escape(display_name)}</b> | شناسه داخلی: <code>{user_id or '—'}</code>"
            )
            lines.append(f"<code>{grid}</code>")

        lines: list[str] = [
            f"🎮 بازی: <b>#{game_id}</b>",
            f"وضعیت: <b>{_fa_status(game_status)}</b>",
            f"تعداد اعداد اعلام‌شده: <b>{len(called)}</b>",
            "",
            "راهنما: ✅ عدد اعلام‌شده | ⬜️ عدد اعلام‌نشده",
            "",
        ]

        if col_winner_cards and not col_absorbed_into_row:
            lines += [
                "🏆 <b>برنده‌های تورنا</b>",
                f"🪪 کارت(ها): <code>{', '.join(str(x) for x in col_winner_cards)}</code>",
            ]
            for cid in col_winner_cards:
                _append_card_block(lines, cid)
            lines.append("")
        elif col_winner_cards and col_absorbed_into_row:
            lines.append("ℹ️ سهم جایزه تورنا در همین برد تمام تسویه شده و برد تورنا جدا ثبت نشده است.")
            lines.append("")

        if row_winner_cards:
            lines += [
                "🏁 <b>برنده‌های تمام</b>",
                f"🪪 کارت(ها): <code>{', '.join(str(x) for x in row_winner_cards)}</code>",
            ]
            for cid in row_winner_cards:
                _append_card_block(lines, cid)
            lines.append("")

        if not col_winner_cards and not row_winner_cards:
            lines.append("هنوز کارت برنده تمام/تورنا ثبت نشده است.")

        await safe_edit_or_send(
            cq.message,
            panel("🏆 کارت‌های برنده", "\n".join(lines).strip()),
            parse_mode="HTML",
            reply_markup=admin_winners_kb(game_id=game_id, status=status, offset=offset),
        )
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )

    await cq.answer()


@router.callback_query(
    F.data.startswith("admin:games:monitor:")
    & ~F.data.startswith("admin:games:monitor:refresh:")
    & ~F.data.startswith("admin:games:monitor:auto:")
)
async def admin_monitor_open(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_monitor_open_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        await _render_monitor_view(cq.message, api, game_id=game_id, status=status, offset=offset)
    except ApiError as e:
        auto_on = _monitor_is_on(cq.message.chat.id, game_id)
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_monitor_kb(game_id=game_id, status=status, offset=offset, auto_on=auto_on),
        )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:games:monitor:refresh:"))
async def admin_monitor_refresh(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_monitor_refresh_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        await _render_monitor_view(cq.message, api, game_id=game_id, status=status, offset=offset)
    except ApiError as e:
        auto_on = _monitor_is_on(cq.message.chat.id, game_id)
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_monitor_kb(game_id=game_id, status=status, offset=offset, auto_on=auto_on),
        )
    await cq.answer("تازه‌سازی شد", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:monitor:auto:on:"))
async def admin_monitor_auto_on(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_monitor_auto_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    chat_id = cq.message.chat.id
    existing = _monitor_job(chat_id)
    if existing and existing.game_id == game_id:
        await cq.answer("به‌روزرسانی خودکار از قبل روشن است", show_alert=False)
        return

    if existing:
        existing.task.cancel()

    task = asyncio.create_task(_monitor_loop(api, cq.message, game_id=game_id, status=status, offset=offset))
    ADMIN_MONITORS[chat_id] = MonitorJob(
        task=task,
        message_id=cq.message.message_id,
        chat_id=chat_id,
        game_id=game_id,
    )

    await cq.answer("به‌روزرسانی خودکار روشن شد ✅", show_alert=False)

    try:
        await _render_monitor_view(cq.message, api, game_id=game_id, status=status, offset=offset, force_auto=True)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_monitor_kb(game_id=game_id, status=status, offset=offset, auto_on=True),
        )


@router.callback_query(F.data.startswith("admin:games:monitor:auto:off:"))
async def admin_monitor_auto_off(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_monitor_auto_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    _stop_monitor(cq.message.chat.id)

    try:
        await _render_monitor_view(cq.message, api, game_id=game_id, status=status, offset=offset, force_auto=False)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_monitor_kb(game_id=game_id, status=status, offset=offset, auto_on=False),
        )
    await cq.answer("به‌روزرسانی خودکار متوقف شد 🛑", show_alert=False)



@router.callback_query(F.data.startswith("admin:games:live:set:"))
async def admin_games_live_set(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    _, game_id, status, offset = _parse_live_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return
    _set_live_send_cache(cq.message.chat.id, game_id, url="", failed_tg_ids=[])

    try:
        meta = await api.admin_get_game_live_link(game_id)
        current_url = str(meta.get("url") or "").strip()
        participants_count = _to_int(str(meta.get("participants_count") or "0"), 0)

        await state.clear()
        await state.set_state(AdminGameLiveSG.waiting_url)
        await state.update_data(game_id=game_id, status=status, offset=offset)

        lines = [
            f"🎮 بازی: <b>#{game_id}</b>",
            f"👥 شرکت‌کننده‌ها (خریدار کارت): <b>{participants_count}</b>",
            "",
            "لینک پخش زنده را ارسال کن.",
            "لینک باید با <code>http://</code> یا <code>https://</code> شروع شود.",
            "برای لغو: <code>لغو</code> یا <code>/cancel</code>",
        ]
        if current_url:
            lines += [
                "",
                "🔗 لینک فعلی:",
                f"<code>{html_escape(current_url)}</code>",
            ]
        else:
            lines += [
                "",
                "هنوز لینکی ثبت نشده است.",
            ]

        await safe_edit_or_send(
            cq.message,
            panel("🎥 تنظیم لینک لایو", "\n".join(lines)),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("منتظر لینک هستم…", show_alert=False)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)


@router.callback_query(F.data.startswith("admin:games:live:send:"))
async def admin_games_live_send(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    _, game_id, status, offset = _parse_live_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        meta = await api.admin_get_game_live_link(game_id)
        url = str(meta.get("url") or "").strip()
        if not url:
            await cq.answer("اول لینک لایو را تنظیم کن.", show_alert=True)
            return

        participants_payload = await api.admin_list_game_participants(game_id, only_with_tg=True)
        participants = _extract_participant_items(participants_payload)
        if not participants:
            await cq.answer("برای این بازی شرکت‌کننده‌ای با تلگرام ثبت نشده است.", show_alert=True)
            return

        await cq.answer("در حال ارسال لینک لایو…", show_alert=False)
        sent, failed, failed_ids = await _broadcast_live_link(
            cq,
            game_id=game_id,
            url=url,
            participants=participants,
        )
        _set_live_send_cache(
            cq.message.chat.id,
            game_id,
            url=url,
            failed_tg_ids=failed_ids,
        )

        lines = [
            f"🎮 بازی: <b>#{game_id}</b>",
            f"🔗 لینک فعال: <code>{html_escape(url)}</code>",
            f"👥 کل گیرنده‌ها: <b>{len(participants)}</b>",
            f"✅ ارسال موفق: <b>{sent}</b>",
            f"❌ ارسال ناموفق: <b>{failed}</b>",
        ]
        if failed_ids:
            failed_names = await resolve_tg_identities(cq.bot, failed_ids)
            lines += [
                "",
                "👤 ارسال‌نشده‌ها:",
                f"<b>{html_escape('، '.join(failed_names))}</b>",
            ]

        await safe_edit_or_send(
            cq.message,
            panel("📣 ارسال لینک لایو", "\n".join(lines)),
            parse_mode="HTML",
            reply_markup=_live_send_result_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                has_failed=bool(failed_ids),
            ),
        )
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)



@router.callback_query(F.data.startswith("admin:games:live:resend:"))
async def admin_games_live_resend(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    _, game_id, status, offset = _parse_live_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    cache_item = _get_live_send_cache(cq.message.chat.id, game_id)
    if not cache_item or not cache_item.failed_tg_ids:
        await cq.answer("لیست ارسال‌نشده‌ها پیدا نشد یا منقضی شده است.", show_alert=True)
        return

    url = str(cache_item.url or "").strip()
    try:
        meta = await api.admin_get_game_live_link(game_id)
        latest_url = str(meta.get("url") or "").strip()
        if latest_url:
            url = latest_url
    except ApiError:
        pass

    if not url:
        await cq.answer("لینک لایو موجود نیست. ابتدا لینک را تنظیم کن.", show_alert=True)
        return

    participants = [{"tg_user_id": int(x)} for x in cache_item.failed_tg_ids if int(x) > 0]
    if not participants:
        _set_live_send_cache(cq.message.chat.id, game_id, url=url, failed_tg_ids=[])
        await cq.answer("موردی برای ارسال مجدد وجود ندارد.", show_alert=True)
        return

    await cq.answer("در حال ارسال مجدد به ناموفق‌ها…", show_alert=False)
    sent, failed, failed_ids = await _broadcast_live_link(
        cq,
        game_id=game_id,
        url=url,
        participants=participants,
    )
    _set_live_send_cache(
        cq.message.chat.id,
        game_id,
        url=url,
        failed_tg_ids=failed_ids,
    )

    lines = [
        f"🎮 بازی: <b>#{game_id}</b>",
        f"🔗 لینک فعال: <code>{html_escape(url)}</code>",
        f"👥 تعداد هدف در ارسال مجدد: <b>{len(participants)}</b>",
        f"✅ ارسال موفق: <b>{sent}</b>",
        f"❌ هنوز ناموفق: <b>{failed}</b>",
    ]
    if failed_ids:
        failed_names = await resolve_tg_identities(cq.bot, failed_ids)
        lines += [
            "",
            "👤 هنوز ارسال‌نشده:",
            f"<b>{html_escape('، '.join(failed_names))}</b>",
        ]

    await safe_edit_or_send(
        cq.message,
        panel("🔁 ارسال مجدد لینک لایو", "\n".join(lines)),
        parse_mode="HTML",
        reply_markup=_live_send_result_kb(
            game_id=game_id,
            status=status,
            offset=offset,
            has_failed=bool(failed_ids),
        ),
    )


@router.callback_query(F.data.startswith("admin:games:live:clear:"))
async def admin_games_live_clear(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    _, game_id, status, offset = _parse_live_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return
    _set_live_send_cache(cq.message.chat.id, game_id, url="", failed_tg_ids=[])

    await state.clear()
    try:
        meta = await api.admin_clear_game_live_link(game_id)
        participants_count = _to_int(str(meta.get("participants_count") or "0"), 0)

        game_status = ""
        g: dict = {}
        try:
            rep = await api.admin_get_game_report(game_id)
            g = rep.get("game") or {}
            game_status = str(g.get("status") or "")
        except ApiError:
            pass

        await safe_edit_or_send(
            cq.message,
            panel(
                "🧹 حذف لینک لایو",
                f"🎮 بازی: <b>#{game_id}</b>\n"
                "لینک لایو بازی پاک شد.\n"
                f"👥 شرکت‌کننده‌ها (خریدار کارت): <b>{participants_count}</b>",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
        await cq.answer("لینک پاک شد ✅", show_alert=False)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)
@router.callback_query(F.data.startswith("admin:games:view:"))
async def admin_games_view(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_view_cb(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        rep = await api.admin_get_game_report(game_id)
        g = rep.get("game") or {}
        game_status = str(g.get("status") or "")
        payout_state = g.get("payout_state_json") if isinstance(g.get("payout_state_json"), dict) else {}
        col_info = payout_state.get("col", {}) if isinstance(payout_state.get("col"), dict) else {}
        row_info = payout_state.get("row", {}) if isinstance(payout_state.get("row"), dict) else {}
        col_cards = [int(x) for x in (col_info.get("winner_card_ids") or []) if str(x).isdigit()]
        row_cards = [int(x) for x in (row_info.get("winner_card_ids") or []) if str(x).isdigit()]
        winner_lines: list[str] = []
        if int(g.get("col_paid", 0) or 0) == 1:
            winner_lines.append(f"🏆 کارت(های) برنده ستون: <code>{', '.join(str(x) for x in col_cards) or '—'}</code>")
        if int(g.get("row_paid", 0) or 0) == 1:
            winner_lines.append(f"🏁 کارت(های) برنده ردیف: <code>{', '.join(str(x) for x in row_cards) or '—'}</code>")

        topic_id = g.get("tg_topic_id")
        topic_info = ""
        if topic_id is not None:
            topic_num = _to_int(str(topic_id), 0)
            topic_info = (
                f"🧵 تاپیک: <b>{_topic_title(topic_num if topic_num > 0 else None)}</b>\n"
                f"🧩 شناسه تاپیک: <code>{topic_id}</code>\n"
            )

        txt = (
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"وضعیت: <b>{_fa_status(game_status)}</b>\n"
            f"قیمت کارت: <b>{g.get('card_price')}</b>\n"
            f"گروه: <code>{g.get('tg_group_id')}</code>\n"
            f"{topic_info}"
            f"فروش: <b>{g.get('sold_amount')}</b>\n"
            f"جایزه: <b>{g.get('prize_pool')}</b>\n"
            f"{f'{chr(10).join(winner_lines)}{chr(10)}' if winner_lines else ''}\n"
            "از دکمه‌های پایین می‌تونی بازی رو مدیریت کنی 👇"
        )
        await safe_edit_or_send(
            cq.message,
            panel("🕹️ ادمین بازی | جزئیات", txt),
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
            parse_mode="HTML",
        )
    except ApiError as e:
        await safe_edit_or_send(cq.message, panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")

    await cq.answer()


@router.callback_query(F.data.startswith("admin:games:call:"))
async def admin_call_start(cq: CallbackQuery, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_game_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    try:
        rep = await api.admin_get_game_report(game_id)
    except ApiError as e:
        await safe_edit_or_send(
            cq.message,
            panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)
        return

    g = rep.get("game") or {}
    game_status = str(g.get("status") or "")
    if game_status.strip().upper() != "RUNNING":
        txt = (
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"وضعیت فعلی: <b>{_fa_status(game_status)}</b>\n\n"
            "در وضعیت فعلی امکان اعلام عدد وجود ندارد."
        )
        await safe_edit_or_send(
            cq.message,
            panel("اعلام عدد", txt),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
        await cq.answer("بازی در حال اجرا نیست", show_alert=False)
        return

    await state.set_state(AdminCallSG.waiting_number)
    await state.update_data(game_id=game_id, status=status, offset=offset)

    await safe_edit_or_send(
        cq.message,
        panel("🔢 اعلام عدد", f"🎮 بازی <b>#{game_id}</b>\nیه عدد بین <b>1</b> تا <b>99</b> بفرست 👇"),
        parse_mode="HTML",
        reply_markup=admin_game_item_kb(
            game_id=game_id,
            status=status,
            offset=offset,
            game_status=game_status,
            has_winners=_has_winners(g),
            allow_close_lobby=_can_close_lobby(g),
        ),
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:games:undo:"))
async def admin_games_undo_confirm(cq: CallbackQuery, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset = _parse_undo_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    nonce = int(time.time())
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ بله، بازگردانی کن", callback_data=f"admin:games:undo2:{game_id}:{status}:{offset}:{nonce}")
    kb.button(text="❌ لغو", callback_data=f"admin:games:view:{game_id}:{status}:{offset}")
    kb.adjust(1, 1)

    await safe_edit_or_send(
        cq.message,
        panel(
            "⚠️ تایید بازگردانی",
            f"🎮 بازی <b>#{game_id}</b>\n\n"
            "می‌خوای <b>آخرین شماره</b> حذف بشه؟\n"
            "این عمل می‌تونه روی وضعیت پرداخت تاثیر بذاره.",
        ),
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("admin:games:undo2:"))
async def admin_games_undo_execute(cq: CallbackQuery, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await cq.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    game_id, status, offset, nonce = _parse_undo2_ctx(cq.data or "")
    if game_id <= 0:
        await cq.answer("شناسه بازی نامعتبر است.", show_alert=True)
        return

    idem = f"UNDO:{game_id}:{nonce}"

    try:
        out = await api.admin_undo_last_call(game_id, idempotency_key=idem)
        undone = out.get("undone_number", "-")
        called_count = out.get("called_count", "-")
        out_status = str(out.get("status") or _single_game_status(status) or "RUNNING")

        msg = (
            f"🎮 بازی <b>#{game_id}</b>\n"
            "↩️ <b>بازگردانی انجام شد ✅</b>\n"
            f"🔢 شماره حذف‌شده: <b>{undone}</b>\n"
            f"📌 تعداد شماره‌ها: <b>{called_count}</b>\n"
            f"وضعیت فعلی: <b>{_fa_status(out_status)}</b>"
        )

        await safe_edit_or_send(
            cq.message,
            panel("نتیجه بازگردانی", msg),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=out_status,
                has_winners=(int(out.get("col_paid", 0) or 0) == 1 or int(out.get("row_paid", 0) or 0) == 1),
                allow_close_lobby=(str(out_status).strip().upper() == "LOBBY"),
            ),
        )
        await cq.answer("بازگردانی شد ✅", show_alert=False)
    except ApiError as e:
        detail = str(getattr(e, "raw_detail", "") or e.detail or "")
        hint = ""
        lower = detail.lower()
        if "insufficient" in lower or "balance" in lower:
            hint = "\n\n⚠️ احتمالاً موجودی برنده برای برگشت جایزه کافی نیست."

        await safe_edit_or_send(
            cq.message,
            panel("خطا در بازگردانی", f"<code>{e.status}</code>\n<code>{e.detail}</code>{hint}"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        await cq.answer("خطا", show_alert=False)


@router.message(AdminGameCloseSG.waiting_reason)
async def admin_games_close_lobby_reason_submit(
    m: Message,
    state: FSMContext,
    api: ApiClient,
    is_admin: bool = False,
):
    if not require_admin(is_admin):
        await safe_send(m, "اجازه دسترسی نداری.")
        await state.clear()
        return

    data = await state.get_data()
    game_id = _to_int(str(data.get("game_id") or ""), -1)
    status = str(data.get("status") or DEFAULT_STATUS)
    offset = _to_int(str(data.get("offset") or "0"), 0)

    if game_id <= 0:
        await safe_send(m, panel("خطا", "اطلاعات بازی معتبر نیست. دوباره از منوی ادمین اقدام کن."), parse_mode="HTML")
        await state.clear()
        return

    reason = str(m.text or "").strip()
    if len(reason) < 3:
        await safe_send(
            m,
            panel("علت کنسل نامعتبر", "حداقل ۳ کاراکتر برای علت کنسل ارسال کن."),
            parse_mode="HTML",
            reply_markup=admin_game_close_reason_kb(game_id=game_id, status=status, offset=offset),
        )
        return
    reason = reason[:500]

    idem = f"CLOSE_LOBBY:{game_id}:{uuid.uuid4().hex[:12]}"

    try:
        out = await api.admin_set_game_status(
            game_id,
            status="ENDED",
            idempotency_key=idem,
            cancel_reason=reason,
        )
    except ApiError as e:
        detail = str(getattr(e, "raw_detail", "") or e.detail or "")
        lower = detail.lower()
        human = detail
        if "only lobby game can be closed" in lower:
            human = "فقط بازی در وضعیت لابی قابل بستن است."
        elif "numbers already called" in lower:
            human = "برای این بازی عدد اعلام شده؛ امکان بستن لابی وجود ندارد."
        elif "cancel_reason is required" in lower:
            human = "علت کنسل ارسال نشده است."

        await safe_send(
            m,
            panel("خطا در بستن لابی", f"<code>{e.status}</code>\n{human}"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        return

    await state.clear()

    rep: dict = {}
    g: dict = out if isinstance(out, dict) else {}
    try:
        rep = await api.admin_get_game_report(game_id)
        g = rep.get("game") or g
    except ApiError:
        pass

    final_status = str(g.get("status") or (out.get("status") if isinstance(out, dict) else "") or "ENDED")
    card_price = _to_int(str(g.get("card_price") or "0"), 0)

    participants: list[dict] = []
    try:
        participants_payload = await api.admin_list_game_participants(game_id, only_with_tg=False)
        participants = _extract_participant_items(participants_payload)
    except ApiError:
        participants = []

    notified_ok = 0
    notify_failed = 0
    no_tg_count = 0
    refund_total = 0
    refund_users_count = 0
    if participants:
        notified_ok, notify_failed, no_tg_count, refund_total, refund_users_count = await _notify_lobby_cancel_refunds(
            m,
            game_id=game_id,
            card_price=card_price,
            cancel_reason=reason,
            participants=participants,
        )

    txt = (
        f"🎮 بازی: <b>#{game_id}</b>\n"
        f"وضعیت نهایی: <b>{_fa_status(final_status)}</b>\n"
        f"📝 علت کنسل: <b>{html_escape(reason)}</b>\n"
        f"👥 کاربران مشمول بازگشت: <b>{refund_users_count}</b>\n"
        f"💰 مجموع مبلغ برگشتی: <b>{refund_total:,}</b>\n"
        f"📩 پیام موفق: <b>{notified_ok}</b>\n"
        f"⚠️ پیام ناموفق: <b>{notify_failed}</b>\n"
        f"ℹ️ بدون شناسه تلگرام: <b>{no_tg_count}</b>"
    )

    await safe_send(
        m,
        panel("بستن بازی لابی", txt),
        parse_mode="HTML",
        reply_markup=admin_game_item_kb(
            game_id=game_id,
            status=status,
            offset=offset,
            game_status=final_status,
            has_winners=_has_winners(g),
            allow_close_lobby=False,
        ),
    )


@router.message(AdminGameCreateSG.waiting_card_price)
async def admin_game_create_price_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await safe_send(m, "اجازه دسترسی نداری.")
        await state.clear()
        return

    data = await state.get_data()
    status = str(data.get("status") or DEFAULT_STATUS)
    offset = max(0, _to_int(str(data.get("offset") or "0"), 0))
    group_id = _to_int(str(data.get("target_group_id") or ""), 0)
    topic_id_raw = data.get("target_topic_id")
    topic_id = _to_int(str(topic_id_raw), 0) if topic_id_raw is not None else None
    if topic_id is not None and topic_id <= 0:
        topic_id = None

    raw_text = (m.text or "").strip()
    if raw_text.lower() in {"cancel", "/cancel", "لغو"}:
        await state.clear()
        await safe_send(
            m,
            panel("ایجاد/فعال‌سازی بازی گروه", "ایجاد بازی لغو شد."),
            parse_mode="HTML",
            reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
        )
        return

    card_price = _parse_card_price_input(raw_text)
    if card_price is None:
        await safe_send(
            m,
            panel(
                "ایجاد/فعال‌سازی بازی گروه",
                "❌ مبلغ نامعتبر است.\n"
                "فقط عدد مثبت (به تومان) بفرست.\n"
                "مثال: <code>100000</code>",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_create_price_kb(status=status, offset=offset),
        )
        return

    if group_id == 0:
        await state.clear()
        await safe_send(
            m,
            panel("خطا", "شناسه گروه نامعتبر است. دوباره از منوی ادمین بازی اقدام کن."),
            parse_mode="HTML",
            reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
        )
        return

    try:
        active_before = await _get_active_game_for_group(api, group_id=group_id, topic_id=topic_id)
        active_before_id = _to_int(str((active_before or {}).get("id") or ""), -1)
        g = await api.ensure_active_game_for_group(group_id, card_price=card_price, tg_topic_id=topic_id)
        await state.clear()
        game_id = _to_int(str(g.get("id") or ""), -1)
        game_status = str(g.get("status") or "")
        result_price = _to_int(str(g.get("card_price") or ""), card_price)
        reused_active = bool(active_before_id > 0 and active_before_id == game_id)

        if game_id <= 0:
            await safe_send(
                m,
                panel("🕹️ ادمین بازی | بازی گروه", "ساخت/فعال‌سازی انجام نشد. دوباره تلاش کن."),
                parse_mode="HTML",
                reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
            )
            return

        note_lines: list[str] = []
        if reused_active:
            note_lines.append("ℹ️ بازی فعال از قبل وجود داشت؛ بازی جدید ساخته نشد.")
            if result_price != card_price:
                note_lines.append(
                    "⚠️ مبلغ واردشده روی بازی فعال فعلی اعمال نشد. برای اعمال مبلغ جدید، بازی فعال فعلی را تمام/بسته کن و سپس بازی جدید بساز."
                )
            else:
                note_lines.append("✅ مبلغ واردشده با قیمت کارت بازی فعال یکسان است.")
        else:
            note_lines.append("✅ بازی جدید ساخته شد و مبلغ واردشده برای آن اعمال شد.")
            if result_price != card_price and str(game_status).strip().upper() in {"LOBBY", "RUNNING"}:
                note_lines.append(
                    "⚠️ یک بازی فعال موجود بوده یا همزمان ساخته شده؛ قیمت کارت بازی فعال با مبلغ واردشده متفاوت است."
                )

        topic_info = ""
        if topic_id is not None:
            topic_info = (
                f"🧵 تاپیک: <b>{_topic_title(topic_id)}</b>\n"
                f"🧩 شناسه تاپیک: <code>{topic_id}</code>\n"
            )

        txt = (
            "مرحله <b>2 از 2</b> — انجام شد ✅\n\n"
            f"🎮 بازی: <b>#{game_id}</b>\n"
            f"گروه: <code>{group_id}</code>\n"
            f"{topic_info}"
            f"وضعیت: <b>{_fa_status(game_status)}</b>\n"
            f"💵 مبلغ واردشده: <b>{card_price:,}</b> تومان\n"
            f"💳 قیمت کارت بازی: <b>{result_price:,}</b> تومان\n\n"
            + "\n".join(note_lines)
        )
        await safe_send(
            m,
            panel("🕹️ ادمین بازی | بازی گروه", txt),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=(int(g.get("col_paid", 0) or 0) == 1 or int(g.get("row_paid", 0) or 0) == 1),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
    except ApiError as e:
        await safe_send(
            m,
            panel(
                "خطا در ایجاد بازی",
                f"<code>{e.status}</code>\n<code>{e.detail}</code>\n\n"
                "مبلغ را دوباره درست وارد کن یا لغو بزن.",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_create_price_kb(status=status, offset=offset),
        )



@router.message(AdminGameLiveSG.waiting_url)
async def admin_game_live_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await safe_send(m, "اجازه دسترسی نداری.")
        await state.clear()
        return

    data = await state.get_data()
    game_id = _to_int(str(data.get("game_id") or ""), -1)
    status = str(data.get("status") or DEFAULT_STATUS)
    offset = max(0, _to_int(str(data.get("offset") or "0"), 0))

    if game_id <= 0:
        await state.clear()
        await safe_send(
            m,
            panel("خطا", "نشست تنظیم لینک نامعتبر شد. دوباره از منوی ادمین بازی اقدام کن."),
            parse_mode="HTML",
            reply_markup=admin_games_list_kb([], status=status, offset=offset, has_next=False),
        )
        return

    raw_text = (m.text or "").strip()
    if raw_text.lower() in {"cancel", "/cancel", "لغو"}:
        await state.clear()

        game_status = ""
        g: dict = {}
        try:
            rep = await api.admin_get_game_report(game_id)
            g = rep.get("game") or {}
            game_status = str(g.get("status") or "")
        except ApiError:
            pass

        await safe_send(
            m,
            panel("🎥 تنظیم لینک لایو", "عملیات ثبت لینک لایو لغو شد."),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
        return

    if not raw_text:
        await safe_send(
            m,
            panel(
                "🎥 تنظیم لینک لایو",
                "لینک خالی است. یک لینک معتبر بفرست.\n"
                "مثال: <code>https://example.com/live/room-1</code>",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        return

    if not (raw_text.startswith("http://") or raw_text.startswith("https://")):
        await safe_send(
            m,
            panel(
                "🎥 تنظیم لینک لایو",
                "لینک نامعتبر است.\n"
                "لینک باید با <code>http://</code> یا <code>https://</code> شروع شود.",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )
        return

    try:
        out = await api.admin_set_game_live_link(game_id, url=raw_text)
        await state.clear()

        participants_count = _to_int(str(out.get("participants_count") or "0"), 0)

        game_status = ""
        g: dict = {}
        try:
            rep = await api.admin_get_game_report(game_id)
            g = rep.get("game") or {}
            game_status = str(g.get("status") or "")
        except ApiError:
            pass

        await safe_send(
            m,
            panel(
                "🎥 لینک لایو ثبت شد",
                f"🎮 بازی: <b>#{game_id}</b>\n"
                f"🔗 لینک: <code>{html_escape(str(out.get('url') or raw_text))}</code>\n"
                f"👥 شرکت‌کننده‌ها (خریدار کارت): <b>{participants_count}</b>\n"
                "حالا می‌تونی از دکمه «ارسال لینک لایو» برای اطلاع‌رسانی به شرکت‌کننده‌ها استفاده کنی.",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=game_status,
                has_winners=_has_winners(g),
                allow_close_lobby=_can_close_lobby(g),
            ),
        )
    except ApiError as e:
        await safe_send(
            m,
            panel("خطا در ثبت لینک", f"<code>{e.status}</code>\n<code>{e.detail}</code>"),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
        )


@router.message(AdminCallSG.waiting_number)
async def admin_call_submit(m: Message, state: FSMContext, api: ApiClient, is_admin: bool = False):
    if not require_admin(is_admin):
        await safe_send(m, "اجازه دسترسی نداری.")
        await state.clear()
        return

    data = await state.get_data()
    game_id = int(data["game_id"])
    status = str(data["status"])
    offset = int(data["offset"])

    txt = (m.text or "").strip()
    if not txt.isdigit():
        await safe_send(m, "❌ فقط عدد بفرست؛ مثلاً <code>42</code> 😉", parse_mode="HTML")
        return

    number = int(txt)
    if not (1 <= number <= 99):
        await safe_send(m, "❌ عدد باید بین <b>1</b> تا <b>99</b> باشه.", parse_mode="HTML")
        return

    msg_id = int(getattr(m, "message_id", 0) or 0)
    chat_id = int(getattr(getattr(m, "chat", None), "id", 0) or 0)
    # Deterministic idempotency: same Telegram message => same key.
    idem = f"CALL:{game_id}:{number}:CHAT:{chat_id}:MSG:{msg_id}"

    try:
        out = await api.admin_call_number(game_id, number=number, idempotency_key=idem)
        await state.clear()

        row_paid = int(out.get("row_paid", 0) or 0)
        next_status = "ENDED" if row_paid == 1 else "RUNNING"
        called_count = out.get("called_count")

        extra = ""
        if called_count is not None:
            extra += f"\n📌 تعداد اعداد اعلام‌شده: <b>{called_count}</b>"
        if row_paid == 1:
            extra += "\n🎉 تبریک! با این عدد بازی به پایان رسید."

        await safe_send(
            m,
            panel(
                "اعلام شد ✅",
                f"🎮 بازی <b>#{game_id}</b>\n"
                f"🔢 عدد اعلام‌شده: <b>{number}</b>"
                f"{extra}",
            ),
            parse_mode="HTML",
            reply_markup=admin_game_item_kb(
                game_id=game_id,
                status=status,
                offset=offset,
                game_status=next_status,
                has_winners=(int(out.get("col_paid", 0) or 0) == 1 or int(out.get("row_paid", 0) or 0) == 1),
                allow_close_lobby=False,
            ),
        )
    except ApiError as e:
        detail = str(getattr(e, "raw_detail", "") or e.detail or "")
        lower = detail.lower()
        if e.status == 400 and "game is not running" in lower:
            await state.clear()

            try:
                rep = await api.admin_get_game_report(game_id)
                g = rep.get("game") or {}
                live_status = str(g.get("status") or "")
                last_called = None
                nums = _extract_numbers(rep.get("called_numbers") or [])
                if nums:
                    last_called = nums[-1]

                msg = (
                    f"🎮 بازی: <b>#{game_id}</b>\n"
                    f"وضعیت فعلی: <b>{_fa_status(live_status)}</b>\n"
                    f"آخرین عدد: <b>{last_called if last_called is not None else '—'}</b>\n\n"
                    "اعلام عدد انجام نشد چون بازی دیگر در حال اجرا نیست."
                )
                await safe_send(
                    m,
                    panel("امکان اعلام عدد نیست", msg),
                    parse_mode="HTML",
                    reply_markup=admin_game_item_kb(
                        game_id=game_id,
                        status=status,
                        offset=offset,
                        game_status=live_status,
                        has_winners=_has_winners(g),
                        allow_close_lobby=_can_close_lobby(g, called_count=len(nums)),
                    ),
                )
            except ApiError:
                await safe_send(
                    m,
                    panel("امکان اعلام عدد نیست", "اعلام عدد انجام نشد چون بازی دیگر در حال اجرا نیست."),
                    parse_mode="HTML",
                    reply_markup=admin_game_item_kb(game_id=game_id, status=status, offset=offset),
                )
            return

        await safe_send(m, panel("خطا", f"<code>{e.status}</code>\n<code>{e.detail}</code>"), parse_mode="HTML")
