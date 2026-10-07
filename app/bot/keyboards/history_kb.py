"""History, settings and search-count keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.base import DANGER, NEUTRAL, PRIMARY, SUCCESS, btn
from app.bot.keyboards.design import NAVIGATE, POSITIVE, SECONDARY
from app.services.i18n import LANGUAGES, t

LENGTH_OPTIONS = [5, 6, 7, 8, 10, 12]


def _mark(active: bool, text: str) -> str:
    return ("\u2713 " if active else "") + text


def history_keyboard(lang: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list] = []

    nav: list = []
    if total_pages > 1:
        if page > 0:
            nav.append(btn("\u25C0", style=PRIMARY, callback_data=f"{cb.HISTORY_PREFIX}:{page - 1}"))
        nav.append(btn(f"{page + 1} / {total_pages}", style=NEUTRAL, callback_data="noop"))
        if page < total_pages - 1:
            nav.append(
                btn("\u25B6", style=PRIMARY, callback_data=f"{cb.HISTORY_PREFIX}:{page + 1}")
            )
    if nav:
        rows.append(nav)

    rows.append(
        [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard(
    lang: str, search_length: int, search_digits: bool,
    language: str, daily_drop: bool = False,
) -> InlineKeyboardMarkup:
    """Search defaults plus language, and the Daily Drop toggle.

    The old basic/collectible/all-in-one mode switch is gone: the search wizard
    now picks the target explicitly, so a stored "mode" had no effect on
    anything and only confused people. The rating filter is gone for good too -
    the bot applies its own quality criteria, so a user-facing score knob had
    nothing left to do.

    Every possible value used to be its own button here - sixteen buttons across
    four rows, six of them sharing a single icon. Dense, and monotonous for
    exactly that reason. Each setting is now one row showing its current value,
    and opens its own picker.
    """
    digits = t(lang, "search.on") if search_digits else t(lang, "search.off")
    drop_state = t(lang, "search.on") if daily_drop else t(lang, "search.off")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    f"{t(lang, 'settings.def_length')}: {search_length}",
                    icon="letters", style=NAVIGATE,
                    callback_data=f"{cb.SETTINGS_LENGTH_PREFIX}:menu",
                )
            ],
            [
                btn(
                    f"{t(lang, 'settings.def_digits')}: {digits}",
                    icon="numbers",
                    style=POSITIVE if search_digits else SECONDARY,
                    callback_data=f"{cb.SETTINGS_DIGITS_PREFIX}:{0 if search_digits else 1}",
                )
            ],
            [
                btn(
                    f"{t(lang, 'settings.digest')}: {drop_state}",
                    icon="bell",
                    style=POSITIVE if daily_drop else SECONDARY,
                    callback_data=f"{cb.SETTINGS_DIGEST_PREFIX}:menu",
                )
            ],
            [
                btn(
                    _mark(code == language, name),
                    style=SECONDARY,
                    callback_data=f"{cb.SETTINGS_LANG_PREFIX}:{code}",
                )
                for code, name in LANGUAGES.items()
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=SECONDARY,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def value_picker_keyboard(
    lang: str, prefix: str, options: list[int], current: int, *, suffix: str = ""
) -> InlineKeyboardMarkup:
    """A plain grid of values - no icons, because these are data, not actions."""
    rows = [options[i : i + 4] for i in range(0, len(options), 4)]
    markup = [
        [
            btn(
                _mark(value == current, f"{value}{suffix}"),
                style=POSITIVE if value == current else SECONDARY,
                callback_data=f"{prefix}:{value}",
            )
            for value in row
        ]
        for row in rows
    ]
    markup.append(
        [
            btn(
                t(lang, "btn.back_settings"), icon="back", style=SECONDARY,
                callback_data=cb.MENU_SETTINGS,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=markup)


def digest_keyboard(lang: str, daily_drop: bool) -> InlineKeyboardMarkup:
    """The Daily Drop screen: toggle it, grab one now, or go back."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "digest.turn_off") if daily_drop else t(lang, "digest.turn_on"),
                    icon="bell",
                    style=DANGER if daily_drop else SUCCESS,
                    callback_data=f"{cb.SETTINGS_DIGEST_PREFIX}:{0 if daily_drop else 1}",
                )
            ],
            [
                btn(
                    t(lang, "digest.now"), icon="search", style=PRIMARY,
                    callback_data=cb.DIGEST_NOW,
                )
            ],
            [
                btn(
                    t(lang, "btn.back_settings"), icon="back", style=SECONDARY,
                    callback_data=cb.MENU_SETTINGS,
                )
            ],
        ]
    )


def search_count_keyboard(lang: str, counts: list[int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(str(value), style=PRIMARY, callback_data=f"{cb.SEARCH_COUNT_PREFIX}:{value}")
                for value in counts
            ],
            [
                btn(t(lang, "btn.cancel"), icon="cross_mark", style=NEUTRAL, callback_data=cb.MENU_HOME)
            ],
        ]
    )
