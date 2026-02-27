import asyncio
import logging
from contextlib import suppress

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.config import settings
from bot.log import setup_logging
from bot.storage.fsm import build_storage

from bot.middlewares.throttling import ThrottlingMiddleware
from bot.middlewares.user_context import UserContextMiddleware
from bot.middlewares.api import ApiMiddleware
from bot.middlewares.user_forum_isolation import UserForumIsolationMiddleware

from bot.services.api_client import ApiClient
from bot.workers.notifier import notifier_loop

# routers...
from bot.routers.start import router as start_router
from bot.routers.menu import router as menu_router
from bot.routers.help import router as help_router
from bot.routers.wallet import router as wallet_router
from bot.routers.game import router as game_router
from bot.routers.errors import router as errors_router
from bot.routers.fallback import router as fallback_router
from bot.routers.cards import router as cards_router
from bot.routers.withdraw import router as withdraw_router
from bot.routers.deposit import router as deposit_router
from bot.routers.admin_finance import router as admin_finance_router
from bot.routers.purchase import router as purchase_router
from bot.routers.join_gate import router as join_gate_router
from bot.routers.notifications import router as notifications_router
from bot.routers.admin_games import router as admin_games_router
from bot.routers.admin_users import router as admin_users_router
from bot.routers.super_admin import router as super_admin_router


logger = logging.getLogger(__name__)

BOT_WELCOME_DESCRIPTION = (
    "سلام رفیق 👋\n"
    "به «پیمون دورنا» خوش اومدی 🎯\n"
    "اینجا می تونی کارت بازی بخری 🃏، بازی زنده رو دنبال کنی 📡 "
    "و برای برد جایزه آماده بشی 🏆\n"
    "برای شروع، دکمه Start رو بزن تا بریم داخل بازی 🚀"
)

BOT_WELCOME_SHORT_DESCRIPTION = "دورنا | خرید کارت، اعلام زنده اعداد و جایزه 🃏🏆"


async def _sync_bot_profile_texts(bot: Bot) -> None:
    for language_code in (None, "fa"):
        kwargs = {"language_code": language_code} if language_code else {}
        try:
            await bot.set_my_short_description(
                short_description=BOT_WELCOME_SHORT_DESCRIPTION,
                **kwargs,
            )
            await bot.set_my_description(
                description=BOT_WELCOME_DESCRIPTION,
                **kwargs,
            )
        except Exception as exc:
            logger.warning(
                "Failed to set bot profile text (lang=%s): %s",
                language_code or "default",
                exc,
            )


async def main():
    setup_logging()

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    await _sync_bot_profile_texts(bot)

    dp = Dispatcher(storage=build_storage())

    # Create shared aiohttp session + ApiClient
    session = aiohttp.ClientSession()
    api = ApiClient(
        base_url=settings.API_BASE_URL,
        session=session,
        bot_service_token=settings.BOT_SERVICE_TOKEN,
        admin_api_token=settings.ADMIN_API_TOKEN,
        super_admin_api_token=settings.SUPER_ADMIN_API_TOKEN,
    )
    dp.workflow_data["http"] = session
    dp.workflow_data["api"] = api

    # Start background notifier worker after Bot/Dispatcher/ApiClient are ready.
    notifier_task = asyncio.create_task(
        notifier_loop(
            bot,
            api,
            interval_sec=max(0.5, float(settings.NOTIFIER_INTERVAL_SEC or 2.0)),
            last_n=max(50, int(settings.NOTIFIER_LAST_N or 200)),
            send_workers=max(1, int(settings.NOTIFIER_SEND_WORKERS or 2)),
            adaptive_max_workers=max(
                max(1, int(settings.NOTIFIER_SEND_WORKERS or 2)),
                int(settings.NOTIFIER_SEND_WORKERS_MAX or 3),
            ),
            send_delay_sec=max(0.0, float(settings.NOTIFIER_SEND_DELAY_SEC or 0.025)),
            queue_maxsize=max(500, int(settings.NOTIFIER_QUEUE_MAXSIZE or 5000)),
            dead_fail_threshold=max(1, int(settings.NOTIFIER_DEAD_FAIL_THRESHOLD or 3)),
            fast_events_limit=max(20, int(settings.NOTIFIER_EVENTS_LIMIT_FAST or 100)),
            fast_games_limit=max(20, int(settings.NOTIFIER_FAST_GAMES_LIMIT or 120)),
            slow_interval_sec=max(5.0, float(settings.NOTIFIER_HEAVY_INTERVAL_SEC or 30.0)),
            slow_events_limit=max(20, int(settings.NOTIFIER_EVENTS_LIMIT_SLOW or 150)),
            slow_games_limit=max(10, int(settings.NOTIFIER_SLOW_GAMES_LIMIT or 80)),
            hot_game_ttl_sec=max(15.0, float(settings.NOTIFIER_HOT_GAME_TTL_SEC or 120.0)),
            adaptive_check_sec=max(30.0, float(settings.NOTIFIER_ADAPTIVE_CHECK_SEC or 180.0)),
            adaptive_min_jobs=max(20, int(settings.NOTIFIER_ADAPTIVE_MIN_JOBS or 120)),
            metrics_report_sec=max(15.0, float(settings.NOTIFIER_METRICS_REPORT_SEC or 60.0)),
        )
    )

    # Middlewares
    dp.update.middleware(UserForumIsolationMiddleware(settings.USER_FORUM_CHAT_ID))
    dp.update.middleware(UserContextMiddleware())
    dp.update.middleware(ThrottlingMiddleware(rate_limit_sec=0.6))
    dp.update.middleware(ApiMiddleware())

    if settings.USER_FORUM_CHAT_ID is not None:
        logger.info(
            "user forum isolation enabled: inbound updates are blocked for chat_id=%s",
            int(settings.USER_FORUM_CHAT_ID),
        )

    # Routers
    dp.include_router(start_router)
    dp.include_router(menu_router)
    dp.include_router(help_router)
    dp.include_router(wallet_router)
    dp.include_router(game_router)
    dp.include_router(cards_router)
    dp.include_router(deposit_router)
    dp.include_router(withdraw_router)
    dp.include_router(admin_finance_router)
    dp.include_router(purchase_router)
    dp.include_router(join_gate_router)
    dp.include_router(notifications_router)
    dp.include_router(admin_games_router)
    dp.include_router(admin_users_router)
    dp.include_router(super_admin_router)
    # error router should be near the end
    dp.include_router(errors_router)
    # fallback (messages and callback-fallback) must be last
    dp.include_router(fallback_router)

    try:
        await dp.start_polling(bot)
    finally:
        notifier_task.cancel()
        with suppress(asyncio.CancelledError):
            await notifier_task
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
