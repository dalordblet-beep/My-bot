"""Language selection.

Shown once, immediately after /start and before the captcha, so the whole
onboarding (and everything after it) is in the user's language. Changeable later
from Settings.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.gate import render_gate
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.main_menu import language_keyboard, main_menu_keyboard
from app.database import repository as repo
from app.database.models import User
from app.services.access import access_guard
from app.services.captcha import CaptchaService
from app.services.i18n import LANGUAGES, normalise, t
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="language")


async def show_language_picker(bot: Bot, chat_id: int, lang: str, edit_message_id: int | None = None) -> None:
    text = texts.language_screen(lang)
    keyboard = language_keyboard(lang)
    if edit_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=edit_message_id, text=text, reply_markup=keyboard
            )
            return
        except Exception:
            pass
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{cb.LANG_PREFIX}:"))
async def cb_choose_language(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    captcha_service: CaptchaService,
    state: FSMContext,
) -> None:
    code = (callback.data or "").split(":")[-1]
    if code not in LANGUAGES:
        await callback.answer()
        return

    await repo.update_user_settings(session, user.id, language=code)
    lang = normalise(code)
    logger.info("language set user=%s lang=%s", user.telegram_id, lang)

    await callback.answer(t(lang, "lang.changed"))

    message_id = getattr(callback.message, "message_id", None)
    access = await access_guard.evaluate(session, bot, user, live_membership=True)

    if access.granted:
        if message_id is not None:
            try:
                await bot.edit_message_text(
                    chat_id=callback.from_user.id,
                    message_id=message_id,
                    text=texts.welcome(lang, user),
                    reply_markup=main_menu_keyboard(lang, access.is_admin),
                )
                return
            except Exception:
                pass
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=texts.welcome(lang, user),
            reply_markup=main_menu_keyboard(lang, access.is_admin),
        )
        return

    await render_gate(
        bot,
        callback.from_user.id,
        access,
        captcha_service,
        lang=lang,
        edit_message_id=message_id,
    )
