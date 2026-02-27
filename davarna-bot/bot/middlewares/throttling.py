import time
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit_sec: float = 0.7):
        self.rate = rate_limit_sec
        self._last: dict[int, float] = {}

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user:
            now = time.time()
            last = self._last.get(user.id, 0.0)
            if now - last < self.rate:
                # silently drop
                return
            self._last[user.id] = now
        return await handler(event, data)
