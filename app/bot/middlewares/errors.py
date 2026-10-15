"""Global error middleware.

The user must never see a Python traceback. Everything unexpected is logged and
replaced with a calm message.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot import texts
from app.services.i18n import DEFAULT_LANGUAGE
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)


class ErrorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        lang = data.get("lang") or DEFAULT_LANGUAGE
        try:
            return await handler(event, data)
        except TelegramAPIError as exc:
            logger.warning("telegram api error: %s", exc)
            await self._notify(event, data, texts.error_screen(lang))
        except Exception as exc:  # noqa: BLE001 - last line of defence
            logger.exception("unhandled error while processing update: %s", exc)
            await self._notify(event, data, texts.error_screen(lang))
        return None

    @staticmethod
    def _inner(event: TelegramObject) -> TelegramObject:
        """Unwrap an ``Update`` to the message/callback it carries.

        This middleware is registered at the update level, where aiogram hands
        the ``Update`` wrapper, not the inner event - so without unwrapping, the
        "something went wrong" notice was silently never sent.
        """
        if isinstance(event, (Message, CallbackQuery)):
            return event
        try:
            return event.event  # type: ignore[attr-defined]
        except Exception:
            return event

    @staticmethod
    async def _notify(event: TelegramObject, data: dict[str, Any], text: str) -> None:
        inner = ErrorMiddleware._inner(event)
        try:
            if isinstance(inner, CallbackQuery):
                await inner.answer("Something went wrong", show_alert=False)
                if isinstance(inner.message, Message):
                    await inner.message.answer(text)
                elif inner.from_user is not None:
                    await data["bot"].send_message(inner.from_user.id, text)
            elif isinstance(inner, Message):
                await inner.answer(text)
        except Exception:
            pass
