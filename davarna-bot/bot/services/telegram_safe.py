from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramBadRequest
import asyncio


async def safe_edit_or_send(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        # مثلا پیام تغییر نکرده/یا قابل ادیت نیست
        if "message is not modified" in str(e).lower():
            return
        try:
            await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramNetworkError:
            return
    except TelegramNetworkError:
        return
    except Exception:
        try:
            await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramNetworkError:
            return



async def safe_send(message, text: str, **kwargs):
    try:
        return await message.answer(text, **kwargs)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            return await message.answer(text, **kwargs)
        except TelegramNetworkError:
            return None
    except (TelegramNetworkError, TelegramBadRequest):
        return None
    except Exception:
        return None
