"""Access-gate screens.

Shared by the middleware and the onboarding handlers so the exact same screen
is shown whether the user arrived via a button or typed a command.
"""

from __future__ import annotations

import os

from aiogram import Bot
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InputMediaPhoto, Message

from app.bot import texts
from app.bot.keyboards.captcha_kb import captcha_keyboard, captcha_retry_keyboard
from app.bot.keyboards.main_menu import main_menu_keyboard
from app.bot.keyboards.subscription_kb import subscriptions_keyboard
from app.config import settings
from app.services.access import (
    STEP_BANNED,
    STEP_CAPTCHA,
    STEP_RESTRICTED,
    STEP_SUBS,
    AccessState,
)
from app.services.captcha import CaptchaService
from app.services.i18n import DEFAULT_LANGUAGE
from app.services.runtime_config import runtime
from app.services.subscriptions import RequiredSub, required_subs
from app.telegram.bot_api import invite_link
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)



async def channel_join_url(bot: Bot) -> str | None:
    # An explicit invite link always wins: private channels have no username,
    # and the bot may not be allowed to export one.
    invite = runtime.required_channel_invite_url
    if invite:
        return invite
    username = runtime.required_channel_username
    if username:
        return f"https://t.me/{username.lstrip('@')}"
    channel_id = runtime.required_channel_id
    if channel_id:
        return await invite_link(bot, channel_id)
    return None


async def chat_join_url(bot: Bot) -> str | None:
    invite = runtime.required_chat_invite_url
    if invite:
        return invite
    username = runtime.required_chat_username
    if username:
        return f"https://t.me/{username.lstrip('@')}"
    chat_id = runtime.required_chat_id
    if chat_id:
        return await invite_link(bot, chat_id)
    return None


async def subscription_join_url(bot: Bot, sub: RequiredSub) -> str | None:
    """Where the "Subscribe" button should point for one subscription."""
    if sub.invite_url:
        return sub.invite_url
    if sub.username:
        return f"https://t.me/{sub.username}"
    if sub.chat_id:
        return await invite_link(bot, sub.chat_id)
    return None


async def subscriptions_payload(
    bot: Bot, lang: str, state: AccessState
) -> tuple[str, InlineKeyboardMarkup]:
    """The combined subscriptions screen: every required sub, joined or not."""
    pending = {sub.key for sub in state.pending_subs}
    items: list[tuple[RequiredSub, bool, str | None]] = []
    for sub in required_subs():
        url = await subscription_join_url(bot, sub)
        items.append((sub, sub.key not in pending, url))
    text = texts.subscriptions_screen(lang, [(sub, ok) for sub, ok, _ in items])
    return text, subscriptions_keyboard(lang, items)


async def captcha_payload(
    user_id: int, captcha: CaptchaService, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    challenge = captcha.create(user_id)
    text = texts.captcha_screen(lang, challenge.title, challenge.prompt, challenge.attempts_left)
    return text, captcha_keyboard(challenge, lang)


async def render_gate(
    bot: Bot,
    chat_id: int,
    state: AccessState,
    captcha: CaptchaService,
    *,
    lang: str = DEFAULT_LANGUAGE,
    edit_message_id: int | None = None,
    is_admin: bool = False,
) -> None:
    """Show the screen that matches the first missing onboarding step."""
    step = state.missing_step

    if step == STEP_BANNED:
        await _send(
            bot, chat_id, texts.banned_screen(lang, state.restriction_reason), None, edit_message_id
        )
        return

    if step == STEP_RESTRICTED:
        await _send(
            bot, chat_id,
            texts.restricted_screen(lang, state.restriction_reason, state.restricted_until),
            None, edit_message_id,
        )
        return

    if step == STEP_CAPTCHA:
        text, keyboard = await captcha_payload(state.user.telegram_id, captcha, lang)
        await _send(bot, chat_id, text, keyboard, edit_message_id)
        return

    if step == STEP_SUBS:
        text, keyboard = await subscriptions_payload(bot, lang, state)
        await _send(bot, chat_id, text, keyboard, edit_message_id)
        return

    # Access granted - fall back to the menu. Single message: photo on top,
    # caption underneath, inline keyboard attached to the same message.
    await send_main_menu(
        bot, chat_id, lang, is_admin=is_admin, edit_message_id=edit_message_id
    )


async def send_main_menu(
    bot: Bot,
    chat_id: int,
    lang: str,
    text: str | None = None,
    edit_message_id: int | None = None,
    is_admin: bool = False,
) -> None:
    """The main menu: ONE Telegram message with the brand photo on top, a
    short caption underneath, and the inline keyboard attached to that same
    message. Editing an existing text message in place also converts it into
    the photo+caption variant, so pressing Home does not leave a stale text
    message behind. If the photo file is missing, falls back to a plain text
    message with the keyboard - the menu is never dropped.
    """
    caption = text if text is not None else texts.main_menu_caption(lang)
    keyboard = main_menu_keyboard(lang, is_admin)
    await _send_main_menu(bot, chat_id, caption, keyboard, edit_message_id)


async def _send_main_menu(
    bot: Bot,
    chat_id: int,
    caption: str,
    keyboard: InlineKeyboardMarkup,
    edit_message_id: int | None,
) -> None:
    path = (settings.menu_image_path or "").strip()
    if path and os.path.isfile(path):
        photo = FSInputFile(path)
        if edit_message_id is not None:
            try:
                await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=edit_message_id,
                    media=InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
                    reply_markup=keyboard,
                )
                return
            except Exception as exc:
                logger.debug(
                    "edit_message_media failed, falling back to send_photo: %s", exc
                )
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return

    # No photo configured or file missing - plain text menu.
    await _send(bot, chat_id, caption, keyboard, edit_message_id)


async def _send(
    bot: Bot,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup | None,
    edit_message_id: int | None,
) -> None:
    if edit_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=edit_message_id,
                text=text,
                reply_markup=keyboard,
            )
            return
        except Exception as exc:
            logger.debug("edit_message_text failed, sending new: %s", exc)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)


async def safe_edit(message: Message, text: str, keyboard: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except Exception:
        await message.answer(text, reply_markup=keyboard)


async def show_screen(
    callback: CallbackQuery,
    bot: Bot,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Render a sub-screen in place of the current menu message.

    Telegram refuses to edit a *photo* message into a *text* message, so if the
    message the user pressed is the brand photo we delete it and send a fresh
    text message instead - the photo must live only on the main menu, never on
    a sub-screen. For an ordinary text message we edit it in place, falling back
    to a new message if the edit fails (e.g. nothing changed, or the message
    was already replaced by something else).

    In tests the menu message is a plain text ``Message`` (it has no ``.photo``
    attribute), so the edit path is taken and existing assertions keep passing.
    """
    msg = callback.message
    if msg is not None and getattr(msg, "photo", None):
        chat_id = msg.chat.id
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
        except Exception as exc:  # best effort - the next send still shows the screen
            logger.debug("deleting menu photo failed: %s", exc)
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        return
    if msg is not None:
        try:
            await msg.edit_text(text, reply_markup=keyboard)
            return
        except Exception as exc:  # best effort
            logger.debug("edit_message_text failed, sending new: %s", exc)
    await bot.send_message(
        chat_id=callback.from_user.id, text=text, reply_markup=keyboard
    )


def captcha_retry_markup(lang: str) -> InlineKeyboardMarkup:
    return captcha_retry_keyboard(lang)
