import asyncio
import logging
import time

from aiogram import Router
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import ErrorEvent

from bot.services.admin_topics import now_stamp, send_to_topic
from bot.services.api_client import ApiError
from bot.services.ui import panel

router = Router()
log = logging.getLogger("bot.errors")

_ALERT_THROTTLE: dict[str, float] = {}
_ALERT_WINDOW_SEC = 120.0


def _can_send_alert(key: str) -> bool:
    now = time.time()
    last = _ALERT_THROTTLE.get(key, 0.0)
    if now - last < _ALERT_WINDOW_SEC:
        return False
    _ALERT_THROTTLE[key] = now
    return True


async def _send_urgent_alert(event: ErrorEvent, *, title: str, detail: str, alert_key: str) -> None:
    if not _can_send_alert(alert_key):
        return

    bot = getattr(getattr(event, "update", None), "bot", None)
    if bot is None:
        return

    text = panel(
        "هشدار فوری",
        "#فوری #خطای_سیستمی\n"
        f"🕒 زمان: <code>{now_stamp()}</code>\n"
        f"🔎 نوع هشدار: <b>{title}</b>\n"
        f"جزئیات: <code>{detail}</code>",
    )
    await send_to_topic(
        bot,
        name="alerts",
        text=text,
        parse_mode="HTML",
        disable_notification=False,
    )


@router.errors()
async def on_error(event: ErrorEvent):
    exc = event.exception

    if isinstance(exc, ApiError):
        log.warning("خطای سرویس: کد=%s جزئیات=%s", exc.status, exc.detail)
        raw = str(getattr(exc, "raw_detail", "") or exc.detail or "")
        low = raw.lower()
        if exc.status >= 500 or exc.status in {503, 504} or "timeout" in low or "unavailable" in low:
            await _send_urgent_alert(
                event,
                title=f"خطای سرویس ({exc.status})",
                detail=str(exc.detail),
                alert_key=f"api:{exc.status}",
            )
        return True

    if isinstance(exc, asyncio.TimeoutError):
        log.warning("خطای زمان‌انتظار: %s", exc)
        await _send_urgent_alert(
            event,
            title="Timeout",
            detail=str(exc),
            alert_key="timeout",
        )
        return True

    if isinstance(exc, TelegramNetworkError):
        log.warning("خطای شبکه تلگرام: %s", exc)
        await _send_urgent_alert(
            event,
            title="Telegram Network",
            detail=str(exc),
            alert_key="telegram_network",
        )
        return True

    log.exception("خطای مدیریت‌نشده: %s", exc)
    await _send_urgent_alert(
        event,
        title="Unhandled Error",
        detail=str(exc),
        alert_key=f"unhandled:{exc.__class__.__name__}",
    )
    return True

