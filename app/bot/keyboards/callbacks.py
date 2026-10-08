"""Callback-data constants shared by keyboards and handlers.

Every callback carries only opaque ids - never an answer, a role or a flag that
the handler would blindly trust.
"""

from __future__ import annotations

# language
LANG_PREFIX = "lang"

# main menu
MENU_CHECK = "menu:check"
MENU_BASIC = "menu:basic"
MENU_COLLECTIBLE = "menu:collectible"
MENU_ALL_IN_ONE = "menu:allinone"
MENU_SEARCH = "menu:search"
MENU_HISTORY = "menu:history"
MENU_SETTINGS = "menu:settings"
MENU_HOME = "menu:home"

# captcha
CAPTCHA_PREFIX = "captcha"
CAPTCHA_RETRY = "captcha:retry"

# subscription
SUB_CHECK_PREFIX = "sub:check"
SUB_CHECK_CHANNEL = "sub:check:channel"
SUB_CHECK_CHAT = "sub:check:chat"
SUB_JOIN_CHANNEL = "sub:join:channel"
SUB_JOIN_CHAT = "sub:join:chat"

# history / settings
HISTORY_PREFIX = "hist"
SETTINGS_MODE_PREFIX = "set:mode"
SETTINGS_LIMIT_PREFIX = "set:limit"
SETTINGS_LANG_PREFIX = "set:lang"

# search
SEARCH_COUNT_PREFIX = "scan:count"

# admin
ADMIN_ROOT = "adm:root"
ADMIN_USERS = "adm:users"
ADMIN_BLACKLIST = "adm:blacklist"
ADMIN_RESTRICTIONS = "adm:restrictions"
ADMIN_PRIVILEGES = "adm:privileges"
ADMIN_STATS = "adm:stats"
ADMIN_LOGS = "adm:logs"
ADMIN_ACCESS = "adm:access"
ADMIN_SETTINGS = "adm:settings"
ADMIN_SYSTEM = "adm:system"
ADMIN_ACTION_LOGS = "adm:actionlogs"

ADMIN_USER_PREFIX = "adm:user"          # adm:user:<telegram_id>
ADMIN_BAN_PREFIX = "adm:ban"            # adm:ban:<telegram_id>
ADMIN_UNBAN_PREFIX = "adm:unban"        # adm:unban:<telegram_id>
ADMIN_RESTRICT_PREFIX = "adm:restrict"  # adm:restrict:<telegram_id>:<seconds>
ADMIN_CLEAR_PREFIX = "adm:clear"        # adm:clear:<telegram_id>
ADMIN_PRIV_PREFIX = "adm:priv"          # adm:priv:<telegram_id>:<PRIVILEGE>
ADMIN_NOTE_PREFIX = "adm:note"          # adm:note:<telegram_id>
ADMIN_SEARCH_PREFIX = "adm:find"        # adm:find:<page>
ADMIN_BLACKLIST_PAGE_PREFIX = "adm:blpage"
ADMIN_USERLIST_PAGE_PREFIX = "adm:ulpage"
ADMIN_LOGS_PAGE_PREFIX = "adm:lgpage"
ADMIN_ACTIONLOG_PAGE_PREFIX = "adm:alpage"
ADMIN_SETTING_PREFIX = "adm:set"        # adm:set:<key>
ADMIN_ACTIONS_PREFIX = "adm:actions"    # adm:actions:<telegram_id>

ADMIN_MENU = "admin_menu"


def admin_user_cb(telegram_id: int) -> str:
    return f"{ADMIN_USER_PREFIX}:{telegram_id}"


def admin_ban_cb(telegram_id: int) -> str:
    return f"{ADMIN_BAN_PREFIX}:{telegram_id}"


def admin_unban_cb(telegram_id: int) -> str:
    return f"{ADMIN_UNBAN_PREFIX}:{telegram_id}"


def admin_restrict_cb(telegram_id: int, seconds: int) -> str:
    return f"{ADMIN_RESTRICT_PREFIX}:{telegram_id}:{seconds}"


def admin_clear_cb(telegram_id: int) -> str:
    return f"{ADMIN_CLEAR_PREFIX}:{telegram_id}"


def admin_priv_cb(telegram_id: int, privilege: str) -> str:
    return f"{ADMIN_PRIV_PREFIX}:{telegram_id}:{privilege}"


def admin_note_cb(telegram_id: int) -> str:
    return f"{ADMIN_NOTE_PREFIX}:{telegram_id}"


def admin_actions_cb(telegram_id: int) -> str:
    return f"{ADMIN_ACTIONS_PREFIX}:{telegram_id}"


def admin_setting_cb(key: str) -> str:
    return f"{ADMIN_SETTING_PREFIX}:{key}"

# ------------------------------------------------------------------ features
MENU_SEARCH_ENGINE = "menu:find"
MENU_PROFILE = "menu:profile"
MENU_BATTLE = "menu:battle"
MENU_SUPPORT = "menu:support"

FIND_LEN_PREFIX = "find:len"
FIND_DIGITS_PREFIX = "find:dig"
FIND_FILTER = "find:filter"
FIND_MASK = "find:mask"
FIND_CLEAR = "find:clear"
FIND_RUN = "find:run"
FIND_VARIANTS_PREFIX = "find:variants"

MENU_WATCH = "menu:watch"
WATCH_ADD = "watch:add"
WATCH_DEL_PREFIX = "watch:del"
WATCH_CHECK_PREFIX = "watch:check"

BATTLE_MANUAL = "battle:manual"
BATTLE_CHALLENGE = "battle:challenge"
BATTLE_ACCEPT_PREFIX = "battle:accept"

SUPPORT_FAQ = "support:faq"

SETTINGS_LENGTH_PREFIX = "set:len"
SETTINGS_DIGITS_PREFIX = "set:dig"
SETTINGS_DIGEST_PREFIX = "set:digest"
DIGEST_NOW = "digest:now"

MENU_BULK = "menu:bulk"
MENU_TOP = "menu:top"
MENU_FAVORITES = "menu:fav"
FAV_ADD_PREFIX = "fav:add"
FAV_DEL_PREFIX = "fav:del"
PROFILE_ACH = "menu:ach"

# appraisal + collector portfolio + listing sniper
MENU_APPRAISE = "menu:appraise"
MENU_PORTFOLIO = "menu:portfolio"
PORT_ADD = "port:add"
PORT_DEL_PREFIX = "port:del"
PORT_REFRESH = "port:refresh"
PORT_ADD_NAME_PREFIX = "port:addname"
WATCH_LISTING = "watch:listing"
WATCH_ADD_NAME_PREFIX = "watch:addname"
