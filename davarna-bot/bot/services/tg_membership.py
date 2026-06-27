from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

MEMBER_OK = {"member", "administrator", "creator"}


async def is_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        status = str(getattr(member, "status", "") or "").lower()

        if status in MEMBER_OK:
            return True

        if status == "restricted":
            return bool(getattr(member, "is_member", False))

        return False
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    except Exception:
        return False

