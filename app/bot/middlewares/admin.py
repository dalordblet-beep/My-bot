"""Admin guard middleware.

Runs only for handlers inside the admin router, and re-resolves the admin role
from the database on every event. A user who forges an admin callback gets
nothing.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.services.admin import resolve_admin_role
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


class AdminGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        role = resolve_admin_role(user) if user is not None else None

        if role is None:
            logger.warning(
                "unauthorized admin access attempt user=%s event=%s",
                getattr(user, "telegram_id", "?"),
                type(event).__name__,
            )
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Not authorized", show_alert=True)
                except Exception:
                    pass
            elif isinstance(event, Message):
                await event.answer("\U0001F512 This command is restricted.")
            return None

        data["admin_role"] = role
        data["admin"] = user
        return await handler(event, data)
