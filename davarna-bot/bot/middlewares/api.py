from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

class ApiMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        # dp["api"] را داخل handler data می‌ذاریم
        dp = data.get("dispatcher")
        if dp and "api" in dp.workflow_data:
            data["api"] = dp.workflow_data["api"]
        return await handler(event, data)
