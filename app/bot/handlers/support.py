"""Support screen: FAQ plus a direct link to the developer."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import texts
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.features_kb import back_home_keyboard, support_keyboard
from app.services.i18n import t
from app.services.runtime_config import runtime
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)
router = Router(name="support")


def support_url() -> str:
    handle = runtime.support_username or "mogeds2"
    return f"https://t.me/{handle}"


@router.callback_query(F.data == cb.MENU_SUPPORT)
async def cb_support(callback: CallbackQuery, lang: str = "en") -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            texts.support_screen(lang), reply_markup=support_keyboard(lang, support_url())
        )


@router.callback_query(F.data == cb.SUPPORT_FAQ)
async def cb_faq(callback: CallbackQuery, lang: str = "en") -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            texts.faq_screen(lang), reply_markup=support_keyboard(lang, support_url())
        )
