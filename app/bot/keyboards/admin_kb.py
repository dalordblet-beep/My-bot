"""Admin panel keyboards - colour-coded by consequence, not by decoration."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.base import DANGER, NEUTRAL, PRIMARY, SUCCESS, btn
from app.database.models import User
from app.services.i18n import t
from app.utils.enums import Privilege

NAV_PREV = "\u25C0"
NAV_NEXT = "\u25B6"

PRIVILEGE_STYLE = {
    Privilege.FREE.value: NEUTRAL,
    Privilege.VIP.value: PRIMARY,
    Privilege.PREMIUM.value: SUCCESS,
    Privilege.ADMIN.value: DANGER,
}


def _nav(page: int, total_pages: int, prefix: str) -> list:
    if total_pages <= 1:
        return []
    row: list = []
    if page > 0:
        row.append(btn(NAV_PREV, style=PRIMARY, callback_data=f"{prefix}:{page - 1}"))
    row.append(btn(f"{page + 1} / {total_pages}", style=NEUTRAL, callback_data="noop"))
    if page < total_pages - 1:
        row.append(btn(NAV_NEXT, style=PRIMARY, callback_data=f"{prefix}:{page + 1}"))
    return row


def admin_root_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [
            btn(t(lang, "btn.users"), icon="users", style=PRIMARY, callback_data=cb.ADMIN_USERS),
            btn(
                t(lang, "btn.blacklist"),
                icon="ban",
                style=DANGER,
                callback_data=cb.ADMIN_BLACKLIST,
            ),
        ],
        [
            btn(
                t(lang, "btn.restrictions"),
                icon="stopwatch",
                style=DANGER,
                callback_data=cb.ADMIN_RESTRICTIONS,
            ),
            btn(
                t(lang, "btn.privileges"),
                icon="ticket",
                style=SUCCESS,
                callback_data=cb.ADMIN_PRIVILEGES,
            ),
        ],
        [
            btn(
                t(lang, "btn.statistics"),
                icon="chart",
                style=PRIMARY,
                callback_data=cb.ADMIN_STATS,
            ),
            btn(
                t(lang, "btn.search_logs"),
                icon="folder",
                style=NEUTRAL,
                callback_data=cb.ADMIN_LOGS,
            ),
        ],
        [
            btn(
                t(lang, "btn.access"),
                icon="shield_lock",
                style=NEUTRAL,
                callback_data=cb.ADMIN_ACCESS,
            )
        ],
        [
            btn(
                t(lang, "btn.bot_settings"),
                icon="wrench",
                style=NEUTRAL,
                callback_data=cb.ADMIN_SETTINGS,
            ),
            btn(
                t(lang, "btn.system"),
                icon="monitor",
                style=NEUTRAL,
                callback_data=cb.ADMIN_SYSTEM,
            ),
        ],
        [
            btn(
                t(lang, "btn.admin_logs"),
                icon="receipt",
                style=NEUTRAL,
                callback_data=cb.ADMIN_ACTION_LOGS,
            )
        ],
        [btn(t(lang, "btn.main_menu"), icon="home", style=NEUTRAL, callback_data=cb.MENU_HOME)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back_keyboard(lang: str, target: str = cb.ADMIN_ROOT) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=target)]
        ]
    )


def user_list_keyboard(
    lang: str, users: list[User], page: int, total_pages: int, prefix: str
) -> InlineKeyboardMarkup:
    rows: list[list] = []
    for user in users:
        name = f"@{user.username}" if user.username else f"id{user.telegram_id}"
        if user.is_banned:
            icon, style = "hammer", DANGER
        elif user.ban_until is not None:
            icon, style = "stopwatch", DANGER
        else:
            icon, style = "person", PRIMARY
        rows.append([btn(name, icon=icon, style=style, callback_data=cb.admin_user_cb(user.telegram_id))])

    nav = _nav(page, total_pages, prefix)
    if nav:
        rows.append(nav)

    rows.append([btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_search_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    t(lang, "btn.browse_all"),
                    icon="scroll",
                    style=PRIMARY,
                    callback_data=f"{cb.ADMIN_USERLIST_PAGE_PREFIX}:0",
                )
            ],
            [btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_ROOT)],
        ]
    )


def user_profile_keyboard(lang: str, user: User) -> InlineKeyboardMarkup:
    tid = user.telegram_id
    rows: list[list] = []

    if user.is_banned:
        rows.append(
            [
                btn(
                    t(lang, "btn.unban"),
                    icon="dove",
                    style=SUCCESS,
                    callback_data=cb.admin_unban_cb(tid),
                )
            ]
        )
    else:
        rows.append(
            [
                btn(
                    t(lang, "btn.block"),
                    icon="hammer",
                    style=DANGER,
                    callback_data=cb.admin_ban_cb(tid),
                )
            ]
        )

    rows.append(
        [
            btn(
                t(lang, "btn.restrict_10m"),
                icon="stopwatch",
                style=DANGER,
                callback_data=cb.admin_restrict_cb(tid, 600),
            ),
            btn(
                t(lang, "btn.restrict_1h"),
                icon="stopwatch",
                style=DANGER,
                callback_data=cb.admin_restrict_cb(tid, 3600),
            ),
        ]
    )
    rows.append(
        [
            btn(
                t(lang, "btn.restrict_24h"),
                icon="stopwatch",
                style=DANGER,
                callback_data=cb.admin_restrict_cb(tid, 86400),
            ),
            btn(
                t(lang, "btn.restrict_7d"),
                icon="stopwatch",
                style=DANGER,
                callback_data=cb.admin_restrict_cb(tid, 604800),
            ),
        ]
    )
    rows.append(
        [
            btn(
                t(lang, "btn.clear"),
                icon="broom",
                style=NEUTRAL,
                callback_data=cb.admin_clear_cb(tid),
            )
        ]
    )

    rows.append(
        [
            btn(
                privilege.value,
                icon="ticket",
                style=PRIVILEGE_STYLE[privilege.value],
                callback_data=cb.admin_priv_cb(tid, privilege.value),
            )
            for privilege in (Privilege.FREE, Privilege.VIP)
        ]
    )
    rows.append(
        [
            btn(
                privilege.value,
                icon="ticket",
                style=PRIVILEGE_STYLE[privilege.value],
                callback_data=cb.admin_priv_cb(tid, privilege.value),
            )
            for privilege in (Privilege.PREMIUM, Privilege.ADMIN)
        ]
    )

    rows.append(
        [
            btn(t(lang, "btn.note"), icon="pencil", style=NEUTRAL, callback_data=cb.admin_note_cb(tid)),
            btn(
                t(lang, "btn.actions"),
                icon="receipt",
                style=NEUTRAL,
                callback_data=cb.admin_actions_cb(tid),
            ),
        ]
    )
    rows.append([btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_USERS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def blacklist_keyboard(
    lang: str, users: list[User], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    return user_list_keyboard(lang, users, page, total_pages, cb.ADMIN_BLACKLIST_PAGE_PREFIX)


def privilege_picker_keyboard(lang: str, telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(
                    Privilege.FREE.value,
                    icon="ticket",
                    style=PRIVILEGE_STYLE[Privilege.FREE.value],
                    callback_data=cb.admin_priv_cb(telegram_id, Privilege.FREE.value),
                ),
                btn(
                    Privilege.VIP.value,
                    icon="ticket",
                    style=PRIVILEGE_STYLE[Privilege.VIP.value],
                    callback_data=cb.admin_priv_cb(telegram_id, Privilege.VIP.value),
                ),
            ],
            [
                btn(
                    Privilege.PREMIUM.value,
                    icon="ticket",
                    style=PRIVILEGE_STYLE[Privilege.PREMIUM.value],
                    callback_data=cb.admin_priv_cb(telegram_id, Privilege.PREMIUM.value),
                ),
                btn(
                    Privilege.ADMIN.value,
                    icon="ticket",
                    style=PRIVILEGE_STYLE[Privilege.ADMIN.value],
                    callback_data=cb.admin_priv_cb(telegram_id, Privilege.ADMIN.value),
                ),
            ],
            [btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_ROOT)],
        ]
    )


def settings_keyboard(lang: str, keys: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [
        [btn(text, icon="gear", style=NEUTRAL, callback_data=cb.admin_setting_cb(key))]
        for key, text in keys
    ]
    rows.append([btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscriptions_admin_keyboard(lang: str, managed: list) -> InlineKeyboardMarkup:
    """Editor for mandatory channels: remove each, add a new one, back."""
    rows: list[list] = []
    for sub in managed:
        title = sub.label or sub.username or sub.key
        label = f"{t(lang, 'btn.remove_sub')}: {title}"
        if len(label) > 58:
            label = label[:55] + "..."
        rows.append(
            [
                btn(
                    label, icon="ban", style=DANGER,
                    callback_data=f"{cb.ADMIN_SUB_REMOVE_PREFIX}:{sub.key}",
                )
            ]
        )
    rows.append(
        [
            btn(
                t(lang, "btn.add_channel"), icon="satellite", style=SUCCESS,
                callback_data=cb.ADMIN_SUB_ADD,
            )
        ]
    )
    rows.append([btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def logs_keyboard(lang: str, page: int, total_pages: int, prefix: str) -> InlineKeyboardMarkup:
    rows: list[list] = []
    nav = _nav(page, total_pages, prefix)
    if nav:
        rows.append(nav)
    rows.append([btn(t(lang, "btn.back"), icon="back", style=NEUTRAL, callback_data=cb.ADMIN_ROOT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
