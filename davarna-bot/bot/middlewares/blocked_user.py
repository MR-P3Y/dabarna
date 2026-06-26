from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


BLOCKED_TEXT = "حساب شما توسط مدیریت محدود شده است. برای پیگیری با پشتیبانی تماس بگیرید."


def _event_user_id(event: TelegramObject) -> int | None:
    user = getattr(event, "from_user", None)
    if user is None and isinstance(event, CallbackQuery):
        user = event.from_user
    if user is None and isinstance(event, Message):
        user = event.from_user
    if user is None:
        return None
    return int(user.id)


def _truthy_blocked(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "blocked", "banned", "disabled", "suspended", "restricted"}
    return False


def _read_blocked_from_user_object(user: Any) -> bool:
    if not user:
        return False
    if isinstance(user, dict):
        restriction = user.get("restriction")
        if isinstance(restriction, dict) and _truthy_blocked(restriction.get("active")):
            return True
        if _truthy_blocked(user.get("active")) and ("actions" in user or "reason" in user or "until" in user):
            return True
        for key in ("is_blocked", "blocked", "is_banned", "banned", "status"):
            if key in user and _truthy_blocked(user.get(key)):
                return True
        return False
    for key in ("is_blocked", "blocked", "is_banned", "banned", "status"):
        if hasattr(user, key) and _truthy_blocked(getattr(user, key)):
            return True
    return False


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class BlockedUserMiddleware(BaseMiddleware):
    """Stops blocked regular users before finance/game handlers run.

    This middleware supports both patterns used in this project family:
    - a user object already placed in workflow data by UserContextMiddleware
    - an ApiClient method that can return the user/status by Telegram id

    Admin/super-admin ids are allowed through so they can unblock users.
    """

    def __init__(self, admin_ids: set[int] | None = None, super_admin_ids: set[int] | None = None) -> None:
        self.admin_ids = admin_ids or set()
        self.super_admin_ids = super_admin_ids or set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user_id = _event_user_id(event)
        if tg_user_id is None or tg_user_id in self.admin_ids or tg_user_id in self.super_admin_ids:
            return await handler(event, data)

        for key in ("current_user", "user", "db_user", "user_context"):
            if _read_blocked_from_user_object(data.get(key)):
                return await self._reject(event)

        api = data.get("api")
        if api is not None:
            for method_name in (
                "bot_get_user_restriction",
                "get_user_by_telegram_id",
                "get_user_by_tg_id",
                "get_user_status_by_telegram_id",
                "get_user_status",
            ):
                method = getattr(api, method_name, None)
                if method is None:
                    continue
                try:
                    result = await _maybe_await(method(tg_user_id))
                except TypeError:
                    continue
                except Exception:
                    result = None
                if _read_blocked_from_user_object(result):
                    return await self._reject(event)

        return await handler(event, data)

    async def _reject(self, event: TelegramObject) -> None:
        if isinstance(event, CallbackQuery):
            await event.answer(BLOCKED_TEXT, show_alert=True)
            return None
        if isinstance(event, Message):
            await event.answer(BLOCKED_TEXT)
        return None
