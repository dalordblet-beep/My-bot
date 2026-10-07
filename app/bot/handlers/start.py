"""/start, /help and the main menu entry point."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.gate import render_gate, send_main_menu
from app.bot.handlers.language import show_language_picker
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.main_menu import main_menu_keyboard
from app.database.models import User
from app.services.access import access_guard
from app.services.captcha import CaptchaService
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
    captcha_service: CaptchaService,
    lang: str = "en",
    language_chosen: bool = True,
    is_new_user: bool = False,
) -> None:
    await state.clear()

    if user is None:
        return

    # 1. Language first - everything after this is rendered in the chosen one.
    if not language_chosen:
        logger.info("start user=%s -> language picker", user.telegram_id)
        await show_language_picker(bot, message.chat.id, lang)
        return

    # 2. Then the gate: captcha -> channel -> chat -> access.
    access = await access_guard.evaluate(session, bot, user, live_membership=True)
    logger.info(
        "start user=%s granted=%s step=%s",
        user.telegram_id, access.granted, access.missing_step,
    )

    if not access.granted:
        await render_gate(
            bot, message.chat.id, access, captcha_service,
            lang=lang, is_admin=access.is_admin,
        )
        return

    await message.answer(
        texts.welcome(lang, user), reply_markup=main_menu_keyboard(lang, access.is_admin)
    )


@router.message(Command("help"))
async def cmd_help(
    message: Message,
    session: AsyncSession,
    user: User,
    bot: Bot,
    captcha_service: CaptchaService,
    lang: str = "en",
    language_chosen: bool = True,
) -> None:
    if not language_chosen:
        await show_language_picker(bot, message.chat.id, lang)
        return

    access = await access_guard.evaluate(session, bot, user, live_membership=False)
    if not access.granted:
        await render_gate(
            bot, message.chat.id, access, captcha_service, lang=lang, is_admin=access.is_admin
        )
        return
    await message.answer(texts.help_screen(lang, access.is_admin))


@router.callback_query(F.data == cb.MENU_HOME)
async def cb_home(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
    captcha_service: CaptchaService,
    lang: str = "en",
    language_chosen: bool = True,
) -> None:
    # Leaving any wizard must abandon its pending input. Otherwise the next
    # ordinary message can be consumed as a username/mask by the old state.
    await state.clear()
    if not language_chosen:
        await callback.answer()
        await show_language_picker(bot, callback.from_user.id, lang)
        return

    access = await access_guard.evaluate(session, bot, user, live_membership=True)
    await callback.answer()
    message_id = getattr(callback.message, "message_id", None)

    if not access.granted:
        await render_gate(
            bot, callback.from_user.id, access, captcha_service,
            lang=lang, edit_message_id=message_id, is_admin=access.is_admin,
        )
        return

    await send_main_menu(
        bot,
        callback.from_user.id,
        lang,
        text=texts.main_menu(lang),
        edit_message_id=message_id,
        is_admin=access.is_admin,
    )
