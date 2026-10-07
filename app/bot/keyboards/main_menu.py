"""Main menu, welcome and language keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.base import DANGER, NEUTRAL, PRIMARY, SUCCESS, btn
from app.services.i18n import LANGUAGES, t


def main_menu_keyboard(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            btn(
                t(lang, "btn.search_engine"), icon="search", style=PRIMARY,
                callback_data=cb.MENU_SEARCH_ENGINE,
            )
        ],
        [
            btn(
                t(lang, "btn.watch"), icon="eye", style=SUCCESS,
                callback_data=cb.MENU_WATCH,
            )
        ],
        [
            btn(
                t(lang, "btn.profile"), icon="person", style=PRIMARY,
                callback_data=cb.MENU_PROFILE,
            ),
            btn(
                t(lang, "btn.history"), icon="history", style=NEUTRAL,
                callback_data=cb.MENU_HISTORY,
            ),
        ],
        [
            btn(
                t(lang, "btn.battle"), icon="battle", style=DANGER,
                callback_data=cb.MENU_BATTLE,
            ),
        ],
        [
            btn(
                t(lang, "btn.support"), icon="chat", style=NEUTRAL,
                callback_data=cb.MENU_SUPPORT,
            ),
            btn(
                t(lang, "btn.settings"), icon="gear", style=NEUTRAL,
                callback_data=cb.MENU_SETTINGS,
            ),
        ],
    ]
    if is_admin:
        rows.append(
            [
                btn(
                    t(lang, "btn.admin"), icon="crown", style=DANGER,
                    callback_data=cb.ADMIN_ROOT,
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)]
        ]
    )


def admin_entry_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.admin"), icon="crown", style=DANGER,
                    callback_data=cb.ADMIN_ROOT,
                )
            ],
            [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)],
        ]
    )


def language_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(name, style=PRIMARY, callback_data=f"{cb.LANG_PREFIX}:{code}")]
            for code, name in LANGUAGES.items()
        ]
    )
