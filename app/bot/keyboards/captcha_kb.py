"""CAPTCHA keyboard. Options carry indices, never answers."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.base import PRIMARY, btn
from app.services.captcha import CaptchaChallenge
from app.services.i18n import t


def captcha_keyboard(challenge: CaptchaChallenge, lang: str) -> InlineKeyboardMarkup:
    buttons = [
        btn(
            option,
            icon="numbers",
            style=PRIMARY,
            callback_data=f"{cb.CAPTCHA_PREFIX}:ans:{challenge.session_id}:{index}",
        )
        for index, option in enumerate(challenge.options)
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def captcha_retry_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "captcha.new"),
                    icon="refresh",
                    style=PRIMARY,
                    callback_data=cb.CAPTCHA_RETRY,
                )
            ]
        ]
    )
