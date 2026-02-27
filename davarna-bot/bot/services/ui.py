from bot.constants import APP_NAME
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramNetworkError, TelegramBadRequest

def panel(title: str, body: str) -> str:
    # HTML parse mode
    return f"🟦 <b>{APP_NAME}</b> | <b>{title}</b>\n\n{body}"




async def safe_edit_or_send(
    message: Message,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = "HTML",
):
    """
    اول تلاش می‌کند edit کند؛ اگر نشد (مثلاً message not modified / یا شبکه خراب)
    یک send_message می‌زند.
    """
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        # مثلا پیام تغییر نکرده
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramNetworkError:
        # شبکه قطع است: حداقل کرش نکن
        # اینجا هیچ کاری نکن یا لاگ کن
        return
    except Exception:
        # هر چیز غیرمنتظره
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
