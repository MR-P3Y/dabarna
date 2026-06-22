from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from bot.config import settings
from bot.services.jalali import format_jalali_datetime
from bot.services.notify_store import get_meta_marker, set_meta_marker

TopicName = Literal["general", "winners", "withdraw", "deposit", "income", "games", "alerts", "antifraud", "game_audit", "users"]
_META_RULES_VERSION = "admin_topics_rules_v2"


def forum_enabled() -> bool:
    return settings.ADMIN_FORUM_CHAT_ID is not None and int(settings.ADMIN_FORUM_CHAT_ID) < 0


def topic_id(name: TopicName) -> int | None:
    if name == "general":
        return settings.ADMIN_TOPIC_GENERAL_ID
    if name == "winners":
        return settings.ADMIN_TOPIC_WINNERS_ID
    if name == "withdraw":
        return settings.ADMIN_TOPIC_WITHDRAW_ID
    if name == "deposit":
        return settings.ADMIN_TOPIC_DEPOSIT_ID
    if name == "income":
        return settings.ADMIN_TOPIC_INCOME_ID or settings.ADMIN_TOPIC_GENERAL_ID
    if name == "games":
        return settings.ADMIN_TOPIC_GAMES_ID or settings.ADMIN_TOPIC_GENERAL_ID
    if name == "alerts":
        return settings.ADMIN_TOPIC_ALERTS_ID or settings.ADMIN_TOPIC_GENERAL_ID
    if name == "antifraud":
        return settings.ADMIN_TOPIC_ANTIFRAUD_ID or settings.ADMIN_TOPIC_DEPOSIT_ID or settings.ADMIN_TOPIC_GENERAL_ID
    if name == "game_audit":
        return settings.ADMIN_TOPIC_GAME_AUDIT_ID or settings.ADMIN_TOPIC_GAMES_ID or settings.ADMIN_TOPIC_GENERAL_ID
    if name == "users":
        return settings.ADMIN_TOPIC_USERS_ID or settings.ADMIN_TOPIC_GENERAL_ID
    return None


def now_stamp() -> str:
    tz_name = str(settings.ADMIN_TOPIC_TIMEZONE or "Asia/Tehran").strip() or "Asia/Tehran"
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now()
    return format_jalali_datetime(now, seconds=True)


async def send_to_topic(
    bot: Bot,
    *,
    name: TopicName,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
    disable_notification: bool = True,
) -> bool:
    if not forum_enabled():
        return False

    chat_id = int(settings.ADMIN_FORUM_CHAT_ID or 0)
    thread_id = topic_id(name)
    if thread_id is None:
        return False

    try:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=int(thread_id),
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_notification=disable_notification,
        )
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(float(getattr(e, "retry_after", 1.0)) + 0.1)
        try:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=int(thread_id),
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_notification=disable_notification,
            )
            return True
        except Exception:
            return False
    except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError):
        return False
    except Exception:
        return False


async def ensure_topic_rules(bot: Bot) -> None:
    if not forum_enabled() or not bool(settings.ADMIN_TOPIC_AUTO_PIN_RULES):
        return

    if get_meta_marker(_META_RULES_VERSION, "") == "done":
        return

    rules: list[tuple[TopicName, str]] = [
        (
            "general",
            "📌 <b>قوانین تاپیک عمومی ادمین</b>\n"
            "• هماهنگی تیمی و تصمیم‌های اجرایی.\n"
            "• مباحث مالی فقط لینک شود و در تاپیک مالی مدیریت شود.\n"
            "• برای موارد فوری از برچسب <code>#فوری</code> استفاده کنید.",
        ),
        (
            "winners",
            "📌 <b>قوانین تاپیک برندگان</b>\n"
            "• گزارش‌های خودکار برد تمام/تورنا اینجا ثبت می‌شود.\n"
            "• هر پیام شامل شماره بازی، کارت‌های برنده و مبلغ است.\n"
            "• برای بازبینی نهایی از دکمه آرشیو کارت‌های برنده استفاده کنید.",
        ),
        (
            "withdraw",
            "📌 <b>قوانین تاپیک برداشت</b>\n"
            "• هر درخواست با مبلغ، کاربر و موجودی لحظه‌ای ثبت می‌شود.\n"
            "• ابتدا صحت اطلاعات بانکی و موجودی را بررسی کنید.\n"
            "• وضعیت هر درخواست باید سریع از حالت «در انتظار» خارج شود.",
        ),
        (
            "deposit",
            "📌 <b>قوانین تاپیک واریز</b>\n"
            "• هر رسید با هش تصویر و هشدار رسید تکراری بررسی می‌شود.\n"
            "• درخواست‌ها با اولویت زمانی بررسی شوند.\n"
            "• پس از تایید/رد، وضعیت کاربر نهایی شود.",
        ),
    ]

    if settings.ADMIN_TOPIC_GAMES_ID is not None:
        rules.append(
            (
                "games",
                "📌 <b>قوانین تاپیک گزارش بازی‌ها</b>\n"
                "• با شروع هر بازی، خلاصه فروش کارت و ساختار جایزه ثبت می‌شود.\n"
                "• با پایان هر بازی، گزارش کامل اعداد و برنده‌ها ثبت می‌شود.\n"
                "• این تاپیک مرجع بازبینی نهایی هر بازی است.",
            )
        )
    if settings.ADMIN_TOPIC_GAME_AUDIT_ID is not None:
        rules.append(
            (
                "game_audit",
                "📌 <b>قوانین تاپیک حسابرسی بازی</b>\n"
                "• گزارش فشرده شروع/پایان بازی و برندگان اینجا ثبت می‌شود.\n"
                "• پیام‌ها مرجع بازبینی مالی/عملیاتی بازی هستند.\n"
                "• در صورت مغایرت، آیتم را با برچسب <code>#نیاز_به_بررسی</code> علامت‌گذاری کنید.",
            )
        )
    if settings.ADMIN_TOPIC_ANTIFRAUD_ID is not None:
        rules.append(
            (
                "antifraud",
                "📌 <b>قوانین تاپیک ضدتقلب</b>\n"
                "• رسید تکراری و رفتار مشکوک اینجا اعلام می‌شود.\n"
                "• هر مورد باید وضعیت نهایی داشته باشد: تایید/رد/نیاز به بررسی.\n"
                "• اطلاعات حساس کاربران را خارج از نیاز عملیاتی منتشر نکنید.",
            )
        )
    if settings.ADMIN_TOPIC_ALERTS_ID is not None:
        rules.append(
            (
                "alerts",
                "📌 <b>قوانین تاپیک هشدار فوری</b>\n"
                "• خطاهای بحرانی، قطعی سرویس، Timeout و Retry غیرعادی اینجا می‌آید.\n"
                "• روی هر هشدار، زمان، علت و اقدام انجام‌شده ثبت شود.\n"
                "• بعد از رفع مشکل، هشدار با نتیجه نهایی جمع‌بندی شود.",
            )
        )
    if settings.ADMIN_TOPIC_USERS_ID is not None:
        rules.append(
            (
                "users",
                "📌 <b>قوانین تاپیک مدیریت کاربران</b>\n"
                "• هر اقدام ادمین روی کاربر باید با دلیل شفاف ثبت شود.\n"
                "• عملیات حساس مثل محدودسازی/اصلاح کیف پول باید قابل پیگیری باشد.\n"
                "• پیام خصوصی به کاربر باید محترمانه و روشن ارسال شود.",
            )
        )

    chat_id = int(settings.ADMIN_FORUM_CHAT_ID or 0)
    pinned_thread_ids: set[int] = set()
    for name, text in rules:
        t_id = topic_id(name)
        if t_id is None:
            continue
        if int(t_id) in pinned_thread_ids:
            continue
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                message_thread_id=int(t_id),
                text=text,
                parse_mode="HTML",
                disable_notification=True,
            )
        except Exception:
            continue
        pinned_thread_ids.add(int(t_id))
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
        except Exception:
            continue

    set_meta_marker(_META_RULES_VERSION, "done")
