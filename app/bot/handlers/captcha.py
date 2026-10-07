"""CAPTCHA handler. Answers are verified server-side only."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.gate import captcha_payload, render_gate
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.captcha_kb import captcha_retry_keyboard
from app.bot.keyboards.main_menu import main_menu_keyboard
from app.database import repository as repo
from app.database.models import User
from app.services.access import access_guard
from app.services.captcha import STATE_EXPIRED, STATE_FAILED, STATE_PASSED, CaptchaService
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="captcha")


async def _edit(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


@router.callback_query(F.data == cb.CAPTCHA_RETRY)
async def cb_captcha_retry(
    callback: CallbackQuery,
    user: User,
    bot: Bot,
    captcha_service: CaptchaService,
    lang: str = "en",
) -> None:
    text, keyboard = await captcha_payload(user.telegram_id, captcha_service, lang)
    await callback.answer()
    await _edit(callback, bot, text, keyboard)


@router.callback_query(F.data.startswith(f"{cb.CAPTCHA_PREFIX}:ans:"))
async def cb_captcha_answer(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    captcha_service: CaptchaService,
    state: FSMContext,
    lang: str = "en",
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return

    session_id, raw_index = parts[2], parts[3]
    try:
        index = int(raw_index)
    except ValueError:
        await callback.answer()
        return

    outcome = captcha_service.verify(user.telegram_id, session_id, index)

    if outcome.state == STATE_PASSED and outcome.correct:
        await repo.set_captcha_verified(session, user)
        access_guard.invalidate(user.telegram_id)
        await callback.answer(texts.captcha_passed(lang).replace("<b>", "").replace("</b>", ""))
        logger.info("captcha completed user=%s", user.telegram_id)

        access = await access_guard.evaluate(session, bot, user, live_membership=True)
        if access.granted:
            await _edit(
                callback, bot, texts.welcome(lang, user),
                main_menu_keyboard(lang, access.is_admin),
            )
        else:
            await render_gate(
                bot,
                callback.from_user.id,
                access,
                captcha_service,
                lang=lang,
                edit_message_id=getattr(callback.message, "message_id", None),
                is_admin=access.is_admin,
            )
        return

    if outcome.state == STATE_FAILED:
        await callback.answer(texts.captcha_failed(lang).split("\n")[0].replace("<b>", "").replace("</b>", ""))
        await _edit(callback, bot, texts.captcha_failed(lang), captcha_retry_keyboard(lang))
        return

    if outcome.state == STATE_EXPIRED:
        await callback.answer("\u23F3")
        await _edit(callback, bot, texts.captcha_expired(lang), captcha_retry_keyboard(lang))
        return

    await callback.answer("\u274C")
    await _edit(callback, bot, texts.captcha_wrong(lang, outcome.attempts_left))
