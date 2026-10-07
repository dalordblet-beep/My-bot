"""User settings: search defaults and language."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.history_kb import (
    LENGTH_OPTIONS,
    digest_keyboard,
    settings_keyboard,
    value_picker_keyboard,
)
from app.database import repository as repo
from app.database.models import User
from app.search.finder import TARGET_FREE, SearchCriteria
from app.services import user as user_service
from app.services.daily_drop import DEFAULT_HOUR
from app.services.i18n import LANGUAGES, normalise, t
from app.services.search_queue import SearchQueue, priority_for
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="settings")



async def _render(session: AsyncSession, user: User, lang: str):
    row = await user_service.get_settings_row(session, user)
    effective = normalise(row.language or lang)
    text = texts.settings_screen(
        effective, user,
        search_length=row.search_length or 8,
        search_digits=bool(row.search_digits),
        language=effective,
        daily_drop=bool(row.daily_drop),
    )
    keyboard = settings_keyboard(
        effective, row.search_length or 8, bool(row.search_digits),
        effective, bool(row.daily_drop),
    )
    return text, keyboard, effective


async def _show(callback: CallbackQuery, bot: Bot, text: str, keyboard) -> None:
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


@router.callback_query(F.data == cb.MENU_SETTINGS)
async def cb_settings(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    text, keyboard, _ = await _render(session, user, lang)
    await callback.answer()
    await _show(callback, bot, text, keyboard)


@router.callback_query(F.data.startswith(f"{cb.SETTINGS_LENGTH_PREFIX}:"))
async def cb_set_length(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    """``menu`` opens the picker; a number saves it."""
    raw = (callback.data or "").split(":")[-1]
    row = await user_service.get_settings_row(session, user)

    if raw == "menu":
        await callback.answer()
        if callback.message is not None:
            await callback.message.edit_text(
                t(lang, "settings.pick_length"),
                reply_markup=value_picker_keyboard(
                    lang, cb.SETTINGS_LENGTH_PREFIX, LENGTH_OPTIONS, row.search_length or 8
                ),
            )
        return

    try:
        value = int(raw)
    except ValueError:
        await callback.answer()
        return

    if value in LENGTH_OPTIONS:
        await repo.update_user_settings(session, user.id, search_length=value)
        await callback.answer(t(lang, "settings.updated_mode"))
    else:
        await callback.answer(t(lang, "settings.unknown"), show_alert=True)

    text, keyboard, _ = await _render(session, user, lang)
    await _show(callback, bot, text, keyboard)


@router.callback_query(F.data.startswith(f"{cb.SETTINGS_DIGITS_PREFIX}:"))
async def cb_set_digits(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    value = (callback.data or "").split(":")[-1] == "1"
    await repo.update_user_settings(session, user.id, search_digits=value)
    await callback.answer(t(lang, "settings.updated_mode"))
    text, keyboard, _ = await _render(session, user, lang)
    await _show(callback, bot, text, keyboard)


@router.callback_query(F.data.startswith(f"{cb.SETTINGS_LANG_PREFIX}:"))
async def cb_set_lang(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    value = (callback.data or "").split(":")[-1]
    if value not in LANGUAGES:
        await callback.answer(t(lang, "settings.unknown"), show_alert=True)
        return

    await repo.update_user_settings(session, user.id, language=value)
    new_lang = normalise(value)
    await callback.answer(t(new_lang, "settings.updated_lang"))

    text, keyboard, _ = await _render(session, user, new_lang)
    await _show(callback, bot, text, keyboard)


@router.message(Command("settings"))
async def cmd_settings(
    message: Message, session: AsyncSession, user: User, lang: str = "en"
) -> None:
    text, keyboard, _ = await _render(session, user, lang)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith(f"{cb.SETTINGS_DIGEST_PREFIX}:"))
async def cb_set_digest(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    """Open the Daily Drop screen, or toggle it on/off (``1`` on, ``0`` off)."""
    raw = (callback.data or "").split(":")[-1]
    await callback.answer()

    if raw == "menu":
        row = await user_service.get_settings_row(session, user)
        enabled = bool(row.daily_drop)
        await _show(
            callback, bot,
            texts.digest_screen(lang, enabled, hour=DEFAULT_HOUR),
            digest_keyboard(lang, enabled),
        )
        return

    enable = raw == "1"
    await repo.update_user_settings(session, user.id, daily_drop=enable)
    await _show(
        callback, bot,
        texts.digest_screen(lang, enable, hour=DEFAULT_HOUR),
        digest_keyboard(lang, enable),
    )


@router.callback_query(F.data == cb.DIGEST_NOW)
async def cb_digest_now(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot,
    search_queue: SearchQueue, lang: str = "en",
) -> None:
    """Run one Daily Drop immediately, so the feature is not a mystery."""
    row = await user_service.get_settings_row(session, user)
    criteria = SearchCriteria(
        length=row.search_length or None,
        allow_digits=bool(row.search_digits),
        mask=row.search_mask or None,
        target=TARGET_FREE,
    )

    message = callback.message
    chat_id = message.chat.id if message is not None else callback.from_user.id
    message_id = message.message_id if message is not None else None

    ahead = await search_queue.submit(
        user_id=callback.from_user.id,
        chat_id=chat_id,
        message_id=message_id,
        criteria=criteria,
        lang=lang,
        used=1,
        priority=priority_for(user.privilege),
        kind="digest",
    )

    if ahead == -1:
        await callback.answer(t(lang, "search.queue_full"), show_alert=True)
        return
    if ahead == 0:
        await callback.answer(t(lang, "search.running"))
        return

    await callback.answer()
    await _show(callback, bot, t(lang, "digest.now_queued"), digest_keyboard(lang, True))
