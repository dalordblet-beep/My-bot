"""Keyboards for the search wizard, profile, battle and support."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.base import DANGER, NEUTRAL, PRIMARY, SUCCESS, btn
from app.services.i18n import t

LENGTHS = [5, 6, 7, 8, 10, 12, 16]


def search_setup_keyboard(
    lang: str, *, length: int | None, digits: bool, mask: str | None,
) -> InlineKeyboardMarkup:
    digit_label = t(lang, "search.on") if digits else t(lang, "search.off")
    length_label = str(length) if length else t(lang, "search.any")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    f"{t(lang, 'btn.length')}: {length_label}",
                    icon="letters", style=PRIMARY, callback_data=f"{cb.FIND_LEN_PREFIX}:menu",
                ),
                btn(
                    f"{t(lang, 'btn.digits')}: {digit_label}",
                    icon="numbers", style=PRIMARY,
                    callback_data=f"{cb.FIND_DIGITS_PREFIX}:{0 if digits else 1}",
                ),
            ],
            [
                btn(
                    t(lang, "btn.filters"), icon="filter", style=PRIMARY,
                    callback_data=cb.FIND_FILTER,
                )
            ],
            [
                btn(
                    t(lang, "btn.run_search"), icon="rocket", style=SUCCESS,
                    callback_data=cb.FIND_RUN,
                )
            ],
            [
                btn(
                    t(lang, "btn.bulk"), icon="clipboard", style=PRIMARY,
                    callback_data=cb.MENU_BULK,
                ),
                btn(
                    t(lang, "btn.top"), icon="trophy", style=NEUTRAL,
                    callback_data=cb.MENU_TOP,
                ),
            ],
            [
                btn(
                    t(lang, "btn.favorites"), icon="star", style=NEUTRAL,
                    callback_data=cb.MENU_FAVORITES,
                )
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def length_keyboard(lang: str, current: int | None) -> InlineKeyboardMarkup:
    rows = [
        [
            btn(
                ("\u2713 " if value == current else "") + str(value),
                style=SUCCESS if value == current else PRIMARY,
                callback_data=f"{cb.FIND_LEN_PREFIX}:{value}",
            )
            for value in LENGTHS[:4]
        ],
        [
            btn(
                ("\u2713 " if value == current else "") + str(value),
                style=SUCCESS if value == current else PRIMARY,
                callback_data=f"{cb.FIND_LEN_PREFIX}:{value}",
            )
            for value in LENGTHS[4:]
        ],
        [
            btn(
                t(lang, "search.any"), icon="compass", style=NEUTRAL,
                callback_data=f"{cb.FIND_LEN_PREFIX}:0",
            )
        ],
        [
            btn(
                t(lang, "btn.back_search"), icon="back", style=NEUTRAL,
                callback_data=cb.MENU_SEARCH_ENGINE,
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def filter_keyboard(lang: str, mask: str | None) -> InlineKeyboardMarkup:
    """Filters screen: the mask is the only filter left.

    The rating filter is gone for good - the bot applies its own quality
    criteria to every candidate, so a user-facing score knob had nothing left
    to do but confuse.
    """
    mask_label = mask or t(lang, "search.none")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    f"{t(lang, 'btn.mask')}: {mask_label}", icon="tag",
                    style=PRIMARY if mask else NEUTRAL, callback_data=cb.FIND_MASK,
                )
            ],
            [
                btn(
                    t(lang, "btn.clear_filters"), icon="broom", style=DANGER,
                    callback_data=cb.FIND_CLEAR,
                )
            ],
            [
                btn(
                    t(lang, "btn.back_search"), icon="back", style=NEUTRAL,
                    callback_data=cb.MENU_SEARCH_ENGINE,
                )
            ],
        ]
    )


def watch_keyboard(lang: str, watches: list) -> InlineKeyboardMarkup:
    """Dedicated username-watch screen: check or remove each watch, add another."""
    rows = []
    for watch in watches[:10]:
        rows.append(
            [
                btn(
                    f"@{watch.username}", icon="eye", style=PRIMARY,
                    callback_data=f"{cb.WATCH_CHECK_PREFIX}:{watch.id}",
                ),
                btn(
                    t(lang, "btn.remove"), icon="cross_mark", style=DANGER,
                    callback_data=f"{cb.WATCH_DEL_PREFIX}:{watch.id}",
                ),
            ]
        )
    rows.append(
        [btn(t(lang, "watch.add"), icon="bell", style=SUCCESS, callback_data=cb.WATCH_ADD)]
    )
    rows.append(
        [
            btn(
                t(lang, "watch.watch_listing"), icon="money", style=PRIMARY,
                callback_data=cb.WATCH_LISTING,
            )
        ]
    )
    rows.append(
        [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def portfolio_keyboard(lang: str, items: list) -> InlineKeyboardMarkup:
    """Each holding opens on Fragment; the cross removes it."""
    rows = []
    for item in items[:8]:
        rows.append(
            [
                btn(
                    f"@{item.username}", icon="money", style=PRIMARY,
                    url=f"https://fragment.com/username/{item.username}",
                ),
                btn(
                    t(lang, "btn.remove"), icon="cross_mark", style=DANGER,
                    callback_data=f"{cb.PORT_DEL_PREFIX}:{item.id}",
                ),
            ]
        )
    rows.append(
        [
            btn(t(lang, "portfolio.add"), icon="star", style=SUCCESS, callback_data=cb.PORT_ADD),
            btn(t(lang, "btn.refresh"), icon="refresh", style=NEUTRAL, callback_data=cb.PORT_REFRESH),
        ]
    )
    rows.append(
        [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def appraise_keyboard(lang: str, username: str, is_free: bool) -> InlineKeyboardMarkup:
    """Actions for an appraisal: claim it, track it, or hunt alternatives."""
    rows = []
    if is_free:
        rows.append(
            [
                btn(
                    t(lang, "btn.open"), icon="link", style=SUCCESS,
                    url=f"https://t.me/{username}",
                )
            ]
        )
    rows.append(
        [
            btn(
                t(lang, "btn.add_portfolio"), icon="money", style=PRIMARY,
                callback_data=f"{cb.PORT_ADD_NAME_PREFIX}:{username}",
            ),
            btn(
                t(lang, "btn.watch"), icon="eye", style=SUCCESS,
                callback_data=f"{cb.WATCH_ADD_NAME_PREFIX}:{username}",
            ),
        ]
    )
    rows.append(
        [
            btn(
                t(lang, "btn.variants"), icon="compass", style=NEUTRAL,
                callback_data=f"{cb.FIND_VARIANTS_PREFIX}:{username}",
            ),
            btn(
                t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                callback_data=cb.MENU_HOME,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def battle_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "battle.mode_manual"), icon="battle", style=DANGER,
                    callback_data=cb.BATTLE_MANUAL,
                )
            ],
            [
                btn(
                    t(lang, "battle.mode_challenge"), icon="link", style=PRIMARY,
                    callback_data=cb.BATTLE_CHALLENGE,
                )
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def support_keyboard(lang: str, support_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "support.faq_btn"), icon="question", style=PRIMARY,
                    callback_data=cb.SUPPORT_FAQ,
                )
            ],
            [
                btn(
                    t(lang, "support.write_btn"), icon="envelope", style=SUCCESS,
                    url=support_url,
                )
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def back_home_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)]
        ]
    )


def profile_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.achievements"), icon="medal", style=SUCCESS,
                    callback_data=cb.PROFILE_ACH,
                )
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def battle_accept_keyboard(lang: str, battle_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "battle.accept"), icon="battle", style=DANGER,
                    callback_data=f"{cb.BATTLE_ACCEPT_PREFIX}:{battle_id}",
                )
            ]
        ]
    )


def favorite_toggle_keyboard(lang: str, username: str, premium_total: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.save"), icon="star", style=SUCCESS,
                    callback_data=f"{cb.FAV_ADD_PREFIX}:{username}:{premium_total}",
                ),
                btn(
                    t(lang, "btn.rate"), icon="chart", style=NEUTRAL,
                    callback_data=cb.MENU_TOP,
                ),
            ],
            [
                btn(
                    t(lang, "btn.back_search"), icon="back", style=NEUTRAL,
                    callback_data=cb.MENU_SEARCH_ENGINE,
                )
            ],
        ]
    )


def claim_kit_keyboard(lang: str, username: str, premium_total: int) -> InlineKeyboardMarkup:
    """The action row for a confirmed-free name.

    A free name is only useful if the user can take it, and usernames are
    first-come-first-served, so the moment of the result is the moment to act:
    open it on Telegram, save it, hunt close alternatives, or start a new
    search. The "Open" button is a real ``url`` button - one tap from the result
    to the profile - while the rest are the usual inline actions.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.open"), icon="link", style=SUCCESS,
                    url=f"https://t.me/{username}",
                ),
                btn(
                    t(lang, "btn.save"), icon="star", style=PRIMARY,
                    callback_data=f"{cb.FAV_ADD_PREFIX}:{username}:{premium_total}",
                ),
            ],
            [
                btn(
                    t(lang, "btn.variants"), icon="compass", style=PRIMARY,
                    callback_data=f"{cb.FIND_VARIANTS_PREFIX}:{username}",
                ),
                btn(
                    t(lang, "btn.new_search"), icon="search", style=NEUTRAL,
                    callback_data=cb.MENU_SEARCH_ENGINE,
                ),
            ],
        ]
    )


def variants_keyboard(lang: str, seed: str) -> InlineKeyboardMarkup:
    """Action row for a variants shortlist: re-roll, or leave."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.new_search"), icon="search", style=PRIMARY,
                    callback_data=cb.MENU_SEARCH_ENGINE,
                ),
                btn(
                    t(lang, "btn.variants"), icon="compass", style=NEUTRAL,
                    callback_data=f"{cb.FIND_VARIANTS_PREFIX}:{seed}",
                ),
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def occupied_result_keyboard(lang: str, username: str) -> InlineKeyboardMarkup:
    """Action row for an occupied /check result.

    The basic check correctly reports a name as occupied, but the screen used to
    be a dead end - the user could only go back to the menu. One tap now hands
    them straight to free alternatives through the same variants flow the
    search "find similar" button uses, so an occupied name never strands them.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.variants"), icon="compass", style=PRIMARY,
                    callback_data=f"{cb.FIND_VARIANTS_PREFIX}:{username}",
                ),
                btn(
                    t(lang, "btn.new_search"), icon="search", style=NEUTRAL,
                    callback_data=cb.MENU_SEARCH_ENGINE,
                ),
            ],
            [
                btn(
                    t(lang, "btn.main_menu"), icon="home", style=NEUTRAL,
                    callback_data=cb.MENU_HOME,
                )
            ],
        ]
    )


def favorites_keyboard(lang: str, favorites: list) -> InlineKeyboardMarkup:
    rows = [
        [
            btn(
                f"@{row.username}", icon="star", style=PRIMARY,
                callback_data=f"{cb.FAV_DEL_PREFIX}:{row.id}",
            )
        ]
        for row in favorites[:12]
    ]
    rows.append(
        [btn(t(lang, "btn.back_search"), icon="back", style=NEUTRAL, callback_data=cb.MENU_SEARCH_ENGINE)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
