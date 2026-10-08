"""Localisation.

One flat registry of dotted keys per language. Handlers and keyboards never
hardcode user-visible text - they call :func:`t`.

Adding a language = adding one dict. Nothing else changes.
"""

from __future__ import annotations

from app.services.emoji import PLAIN, emoji as _emoji
from app.services.runtime_config import runtime
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# Admin-editable button/label overrides, refreshed from runtime on boot and on
# every edit so t() stays cheap (no JSON parse per call).
_LABEL_OVERRIDES: dict[str, str] = {}


def refresh_custom_labels() -> None:
    """Pull the admin's label overrides into the fast lookup cache."""
    global _LABEL_OVERRIDES
    _LABEL_OVERRIDES = dict(runtime.custom_labels)

# Every template may reference {shield}, {search}, ... without passing them in.
_EMOJI_CONTEXT: dict[str, str] = {name: _emoji.render(name) for name in PLAIN}

DEFAULT_LANGUAGE = "en"

# code -> native label shown in the picker
LANGUAGES: dict[str, str] = {
    "ru": "\U0001F1F7\U0001F1FA  \u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    "en": "\U0001F1EC\U0001F1E7  English",
}

EN: dict[str, str] = {
    # ---------------------------------------------------------------- language
    "lang.title": "{shield} <b>CHOOSE YOUR LANGUAGE</b>",
    "lang.body": "Pick the language for the interface.\nYou can change it later in Settings.",
    "lang.changed": "Language updated",

    # ---------------------------------------------------------------- captcha
    "captcha.title": "{shield} <b>SECURITY CHECK</b>",
    "captcha.intro": "Before you start, please confirm that you are not a bot.",
    "captcha.attempts": "Attempts left: {left}",
    "captcha.wrong": "{cross} <b>Wrong answer</b>\n\nTry again. Attempts left: {left}",
    "captcha.failed": "{warn} <b>Too many attempts.</b>\n\nCreate a new check to continue.",
    "captcha.expired": "{hourglass} <b>Check expired.</b>\n\nCreate a new one to continue.",
    "captcha.passed": "{check} <b>Verification passed</b>",
    "captcha.new": "New check",

    # ---------------------------------------------------------------- gate
    "gate.channel.title": "{channel} <b>STEP 1 OF 2 - CHANNEL</b>",
    "gate.channel.body": (
        "Subscribe to our Telegram channel to continue.\n\n"
        "Tap the button below, then press Verify - "
        "the subscription is checked for real."
    ),
    "gate.channel.missing": "{cross} <b>Channel is not confirmed yet.</b>",
    "gate.chat.title": "{chat} <b>STEP 2 OF 2 - CHAT</b>",
    "gate.chat.body": (
        "Almost there. Join our chat to unlock full access.\n\n"
        "Tap the button below, then press Verify."
    ),
    "gate.chat.missing": "{cross} <b>You have not joined the chat yet.</b>",
    "gate.subs.title": "{channel} <b>REQUIRED SUBSCRIPTIONS</b>",
    "gate.subs.body": (
        "Subscribe to all {total} below, then press <b>I subscribed</b> under each.\n"
        "Each one is verified against Telegram for real."
    ),
    "gate.subs.item": "{n}. {status} {title}",
    "gate.subs.done": "\u2705",
    "gate.subs.todo": "\u2b1c",
    "gate.subs.generic": "Subscription {n}",
    "gate.subs.not_confirmed": "{cross} <b>Not confirmed yet</b> - join it and press again.",
    "gate.channel.name": "Channel",
    "gate.chat.name": "Community chat",
    "gate.unverified": (
        "{warn} Could not verify your membership.\n\n"
        "Make sure the bot is an administrator of the channel and chat, then try again."
    ),

    # ---------------------------------------------------------------- welcome
    "welcome.title": "{sparkle} <b>WELCOME, {name}</b>",
    "welcome.body": (
        "You now have full access to <b>Username Scanner</b>.\n\n"
        "Search, check and analyse Telegram usernames - "
        "basic names, collectible names and everything in between."
    ),
    "welcome.pick": "{search} Pick an action below.",

    # ---------------------------------------------------------------- menu
    "menu.title": "{search} <b>USERNAME SCANNER</b>",
    "menu.question": "What would you like to do?",

    # ---------------------------------------------------------------- ban / restrict
    "ban.title": "{ban} <b>ACCESS BLOCKED</b>",
    "ban.body": "Your access has been revoked by an administrator.",
    "ban.reason": "Reason: {reason}",
    "restrict.title": "{hourglass} <b>ACCESS RESTRICTED</b>",
    "restrict.body": "Your access is temporarily limited.",
    "restrict.reason": "Reason: {reason}",
    "restrict.until": "Active until: {until}",

    # ---------------------------------------------------------------- results
    "status.available": "{available} Available",
    "status.occupied": "{occupied} Occupied",
    "status.invalid": "{warn} Invalid",
    "status.unknown": "{warn} Unknown",
    "status.rate_limited": "{hourglass} Rate limited",
    "status.error": "{cross} Error",

    "result.title": "{search} <b>USERNAME RESULT</b>",
    "result.basic": "{available} <b>BASIC</b>",
    "result.collectible": "{collectible} <b>COLLECTIBLE</b>",
    "result.type": "Type: {value}",
    "result.reason": "Reason: {value}",
    "result.title_field": "Title: {value}",
    "result.occupied_hint": (
        "{info} <i>Press <b>Find similar</b> below for free alternatives.</i>"
    ),
    "result.verified": "{bolt} Verified just now",
    "result.verified_ms": "{bolt} Verified just now ({ms} ms)",
    "result.source": "Checked via: {value}",
    "source.mtproto": "Telegram, direct connection",
    "source.bot_api": "Telegram, bot interface",
    "source.public_page": "Telegram, public profile",
    "source.validation": "local validation",
    "source.fragment": "collectible marketplace",
    "source.fragment_web": "collectible marketplace",
    "source.none": "not checked",
    "result.source_cached": "Checked via: {value}",
    "result.telegram_no_owner": "Telegram: no active owner detected",
    "result.telegram_active": "Telegram: active {kind}",
    "result.not_checked": "Not checked",
    "result.not_detected": "Not detected",
    "result.no_answer": "{warn} Telegram did not give a trustworthy answer.",
    "result.need_mtproto": (
        "{hourglass} Telegram did not give a definitive answer.\n"
        "Please try again in a moment."
    ),
    "result.no_checker": "{hourglass} Checking is unavailable right now. Please try again later.",

    "collectible.title": "{collectible} <b>COLLECTIBLE RESULT</b>",
    "collectible.status": "Status: {value}",
    "collectible.marketplace": "Marketplace: Fragment",
    "collectible.owner": "Owner: @{value}",
    "collectible.price": "Price: {value}",
    "collectible.s_purchase": "Purchase available",
    "collectible.s_owned": "Owned",
    "collectible.s_listed": "Listed",
    "collectible.s_not_detected": "Not detected",
    "collectible.s_unavailable": "Unavailable",
    "collectible.s_unknown": "Unknown",
    "collectible.disabled": (
        "{hourglass} <b>Collectible lookup is unavailable right now.</b>\n\n"
        "Please try again later."
    ),
    "collectible.no_data": "{warn} No trustworthy data available.",
    "collectible.unavailable_short": "{warn} Temporarily unavailable (not configured)",
    "collectible.purchased": "Purchased: {value}",
    "collectible.need_login": (
        "{hourglass} <b>Collectible lookup is busy right now.</b>\n\n"
        "Please try again in a few minutes."
    ),
    "collectible.need_login_short": "{hourglass} Temporarily unavailable",
    "collectible.min_bid": "min bid {value} TON",
    "value.estimate": (
        "{chart} Comparable names are asking <b>{low}-{high} TON</b> on Fragment "
        "right now (median <b>≈ {price} TON</b>, {n} live listings)"
    ),
    "value.no_market": (
        "{info} No comparable listing on Fragment - this name is not a traded "
        "collectible, so there is no honest price to quote."
    ),
    "value.wordlike": "looks like a real word - premium over random",

    # ---------------------------------------------------------------- scan
    "scan.scanning": "{search} <b>SCANNING...</b>",
    "scan.checked": "{done} / {total} checked",
    "scan.available": "{available} Available: {n}",
    "scan.collectible": "{collectible} Collectible: {n}",
    "scan.occupied": "{occupied} Occupied: {n}",
    "scan.unknown": "{warn} Unknown: {n}",
    "scan.invalid": "{cross} Invalid: {n}",
    "scan.rate_limited": "{hourglass} Rate limited: {n}",
    "scan.complete": "{check} <b>SCAN COMPLETE</b>",
    "scan.usernames_checked": "{n} usernames checked",
    "scan.available_list": "<b>Available:</b>",
    "scan.more": "<i>...and {n} more</i>",
    "scan.time": "Time: {value} sec",

    # ---------------------------------------------------------------- search
    "search.title": "{bolt} <b>USERNAME SEARCH</b>",
    "search.body": "Send a base word and I will generate variants and scan them.",
    "search.example": "Example: <code>moged</code>",
    "search.bad_seed": "{warn} That does not look like a usable base word.\n\nSend something like <code>moged</code>.",
    "search.how_many": "{bolt} <b>HOW MANY VARIANTS?</b>",
    "search.base": "Base: <b>{value}</b>",
    "search.pick": "Pick how many to generate and check (max {max}).",
    "search.need_seed": "Send a base word first",
    "search.capped": "Limited to {n} by your plan",

    # ---------------------------------------------------------------- history
    "history.title": "{history} <b>YOUR HISTORY</b>",
    "history.empty": "{history} <b>YOUR HISTORY</b>\n\nNothing here yet. Run a check first.",
    "history.page": "Page {page} / {total}",

    # ---------------------------------------------------------------- settings
    "settings.title": "{settings} <b>SETTINGS</b>",
    "settings.default_mode": "Default mode",
    "settings.def_length": "Default length",
    "settings.def_digits": "Default digits",
    "settings.pick_length": (
        "{letters} <b>DEFAULT LENGTH</b>\n\n"
        "How many characters should a generated name have?"
    ),
    "settings.results_limit": "Results limit",
    "settings.language": "Language",
    "settings.privilege": "Privilege",
    "settings.digest": "Daily Drop",
    "settings.updated_mode": "Default mode updated",
    "settings.updated_limit": "Results limit updated",
    "settings.updated_lang": "Language updated",
    "settings.updated_digest": "Daily Drop updated",
    "settings.unknown": "Unsupported value",

    # ---------------------------------------------------------------- help
    "help.title": "{search} <b>HELP</b>",
    "help.start": "/start - onboarding and main menu",
    "help.check": "/check &lt;username&gt; - check a username",
    "help.search": "/search &lt;word&gt; - generate and scan variants",
    "help.history": "/history - your recent searches",
    "help.settings": "/settings - language and preferences",
    "help.help": "/help - this message",
    "help.admin": "/admin - admin panel",

    # ---------------------------------------------------------------- admin
    "admin.title": "{crown} <b>ADMIN PANEL</b>",
    "admin.signed_in": "Signed in as <b>{id}</b>",
    "admin.role": "Role: <b>{role}</b>",
    "admin.pick": "Pick a section.",
    "admin.denied": "{lock} This command is restricted.",
    "admin.not_authorized": "Not authorized",

    "admin.users_title": "{users} <b>USERS</b>",
    "admin.users_hint": "Send a Telegram ID or a username to search.",
    "admin.users_count": "{users} <b>USERS</b> ({n})",
    "admin.users_page": "Page {page} / {total}",
    "admin.not_found": "No users found.",
    "admin.user_not_found": "User not found",
    "admin.found": "Found <b>{n}</b> user(s).",

    "admin.profile_title": "{person} <b>USER PROFILE</b>",
    "admin.p_id": "ID",
    "admin.p_username": "Username",
    "admin.p_registered": "Registered",
    "admin.p_last": "Last activity",
    "admin.p_checks": "Checks",
    "admin.p_privilege": "Privilege",
    "admin.p_status": "Status",
    "admin.p_note": "Note",
    "admin.status_active": "{available} Active",
    "admin.status_banned": "{ban} Banned",
    "admin.status_restricted": "{hourglass} Restricted until {until}",

    "admin.blacklist_title": "{ban} <b>BLACKLIST</b> ({n})",
    "admin.blacklist_empty": "{ban} <b>BLACKLIST</b>\n\nNobody is blocked.",
    "admin.restrictions_title": "{hourglass} <b>ACTIVE RESTRICTIONS</b> ({n})",
    "admin.restrictions_empty": "{hourglass} <b>ACTIVE RESTRICTIONS</b>\n\nNo active restrictions.",
    "admin.privileges_title": "{gift} <b>PRIVILEGES</b>",
    "admin.privileges_hint": "Send the Telegram ID or username of the user.",
    "admin.privileges_current": "Current: <b>{value}</b>",

    "admin.ban_title": "{ban} <b>BLOCK USER</b>",
    "admin.ban_ask": "Send the reason for the block, or /skip.",
    "admin.restrict_title": "{hourglass} <b>RESTRICT USER</b>",
    "admin.restrict_ask": "Send a duration in minutes, or /skip to skip the reason.",
    "admin.note_title": "{clipboard} <b>ADMIN NOTE</b>",
    "admin.note_ask": "Send the note text.",
    "admin.user": "User",
    "admin.blocked": "{ban} Blocked {id}.",
    "admin.note_saved": "Note saved.",
    "admin.no_actions": "No admin actions for this user.",
    "admin.actions_title": "{clipboard} <b>ACTIONS</b>",
    "admin.action_by": "{action} by {admin}",

    "admin.stats_title": "{chart} <b>STATISTICS</b>",
    "admin.s_users": "{users} Users: <b>{n}</b>",
    "admin.s_active": "{available} Active today: <b>{n}</b>",
    "admin.s_checks": "{search} Username checks: <b>{n}</b>",
    "admin.s_searches": "{bolt} Searches: <b>{n}</b>",
    "admin.s_collectible": "{collectible} Collectible checks: <b>{n}</b>",
    "admin.s_banned": "{ban} Banned: <b>{n}</b>",
    "admin.s_restricted": "{hourglass} Restricted: <b>{n}</b>",

    "admin.logs_title": "{search} <b>SEARCH LOGS</b>",
    "admin.logs_empty": "{search} <b>SEARCH LOGS</b>\n\nNothing yet.",
    "admin.alogs_title": "{clipboard} <b>ADMIN LOGS</b>",
    "admin.alogs_empty": "{clipboard} <b>ADMIN LOGS</b>\n\nNo actions yet.",

    "admin.subs_title": "{shield} <b>REQUIRED SUBSCRIPTIONS</b>",
    "admin.subs_hint": (
        "These channels are mandatory for every user. Add or remove them here - "
        "no restart needed. When you add a channel, users who already joined the "
        "others are asked to join the new one on their next action."
    ),
    "admin.subs_none": "No mandatory subscriptions are set - users skip this step.",
    "admin.subs_managed": "<b>Mandatory ({n}):</b>",
    "admin.subs_item": "{n}. {title} - <code>{id}</code>",
    "admin.subs_legacy": "<b>From .env (read-only):</b>",
    "admin.subs_add_prompt": (
        "Send the channel: @username, a t.me link, a private invite "
        "(https://t.me/+...), or a numeric id. The bot will resolve it."
    ),
    "admin.subs_add_help": (
        "Examples: @my_channel  |  https://t.me/my_channel  |  "
        "https://t.me/+AbCdEfGh  |  -1001234567890"
    ),
    "admin.subs_added": "Added: {title}",
    "admin.subs_failed": "Could not resolve that channel. Check the link/id and try again.",
    "admin.subs_duplicate": "{title} is already in the list.",
    "admin.subs_removed": "Removed: {title}",
    "admin.subs_invalid": "Send a channel @username, link or id (one line).",

    "admin.settings_title": "{settings} <b>BOT SETTINGS</b>",
    "admin.settings_hint": "Tap a parameter to change it. Secrets stay in .env and are never editable here.",
    "admin.setting_key": "Key",
    "admin.setting_current": "Current",
    "admin.setting_ask": "Send the new value, or /reset to fall back to .env.",
    "admin.setting_saved": "<code>{key}</code> set to <code>{value}</code>.",
    "admin.setting_reset": "<code>{key}</code> reset to the .env value.",
    "admin.setting_invalid": "That value is not valid for this setting.",
    "admin.setting_unknown": "Unknown setting.",

    "admin.system_title": "{wrench} <b>SYSTEM</b>",
    "admin.sys_bot": "{robot} Bot",
    "admin.sys_db": "{database} Database",
    "admin.sys_redis": "{bolt} Redis",
    "admin.sys_telegram": "{antenna} Telegram API",
    "admin.sys_mtproto": "{key} MTProto",
    "admin.sys_engine": "{collectible} Collectible Engine",
    "admin.online": "Online",
    "admin.connected": "Connected",
    "admin.unavailable": "Unavailable",
    "admin.enabled": "Enabled",
    "admin.disabled": "Disabled",
    "admin.not_configured": "Not configured",
    "admin.not_authorised": "Session not authorised",
    "admin.sys_build": "Build: {value}",
    "admin.sys_cache": "Cache TTL: {value}s",
    "admin.sys_conc": "Concurrency: {value}",
    "admin.sys_max": "Max search results: {value}",

    # ---------------------------------------------------------------- errors
    "error.title": "{cross} <b>Something went wrong.</b>",
    "error.body": "The issue was logged. Please try again in a moment.",
    "error.busy": "{hourglass} Working on it, one moment...",

    # ---------------------------------------------------------------- buttons
    "btn.search": "Username Search",
    "btn.history": "History",
    "btn.settings": "Settings",
    "btn.admin": "Admin panel",
    "btn.main_menu": "Main menu",
    "btn.back": "Back",
    "btn.subscribe": "Subscribe",
    "btn.join_chat": "Join chat",
    "btn.verify": "Verify",
    "btn.subscribed": "I subscribed",
    "btn.users": "Users",
    "btn.blacklist": "Blacklist",
    "btn.restrictions": "Restrictions",
    "btn.privileges": "Privileges",
    "btn.statistics": "Statistics",
    "btn.search_logs": "Search logs",
    "btn.access": "Required subscriptions",
    "btn.bot_settings": "Bot settings",
    "btn.system": "System",
    "btn.admin_logs": "Admin logs",
    "btn.browse_all": "Browse all",
    "btn.block": "Block",
    "btn.unban": "Unblock",
    "btn.clear": "Clear",
    "btn.note": "Admin note",
    "btn.actions": "Actions",
    "btn.cancel": "Cancel",
    "btn.add_channel": "Add channel",
    "btn.remove_sub": "Remove",
    "btn.mode_basic": "Basic",
    "btn.mode_collectible": "Collectible",
    "btn.mode_all_in_one": "All-in-One",
    "btn.restrict_10m": "10 min",
    "btn.restrict_1h": "1 hour",
    "btn.restrict_24h": "24 hours",
    "btn.restrict_7d": "7 days",
    "btn.edit": "Edit",

    # ---------------------------------------------------------------- search engine
    "search.setup_title": "<b>SEARCH</b>",
    "search.setup_body": (
        "Tune the criteria, then run the search. One search = one attempt, and "
        "you never wait on it: the result arrives in this message."
    ),
    "search.criteria": "<b>Criteria</b>\n{lines}",
    "search.c_length": "Length: <b>{value}</b>",
    "search.c_digits": "Digits: <b>{value}</b>",
    "search.c_mask": "Mask: <code>{value}</code>",
    "search.on": "yes",
    "search.off": "no",
    "search.any": "any",
    "search.none": "none",
    "search.target_variants": "variants",
    "search.length_title": "{letters} <b>LENGTH</b>",
    "search.length_body": "How many characters should the name have?",
    "search.digits_title": "{numbers} <b>DIGITS</b>",
    "search.digits_body": "Should the name contain digits?",
    "search.filter_title": "{filter} <b>FILTERS</b>",
    "search.filter_body": "A mask fixes the shape of the name. The bot applies its own quality criteria to every candidate - a user rating filter is gone for good.",
    "search.filter_mask_btn": "Mask",
    "search.filter_mask_prompt": (
        "{filter} <b>MASK</b>\n\n"
        "<code>?</code> - one letter\n<code>#</code> - one digit\n"
        "<code>*</code> - any letters\n\n"
        "Example: <code>??ged</code> matches <code>moged</code>"
    ),
    "search.filter_mask_bad": "{warn} That mask is not usable. Use letters, <code>?</code>, <code>#</code> and <code>*</code>.",
    "search.filter_mask_set": "Mask saved",
    "search.filter_clear": "Clear filters",
    "search.filter_cleared": "Filters cleared",
    "search.running": "{search} <b>SEARCHING...</b>",
    "search.progress_phase_valuable": "{compass} <i>Hunting the beautiful names…</i>",
    "search.progress_phase_guarantee": "{gem} <i>Digging for a free one…</i>",
    "search.progress_phase_waiting": (
        "{hourglass} <i>Telegram asked us to slow down - holding on, not giving up…</i>"
    ),
    "search.progress_phase_stock": (
        "{gem} <i>Taking a name we already proved free and re-checking it…</i>"
    ),
    "search.progress_checked": (
        "{bolt} Checked: <b>{n}</b> · confirmed <b>{c}</b> · {s}s"
    ),
    "search.started": (
        "{search} <b>SEARCH RUNNING</b>\n\n"
        "The result will arrive right here - keep this screen open."
    ),
    "search.queue_full": (
        "{warn} The bot is at capacity right now. Wait a moment and press again."
    ),
    "search.result_title": "<b>RESULT</b>",
    "search.hit_free": "{check} <b>FREE</b> - nobody owns it",
    "search.miss_free": "{cross} <b>TAKEN</b> - the name already has an owner",
    "search.p_no_digits": "No digits",
    "search.p_no_separators": "No separators",
    "search.p_collectible": "Collectible length (4-7)",
    "search.p_readable": "Readable",
    "search.p_dictionary": "Real dictionary word",
    # The failed case must read as a statement too. Printing "Real dictionary
    # word" with a cross next to it still reads like a claim about the name -
    # which is how a random handle ended up looking like a dictionary word.
    "search.pn_no_digits": "Contains digits",
    "search.pn_no_separators": "Contains separators",
    "search.pn_collectible": "Ordinary length",
    "search.pn_readable": "Not readable out loud",
    "search.pn_dictionary": "Not a dictionary word",
    "search.premium_badge": "Premium quality: {value}/5",
    "search.premium_ok": "{check} {label}",
    "search.premium_no": "{cross} {label}",
    "search.premium_note": (
        "<i>The bot only shows beautiful, unoccupied usernames worth reselling - "
        "each is judged on 5 criteria and scored N/5.</i>"
    ),
    "search.fragment_ok": "{check} Fragment: not listed for sale or auction",
    "search.fragment_off": "{warn} Fragment: could not be checked (marketplace off)",
    "search.claim_unavailable": (
        "{warn} <b>CANNOT VERIFY CLAIMABILITY RIGHT NOW</b>\n\n"
        "I screened <b>{n}</b> names and some looked free - but the session that "
        "proves a name can actually be claimed is missing or rate-limited by "
        "Telegram. Rather than hand you a name you might not be able to take, "
        "I stop here.\n\n"
        "{info} <i>Occupied names are still screened out. The search returns "
        "once claimability checking is back.</i>"
    ),
    "search.claim_unverified": (
        "{warn} Claimability not verified (no user session here) - Telegram may "
        "still refuse this name. See the FAQ / ask support."
    ),
    "search.attempts": "{bolt} Attempts used: <b>{n}</b>",
    "search.no_candidate": "{warn} Could not build a name for those criteria. Loosen the mask or allow digits.",
    "search.no_free_found": (
        "{warn} Checked {n} names and every one of them is taken.\n\n"
        "Try a longer name, allow digits, or run again for a different set."
    ),
    "search.all_taken": (
        "{cross} All {n} names checked are already taken.\n\n"
        "Short, valuable names are almost all owned - that is what makes them "
        "valuable."
    ),
    "search.all_taken_hint": (
        "{info} <i>For 5-6 character names, turn <b>Digits</b> on: letter-only short "
        "names are almost all gone, while a short name with 1-2 digits is usually "
        "still free. You can also add a name to Watch and get an alert when a later "
        "check confirms it free, or press again for a different set.</i>"
    ),
    "search.unconfirmed": (
        "{warn} Checked {n} names, but Telegram could not confirm any of them as "
        "free.\n\n"
        "This is not a \"taken\" verdict - the check was simply inconclusive for "
        "these names. The bot never reports a name as free unless that is actually "
        "confirmed."
    ),
    "search.unconfirmed_hint": (
        "{info} <i>Add the name to Watch from the main menu; the bot will alert you "
        "when a later check confirms it free. Or press again - the next run tries a "
        "different set.</i>"
    ),
    "search.throttled": (
        "{cross} Telegram is rate-limiting this account right now, so the search "
        "was stopped after {n} lookups.\n\n"
        "This is not a \"taken\" result - the bot simply cannot ask Telegram any "
        "more questions for a while. Wait a bit and press Search again; the bot "
        "will not report an occupied name as free just to have something to show."
    ),
    "search.no_collectible": (
        "{warn} Checked {n} names - none of them is a collectible on Fragment.\n\n"
        "Collectible usernames are a small fixed set, so a random guess almost never "
        "lands on one. Set a mask (e.g. <code>moged?</code>) to target a specific word, "
        "then press again."
    ),
    "search.hint_short": (
        "{info} <i>Short names are almost all taken. Raise the length or add a name to "
        "Username Watch in the main menu.</i>"
    ),
    "search.collectible_browse_title": "Collectibles listed on Fragment right now",
    "search.browse_note": (
        "{info} No pattern was set, so here are collectibles listed for sale right "
        "now. Send a specific name (e.g. <code>love</code>) to check its exact price."
    ),

    # ---------------------------------------------------------------- variants
    "variants.title": "{link} <b>VARIANTS</b>",
    "variants.body": (
        "Close alternatives to <b>@{seed}</b> - screened, then confirmed free."
    ),
    "variants.line": "{icon} <b>@{name}</b> - premium {score}/5",
    "variants.none": (
        "{warn} Nothing close to <b>@{seed}</b> is free right now.\n\n"
        "Try a shorter root, or a different suffix."
    ),
    "variants.started": (
        "{search} <b>HUNTING VARIANTS</b>\n\n"
        "The free ones will be posted right here."
    ),
    "variants.usage": "{info} Usage: <code>/variants moged</code>",
    "variants.invalid": "{warn} That is not a usable username.",
    "variants.hint": (
        "{info} <i>Press a variant to open it, or run Variants again for a "
        "different set.</i>"
    ),

    # ---------------------------------------------------------------- claim
    "claim.handle": "{info} Handle: <code>@{name}</code>",
    "claim.note": (
        "{bolt} <i>Usernames are first come, first served. Open it and set it in "
        "Telegram Settings before someone else does.</i>"
    ),
    "claim.share": "{link} <code>https://t.me/{name}</code>",

    # ---------------------------------------------------------------- daily drop
    "digest.title": "{bell} <b>DAILY DROP</b>",
    "digest.body": (
        "One search a day with your saved settings, sent to you as a message. "
        "The bot keeps hunting while you are away."
    ),
    "digest.line": "{bell} Daily Drop: <b>{value}</b>",
    "digest.enabled": "{check} Daily Drop is on - one search a day, delivered here.",
    "digest.disabled": "{info} Daily Drop is off.",
    "digest.message": (
        "{bell} <b>DAILY DROP</b>\n\n"
        "Fresh for you: <b>@{name}</b> - premium {score}/5"
    ),
    "digest.empty": (
        "{bell} <b>DAILY DROP</b>\n\n"
        "Nothing worth sending today - every candidate was already taken. "
        "Trying again tomorrow."
    ),
    "digest.throttled": (
        "{bell} <b>DAILY DROP</b>\n\n"
        "Telegram is rate-limiting lookups right now, so today's drop is skipped. "
        "Back tomorrow."
    ),
    "digest.hint": (
        "Daily Drop is a personal hunting service. Once a day the bot runs one "
        "search with your saved settings and sends the result here - so a fresh "
        "name finds you without opening the bot. Turn it on below, or grab one "
        "right now."
    ),
    "digest.next": "{clock} Next drop: <b>{hour}:00</b>",
    "digest.turn_on": "Turn on",
    "digest.turn_off": "Turn off",
    "digest.now": "Get one now",
    "digest.now_queued": (
        "{search} <b>DROP RUNNING</b> - your Daily Drop will arrive here."
    ),

    # ---------------------------------------------------------- username watches
    "watch.title": "{eye} <b>USERNAME ALERTS</b>",
    "watch.body": (
        "Add a taken username and I will message you when a check confirms it is free.\n\n"
        "Telegram does not send a release event. Checks are rate-paced: the first starts "
        "within about a second, then a single watch is checked about every {interval}s. "
        "When many watches are due, they queue and may take longer."
    ),
    "watch.empty": "Nothing watched yet. Add a username to start.",
    "watch.item_line": "{status} <b>@{name}</b>\n   Last check: {checked} · {result}",
    "watch.status_waiting": "Watching",
    "watch.status_fired": "Alert delivered",
    "watch.result_available": "Free confirmed",
    "watch.result_occupied": "Still taken",
    "watch.result_unknown": "Could not confirm",
    "watch.result_rate_limited": "Rate-limited; will retry",
    "watch.result_error": "Check failed; will retry",
    "watch.result_invalid": "Invalid username",
    "watch.result_searching": "Searching matches",
    "watch.result_none": "Not checked yet",
    "watch.checked_seconds": "{n}s ago",
    "watch.checked_minutes": "{n}m ago",
    "watch.checked_hours": "{n}h ago",
    "watch.never_checked": "not checked yet",
    "watch.interval": "Repeat interval: about <b>{n}s</b> per watch",
    "watch.add": "Add username",
    "watch.add_prompt": "{bell} <b>ADD USERNAME WATCH</b>\n\nSend one valid username, with or without @.",
    "watch.added": "{check} Watching @{name}. First check starts shortly.",
    "watch.exists": "{info} Already watching @{name}.",
    "watch.removed": "Username watch removed.",
    "watch.limit": "{warn} Watch limit reached ({max}). Remove one before adding another.",
    "watch.checking": "Checking @{name} now…",
    "watch.available_now": "{check} @{name} is already confirmed free. Claim it now.",
    "watch.still_occupied": "@{name} is still taken or could not be confirmed free.",
    "watch.alert": (
        "{bell} <b>USERNAME IS FREE</b>\n\n"
        "<b>@{name}</b> was confirmed free on the latest check.\n\n"
        "Claim it immediately in Telegram: Settings → Username."
    ),

    # Compatibility notification for previously-created collectible watches.
    "trap.collectible": (
        "{gem} <b>COLLECTIBLE ALERT</b>\n\n"
        "<b>@{name}</b> is listed on Fragment.\n\n"
        "Price: {price}\nStatus: {status}\n\n"
        "fragment.com/username/{name}"
    ),

    # ---------------------------------------------------------------- profile
    "profile.title": "{person} <b>YOUR PROFILE</b>",
    "profile.id": "ID",
    "profile.username": "Username",
    "profile.privilege": "Privilege",
    "profile.language": "Language",
    "profile.registered": "With us since",
    "profile.stats_title": "{chart} <b>ACTIVITY</b>",
    "profile.checks": "Checks",
    "profile.searches": "Searches",
    "profile.traps": "Active username watches",
    "profile.battles": "Battles",
    "profile.best": "Best find",
    "profile.achievements": "Achievements",
    "profile.best_none": "nothing yet",

    # ---------------------------------------------------------------- battle
    "battle.title": "{battle} <b>USERNAME BATTLE</b>",
    "battle.body": (
        "Two usernames, five measurable criteria, a winner out of 10.\n\n"
        "Nothing is invented - every score comes from the name itself or a real lookup."
    ),
    "battle.mode_manual": "Manual duel",
    "battle.mode_challenge": "Send a challenge",
    "battle.enter_left": "{person} <b>YOUR USERNAME</b>\n\nSend your own username.",
    "battle.enter_right": "{battle} <b>RIVAL'S USERNAME</b>\n\nSend the username you want to challenge.",
    "battle.comparing": "{battle} <b>COMPARING...</b>",
    "battle.timeout": "{warn} The lookup timed out. Try the battle again shortly.",
    "battle.result_title": "{trophy} <b>BATTLE RESULT</b>",
    "battle.winner": "{trophy} <b>@{name}</b> wins",
    "battle.draw": "{handshake} <b>Draw</b>",
    "battle.side_one": "{icon} <b>FIRST USERNAME: @{name}</b>",
    "battle.side_two": "{icon} <b>SECOND USERNAME: @{name}</b>",
    "battle.total_line": "{chart} Overall score: <b>{score}/10</b>",
    "battle.score_item": "{icon} {label}: <b>{score}</b>",
    "battle.side_winner": "{trophy} <b>Winner</b>",
    "battle.versus": "{battle} <b>@{left}</b>  vs  <b>@{right}</b>",
    "battle.criteria_header": "<b>By criterion</b>",
    "battle.totals_header": "<b>Totals</b>",
    "battle.c_length": "Length",
    "battle.c_word": "Word",
    "battle.c_spelling": "Spelling",
    "battle.c_digits": "Digits",
    "battle.c_symbols": "Symbols",
    "battle.c_readability": "Readability",
    "battle.c_status": "Status",
    "battle.status_collectible": "collectible",
    "battle.status_taken": "taken",
    "battle.status_free": "free",
    "battle.status_unknown": "unknown",
    "battle.invalid": "{warn} Both usernames must be valid and different.",
    "battle.accept": "Accept the challenge",
    "battle.challenge_text": "{battle} <b>@{challenger}</b> challenges <b>@{rival}</b>",
    "battle.challenge_waiting": "Waiting for the rival to accept...",
    "battle.pick_chat": "Choose a chat",
    "battle.pick_chat_hint": (
        "{battle} <b>CHOOSE A CHAT</b>\n\n"
        "Tap the button below and pick the chat where you want to send the "
        "challenge. Only chats this bot is already in are listed."
    ),
    "battle.challenge_sent": "{check} Challenge posted",
    "battle.cannot_post": (
        "{warn} Could not post the challenge there. Make sure the bot is a "
        "member of that chat and can send messages."
    ),
    "battle.need_username": (
        "{warn} Set a username on your Telegram account first - the battle "
        "needs a name to fight with."
    ),
    "battle.open_rival": "anyone who accepts",
    "battle.self_challenge": "{warn} You cannot challenge yourself.",

    # ---------------------------------------------------------------- support
    "support.title": "{support} <b>SUPPORT</b>",
    "support.body": (
        "Questions, a bug, an idea - we read everything.\n\n"
        "Check the FAQ first: the answer is usually already there."
    ),
    "support.faq_btn": "FAQ",
    "support.write_btn": "Message the developer",
    "support.faq_title": "{question} <b>FAQ</b>",
    "support.faq_q1": "<b>How do I find a free username?</b>",
    "support.faq_a1": (
        "Open <b>Search</b> from the main menu. Choose a length, switch digits "
        "on or off, and add a mask to target real words - for example "
        "<code>cat*</code>. The bot screens public pages, confirms availability "
        "through Telegram, and shows only names you can actually claim."
    ),
    "support.faq_q2": "<b>What do the grades S, A, B, C and D mean?</b>",
    "support.faq_a2": (
        "Our own 0-100 rating. It scores scarcity (shorter is rarer), whether it "
        "is a real word, how easy it is to pronounce and spell, and the use of "
        "digits. S is a name worth taking today; D is forgettable. Each result "
        "also shows what lifts the score and what caps it."
    ),
    "support.faq_q3": "<b>A name says \"free\" but Telegram won't let me take it. Why?</b>",
    "support.faq_a3": (
        "\"Free\" means it is not occupied right now, but Telegram still refuses "
        "some names: short dictionary words, names on cooldown after a rename, and "
        "reserved handles. Some are also listed for sale on Fragment, not up for "
        "grabs. The appraiser's <b>claimable</b> check tells you whether you can "
        "really grab it."
    ),
    "support.faq_q4": "<b>How is a username's price estimated?</b>",
    "support.faq_a4": (
        "Tap <b>Appraise</b> or send <code>/appraise name</code>. The bot compares "
        "your name to real Fragment listings of the same length and digit shape, "
        "shows one approximate price in TON, its rarity band, and warns if it is a "
        "brand name. Prices are estimates, not offers."
    ),
    "support.faq_q5": "<b>What is the Portfolio for?</b>",
    "support.faq_a5": (
        "Your saved list. Appraise a name and add it, and the bot keeps it with "
        "its latest value and claimable status. Use <b>Refresh</b> to re-check the "
        "whole list at once, and remove items you no longer want."
    ),
    "support.faq_q6": "<b>How does Username Watch work?</b>",
    "support.faq_a6": (
        "Open <b>Username Watch</b> and add an exact username. The bot checks it "
        "on a timer (about every 15 seconds per name) and alerts you the moment it "
        "becomes claimable. Telegram sends no \"released\" event, so timing depends "
        "on the check interval - checks pace themselves to avoid limits."
    ),
    "support.faq_q7": "<b>What is the Daily Drop?</b>",
    "support.faq_a7": (
        "One automatic search per day using your saved settings, delivered as a "
        "message while you are away. Turn it on in <b>Settings</b>."
    ),
    "support.faq_q8": "<b>How do masks and filters help?</b>",
    "support.faq_a8": (
        "A mask targets a specific idea instead of random guesses - "
        "<code>*bot</code>, <code>neo?</code>, digits in fixed spots. Filters "
        "narrow by length and digits. Targeted searches find real, brandable names "
        "far faster than pure brute force."
    ),
    "support.faq_q9": "<b>Why does the bot sometimes pause or say Telegram is limiting it?</b>",
    "support.faq_a9": (
        "Telegram caps how often one account may check usernames. When the limit "
        "is hit the bot says so plainly and waits instead of faking \"taken\" "
        "results. Nothing is lost - just run the search again in a few minutes."
    ),
    "support.faq_q10": "<b>Is my data safe?</b>",
    "support.faq_a10": (
        "The bot stores only your Telegram id, your settings and your search "
        "history. Nothing is sold or shared with third parties."
    ),

    # ---------------------------------------------------------------- new buttons
    "btn.search_engine": "Search",
    "btn.watch": "Username watch",
    "btn.profile": "Profile",
    "btn.battle": "Username Battle",
    "btn.support": "Support",
    "btn.faq": "FAQ",
    "btn.write_support": "Message the developer",
    "btn.length": "Length",
    "btn.digits": "Digits",
    "btn.filters": "Filters",
    "btn.run_search": "Run search",
    "btn.mask": "Mask",
    "btn.clear_filters": "Clear filters",
    "btn.manual_duel": "Manual duel",
    "btn.challenge": "Send a challenge",
    "btn.accept": "Accept",
    "btn.remove": "Remove",
    "btn.back_search": "Back to search",
    "btn.achievements": "Achievements",
    "btn.back_settings": "Back to settings",
    "btn.variants": "Variants",
    "btn.open": "Open",
    "btn.digest": "Daily Drop",
    "btn.new_search": "New search",

    # ---------------------------------------------------------------- bulk / rate / top
    "btn.bulk": "Check a list",
    "btn.top": "Top finds",
    "btn.favorites": "Favourites",
    "btn.save": "Save",
    "btn.rate": "Rate",
    "btn.appraise": "Appraise a name",
    "btn.portfolio": "Portfolio",
    "btn.refresh": "Refresh",
    "btn.add_portfolio": "To portfolio",

    # ---------------------------------------------------------------- appraisal
    "appraise.title": "{gem} <b>APPRAISAL</b>",
    "appraise.usage": "Appraise a name: <code>/appraise love</code>",
    "appraise.invalid": "{warn} That is not a valid username.",
    "appraise.running": "{search} <b>APPRAISING…</b>",
    "appraise.availability": "Availability: {value}",
    "appraise.a_free": "{check} free — claimable right now",
    "appraise.a_free_unverified": "{check} free (unverified — confirm in the app)",
    "appraise.a_taken": "{cross} taken",
    "appraise.a_unassignable": "{warn} cannot be claimed (reserved or in cooldown)",
    "appraise.a_unknown": "{warn} unknown",
    "appraise.fragment_none": "Fragment: not listed",
    "appraise.fragment_sale": "Fragment: {status} — {price}",
    "appraise.fragment_unknown": "Fragment: unknown",
    "appraise.market": "{chart} Estimated price: <b>≈ {price} TON</b> (from {n} similar {length}-char listings)",
    "appraise.market_none": "{chart} Market: no comparable listings right now",
    "appraise.rarity": "{sparkle} Rarity: <b>{score}</b>/100{wordlike}",
    "appraise.wordlike": " — reads like a real word",
    "appraise.brand": "{warn} Looks like a brand name — check the trademark before buying.",
    "appraise.footer": "<i>Availability from Telegram, prices from Fragment. Not financial advice.</i>",

    # ---------------------------------------------------------------- portfolio
    "portfolio.title": "{money} <b>PORTFOLIO</b>",
    "portfolio.body": "Your collectible holdings and their latest Fragment value. Tap a name to open it; the cross removes it.",
    "portfolio.empty": "{money} <b>PORTFOLIO</b>\n\nNothing tracked yet. Add a name you own and the bot will follow its value.",
    "portfolio.line": "{icon} <b>@{name}</b> — {value}",
    "portfolio.value_estimate": "≈ {price} TON (est.)",
    "portfolio.value_unknown": "not listed",
    "portfolio.total": "Tracked: {n} name(s)",
    "portfolio.add": "Add",
    "portfolio.add_prompt": "{star} <b>ADD TO PORTFOLIO</b>\n\nSend the username you own.",
    "portfolio.added": "{check} @{name} added to your portfolio",
    "portfolio.exists": "{info} @{name} is already in your portfolio",
    "portfolio.removed": "Removed from portfolio",
    "portfolio.full": "Portfolio is full ({max})",
    "portfolio.refresh_done": "{check} Values refreshed",

    # ---------------------------------------------------------------- listing watch
    "watch.watch_listing": "Watch listings",
    "watch.listing_prompt": "{money} <b>WATCH LISTINGS</b>\n\nSend a keyword — the bot pings you when a matching collectible appears for sale on Fragment.",
    "watch.listing_added": "{check} Watching Fragment listings for “{q}”",
    "watch.listing_note": "{info} <i>Checked every few minutes. Only new matches are reported.</i>",
    "watch.listing_alert": "{money} <b>NEW LISTING</b>\n\n@{name} — {price}\n\nfragment.com/username/{name}",

    "bulk.title": "{clipboard} <b>CHECK A LIST</b>",
    "bulk.body": (
        "Send up to {max} usernames, one per line or separated by commas.\n\n"
        "You get back only the ones that matter - free names worth having."
    ),
    "bulk.empty": "{warn} No usable usernames found in that message.",
    "bulk.running": "{search} <b>CHECKING {n} NAMES...</b>",
    "bulk.result": "{clipboard} <b>LIST RESULT</b>",
    "bulk.summary": "Checked <b>{n}</b> names",
    "bulk.hits": "{check} Free: <b>{n}</b>",
    "bulk.none": "{cross} Nothing free in this list.",
    "bulk.too_many": "{warn} Too many names - {max} at a time.",

    "rate.title": "{chart} <b>PREMIUM CHECK</b>",
    "rate.usage": "{info} Usage: <code>/rate moged</code>",
    "rate.invalid": "{warn} That is not a usable username.",
    "rate.note": "<i>The bot's own 5 quality criteria, not a market price.</i>",

    "top.title": "{trophy} <b>TOP FINDS</b>",
    "top.body": "The best free names found by everyone using this bot.",
    "top.empty": "{trophy} <b>TOP FINDS</b>\n\nNothing here yet - be the first.",
    "top.line": "{rank}. <b>@{name}</b> - {score}/5",

    "fav.title": "{star} <b>FAVOURITES</b>",
    "fav.empty": "{star} <b>FAVOURITES</b>\n\nNothing saved yet. Press Save on any result.",
    "fav.line": "{icon} <b>@{name}</b> - {score}/5{note}",
    "fav.added": "{check} @{name} saved",
    "fav.exists": "{info} @{name} is already saved",
    "fav.removed": "Removed from favourites",
    "fav.full": "{warn} Favourites are full ({max}).",

    "ach.title": "{medal} <b>ACHIEVEMENTS</b>",
    "ach.summary": "Unlocked <b>{done}</b> of <b>{total}</b>",
    "ach.unlocked": "{icon} <b>{name}</b>",
    "ach.locked": "{icon} {name} - {progress}/{target}",
    "ach.a_first_find": "First free name",
    "ach.a_ten_finds": "10 free names",
    "ach.a_fifty_finds": "50 free names",
    "ach.a_first_collectible": "First collectible",
    "ach.a_first_trap": "First username watch",
    "ach.a_trap_fired": "Username watch alert",
    "ach.a_first_battle": "First battle",
    "ach.a_battle_win": "Battle won",
    "ach.a_perfect_score": "A perfect 100",
    "ach.a_hundred_checks": "100 checks",
    "ach.a_collector": "10 favourites",

}


RU: dict[str, str] = {
    # ---------------------------------------------------------------- language
    "lang.title": "{shield} <b>ВЫБЕРИТЕ ЯЗЫК</b>",
    "lang.body": "Выберите язык интерфейса.\nПозже его можно сменить в настройках.",
    "lang.changed": "Язык обновлён",

    # ---------------------------------------------------------------- captcha
    "captcha.title": "{shield} <b>ПРОВЕРКА БЕЗОПАСНОСТИ</b>",
    "captcha.intro": "Перед началом работы подтвердите, что вы не бот.",
    "captcha.attempts": "Осталось попыток: {left}",
    "captcha.wrong": "{cross} <b>Неверный ответ</b>\n\nПопробуйте ещё раз. Осталось попыток: {left}",
    "captcha.failed": "{warn} <b>Слишком много попыток.</b>\n\nСоздайте новую проверку, чтобы продолжить.",
    "captcha.expired": "{hourglass} <b>Проверка истекла.</b>\n\nСоздайте новую, чтобы продолжить.",
    "captcha.passed": "{check} <b>Проверка пройдена</b>",
    "captcha.new": "Новая проверка",

    # ---------------------------------------------------------------- gate
    "gate.channel.title": "{channel} <b>ШАГ 1 ИЗ 2 — КАНАЛ</b>",
    "gate.channel.body": (
        "Чтобы продолжить, подпишитесь на наш Telegram-канал.\n\n"
        "Нажмите кнопку ниже, затем «Проверить» — "
        "подписка проверяется по-настоящему."
    ),
    "gate.channel.missing": "{cross} <b>Канал ещё не подтверждён.</b>",
    "gate.chat.title": "{chat} <b>ШАГ 2 ИЗ 2 — ЧАТ</b>",
    "gate.chat.body": (
        "Почти готово. Вступите в наш чат, чтобы получить полный доступ.\n\n"
        "Нажмите кнопку ниже, затем «Проверить»."
    ),
    "gate.chat.missing": "{cross} <b>Вы ещё не вступили в чат.</b>",
    "gate.subs.title": "{channel} <b>ОБЯЗАТЕЛЬНЫЕ ПОДПИСКИ</b>",
    "gate.subs.body": (
        "Подпишитесь на все {total} ниже, затем нажмите <b>Я подписался</b> под каждой.\n"
        "Каждая проверяется по-настоящему, через Telegram."
    ),
    "gate.subs.item": "{n}. {status} {title}",
    "gate.subs.done": "\u2705",
    "gate.subs.todo": "\u2b1c",
    "gate.subs.generic": "Подписка {n}",
    "gate.subs.not_confirmed": "{cross} <b>Пока не подтверждено</b> — вступите и нажмите снова.",
    "gate.channel.name": "Канал",
    "gate.chat.name": "Чат сообщества",
    "gate.unverified": (
        "{warn} Не удалось проверить подписку.\n\n"
        "Убедитесь, что бот назначен администратором канала и чата, и попробуйте снова."
    ),

    # ---------------------------------------------------------------- welcome
    "welcome.title": "{sparkle} <b>ДОБРО ПОЖАЛОВАТЬ, {name}</b>",
    "welcome.body": (
        "Вам открыт полный доступ к <b>Username Scanner</b>.\n\n"
        "Ищите, проверяйте и анализируйте Telegram username — "
        "обычные имена, коллекционные и всё между ними."
    ),
    "welcome.pick": "{search} Выберите действие ниже.",

    # ---------------------------------------------------------------- menu
    "menu.title": "{search} <b>USERNAME SCANNER</b>",
    "menu.question": "Что будем делать?",

    # ---------------------------------------------------------------- ban / restrict
    "ban.title": "{ban} <b>ДОСТУП ЗАБЛОКИРОВАН</b>",
    "ban.body": "Ваш доступ отозван администратором.",
    "ban.reason": "Причина: {reason}",
    "restrict.title": "{hourglass} <b>ДОСТУП ОГРАНИЧЕН</b>",
    "restrict.body": "Ваш доступ временно ограничен.",
    "restrict.reason": "Причина: {reason}",
    "restrict.until": "Ограничение действует до: {until}",

    # ---------------------------------------------------------------- results
    "status.available": "{available} Свободен",
    "status.occupied": "{occupied} Занят",
    "status.invalid": "{warn} Некорректный",
    "status.unknown": "{warn} Неизвестно",
    "status.rate_limited": "{hourglass} Лимит запросов",
    "status.error": "{cross} Ошибка",

    "result.title": "{search} <b>РЕЗУЛЬТАТ ПРОВЕРКИ</b>",
    "result.basic": "{available} <b>ОСНОВНАЯ ПРОВЕРКА</b>",
    "result.collectible": "{collectible} <b>КОЛЛЕКЦИОННЫЙ</b>",
    "result.type": "Тип: {value}",
    "result.reason": "Причина: {value}",
    "result.title_field": "Название: {value}",
    "result.occupied_hint": (
        "{info} <i>Нажмите <b>«Найти похожие»</b> ниже — бот сам найдёт "
        "свободные варианты.</i>"
    ),
    "result.verified": "{bolt} Проверено только что",
    "result.verified_ms": "{bolt} Проверено только что ({ms} мс)",
    "result.source": "Проверено через: {value}",
    "source.mtproto": "Telegram, прямое подключение",
    "source.bot_api": "Telegram, интерфейс бота",
    "source.public_page": "Telegram, публичный профиль",
    "source.validation": "локальная проверка",
    "source.fragment": "маркетплейс коллекционных имён",
    "source.fragment_web": "маркетплейс коллекционных имён",
    "source.none": "не проверялось",
    "result.source_cached": "Проверено через: {value}",
    "result.telegram_no_owner": "Telegram: активный владелец не обнаружен",
    "result.telegram_active": "Telegram: активный {kind}",
    "result.not_checked": "Не проверялось",
    "result.not_detected": "Не обнаружен",
    "result.no_answer": "{warn} Telegram не дал достоверного ответа.",
    "result.need_mtproto": (
        "{hourglass} Telegram не дал однозначного ответа.\n"
        "Попробуйте через момент."
    ),
    "result.no_checker": "{hourglass} Проверка сейчас недоступна. Попробуйте позже.",

    "collectible.title": "{collectible} <b>КОЛЛЕКЦИОННЫЙ USERNAME</b>",
    "collectible.status": "Статус: {value}",
    "collectible.marketplace": "Маркетплейс: Fragment",
    "collectible.owner": "Владелец: @{value}",
    "collectible.price": "Цена: {value}",
    "collectible.s_purchase": "Доступен для покупки",
    "collectible.s_owned": "Есть владелец",
    "collectible.s_listed": "Выставлен на продажу",
    "collectible.s_not_detected": "Не обнаружен",
    "collectible.s_unavailable": "Недоступен",
    "collectible.s_unknown": "Неизвестно",
    "collectible.disabled": (
        "{hourglass} <b>Проверка коллекционных имён сейчас недоступна.</b>\n\n"
        "Попробуйте позже."
    ),
    "collectible.no_data": "{warn} Достоверных данных нет.",
    "collectible.unavailable_short": "{warn} Временно недоступно (не настроено)",
    "collectible.purchased": "Куплен: {value}",
    "collectible.need_login": (
        "{hourglass} <b>Проверка коллекционных имён сейчас занята.</b>\n\n"
        "Попробуйте через несколько минут."
    ),
    "collectible.need_login_short": "{hourglass} Временно недоступно",
    "collectible.min_bid": "мин. ставка {value} TON",
    "value.estimate": (
        "{chart} Похожие имена сейчас просят <b>{low}–{high} TON</b> на Fragment "
        "(медиана <b>≈ {price} TON</b>, живых лотов: {n})"
    ),
    "value.no_market": (
        "{info} Сравнимых лотов на Fragment нет — имя не торгуется как "
        "коллекционное, поэтому честной цены для него не существует."
    ),
    "value.wordlike": "похоже на настоящее слово — дороже случайного набора",

    # ---------------------------------------------------------------- scan
    "scan.scanning": "{search} <b>СКАНИРОВАНИЕ...</b>",
    "scan.checked": "{done} / {total} проверено",
    "scan.available": "{available} Свободно: {n}",
    "scan.collectible": "{collectible} Коллекционных: {n}",
    "scan.occupied": "{occupied} Занято: {n}",
    "scan.unknown": "{warn} Неизвестно: {n}",
    "scan.invalid": "{cross} Некорректных: {n}",
    "scan.rate_limited": "{hourglass} Лимит запросов: {n}",
    "scan.complete": "{check} <b>СКАНИРОВАНИЕ ЗАВЕРШЕНО</b>",
    "scan.usernames_checked": "Проверено username: {n}",
    "scan.available_list": "<b>Свободные:</b>",
    "scan.more": "<i>...и ещё {n}</i>",
    "scan.time": "Время: {value} сек",

    # ---------------------------------------------------------------- search
    "search.title": "{bolt} <b>ПОИСК USERNAME</b>",
    "search.body": "Отправьте базовое слово — я сгенерирую варианты и проверю их.",
    "search.example": "Пример: <code>moged</code>",
    "search.bad_seed": "{warn} Это не похоже на подходящее базовое слово.\n\nОтправьте что-то вроде <code>moged</code>.",
    "search.how_many": "{bolt} <b>СКОЛЬКО ВАРИАНТОВ?</b>",
    "search.base": "Основа: <b>{value}</b>",
    "search.pick": "Выберите, сколько сгенерировать и проверить (максимум {max}).",
    "search.need_seed": "Сначала отправьте базовое слово",
    "search.capped": "Ограничено до {n} вашим тарифом",

    # ---------------------------------------------------------------- history
    "history.title": "{history} <b>ВАША ИСТОРИЯ</b>",
    "history.empty": "{history} <b>ВАША ИСТОРИЯ</b>\n\nПока пусто. Сначала выполните проверку.",
    "history.page": "Страница {page} / {total}",

    # ---------------------------------------------------------------- settings
    "settings.title": "{settings} <b>НАСТРОЙКИ</b>",
    "settings.default_mode": "Режим по умолчанию",
    "settings.def_length": "Длина по умолчанию",
    "settings.def_digits": "Цифры по умолчанию",
    "settings.pick_length": (
        "{letters} <b>ДЛИНА ПО УМОЛЧАНИЮ</b>\n\n"
        "Сколько символов должно быть в генерируемом имени?"
    ),
    "settings.results_limit": "Лимит результатов",
    "settings.language": "Язык",
    "settings.privilege": "Привилегия",
    "settings.digest": "Daily Drop",
    "settings.updated_mode": "Режим по умолчанию обновлён",
    "settings.updated_limit": "Лимит результатов обновлён",
    "settings.updated_lang": "Язык обновлён",
    "settings.updated_digest": "Daily Drop обновлён",
    "settings.unknown": "Неподдерживаемое значение",

    # ---------------------------------------------------------------- help
    "help.title": "{search} <b>СПРАВКА</b>",
    "help.start": "/start — онбординг и главное меню",
    "help.check": "/check &lt;username&gt; — проверить username",
    "help.search": "/search &lt;слово&gt; — сгенерировать и просканировать варианты",
    "help.history": "/history — последние поиски",
    "help.settings": "/settings — язык и настройки",
    "help.help": "/help — это сообщение",
    "help.admin": "/admin — панель администратора",

    # ---------------------------------------------------------------- admin
    "admin.title": "{crown} <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>",
    "admin.signed_in": "Вы вошли как <b>{id}</b>",
    "admin.role": "Роль: <b>{role}</b>",
    "admin.pick": "Выберите раздел.",
    "admin.denied": "{lock} Команда доступна только администраторам.",
    "admin.not_authorized": "Нет доступа",

    "admin.users_title": "{users} <b>ПОЛЬЗОВАТЕЛИ</b>",
    "admin.users_hint": "Отправьте Telegram ID или username для поиска.",
    "admin.users_count": "{users} <b>ПОЛЬЗОВАТЕЛИ</b> ({n})",
    "admin.users_page": "Страница {page} / {total}",
    "admin.not_found": "Пользователи не найдены.",
    "admin.user_not_found": "Пользователь не найден",
    "admin.found": "Найдено пользователей: <b>{n}</b>.",

    "admin.profile_title": "{person} <b>ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ</b>",
    "admin.p_id": "ID",
    "admin.p_username": "Username",
    "admin.p_registered": "Регистрация",
    "admin.p_last": "Последняя активность",
    "admin.p_checks": "Проверок",
    "admin.p_privilege": "Привилегия",
    "admin.p_status": "Статус",
    "admin.p_note": "Заметка",
    "admin.status_active": "{available} Активен",
    "admin.status_banned": "{ban} Заблокирован",
    "admin.status_restricted": "{hourglass} Ограничен до {until}",

    "admin.blacklist_title": "{ban} <b>ЧЁРНЫЙ СПИСОК</b> ({n})",
    "admin.blacklist_empty": "{ban} <b>ЧЁРНЫЙ СПИСОК</b>\n\nНикто не заблокирован.",
    "admin.restrictions_title": "{hourglass} <b>АКТИВНЫЕ ОГРАНИЧЕНИЯ</b> ({n})",
    "admin.restrictions_empty": "{hourglass} <b>АКТИВНЫЕ ОГРАНИЧЕНИЯ</b>\n\nАктивных ограничений нет.",
    "admin.privileges_title": "{gift} <b>ПРИВИЛЕГИИ</b>",
    "admin.privileges_hint": "Отправьте Telegram ID или username пользователя.",
    "admin.privileges_current": "Сейчас: <b>{value}</b>",

    "admin.ban_title": "{ban} <b>БЛОКИРОВКА ПОЛЬЗОВАТЕЛЯ</b>",
    "admin.ban_ask": "Отправьте причину блокировки или /skip.",
    "admin.restrict_title": "{hourglass} <b>ОГРАНИЧЕНИЕ ПОЛЬЗОВАТЕЛЯ</b>",
    "admin.restrict_ask": "Отправьте длительность в минутах или /skip, чтобы без причины.",
    "admin.note_title": "{clipboard} <b>ЗАМЕТКА АДМИНА</b>",
    "admin.note_ask": "Отправьте текст заметки.",
    "admin.user": "Пользователь",
    "admin.blocked": "{ban} Заблокирован {id}.",
    "admin.note_saved": "Заметка сохранена.",
    "admin.no_actions": "По этому пользователю действий нет.",
    "admin.actions_title": "{clipboard} <b>ДЕЙСТВИЯ</b>",
    "admin.action_by": "{action} от {admin}",

    "admin.stats_title": "{chart} <b>СТАТИСТИКА</b>",
    "admin.s_users": "{users} Пользователей: <b>{n}</b>",
    "admin.s_active": "{available} Активны сегодня: <b>{n}</b>",
    "admin.s_checks": "{search} Проверок username: <b>{n}</b>",
    "admin.s_searches": "{bolt} Поисков: <b>{n}</b>",
    "admin.s_collectible": "{collectible} Проверок коллекционных: <b>{n}</b>",
    "admin.s_banned": "{ban} Заблокировано: <b>{n}</b>",
    "admin.s_restricted": "{hourglass} Ограничено: <b>{n}</b>",

    "admin.logs_title": "{search} <b>ЛОГИ ПОИСКОВ</b>",
    "admin.logs_empty": "{search} <b>ЛОГИ ПОИСКОВ</b>\n\nПока пусто.",
    "admin.alogs_title": "{clipboard} <b>ЛОГИ АДМИНИСТРАТОРОВ</b>",
    "admin.alogs_empty": "{clipboard} <b>ЛОГИ АДМИНИСТРАТОРОВ</b>\n\nДействий пока нет.",

    "admin.subs_title": "{shield} <b>ОБЯЗАТЕЛЬНЫЕ ПОДПИСКИ</b>",
    "admin.subs_hint": (
        "Эти каналы обязательны для каждого пользователя. Добавляйте или убирайте "
        "их отсюда — перезапуск не нужен. Когда вы добавляете канал, пользователи, "
        "уже вступившие в остальные, получат просьбу вступить в новый при следующем "
        "действии."
    ),
    "admin.subs_none": "Обязательных подписок нет — пользователи пропускают этот шаг.",
    "admin.subs_managed": "<b>Обязательные ({n}):</b>",
    "admin.subs_item": "{n}. {title} — <code>{id}</code>",
    "admin.subs_legacy": "<b>Из .env (только чтение):</b>",
    "admin.subs_add_prompt": (
        "Отправьте канал: @username, ссылку t.me, приватное приглашение "
        "(https://t.me/+...) или числовой id. Бот определит его сам."
    ),
    "admin.subs_add_help": (
        "Примеры: @my_channel  |  https://t.me/my_channel  |  "
        "https://t.me/+AbCdEfGh  |  -1001234567890"
    ),
    "admin.subs_added": "Добавлено: {title}",
    "admin.subs_failed": "Не удалось определить канал. Проверьте ссылку/id и попробуйте снова.",
    "admin.subs_duplicate": "{title} уже в списке.",
    "admin.subs_removed": "Убрано: {title}",
    "admin.subs_invalid": "Отправьте @username, ссылку или id канала (в одну строку).",

    "admin.settings_title": "{settings} <b>НАСТРОЙКИ БОТА</b>",
    "admin.settings_hint": "Нажмите параметр, чтобы изменить. Секреты остаются в .env и здесь недоступны.",
    "admin.setting_key": "Ключ",
    "admin.setting_current": "Сейчас",
    "admin.setting_ask": "Отправьте новое значение или /reset, чтобы вернуть значение из .env.",
    "admin.setting_saved": "<code>{key}</code> установлено в <code>{value}</code>.",
    "admin.setting_reset": "<code>{key}</code> сброшено к значению из .env.",
    "admin.setting_invalid": "Это значение не подходит для данного параметра.",
    "admin.setting_unknown": "Неизвестный параметр.",

    "admin.system_title": "{wrench} <b>СИСТЕМА</b>",
    "admin.sys_bot": "{robot} Бот",
    "admin.sys_db": "{database} База данных",
    "admin.sys_redis": "{bolt} Redis",
    "admin.sys_telegram": "{antenna} Telegram API",
    "admin.sys_mtproto": "{key} MTProto",
    "admin.sys_engine": "{collectible} Движок коллекционных",
    "admin.online": "В сети",
    "admin.connected": "Подключено",
    "admin.unavailable": "Недоступно",
    "admin.enabled": "Включён",
    "admin.disabled": "Выключен",
    "admin.not_configured": "Не настроено",
    "admin.not_authorised": "Сессия не авторизована",
    "admin.sys_build": "Сборка: {value}",
    "admin.sys_cache": "TTL кеша: {value} с",
    "admin.sys_conc": "Параллельных проверок: {value}",
    "admin.sys_max": "Максимум результатов: {value}",

    # ---------------------------------------------------------------- errors
    "error.title": "{cross} <b>Что-то пошло не так.</b>",
    "error.body": "Ошибка записана в лог. Попробуйте ещё раз через момент.",
    "error.busy": "{hourglass} Обрабатываю, секунду...",

    # ---------------------------------------------------------------- buttons
    "btn.search": "Поиск username",
    "btn.history": "История",
    "btn.settings": "Настройки",
    "btn.admin": "Админ-панель",
    "btn.main_menu": "Главное меню",
    "btn.back": "Назад",
    "btn.subscribe": "Подписаться",
    "btn.join_chat": "Вступить в чат",
    "btn.verify": "Проверить",
    "btn.subscribed": "Я подписался",
    "btn.users": "Пользователи",
    "btn.blacklist": "Чёрный список",
    "btn.restrictions": "Ограничения",
    "btn.privileges": "Привилегии",
    "btn.statistics": "Статистика",
    "btn.search_logs": "Логи поисков",
    "btn.access": "Обязательные подписки",
    "btn.bot_settings": "Настройки бота",
    "btn.system": "Система",
    "btn.admin_logs": "Логи админов",
    "btn.browse_all": "Показать всех",
    "btn.block": "Заблокировать",
    "btn.unban": "Разблокировать",
    "btn.clear": "Снять",
    "btn.note": "Заметка",
    "btn.actions": "Действия",
    "btn.cancel": "Отмена",
    "btn.add_channel": "Добавить канал",
    "btn.remove_sub": "Убрать",
    "btn.mode_basic": "Обычный",
    "btn.mode_collectible": "Коллекционный",
    "btn.mode_all_in_one": "Всё сразу",
    "btn.restrict_10m": "10 минут",
    "btn.restrict_1h": "1 час",
    "btn.restrict_24h": "24 часа",
    "btn.restrict_7d": "7 дней",
    "btn.edit": "Изменить",

    # ---------------------------------------------------------------- search engine
    "search.setup_title": "<b>ПОИСК</b>",
    "search.setup_body": (
        "Настройте критерии и запустите поиск. Один поиск = одна попытка, и ждать "
        "её не нужно: результат придёт в это же сообщение."
    ),
    "search.criteria": "<b>Критерии</b>\n{lines}",
    "search.c_length": "Длина: <b>{value}</b>",
    "search.c_digits": "Цифры: <b>{value}</b>",
    "search.c_mask": "Маска: <code>{value}</code>",
    "search.on": "да",
    "search.off": "нет",
    "search.any": "любая",
    "search.none": "нет",
    "search.target_variants": "варианты",
    "search.length_title": "{letters} <b>ДЛИНА</b>",
    "search.length_body": "Сколько символов должно быть в имени?",
    "search.digits_title": "{numbers} <b>ЦИФРЫ</b>",
    "search.digits_body": "Допускать цифры в имени?",
    "search.filter_title": "{filter} <b>ФИЛЬТРЫ</b>",
    "search.filter_body": "Маска задаёт форму имени. Свои критерии качества бот применяет к каждому кандидату сам — пользовательский фильтр по рейтингу убран навсегда.",
    "search.filter_mask_btn": "Маска",
    "search.filter_mask_prompt": (
        "{filter} <b>МАСКА</b>\n\n"
        "<code>?</code> — одна буква\n<code>#</code> — одна цифра\n"
        "<code>*</code> — любые буквы\n\n"
        "Пример: <code>??ged</code> подойдёт <code>moged</code>"
    ),
    "search.filter_mask_bad": "{warn} Такая маска не подойдёт. Используйте буквы, <code>?</code>, <code>#</code> и <code>*</code>.",
    "search.filter_mask_set": "Маска сохранена",
    "search.filter_clear": "Сбросить фильтры",
    "search.filter_cleared": "Фильтры сброшены",
    "search.running": "{search} <b>ИДЁТ ПОИСК...</b>",
    "search.progress_phase_valuable": "{compass} <i>Перебираю красивые имена…</i>",
    "search.progress_phase_guarantee": "{gem} <i>Копаю до свободного…</i>",
    "search.progress_phase_waiting": (
        "{hourglass} <i>Telegram просит сбавить темп — держусь и не бросаю поиск…</i>"
    ),
    "search.progress_phase_stock": (
        "{gem} <i>Беру имя, которое уже доказано свободным, и перепроверяю его…</i>"
    ),
    "search.progress_checked": (
        "{bolt} Проверено: <b>{n}</b> · подтверждено <b>{c}</b> · {s}с"
    ),
    "search.started": (
        "{search} <b>ПОИСК ЗАПУЩЕН</b>\n\n"
        "Результат придёт прямо сюда — не отходите от экрана."
    ),
    "search.queue_full": (
        "{warn} Бот сейчас на пределе возможностей. Подождите минуту и нажмите снова."
    ),
    "search.result_title": "<b>РЕЗУЛЬТАТ</b>",
    "search.hit_free": "{check} <b>СВОБОДЕН</b> — владельца нет",
    "search.miss_free": "{cross} <b>ЗАНЯТ</b> — у имени уже есть владелец",
    "search.p_no_digits": "Без цифр",
    "search.p_no_separators": "Без разделителей",
    "search.p_collectible": "Коллекционная длина (4-7)",
    "search.p_readable": "Читается",
    "search.p_dictionary": "Настоящее слово из словаря",
    "search.pn_no_digits": "С цифрами",
    "search.pn_no_separators": "С разделителями",
    "search.pn_collectible": "Обычная длина",
    "search.pn_readable": "Не читается вслух",
    "search.pn_dictionary": "Не словарное слово",
    "search.premium_badge": "Премиум-качество: {value}/5",
    "search.premium_ok": "{check} {label}",
    "search.premium_no": "{cross} {label}",
    "search.premium_note": (
        "<i>Бот показывает только красивые, незанятые имена, годные для перепродажи — "
        "каждое оценивается по 5 критериям и получает N/5.</i>"
    ),
    "search.fragment_ok": "{check} Fragment: не выставлено на продажу или аукцион",
    "search.fragment_off": "{warn} Fragment: проверить не удалось (маркетплейс выключен)",
    "search.claim_unavailable": (
        "{warn} <b>НЕ МОГУ ПРОВЕРИТЬ ЗАНЯТИЕ ПРЯМО СЕЙЧАС</b>\n\n"
        "Я проверил <b>{n}</b> имён — некоторые выглядели свободными, но сессия, "
        "подтверждающая, что имя реально можно занять, отсутствует или "
        "ограничена Telegram. Я не буду выдавать имя, которое потом нельзя "
        "занять.\n\n"
        "{info} <i>Занятые имена по-прежнему отсекаются. Поиск вернётся, как "
        "только проверка занятия восстановится.</i>"
    ),
    "search.claim_unverified": (
        "{warn} Возможность занятия не проверена (здесь нет user-сессии) — "
        "Telegram может всё равно не отдать это имя."
    ),
    "search.attempts": "{bolt} Попыток использовано: <b>{n}</b>",
    "search.no_candidate": "{warn} Не удалось собрать имя под эти критерии. Ослабьте маску или разрешите цифры.",
    "search.no_free_found": (
        "{warn} Проверено имён: {n} — все заняты.\n\n"
        "Попробуйте имя подлиннее, разрешите цифры или запустите поиск ещё раз для другого набора."
    ),
    "search.all_taken": (
        "{cross} Все {n} проверенных имён уже заняты.\n\n"
        "Короткие дорогие имена почти все разобраны — именно поэтому они и дорогие."
    ),
    "search.all_taken_hint": (
        "{info} <i>Для имён из 5–6 символов включите <b>«Цифры»</b>: короткие имена "
        "без цифр почти все разобраны, а короткое имя с 1–2 цифрами обычно ещё "
        "свободно. Ещё можно добавить имя в «Слежение за никами» — бот уведомит, "
        "когда проверка подтвердит, что оно свободно, — или нажать ещё раз: будет "
        "проверен другой набор.</i>"
    ),
    "search.unconfirmed": (
        "{warn} Проверено имён: {n}, но ни одно из них Telegram не подтвердил как "
        "свободное.\n\n"
        "Это не вердикт «занят» — просто проверка по этим именам не дала "
        "однозначного ответа. Бот никогда не выдаёт имя за свободное, пока это не "
        "подтверждено по-настоящему."
    ),
    "search.unconfirmed_hint": (
        "{info} <i>Добавьте нужное имя в «Слежение за никами» в главном меню. Бот "
        "уведомит, когда проверка подтвердит, что оно свободно. Или нажмите ещё раз — "
        "следующий прогон проверит другой набор.</i>"
    ),
    "search.throttled": (
        "{cross} Telegram сейчас ограничивает этот аккаунт, поэтому поиск "
        "остановлен после {n} проверок.\n\n"
        "Это не результат «занят» — просто бот какое-то время не может задавать "
        "Telegram новые вопросы. Подождите немного и нажмите «Поиск» снова. Бот не "
        "станет выдавать занятое имя за свободное, лишь бы что-то показать."
    ),
    "search.no_collectible": (
        "{warn} Проверено имён: {n} — ни одно не оказалось коллекционным на Fragment.\n\n"
        "Коллекционных имён очень мало, поэтому случайное угадывание почти не попадает. "
        "Задайте маску (например <code>moged?</code>) под конкретное слово и нажмите снова."
    ),
    "search.hint_short": (
        "{info} <i>Короткие имена почти все заняты. Увеличьте длину или добавьте "
        "нужное имя в «Слежение за никами» в главном меню.</i>"
    ),
    "search.collectible_browse_title": "Коллекционные имена, выставленные на Fragment сейчас",
    "search.browse_note": (
        "{info} Маска не задана, поэтому вот что сейчас продаётся на Fragment. "
        "Отправьте конкретное имя (например <code>love</code>), чтобы узнать его точную цену."
    ),

    # ---------------------------------------------------------------- variants
    "variants.title": "{link} <b>ВАРИАНТЫ</b>",
    "variants.body": (
        "Близкие замены для <b>@{seed}</b> — отсеяны лишние, свободные подтверждены."
    ),
    "variants.line": "{icon} <b>@{name}</b> — премиум {score}/5",
    "variants.none": (
        "{warn} Ничего близкого к <b>@{seed}</b> сейчас не свободно.\n\n"
        "Попробуйте более короткую основу или другую приставку."
    ),
    "variants.started": (
        "{search} <b>ИЩУ ВАРИАНТЫ</b>\n\n"
        "Свободные пришлю сюда же."
    ),
    "variants.usage": "{info} Использование: <code>/variants moged</code>",
    "variants.invalid": "{warn} Это не похоже на username.",
    "variants.hint": (
        "{info} <i>Нажмите на вариант, чтобы открыть его, или запустите Варианты "
        "снова — набор будет другим.</i>"
    ),

    # ---------------------------------------------------------------- claim
    "claim.handle": "{info} Ник: <code>@{name}</code>",
    "claim.note": (
        "{bolt} <i>Юзернеймы выдаются по принципу «кто первый». Откройте его и "
        "займите в настройках Telegram, пока это не сделал кто-то другой.</i>"
    ),
    "claim.share": "{link} <code>https://t.me/{name}</code>",

    # ---------------------------------------------------------------- daily drop
    "digest.title": "{bell} <b>DAILY DROP</b>",
    "digest.body": (
        "Один поиск в день с вашими настройками — приходит сообщением. "
        "Бот охотится, пока вас нет."
    ),
    "digest.line": "{bell} Daily Drop: <b>{value}</b>",
    "digest.enabled": "{check} Daily Drop включён — один поиск в день, сюда же.",
    "digest.disabled": "{info} Daily Drop выключен.",
    "digest.message": (
        "{bell} <b>DAILY DROP</b>\n\n"
        "Свежая находка: <b>@{name}</b> — премиум {score}/5"
    ),
    "digest.empty": (
        "{bell} <b>DAILY DROP</b>\n\n"
        "Сегодня отправлять нечего — все кандидаты оказались заняты. "
        "Попробую завтра."
    ),
    "digest.throttled": (
        "{bell} <b>DAILY DROP</b>\n\n"
        "Telegram сейчас ограничивает запросы, поэтому сегодняшний выпуск "
        "пропущен. Вернусь завтра."
    ),
    "digest.hint": (
        "Daily Drop — персональная охота. Раз в день бот сам запускает один "
        "поиск с вашими настройками и присылает результат сюда — свежее имя "
        "находит вас, даже если вы не открываете бота. Включите ниже или "
        "заберите один прямо сейчас."
    ),
    "digest.next": "{clock} Следующий выпуск: <b>{hour}:00</b>",
    "digest.turn_on": "Включить",
    "digest.turn_off": "Выключить",
    "digest.now": "Получить сейчас",
    "digest.now_queued": (
        "{search} <b>ЗАПУЩЕНО</b> — ваш Daily Drop придёт сюда."
    ),

    # --------------------------------------------------------- username watches
    "watch.title": "{eye} <b>СЛЕЖЕНИЕ ЗА НИКАМИ</b>",
    "watch.body": (
        "Добавьте занятый ник — я напишу, когда проверка подтвердит, что он освободился.\n\n"
        "У Telegram нет события об освобождении ника. Проверки идут с ограничением частоты: "
        "первая начнётся примерно в течение секунды, затем один ник проверяется примерно "
        "раз в {interval} с. При высокой нагрузке проверки стоят в очереди и могут занять дольше."
    ),
    "watch.empty": "Пока ничего не отслеживается. Добавьте ник.",
    "watch.item_line": "{status} <b>@{name}</b>\n   Последняя проверка: {checked} · {result}",
    "watch.status_waiting": "Отслеживается",
    "watch.status_fired": "Уведомление отправлено",
    "watch.result_available": "Свободен подтверждён",
    "watch.result_occupied": "Всё ещё занят",
    "watch.result_unknown": "Не удалось подтвердить",
    "watch.result_rate_limited": "Лимит запросов; повторю позже",
    "watch.result_error": "Ошибка проверки; повторю позже",
    "watch.result_invalid": "Некорректный username",
    "watch.result_searching": "Ищу подходящие имена",
    "watch.result_none": "Ещё не проверялся",
    "watch.checked_seconds": "{n} с назад",
    "watch.checked_minutes": "{n} мин назад",
    "watch.checked_hours": "{n} ч назад",
    "watch.never_checked": "ожидает первой проверки",
    "watch.interval": "Интервал повтора: примерно <b>{n} с</b> на ник",
    "watch.add": "Добавить ник",
    "watch.add_prompt": "{bell} <b>ДОБАВИТЬ НИК</b>\n\nОтправьте один корректный username, можно с @.",
    "watch.added": "{check} Слежу за @{name}. Первая проверка скоро.",
    "watch.exists": "{info} @{name} уже отслеживается.",
    "watch.removed": "Отслеживание отключено.",
    "watch.limit": "{warn} Достигнут лимит наблюдений ({max}). Удалите одно, чтобы добавить новое.",
    "watch.checking": "Проверяю @{name}…",
    "watch.available_now": "{check} @{name} уже подтверждён как свободный. Забирайте сейчас.",
    "watch.still_occupied": "@{name} всё ещё занят или его не удалось подтвердить свободным.",
    "watch.alert": (
        "{bell} <b>USERNAME СВОБОДЕН</b>\n\n"
        "Последняя проверка подтвердила, что <b>@{name}</b> свободен.\n\n"
        "Заберите его сразу в Telegram: Настройки → Имя пользователя."
    ),

    # Совместимость уведомлений для ранее созданных коллекционных подписок.
    "trap.collectible": (
        "{gem} <b>КОЛЛЕКЦИОННЫЙ АЛЕРТ</b>\n\n"
        "<b>@{name}</b> выставлен на Fragment.\n\n"
        "Цена: {price}\nСтатус: {status}\n\n"
        "fragment.com/username/{name}"
    ),

    # ---------------------------------------------------------------- profile
    "profile.title": "{person} <b>ВАШ ПРОФИЛЬ</b>",
    "profile.id": "ID",
    "profile.username": "Username",
    "profile.privilege": "Привилегия",
    "profile.language": "Язык",
    "profile.registered": "С нами с",
    "profile.stats_title": "{chart} <b>АКТИВНОСТЬ</b>",
    "profile.checks": "Проверок",
    "profile.searches": "Поисков",
    "profile.traps": "Активных наблюдений за никами",
    "profile.battles": "Битв",
    "profile.best": "Лучшая находка",
    "profile.achievements": "Достижения",
    "profile.best_none": "пока нет",

    # ---------------------------------------------------------------- battle
    "battle.title": "{battle} <b>БИТВА USERNAME</b>",
    "battle.body": (
        "Два username, пять измеримых критериев, победитель по шкале до 10.\n\n"
        "Ничего не выдумано — каждая оценка берётся из самого имени или реальной проверки."
    ),
    "battle.mode_manual": "Ручная дуэль",
    "battle.mode_challenge": "Кинуть вызов",
    "battle.enter_left": "{person} <b>ВАШ USERNAME</b>\n\nОтправьте свой username.",
    "battle.enter_right": "{battle} <b>USERNAME СОПЕРНИКА</b>\n\nОтправьте username, с которым хотите сразиться.",
    "battle.comparing": "{battle} <b>СРАВНИВАЮ...</b>",
    "battle.timeout": "{warn} Проверка не успела завершиться. Попробуйте батл ещё раз чуть позже.",
    "battle.result_title": "{trophy} <b>ИТОГ БИТВЫ</b>",
    "battle.winner": "{trophy} <b>@{name}</b> побеждает",
    "battle.draw": "{handshake} <b>Ничья</b>",
    "battle.side_one": "{icon} <b>ПЕРВЫЙ USERNAME: @{name}</b>",
    "battle.side_two": "{icon} <b>ВТОРОЙ USERNAME: @{name}</b>",
    "battle.total_line": "{chart} Общая оценка: <b>{score}/10</b>",
    "battle.score_item": "{icon} {label}: <b>{score}</b>",
    "battle.side_winner": "{trophy} <b>Победитель</b>",
    "battle.versus": "{battle} <b>@{left}</b>  против  <b>@{right}</b>",
    "battle.criteria_header": "<b>По критериям</b>",
    "battle.totals_header": "<b>Итог</b>",
    "battle.c_length": "Длина",
    "battle.c_word": "Слово",
    "battle.c_spelling": "Написание",
    "battle.c_digits": "Цифры",
    "battle.c_symbols": "Символы",
    "battle.c_readability": "Читаемость",
    "battle.c_status": "Статус",
    "battle.status_collectible": "коллекционный",
    "battle.status_taken": "занят",
    "battle.status_free": "свободен",
    "battle.status_unknown": "неизвестно",
    "battle.invalid": "{warn} Оба username должны быть корректны и различаться.",
    "battle.accept": "Принять вызов",
    "battle.challenge_text": "{battle} <b>@{challenger}</b> вызывает <b>@{rival}</b>",
    "battle.challenge_waiting": "Ждём, пока соперник примет вызов...",
    "battle.pick_chat": "Выбрать чат",
    "battle.pick_chat_hint": (
        "{battle} <b>ВЫБЕРИТЕ ЧАТ</b>\n\n"
        "Нажмите кнопку ниже и выберите чат, куда отправить вызов. "
        "В списке будут только чаты, где бот уже состоит."
    ),
    "battle.challenge_sent": "{check} Вызов отправлен",
    "battle.cannot_post": (
        "{warn} Не удалось отправить вызов в этот чат. Убедитесь, что бот "
        "состоит в нём и может писать сообщения."
    ),
    "battle.need_username": (
        "{warn} Сначала задайте username в своём аккаунте Telegram — "
        "битве нужно имя, за которое сражаться."
    ),
    "battle.open_rival": "тот, кто примет вызов",
    "battle.self_challenge": "{warn} Нельзя вызвать самого себя.",

    # ---------------------------------------------------------------- support
    "support.title": "{support} <b>ПОДДЕРЖКА</b>",
    "support.body": (
        "Вопросы, баги, идеи — читаем всё.\n\n"
        "Сначала загляните в FAQ: обычно ответ уже там."
    ),
    "support.faq_btn": "FAQ",
    "support.write_btn": "Написать разработчику",
    "support.faq_title": "{question} <b>FAQ</b>",
    "support.faq_q1": "<b>Как найти свободный юзернейм?</b>",
    "support.faq_a1": (
        "Откройте <b>Поиск</b> в главном меню. Выберите длину, включите или "
        "выключите цифры и задайте маску под настоящее слово — например "
        "<code>cat*</code>. Бот проверяет публичные страницы, подтверждает "
        "доступность через Telegram и показывает только те имена, которые реально "
        "можно занять."
    ),
    "support.faq_q2": "<b>Что означают классы S / A / B / C / D?</b>",
    "support.faq_a2": (
        "Это наша собственная оценка от 0 до 100. Учитываются редкость (короче = "
        "реже), настоящее ли это слово, насколько легко произнести и написать на "
        "слух, а также цифры. S — имя, которое стоит забрать сегодня, D — "
        "проходное. В каждом результате видно, что поднимает оценку, а что её "
        "ограничивает."
    ),
    "support.faq_q3": "<b>Имя пишут «свободно», а Telegram не даёт его занять — почему?</b>",
    "support.faq_a3": (
        "«Свободно» значит, что оно сейчас не занято, но Telegram всё равно "
        "отказывает в некоторых именах: коротких словарных словах, именах на "
        "«остывании» после смены и зарезервированных. Часть также выставлена на "
        "продажу на Fragment и недоступна бесплатно. Проверка <b>claimable</b> в "
        "оценке говорит, можно ли его реально забрать."
    ),
    "support.faq_q4": "<b>Как оценивается цена юзернейма?</b>",
    "support.faq_a4": (
        "Нажмите <b>Оценить имя</b> или отправьте <code>/appraise имя</code>. Бот "
        "сравнивает имя с реальными лотами Fragment той же длины и формы цифр, "
        "показывает одну примерную цену в TON, её редкость и предупреждает, если "
        "это бренд. Цены — оценка, а не предложение."
    ),
    "support.faq_q5": "<b>Для чего Портфель?</b>",
    "support.faq_a5": (
        "Это ваш сохранённый список. Оцените имя и добавьте его — бот хранит его с "
        "актуальной стоимостью и статусом claimable. Кнопка <b>Обновить</b> "
        "перепроверяет весь список сразу, а ненужные можно удалить."
    ),
    "support.faq_q6": "<b>Как работает слежение за username?</b>",
    "support.faq_a6": (
        "Откройте <b>Слежение за никами</b> и добавьте точный username. Бот "
        "проверяет его по таймеру (примерно раз в 15 секунд на имя) и предупредит, "
        "как только имя станет доступным. Telegram не присылает событие "
        "«освободилось», поэтому точность зависит от интервала проверки — проверки "
        "сами ограничивают частоту, чтобы не упереться в лимиты."
    ),
    "support.faq_q7": "<b>Что такое Daily Drop?</b>",
    "support.faq_a7": (
        "Один автоматический поиск в день с вашими настройками, который приходит "
        "сообщением, пока вас нет. Включается в <b>Настройках</b>."
    ),
    "support.faq_q8": "<b>Как помогают маски и фильтры?</b>",
    "support.faq_a8": (
        "Маска целится в конкретную идею вместо случайных угадываний — "
        "<code>*bot</code>, <code>neo?</code>, цифры в фиксированных местах. "
        "Фильтры сужают по длине и цифрам. Целевой поиск находит настоящие, "
        "брендовые имена куда быстрее грубого перебора."
    ),
    "support.faq_q9": "<b>Почему бот иногда делает паузу или пишет, что Telegram его ограничивает?</b>",
    "support.faq_a9": (
        "Telegram ограничивает, как часто один аккаунт может проверять юзернеймы. "
        "Когда лимит достигнут, бот прямо об этом сообщает и ждёт вместо того, "
        "чтобы выдавать занятые за свободные. Ничего не потеряно — просто запустите "
        "поиск снова через пару минут."
    ),
    "support.faq_q10": "<b>Мои данные в безопасности?</b>",
    "support.faq_a10": (
        "Бот хранит только ваш Telegram id, настройки и историю поиска. Ничего не "
        "продаётся и не передаётся третьим лицам."
    ),

    # ---------------------------------------------------------------- new buttons
    "btn.search_engine": "Поиск",
    "btn.watch": "Слежение за никами",
    "btn.profile": "Профиль",
    "btn.battle": "Битва юзернеймов",
    "btn.support": "Поддержка",
    "btn.faq": "FAQ",
    "btn.write_support": "Написать разработчику",
    "btn.length": "Длина",
    "btn.digits": "Цифры",
    "btn.filters": "Фильтры",
    "btn.run_search": "Искать",
    "btn.mask": "Маска",
    "btn.clear_filters": "Сбросить фильтры",
    "btn.manual_duel": "Ручная дуэль",
    "btn.challenge": "Кинуть вызов",
    "btn.accept": "Принять",
    "btn.remove": "Снять",
    "btn.back_search": "К поиску",
    "btn.achievements": "Достижения",
    "btn.back_settings": "К настройкам",
    "btn.variants": "Варианты",
    "btn.open": "Открыть",
    "btn.digest": "Daily Drop",
    "btn.new_search": "Новый поиск",

    # ---------------------------------------------------------------- bulk / rate / top
    "btn.bulk": "Проверить список",
    "btn.top": "Топ находок",
    "btn.favorites": "Избранное",
    "btn.save": "Сохранить",
    "btn.rate": "Оценить",
    "btn.appraise": "Оценить имя",
    "btn.portfolio": "Портфель",
    "btn.refresh": "Обновить",
    "btn.add_portfolio": "В портфель",

    # ---------------------------------------------------------------- appraisal
    "appraise.title": "{gem} <b>ОЦЕНКА</b>",
    "appraise.usage": "Оценка имени: <code>/appraise love</code>",
    "appraise.invalid": "{warn} Это не похоже на username.",
    "appraise.running": "{search} <b>ОЦЕНИВАЮ…</b>",
    "appraise.availability": "Доступность: {value}",
    "appraise.a_free": "{check} свободно — можно занять прямо сейчас",
    "appraise.a_free_unverified": "{check} свободно (без проверки — подтвердите в приложении)",
    "appraise.a_taken": "{cross} занято",
    "appraise.a_unassignable": "{warn} занять нельзя (резерв или cooldown)",
    "appraise.a_unknown": "{warn} неизвестно",
    "appraise.fragment_none": "Fragment: не выставлено",
    "appraise.fragment_sale": "Fragment: {status} — {price}",
    "appraise.fragment_unknown": "Fragment: неизвестно",
    "appraise.market": "{chart} Примерная цена: <b>≈ {price} TON</b> (по {n} похожим лотам на {length} симв.)",
    "appraise.market_none": "{chart} Рынок: сравнимых лотов сейчас нет",
    "appraise.rarity": "{sparkle} Редкость: <b>{score}</b>/100{wordlike}",
    "appraise.wordlike": " — читается как настоящее слово",
    "appraise.brand": "{warn} Похоже на бренд — проверьте права на торговую марку перед покупкой.",
    "appraise.footer": "<i>Доступность — из Telegram, цены — с Fragment. Это не инвестиционный совет.</i>",

    # ---------------------------------------------------------------- portfolio
    "portfolio.title": "{money} <b>ПОРТФЕЛЬ</b>",
    "portfolio.body": "Ваши коллекционные имена и их последняя цена на Fragment. Нажмите на имя, чтобы открыть; крестик — убрать.",
    "portfolio.empty": "{money} <b>ПОРТФЕЛЬ</b>\n\nПока пусто. Добавьте имя, которым владеете, — бот будет следить за его ценой.",
    "portfolio.line": "{icon} <b>@{name}</b> — {value}",
    "portfolio.value_estimate": "≈ {price} TON (оценка)",
    "portfolio.value_unknown": "не выставлено",
    "portfolio.total": "В портфеле: {n}",
    "portfolio.add": "Добавить",
    "portfolio.add_prompt": "{star} <b>ДОБАВИТЬ В ПОРТФЕЛЬ</b>\n\nОтправьте имя, которым владеете.",
    "portfolio.added": "{check} @{name} добавлен в портфель",
    "portfolio.exists": "{info} @{name} уже в портфеле",
    "portfolio.removed": "Убрано из портфеля",
    "portfolio.full": "Портфель заполнен ({max})",
    "portfolio.refresh_done": "{check} Цены обновлены",

    # ---------------------------------------------------------------- listing watch
    "watch.watch_listing": "Следить за лотами",
    "watch.listing_prompt": "{money} <b>СЛЕЖЕНИЕ ЗА ЛОТАМИ</b>\n\nОтправьте слово — бот напишет, когда на Fragment появится подходящий коллекционный лот.",
    "watch.listing_added": "{check} Слежу за лотами Fragment по «{q}»",
    "watch.listing_note": "{info} <i>Проверяю раз в несколько минут. Сообщаю только о новых совпадениях.</i>",
    "watch.listing_alert": "{money} <b>НОВЫЙ ЛОТ</b>\n\n@{name} — {price}\n\nfragment.com/username/{name}",

    "bulk.title": "{clipboard} <b>ПРОВЕРКА СПИСКА</b>",
    "bulk.body": (
        "Отправьте до {max} имён — по одному в строке или через запятую.\n\n"
        "В ответ придут только те, что важны: свободные имена, годные для перепродажи."
    ),
    "bulk.empty": "{warn} В сообщении не нашлось подходящих имён.",
    "bulk.running": "{search} <b>ПРОВЕРЯЮ {n} ИМЁН...</b>",
    "bulk.result": "{clipboard} <b>РЕЗУЛЬТАТ СПИСКА</b>",
    "bulk.summary": "Проверено имён: <b>{n}</b>",
    "bulk.hits": "{check} Свободных: <b>{n}</b>",
    "bulk.none": "{cross} В этом списке свободных нет.",
    "bulk.too_many": "{warn} Слишком много имён — максимум {max} за раз.",

    "rate.title": "{chart} <b>ПРЕМИУМ-ПРОВЕРКА</b>",
    "rate.usage": "{info} Использование: <code>/rate moged</code>",
    "rate.invalid": "{warn} Это не похоже на username.",
    "rate.note": "<i>Наш набор из 5 критериев качества, а не рыночная цена.</i>",

    "top.title": "{trophy} <b>ТОП НАХОДОК</b>",
    "top.body": "Лучшие свободные имена, найденные всеми пользователями бота.",
    "top.empty": "{trophy} <b>ТОП НАХОДОК</b>\n\nПока пусто — станьте первым.",
    "top.line": "{rank}. <b>@{name}</b> — {score}/5",

    "fav.title": "{star} <b>ИЗБРАННОЕ</b>",
    "fav.empty": "{star} <b>ИЗБРАННОЕ</b>\n\nПока ничего не сохранено. Нажмите «Сохранить» на любом результате.",
    "fav.line": "{icon} <b>@{name}</b> — {score}/5{note}",
    "fav.added": "{check} @{name} сохранён",
    "fav.exists": "{info} @{name} уже в избранном",
    "fav.removed": "Удалено из избранного",
    "fav.full": "{warn} Избранное заполнено ({max}).",

    "ach.title": "{medal} <b>ДОСТИЖЕНИЯ</b>",
    "ach.summary": "Открыто <b>{done}</b> из <b>{total}</b>",
    "ach.unlocked": "{icon} <b>{name}</b>",
    "ach.locked": "{icon} {name} — {progress}/{target}",
    "ach.a_first_find": "Первое свободное имя",
    "ach.a_ten_finds": "10 свободных имён",
    "ach.a_fifty_finds": "50 свободных имён",
    "ach.a_first_collectible": "Первый коллекционный",
    "ach.a_first_trap": "Первое наблюдение за ником",
    "ach.a_trap_fired": "Сработало наблюдение за ником",
    "ach.a_first_battle": "Первая битва",
    "ach.a_battle_win": "Победа в битве",
    "ach.a_perfect_score": "Идеальные 100",
    "ach.a_hundred_checks": "100 проверок",
    "ach.a_collector": "10 в избранном",

}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": EN,
    "ru": RU,
}


def normalise(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANGUAGE
    code = lang.strip().lower()[:2]
    return code if code in TRANSLATIONS else DEFAULT_LANGUAGE


def t(lang: str | None, key: str, **kwargs: object) -> str:
    """Translate ``key`` into ``lang``. Unknown keys return the key itself."""
    code = normalise(lang)
    template = TRANSLATIONS.get(code, {}).get(key)
    if template is None:
        template = TRANSLATIONS[DEFAULT_LANGUAGE].get(key)
    if template is None:
        logger.warning("missing translation key: %s", key)
        return key
    # Admin can rename any user-visible key (mostly btn.*) from the panel.
    custom = _LABEL_OVERRIDES.get(key)
    if custom:
        template = custom
    if not kwargs and not _EMOJI_CONTEXT:
        return template
    context = dict(_EMOJI_CONTEXT)
    context.update(kwargs)
    try:
        return template.format(**context)
    except (KeyError, IndexError) as exc:
        logger.warning("bad translation placeholder for %s: %s", key, exc)
        return template
