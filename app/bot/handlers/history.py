"""Search history with pagination."""

from __future__ import annotations

import math

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.history_kb import history_keyboard
from app.database import repository as repo
from app.database.models import User
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="history")

PAGE_SIZE = 10


async def _render(session: AsyncSession, user: User, page: int, lang: str):
    total = await repo.count_searches(session, user.id)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    rows = await repo.list_searches(session, user.id, offset=page * PAGE_SIZE, limit=PAGE_SIZE)
    return (
        texts.history_screen(lang, list(rows), page, total_pages),
        history_keyboard(lang, page, total_pages),
    )


async def _show(callback: CallbackQuery, bot: Bot, text: str, keyboard) -> None:
    message = callback.message
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await bot.send_message(callback.from_user.id, text, reply_markup=keyboard)


@router.callback_query(F.data == cb.MENU_HISTORY)
async def cb_history(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    text, keyboard = await _render(session, user, 0, lang)
    await callback.answer()
    await _show(callback, bot, text, keyboard)


@router.callback_query(F.data.startswith(f"{cb.HISTORY_PREFIX}:"))
async def cb_history_page(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, lang: str = "en"
) -> None:
    try:
        page = int((callback.data or "").split(":")[-1])
    except ValueError:
        page = 0
    text, keyboard = await _render(session, user, page, lang)
    await callback.answer()
    await _show(callback, bot, text, keyboard)


@router.message(Command("history"))
async def cmd_history(message: Message, session: AsyncSession, user: User, lang: str = "en") -> None:
    text, keyboard = await _render(session, user, 0, lang)
    await message.answer(text, reply_markup=keyboard)
