from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

MEMBER_OK = {"member", "administrator", "creator"}

async def is_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return getattr(m, "status", None) in MEMBER_OK
    except TelegramBadRequest:
        return False
    except Exception:
        # اینترنت تلگرام ممکنه بدقلق باشه؛ اینجا تصمیم می‌گیریم fail-open یا fail-closed.
        # پیشنهاد من: fail-closed (اجازه نده) تا دور زده نشه.
        return False
