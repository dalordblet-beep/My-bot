"""Required-subscription gate.

One screen lists every subscription the user must join, each with its own
"I subscribed" button. The button never trusts the click - it re-queries
Telegram and only then marks that subscription as joined.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, ChatJoinRequest, InlineKeyboardMarkup
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
from app.services.subscriptions import find_sub, required_subs
from app.telegram.bot_api import build_chat_ref, get_membership
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="subscription")


def _is_required_chat(chat_id: int, username: str | None) -> bool:
    """Is this chat one of the required subscriptions?

    Only required chats are worth remembering: an unrelated request is noise,
    and the gate never consults it.
    """
    handle = (username or "").lstrip("@").lower()
    for sub in required_subs():
        if sub.chat_id and sub.chat_id == chat_id:
            return True
        if sub.username and handle and sub.username.lstrip("@").lower() == handle:
            return True
    return False


@router.chat_join_request()
async def on_join_request(event: ChatJoinRequest, session: AsyncSession) -> None:
    """Remember a pending request to join a required channel.

    Private channels approve requests by hand, and approval does not always
    happen at once. The gate counts a *pending* request as a subscription, so a
    user who has already asked to join is let through instead of being stuck on
    the gate waiting for the admin's queue. This update is how the bot learns
    about it - it is delivered when the bot is an administrator of the channel.

    The click is never trusted on its own: the gate re-reads this record (and,
    when it can, the request queue itself) on every check.
    """
    user_id = event.from_user.id
    chat = event.chat
    if not _is_required_chat(chat.id, getattr(chat, "username", None)):
        logger.debug("join request for a chat that is not required: %s", chat.id)
        return

    await repo.record_join_request(session, chat.id, user_id)
    # The user may be sitting on the gate right now: drop the cached verdict so
    # their next press of "I subscribed" sees the request.
    access_guard.invalidate(user_id)
    logger.info("join request recorded chat=%s user=%s", chat.id, user_id)


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

    # A member, or somebody whose request to join is still waiting to be
    # approved: both have done their part, so both pass the gate.
    if status.grants_access or await access_guard.join_request_pending(
        session, bot, sub, user
    ):
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
