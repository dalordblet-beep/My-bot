"""AccessGuard middleware.

Blocks every non-public entry point until the onboarding gate is satisfied.
Public (allow-listed) surfaces are only the onboarding itself:

* callbacks: ``captcha:*``, ``sub:*``
* commands:  ``/start``, ``/help``

Everything else - including stale inline buttons from an old session - is
re-evaluated against the database on every event. Nothing in callback data is
trusted.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.gate import render_gate
from app.bot.handlers.language import show_language_picker
from app.services.access import access_guard
from app.services.captcha import CaptchaService
from app.services.i18n import DEFAULT_LANGUAGE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# "battle:" is public on purpose: accepting a challenge happens in a group
# where most members have never onboarded, and showing them the gate there
# would spam the chat.
PUBLIC_CALLBACK_PREFIXES = ("captcha:", "sub:", "lang:", "battle:", "noop")
PUBLIC_COMMANDS = {"start", "help"}


class AccessGuardMiddleware(BaseMiddleware):
    def __init__(self, captcha: CaptchaService) -> None:
        self._captcha = captcha

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("user")
        session = data.get("session")
        bot = data.get("bot")

        if user is None or session is None or bot is None:
            return await handler(event, data)

        # NOTE: administrators are deliberately NOT exempt. Everyone, admins
        # included, passes the language picker, captcha, channel and chat.
        if self._is_public(event):
            return await handler(event, data)

        # Language is the very first step - nothing else is shown until it is set.
        if not data.get("language_chosen", True):
            chat_id, message_id = self._locate(event)
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer()
                except Exception:
                    pass
            if chat_id is not None:
                await show_language_picker(
                    bot, chat_id, data.get("lang") or DEFAULT_LANGUAGE, message_id
                )
            return None

        state = await access_guard.evaluate(session, bot, user, live_membership=True)

        if state.granted:
            data["access"] = state
            return await handler(event, data)

        logger.info(
            "access blocked user=%s step=%s event=%s",
            user.telegram_id, state.missing_step, type(event).__name__,
        )

        chat_id, message_id = self._locate(event)
        if chat_id is None:
            return None

        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass

        await render_gate(
            bot,
            chat_id,
            state,
            self._captcha,
            lang=data.get("lang") or DEFAULT_LANGUAGE,
            edit_message_id=message_id,
        )
        return None

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _is_public(event: TelegramObject) -> bool:
        if isinstance(event, CallbackQuery):
            payload = event.data or ""
            return payload.startswith(PUBLIC_CALLBACK_PREFIXES)
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/"):
                command = text[1:].split()[0].split("@")[0].lower()
                return command in PUBLIC_COMMANDS
            return False
        return True

    @staticmethod
    def _locate(event: TelegramObject) -> tuple[int | None, int | None]:
        if isinstance(event, Message):
            return event.chat.id, None
        if isinstance(event, CallbackQuery):
            message = event.message
            if isinstance(message, Message):
                return message.chat.id, message.message_id
            # Inaccessible / too-old message: reply in the private chat instead.
            if event.from_user is not None:
                return event.from_user.id, None
            return None, None
        return None, None
