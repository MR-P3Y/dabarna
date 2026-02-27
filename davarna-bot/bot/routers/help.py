from __future__ import annotations

from dataclasses import dataclass

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards.help import help_menu_kb, help_topic_kb
from bot.services.telegram_safe import safe_edit_or_send
from bot.services.ui import panel

router = Router()


@dataclass(frozen=True)
class HelpTopic:
    key: str
    button: str
    title: str
    body: str


BASE_TOPICS: list[HelpTopic] = [
    HelpTopic(
        key="quick",
        button="🚀 شروع سریع",
        title="شروع سریع",
        body=(
            "۱) از منوی اصلی، بخش موردنظر را انتخاب کن.\n"
            "۲) برای خرید کارت، اول وارد «🛒 خرید کارت» شو و بازی را انتخاب کن.\n"
            "۳) برای دیدن جریان بازی، وارد «🎮 بازی‌های فعال» شو.\n"
            "۴) کارت‌های خریداری‌شده‌ات را از «🃏 کارت‌های من» ببین.\n"
            "۵) موجودی، واریز و برداشت را از «💰 کیف پول» مدیریت کن."
        ),
    ),
    HelpTopic(
        key="buy",
        button="🛒 راهنمای خرید کارت",
        title="خرید کارت",
        body=(
            "• فقط بازی‌های «در انتظار شروع» برای خرید نمایش داده می‌شوند.\n"
            "• بعد از انتخاب بازی، تعداد کارت را مشخص کن و خرید را تایید کن.\n"
            "• اگر موجودی کافی نباشد، ابتدا کیف پول را شارژ کن.\n"
            "• بعد از شروع بازی، خرید کارت برای همان بازی بسته می‌شود."
        ),
    ),
    HelpTopic(
        key="live",
        button="🎮 راهنمای بازی‌های فعال",
        title="بازی‌های فعال",
        body=(
            "• بازی‌های باز در این بخش به‌صورت دکمه‌ای نمایش داده می‌شوند.\n"
            "• با ورود به هر بازی، وضعیت، تعداد برندگان، قیمت کارت و جایزه کل را می‌بینی.\n"
            "• آخرین عدد و اعداد اخیر (تا ۱۰ عدد) هم نمایش داده می‌شود.\n"
            "• با دکمه تازه‌سازی می‌توانی وضعیت را به‌روز کنی."
        ),
    ),
    HelpTopic(
        key="mycards",
        button="🃏 راهنمای کارت‌های من",
        title="کارت‌های من",
        body=(
            "• ابتدا آخرین بازی‌های تو نمایش داده می‌شود.\n"
            "• با انتخاب هر بازی، کارت‌هایت با علامت ✅ برای عددهای اعلام‌شده دیده می‌شوند.\n"
            "• بازی‌های پایان‌یافته بعد از ۴۸ ساعت بایگانی می‌شوند تا لیست شلوغ نشود.\n"
            "• برای هر کارت می‌توانی به‌روزرسانی انجام بدهی."
        ),
    ),
    HelpTopic(
        key="wallet",
        button="💰 راهنمای کیف پول",
        title="کیف پول",
        body=(
            "• موجودی فعلی و آخرین تراکنش‌ها به‌صورت فارسی نمایش داده می‌شود.\n"
            "• نوع تراکنش (واریز/برداشت)، مبلغ، علت و زمان برای هر مورد مشخص است.\n"
            "• دکمه‌های «واریز» و «برداشت» داخل همین بخش قرار دارند.\n"
            "• در هر بار نمایش، حداکثر ۱۰ تراکنش آخر نشان داده می‌شود."
        ),
    ),
    HelpTopic(
        key="deposit",
        button="📥 راهنمای واریز",
        title="واریز",
        body=(
            "• مبلغ واریز را به تومان ثبت کن و رسید را ارسال کن.\n"
            "• درخواست واریز به‌صورت پیام جدا برای ادمین ارسال می‌شود.\n"
            "• بعد از تایید ادمین، وضعیت واریز در ربات به‌روزرسانی می‌شود.\n"
            "• برای جلوگیری از خطای انسانی، کنترل رسید تکراری فعال است."
        ),
    ),
    HelpTopic(
        key="withdraw",
        button="📤 راهنمای برداشت",
        title="برداشت",
        body=(
            "• مبلغ برداشت باید کمتر یا مساوی موجودی کیف پولت باشد.\n"
            "• بعد از ثبت درخواست، پیام آن برای ادمین ارسال می‌شود.\n"
            "• پس از تایید ادمین، مبلغ از کیف پول کسر و نتیجه برایت ارسال می‌شود.\n"
            "• واریزهای برداشت در بازه زمانی مشخص انجام می‌شوند."
        ),
    ),
    HelpTopic(
        key="rules",
        button="🏁 قوانین برد",
        title="قوانین برد",
        body=(
            "• برد تمام: تکمیل یک ردیف ۵ عددی.\n"
            "• برد تورنا: تکمیل یک ستون ۴ عددی.\n"
            "• عددهای اعلام‌شده روی کارت با ✅ مشخص می‌شوند.\n"
            "• در پایان بازی، اطلاعات برنده‌ها در بخش ادمین قابل بازبینی است."
        ),
    ),
]

ADMIN_TOPIC = HelpTopic(
    key="admin",
    button="🛠 راهنمای ادمین",
    title="راهنمای ادمین",
    body=(
        "• از «🛠 ادمین مالی» واریز/برداشت‌ها را مدیریت می‌کنی.\n"
        "• از «🛠 ادمین بازی» بازی می‌سازی، مدیریت می‌کنی و مانیتور می‌بینی.\n"
        "• از «🏆 کارت‌های برنده» برنده‌های تمام و تورنا بازی‌های پایان‌یافته را بازبینی می‌کنی.\n"
        "• اعلان‌های مهم مالی و برندگان برای ادمین ارسال می‌شوند."
    ),
)


def _topics_for_user(is_admin: bool) -> list[HelpTopic]:
    if is_admin:
        return [*BASE_TOPICS, ADMIN_TOPIC]
    return BASE_TOPICS


def _help_home_text(is_admin: bool) -> str:
    body_lines = [
        "برای یادگیری سریع، موضوع موردنظرت را از دکمه‌های زیر انتخاب کن 👇",
        "",
        "همه راهنماها مرحله‌ای و فارسی هستند:",
        "• خرید کارت",
        "• بازی‌های فعال",
        "• کارت‌های من",
        "• کیف پول، واریز و برداشت",
        "• قوانین برد",
    ]
    if is_admin:
        body_lines.append("• راهنمای اختصاصی ادمین")

    return panel("راهنمای ربات", "\n".join(body_lines))


@router.callback_query(F.data == "menu:help")
async def help_page(cq: CallbackQuery, is_admin: bool = False):
    topics = _topics_for_user(is_admin)
    topic_buttons = [(topic.key, topic.button) for topic in topics]

    await safe_edit_or_send(
        cq.message,
        _help_home_text(is_admin),
        reply_markup=help_menu_kb(topics=topic_buttons),
        parse_mode="HTML",
    )
    await cq.answer()


@router.callback_query(F.data.startswith("help:topic:"))
async def help_topic_page(cq: CallbackQuery, is_admin: bool = False):
    key = (cq.data or "").split(":", 2)[-1].strip().lower()

    topics = _topics_for_user(is_admin)
    keys = [topic.key for topic in topics]
    if key not in keys:
        await cq.answer("موضوع راهنما نامعتبر است.", show_alert=False)
        await safe_edit_or_send(
            cq.message,
            _help_home_text(is_admin),
            reply_markup=help_menu_kb(topics=[(topic.key, topic.button) for topic in topics]),
            parse_mode="HTML",
        )
        return

    idx = keys.index(key)
    topic = topics[idx]
    prev_key = topics[idx - 1].key if idx > 0 else None
    next_key = topics[idx + 1].key if idx + 1 < len(topics) else None

    await safe_edit_or_send(
        cq.message,
        panel(topic.title, topic.body),
        reply_markup=help_topic_kb(prev_key=prev_key, next_key=next_key),
        parse_mode="HTML",
    )
    await cq.answer()
