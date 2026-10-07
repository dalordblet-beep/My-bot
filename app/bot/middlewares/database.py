"""Database + user context middleware.

Runs as the outermost update middleware so every downstream handler gets a
ready ``AsyncSession`` and a loaded ``User`` row in ``data``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, ChatMemberUpdated, InlineQuery, Message, TelegramObject, Update

from app.config import settings
from app.database import repository as repo
from app.database.database import get_session_factory
from app.services import user as user_service
from app.services.admin import resolve_admin_role
from app.services.i18n import normalise
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


def extract_from_user(event: TelegramObject):
    if isinstance(event, Update):
        for field in ("message", "callback_query", "inline_query", "chat_member", "my_chat_member"):
            nested = getattr(event, field, None)
            if nested is not None:
                return getattr(nested, "from_user", None)
        return None
    return getattr(event, "from_user", None)


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        factory = get_session_factory()
        async with factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class UserContextMiddleware(BaseMiddleware):
    """Loads (or creates) the local user and resolves the admin role."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session = data.get("session")
        tg_user = extract_from_user(event)
        if session is None or tg_user is None or getattr(tg_user, "is_bot", False):
            return await handler(event, data)

        try:
            user, created = await user_service.ensure_user(session, tg_user)
            await user_service.ensure_admin_privilege(session, user, settings.admin_id_set)
            settings_row = await repo.get_user_settings(session, user.id)
            data["user"] = user
            data["is_new_user"] = created
            data["admin_role"] = resolve_admin_role(user)
            data["user_settings"] = settings_row
            data["language_chosen"] = bool(settings_row.language)
            data["lang"] = normalise(settings_row.language)
            # ensure_user() updates last_seen and may update the profile. Commit
            # these short-lived writes before entering handlers: some handlers
            # perform slow Telegram/Fragment lookups, and holding SQLite's write
            # transaction across that network work blocks every other update.
            await session.commit()
        except Exception:
            logger.exception(
                "failed to load user %s", getattr(tg_user, "id", "?")
            )
            # Do not dispatch a handler with user=None. The outer error
            # middleware will report a retryable failure and DatabaseMiddleware
            # will roll the transaction back.
            raise

        return await handler(event, data)
