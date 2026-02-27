from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from bot.services.admin_acl import is_admin_user, is_super_admin_user

class UserContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        u = data.get("event_from_user")
        if u:
            data["tg_user_id"] = u.id
            data["tg_username"] = u.username
            data["is_super_admin"] = is_super_admin_user(u.id)
            data["is_admin"] = is_admin_user(u.id)
        return await handler(event, data)
