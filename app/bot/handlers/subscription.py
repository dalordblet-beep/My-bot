"""Required-subscription gate.

One screen lists every subscription the user must join, each with its own
"I subscribed" button. The button never trusts the click - it re-queries
Telegram and only then marks that subscription as joined.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.gate import render_gate, subscriptions_payload
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.main_menu import main_menu_keyboard
from app.database import repository as repo
from app.database.models import User
from app.services.access import access_guard
from app.services.captcha import CaptchaService
from app.services.i18n import t
from app.services.subscriptions import find_sub
from app.telegram.bot_api import build_chat_ref, get_membership
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="subscription")


async def _edit(
    callback: CallbackQuery, bot: Bot, text: str, keyboard: InlineKeyboardMarkup | None
) -> None:
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


async def _advance(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    captcha_service: CaptchaService,
    lang: str,
    success_toast: str,
) -> None:
    access_guard.invalidate(user.telegram_id)
    access = await access_guard.evaluate(session, bot, user, live_membership=True)

    if access.granted:
        await callback.answer(success_toast)
        await _edit(
            callback, bot, texts.welcome(lang, user), main_menu_keyboard(lang, access.is_admin)
        )
        return

    await callback.answer()
    await render_gate(
        bot,
        callback.from_user.id,
        access,
        captcha_service,
        lang=lang,
        edit_message_id=getattr(callback.message, "message_id", None),
        is_admin=access.is_admin,
    )


@router.callback_query(F.data.startswith(f"{cb.SUB_CHECK_PREFIX}:"))
async def cb_check_sub(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    bot: Bot,
    captcha_service: CaptchaService,
    lang: str = "en",
) -> None:
    """Verify one required subscription against Telegram, then advance."""
    key = (callback.data or "").split(":")[-1]
    sub = find_sub(key)

    if sub is None or not sub.configured:
        # Nothing to check for this key - do not block the user on it.
        await _advance(callback, session, user, bot, captcha_service, lang, "\u2705")
        return

    ref = build_chat_ref(sub.chat_id, sub.username)
    status = await get_membership(bot, ref, user.telegram_id)

    if status.grants_access:
        await repo.set_sub_verified(session, user, sub.key)
        logger.info("subscription verified user=%s key=%s", user.telegram_id, sub.key)
        await _advance(callback, session, user, bot, captcha_service, lang, "\u2705")
        return

    # Not joined yet: say so and re-draw the combined screen.
    await callback.answer("\u274C")
    access_guard.invalidate(user.telegram_id)
    access = await access_guard.evaluate(session, bot, user, live_membership=True)
    text, keyboard = await subscriptions_payload(bot, lang, access)
    await _edit(
        callback, bot, f"{t(lang, 'gate.subs.not_confirmed')}\n\n{text}", keyboard
    )
