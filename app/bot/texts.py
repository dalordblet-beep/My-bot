"""All user-visible message rendering.

Handlers stay thin: they gather data and call a builder here with the user's
language code. No user-visible string is hardcoded outside :mod:`app.services.i18n`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape as _html_escape

from app.database.models import AdminAction, Search, User
from app.services.emoji import emoji
from app.services.i18n import t
from app.services.subscriptions import sub_label
from app.utils.buildinfo import build_stamp
from app.utils.enums import CheckStatus, CollectibleStatus, Privilege, UsernameType
from app.utils.results import CheckResult, CollectibleResult, ScanSummary

SEP = "\u2501" * 12

# The five premium criteria, in display order. Each entry is
# ``(Premium attribute, i18n key)``; the verdict is N/5, never a 0-100 average.
PREMIUM_KEYS = (
    ("no_digits", "search.p_no_digits"),
    ("no_separators", "search.p_no_separators"),
    ("collectible", "search.p_collectible"),
    ("readable", "search.p_readable"),
    ("dictionary", "search.p_dictionary"),
)

# Safety bound for the FAQ walk in :func:`faq_screen`. Ten questions fit
# comfortably in one Telegram message; a hundred would not.
MAX_FAQ_ENTRIES = 32


def esc(value: object) -> str:
    """Escape anything that came from a user before putting it in HTML."""
    return _html_escape(str(value), quote=False)


def _fmt_dt(moment: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if moment is None:
        return "-"
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime(fmt)


def _fmt_time(moment: datetime | None) -> str:
    return _fmt_dt(moment, "%H:%M")


STATUS_KEYS: dict[CheckStatus, str] = {
    CheckStatus.AVAILABLE: "status.available",
    CheckStatus.OCCUPIED: "status.occupied",
    CheckStatus.INVALID: "status.invalid",
    CheckStatus.UNKNOWN: "status.unknown",
    CheckStatus.RATE_LIMITED: "status.rate_limited",
    CheckStatus.ERROR: "status.error",
}

COLLECTIBLE_KEYS: dict[CollectibleStatus, str] = {
    CollectibleStatus.AVAILABLE_FOR_PURCHASE: "collectible.s_purchase",
    CollectibleStatus.OWNED: "collectible.s_owned",
    CollectibleStatus.LISTED: "collectible.s_listed",
    CollectibleStatus.NOT_DETECTED: "collectible.s_not_detected",
    CollectibleStatus.UNAVAILABLE: "collectible.s_unavailable",
    CollectibleStatus.UNKNOWN: "collectible.s_unknown",
}

MODE_KEYS = {
    "basic": "btn.mode_basic",
    "collectible": "btn.mode_collectible",
    "all_in_one": "btn.mode_all_in_one",
}


SOURCE_KEYS = {
    "mtproto": "source.mtproto",
    "bot_api": "source.bot_api",
    "public_page": "source.public_page",
    "validation": "source.validation",
    "fragment": "source.fragment",
    "fragment_web": "source.fragment_web",
    "none": "source.none",
}


def source_label(lang: str, source: str) -> str:
    """Human wording for an internal source code - never leak the raw token."""
    key = SOURCE_KEYS.get(source)
    return t(lang, key) if key else t(lang, "source.none")


def status_label(lang: str, status: CheckStatus) -> str:
    return t(lang, STATUS_KEYS.get(status, "status.unknown"))


def mode_label(lang: str, mode: str) -> str:
    return t(lang, MODE_KEYS.get(mode, "btn.mode_basic"))


def collectible_label(lang: str, status: CollectibleStatus) -> str:
    return t(lang, COLLECTIBLE_KEYS.get(status, "collectible.s_unknown"))


def privilege_label(lang: str, privilege: str) -> str:
    return privilege


# --------------------------------------------------------------------- language
def language_screen(lang: str) -> str:
    return f"{t(lang, 'lang.title')}\n\n{t(lang, 'lang.body')}"


# --------------------------------------------------------------------- onboarding
def captcha_screen(lang: str, title: str, prompt: str, attempts_left: int) -> str:
    return (
        f"{t(lang, 'captcha.title')}\n\n"
        f"{t(lang, 'captcha.intro')}\n\n"
        f"<b>{esc(prompt)}</b>\n\n"
        f"<i>{t(lang, 'captcha.attempts', left=attempts_left)}</i>"
    )


def captcha_wrong(lang: str, attempts_left: int) -> str:
    return t(lang, "captcha.wrong", left=attempts_left)


def captcha_failed(lang: str) -> str:
    return t(lang, "captcha.failed")


def captcha_expired(lang: str) -> str:
    return t(lang, "captcha.expired")


def captcha_passed(lang: str) -> str:
    return t(lang, "captcha.passed")


def channel_screen(lang: str) -> str:
    return f"{t(lang, 'gate.channel.title')}\n\n{t(lang, 'gate.channel.body')}"


def chat_screen(lang: str) -> str:
    return f"{t(lang, 'gate.chat.title')}\n\n{t(lang, 'gate.chat.body')}"


def channel_missing(lang: str) -> str:
    return t(lang, "gate.channel.missing")


def chat_missing(lang: str) -> str:
    return t(lang, "gate.chat.missing")


def subscriptions_screen(lang: str, items: list) -> str:
    """Every required subscription on one screen, each marked done or not.

    ``items`` is a list of ``(RequiredSub, verified)``. Showing all of them at
    once - instead of one channel per step - is the whole point: the user can
    see what is left and finish it in any order.
    """
    total = len(items)
    lines = [t(lang, "gate.subs.title"), "", t(lang, "gate.subs.body", total=total), ""]
    for index, (sub, verified) in enumerate(items, start=1):
        mark = t(lang, "gate.subs.done") if verified else t(lang, "gate.subs.todo")
        lines.append(
            t(
                lang, "gate.subs.item",
                n=index, status=mark, title=esc(sub_label(lang, sub, index)),
            )
        )
    return "\n".join(lines)


def membership_unverified(lang: str) -> str:
    return t(lang, "gate.unverified")


def welcome(lang: str, user: User) -> str:
    name = esc(user.first_name or user.username or "friend")
    return (
        f"{t(lang, 'welcome.title', name=name)}\n\n"
        f"{t(lang, 'welcome.body')}\n\n"
        f"{t(lang, 'welcome.pick')}"
    )


def main_menu(lang: str) -> str:
    return f"{t(lang, 'menu.title')}\n\n{t(lang, 'menu.question')}"


def banned_screen(lang: str, reason: str | None) -> str:
    text = f"{t(lang, 'ban.title')}\n\n{t(lang, 'ban.body')}"
    if reason:
        text += f"\n\n{t(lang, 'ban.reason', reason=esc(reason))}"
    return text


def restricted_screen(lang: str, reason: str | None, until: datetime | None) -> str:
    text = f"{t(lang, 'restrict.title')}\n\n{t(lang, 'restrict.body')}"
    if reason:
        text += f"\n\n{t(lang, 'restrict.reason', reason=esc(reason))}"
    if until:
        text += f"\n\n{t(lang, 'restrict.until', until=_fmt_dt(until))}"
    return text


# --------------------------------------------------------------------- results
def _confidence_note(lang: str, result: CheckResult) -> str | None:
    if result.status is not CheckStatus.UNKNOWN:
        return None
    if result.reason == "mtproto_required_for_availability":
        return t(lang, "result.need_mtproto")
    if result.reason == "no_checker_available":
        return t(lang, "result.no_checker")
    return t(lang, "result.no_answer")


def _footer(lang: str, result: CheckResult) -> list[str]:
    verified = (
        t(lang, "result.verified_ms", ms=result.duration_ms)
        if result.duration_ms
        else t(lang, "result.verified")
    )
    source = t(
        lang, "result.source_cached" if result.cached else "result.source",
        value=source_label(lang, result.source),
    )
    return [SEP, verified, source]


def basic_result(lang: str, result: CheckResult) -> str:
    lines = [
        t(lang, "result.title"),
        "",
        f"<b>{esc(result.display)}</b>",
        "",
        status_label(lang, result.status),
    ]

    if result.status is CheckStatus.OCCUPIED and result.entity_type:
        lines.append(t(lang, "result.type", value=esc(result.entity_type)))
    if result.status is CheckStatus.INVALID and result.reason:
        lines.append(t(lang, "result.reason", value=esc(result.reason.replace("_", " "))))

    note = _confidence_note(lang, result)
    if note:
        lines += ["", note]

    lines += [""] + _footer(lang, result)
    return "\n".join(lines)


def collectible_result(lang: str, result: CollectibleResult) -> str:
    lines = [
        t(lang, "collectible.title"),
        "",
        f"<b>@{esc(result.username)}</b>",
        "",
        t(lang, "collectible.status", value=collectible_label(lang, result.status)),
    ]
    if result.is_collectible:
        lines.append(t(lang, "collectible.marketplace"))
    if result.owner:
        lines.append(t(lang, "collectible.owner", value=esc(result.owner)))
    if result.price:
        lines.append(t(lang, "collectible.price", value=esc(result.price)))
    if result.purchase_date:
        lines.append(t(lang, "collectible.purchased", value=esc(result.purchase_date)))

    if result.reason == "needs_mtproto_login":
        lines += ["", t(lang, "collectible.need_login")]
    elif result.reason == "fragment_disabled":
        lines += ["", t(lang, "collectible.disabled")]
    elif result.status is CollectibleStatus.UNKNOWN:
        lines += ["", t(lang, "collectible.no_data")]
    return "\n".join(lines)


def all_in_one_result(
    lang: str, basic: CheckResult, collectible: CollectibleResult | None
) -> str:
    lines = [
        t(lang, "result.title"),
        "",
        f"<b>{esc(basic.display)}</b>",
        "",
        t(lang, "result.basic"),
        status_label(lang, basic.status),
    ]

    if basic.status is CheckStatus.AVAILABLE:
        lines.append(t(lang, "result.telegram_no_owner"))
    elif basic.status is CheckStatus.OCCUPIED:
        if basic.entity_type:
            lines.append(t(lang, "result.telegram_active", kind=esc(basic.entity_type)))
        if basic.title:
            lines.append(t(lang, "result.title_field", value=esc(basic.title)))
    elif basic.status is CheckStatus.INVALID:
        lines.append(
            t(lang, "result.reason", value=esc((basic.reason or "invalid").replace("_", " ")))
        )
    else:
        lines.append(_confidence_note(lang, basic) or t(lang, "result.no_answer"))

    lines += ["", t(lang, "result.collectible")]
    if collectible is None:
        lines.append(t(lang, "result.not_checked"))
    elif collectible.is_collectible:
        lines.append(collectible_label(lang, collectible.status))
        lines.append(t(lang, "collectible.marketplace"))
        if collectible.owner:
            lines.append(t(lang, "collectible.owner", value=esc(collectible.owner)))
        if collectible.price:
            lines.append(t(lang, "collectible.price", value=esc(collectible.price)))
    elif collectible.status is CollectibleStatus.NOT_DETECTED:
        lines.append(t(lang, "result.not_detected"))
    elif collectible.reason == "needs_mtproto_login":
        lines.append(t(lang, "collectible.need_login_short"))
    elif collectible.reason == "fragment_disabled":
        lines.append(t(lang, "collectible.unavailable_short"))
    else:
        lines.append(t(lang, "collectible.s_unknown"))

    lines += [""] + _footer(lang, basic)
    return "\n".join(lines)


# --------------------------------------------------------------------- scan
def _bar(percent: int, width: int = 10) -> str:
    filled = max(0, min(width, round(percent / 100 * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


def scan_progress(lang: str, summary: ScanSummary) -> str:
    total = max(summary.total, 1)
    percent = int(summary.checked / total * 100)
    return (
        f"{t(lang, 'scan.scanning')}\n\n"
        f"{_bar(percent)} {percent}%\n"
        f"{t(lang, 'scan.checked', done=summary.checked, total=summary.total)}\n\n"
        f"{t(lang, 'scan.available', n=summary.available)}\n"
        f"{t(lang, 'scan.collectible', n=summary.collectible)}\n"
        f"{t(lang, 'scan.occupied', n=summary.occupied)}\n"
        f"{t(lang, 'scan.unknown', n=summary.unknown)}"
    )


def scan_complete(lang: str, summary: ScanSummary) -> str:
    lines = [
        t(lang, "scan.complete"),
        "",
        t(lang, "scan.usernames_checked", n=summary.total),
        "",
        t(lang, "scan.available", n=summary.available),
        t(lang, "scan.collectible", n=summary.collectible),
        t(lang, "scan.occupied", n=summary.occupied),
    ]
    if summary.unknown:
        lines.append(t(lang, "scan.unknown", n=summary.unknown))
    if summary.invalid:
        lines.append(t(lang, "scan.invalid", n=summary.invalid))
    if summary.rate_limited:
        lines.append(t(lang, "scan.rate_limited", n=summary.rate_limited))

    if summary.available_usernames:
        preview = summary.available_usernames[:15]
        lines += ["", t(lang, "scan.available_list")]
        lines += [f"@{esc(name)}" for name in preview]
        if len(summary.available_usernames) > len(preview):
            lines.append(
                t(lang, "scan.more", n=len(summary.available_usernames) - len(preview))
            )

    lines += ["", t(lang, "scan.time", value=summary.duration_seconds)]
    return "\n".join(lines)


def search_seed_screen(lang: str) -> str:
    return (
        f"{t(lang, 'search.title')}\n\n"
        f"{t(lang, 'search.body')}\n"
        f"{t(lang, 'search.example')}"
    )


def search_count_screen(lang: str, seed: str, hard_max: int) -> str:
    return (
        f"{t(lang, 'search.how_many')}\n\n"
        f"{t(lang, 'search.base', value=esc(seed))}\n\n"
        f"{t(lang, 'search.pick', max=hard_max)}"
    )


# --------------------------------------------------------------------- history / settings
def history_screen(lang: str, rows: list[Search], page: int, total_pages: int) -> str:
    if not rows:
        return t(lang, "history.empty")
    lines = [t(lang, "history.title"), ""]
    for row in rows:
        mode = mode_label(lang, row.mode)
        lines.append(f"@{esc(row.query)}  \u2022  {mode}  \u2022  {_fmt_time(row.created_at)}")
    lines += ["", t(lang, "history.page", page=page + 1, total=total_pages)]
    return "\n".join(lines)


def settings_screen(
    lang: str, user: User, *, search_length: int, search_digits: bool,
    language: str, daily_drop: bool = False,
) -> str:
    digest_state = t(lang, "search.on") if daily_drop else t(lang, "search.off")
    return (
        f"{t(lang, 'settings.title')}\n\n"
        f"{t(lang, 'settings.def_length')}: <b>{search_length}</b>\n"
        f"{t(lang, 'settings.def_digits')}: "
        f"<b>{t(lang, 'search.on') if search_digits else t(lang, 'search.off')}</b>\n"
        f"{t(lang, 'settings.language')}: <b>{language}</b>\n"
        f"{t(lang, 'settings.digest')}: <b>{digest_state}</b>\n\n"
        f"{t(lang, 'settings.privilege')}: <b>{privilege_label(lang, user.privilege)}</b>"
    )


def digest_screen(lang: str, daily_drop: bool, hour: int = 9) -> str:
    """What the Daily Drop is, its state, and when the next one lands."""
    state = t(lang, "digest.enabled") if daily_drop else t(lang, "digest.disabled")
    lines = [t(lang, "digest.title"), "", t(lang, "digest.hint"), "", state]
    if daily_drop:
        lines.append(t(lang, "digest.next", hour=f"{hour:02d}"))
    return "\n".join(lines)


def digest_header(lang: str) -> str:
    """The banner prepended to a delivered Daily Drop."""
    return t(lang, "digest.title")


def rate_screen(lang: str, name: str, premium) -> str:
    """``/rate`` output - exactly the premium block a search result shows.

    Sharing :func:`premium_block` is the point: a name must never be judged one
    way in a search result and another way in the instant check.
    """
    lines = [t(lang, "rate.title"), "", f"<b>@{esc(name)}</b>", ""]
    lines += premium_block(lang, premium)
    lines += ["", t(lang, "rate.note")]
    return "\n".join(lines)


def help_screen(lang: str, is_admin: bool) -> str:
    lines = [
        t(lang, "help.title"),
        "",
        t(lang, "help.start"),
        t(lang, "help.check"),
        t(lang, "help.search"),
        t(lang, "help.history"),
        t(lang, "help.settings"),
        t(lang, "help.help"),
    ]
    if is_admin:
        lines.append(t(lang, "help.admin"))
    return "\n".join(lines)


# --------------------------------------------------------------------- admin
def admin_root(lang: str, actor: User, role: str) -> str:
    return (
        f"{t(lang, 'admin.title')}\n\n"
        f"{t(lang, 'admin.signed_in', id=actor.telegram_id)}\n"
        f"{t(lang, 'admin.role', role=role)}\n\n"
        f"{t(lang, 'admin.pick')}"
    )


def admin_user_profile(lang: str, user: User, checks: int) -> str:
    text = (
        f"{t(lang, 'admin.profile_title')}\n\n"
        f"{t(lang, 'admin.p_id')}: <code>{user.telegram_id}</code>\n"
        f"{t(lang, 'admin.p_username')}: "
        f"{'@' + esc(user.username) if user.username else '-'}\n\n"
        f"{t(lang, 'admin.p_registered')}: {_fmt_dt(user.created_at, '%d.%m.%Y')}\n"
        f"{t(lang, 'admin.p_last')}: {_fmt_time(user.last_seen)}\n"
        f"{t(lang, 'admin.p_checks')}: {checks}\n\n"
        f"{t(lang, 'admin.p_privilege')}: <b>{privilege_label(lang, user.privilege)}</b>\n"
        f"{t(lang, 'admin.p_status')}: {status_text(lang, user)}"
    )
    if user.admin_note:
        text += f"\n\n{t(lang, 'admin.p_note')}: {esc(user.admin_note)}"
    return text


def status_text(lang: str, user: User) -> str:
    if user.is_banned:
        return t(lang, "admin.status_banned")
    if user.ban_until is not None:
        return t(lang, "admin.status_restricted", until=_fmt_dt(user.ban_until))
    return t(lang, "admin.status_active")


def _target_name(user: User) -> str:
    return f"@{esc(user.username)}" if user.username else str(user.telegram_id)


def admin_ban_prompt(lang: str, user: User) -> str:
    return (
        f"{t(lang, 'admin.ban_title')}\n\n"
        f"{t(lang, 'admin.user')}: {_target_name(user)}\n\n"
        f"{t(lang, 'admin.ban_ask')}"
    )


def admin_restrict_prompt(lang: str, user: User) -> str:
    return (
        f"{t(lang, 'admin.restrict_title')}\n\n"
        f"{t(lang, 'admin.user')}: {_target_name(user)}\n\n"
        f"{t(lang, 'admin.restrict_ask')}"
    )


def admin_note_prompt(lang: str, user: User) -> str:
    return (
        f"{t(lang, 'admin.note_title')}\n\n"
        f"{t(lang, 'admin.user')}: {_target_name(user)}\n\n"
        f"{t(lang, 'admin.note_ask')}"
    )


def admin_setting_prompt(lang: str, key: str, value: str) -> str:
    return (
        f"{t(lang, 'admin.settings_title')}\n\n"
        f"{t(lang, 'admin.setting_key')}: <code>{esc(key)}</code>\n"
        f"{t(lang, 'admin.setting_current')}: <code>{esc(value) or '-'}</code>\n\n"
        f"{t(lang, 'admin.setting_ask')}"
    )


def admin_action_line(lang: str, action: AdminAction) -> str:
    head = t(lang, "admin.action_by", action=esc(action.action), admin=action.admin_id)
    line = f"<code>{_fmt_dt(action.created_at)}</code>\n{head} \u2192 {action.target_user_id or '-'}"
    if action.reason:
        line += f" \u2014 {esc(action.reason)}"
    return line


def statistics_screen(lang: str, stats: dict) -> str:
    return (
        f"{t(lang, 'admin.stats_title')}\n\n"
        f"{t(lang, 'admin.s_users', n=stats['users_total'])}\n"
        f"{t(lang, 'admin.s_active', n=stats['active_today'])}\n"
        f"{t(lang, 'admin.s_checks', n=stats['checks_total'])}\n"
        f"{t(lang, 'admin.s_searches', n=stats['searches_total'])}\n"
        f"{t(lang, 'admin.s_collectible', n=stats['checks_collectible'])}\n"
        f"{t(lang, 'admin.s_banned', n=stats['banned'])}\n"
        f"{t(lang, 'admin.s_restricted', n=stats['restricted'])}"
    )


def _state(lang: str, ok: bool, label: str) -> str:
    dot = "\U0001F7E2" if ok else "\U0001F534"
    return f"{dot} {label}"


def system_screen(lang: str, status: dict) -> str:
    mtproto_line = {
        "ok": _state(lang, True, t(lang, "admin.connected")),
        "not_authorised": _state(lang, False, t(lang, "admin.not_authorised")),
        "not_configured": _state(lang, False, t(lang, "admin.not_configured")),
    }.get(status.get("mtproto"), _state(lang, False, t(lang, "admin.not_configured")))

    engine_ok = status.get("collectible_engine") == "ok"
    engine_line = _state(
        lang, engine_ok, t(lang, "admin.enabled") if engine_ok else t(lang, "admin.disabled")
    )

    bot_line = _state(lang, status.get("bot_online", False), t(lang, "admin.online"))
    if status.get("bot_username"):
        bot_line += f" (@{status['bot_username']})"

    db_ok = status.get("database", False)
    redis_ok = status.get("redis", False)
    tg_ok = status.get("telegram_api", False)

    db_state = _state(lang, db_ok, t(lang, "admin.connected") if db_ok else t(lang, "admin.unavailable"))
    redis_state = _state(
        lang, redis_ok, t(lang, "admin.connected") if redis_ok else t(lang, "admin.unavailable")
    )
    tg_state = _state(
        lang, tg_ok, t(lang, "admin.connected") if tg_ok else t(lang, "admin.unavailable")
    )

    return (
        f"{t(lang, 'admin.system_title')}\n\n"
        f"{t(lang, 'admin.sys_bot')}: {bot_line}\n"
        f"{t(lang, 'admin.sys_db')}: {db_state}\n"
        f"{t(lang, 'admin.sys_redis')}: {redis_state}\n"
        f"{t(lang, 'admin.sys_telegram')}: {tg_state}\n"
        f"{t(lang, 'admin.sys_mtproto')}: {mtproto_line}\n"
        f"{t(lang, 'admin.sys_engine')}: {engine_line}\n\n"
        f"{t(lang, 'admin.sys_build', value=build_stamp())}\n"
        f"{t(lang, 'admin.sys_cache', value=status.get('cache_ttl'))}\n"
        f"{t(lang, 'admin.sys_conc', value=status.get('max_concurrent_checks'))}\n"
        f"{t(lang, 'admin.sys_max', value=status.get('max_search_results'))}"
    )


def access_settings_screen(
    lang: str, channel_id: int, channel_username: str, chat_id: int, chat_username: str,
    subs: list | None = None,
) -> str:
    lines = [
        t(lang, "admin.access_title"),
        "",
        f"{t(lang, 'admin.access_channel_id')}: <code>{channel_id or '-'}</code>",
        f"{t(lang, 'admin.access_channel_user')}: <code>{channel_username or '-'}</code>",
        "",
        f"{t(lang, 'admin.access_chat_id')}: <code>{chat_id or '-'}</code>",
        f"{t(lang, 'admin.access_chat_user')}: <code>{chat_username or '-'}</code>",
    ]
    if subs:
        lines += ["", t(lang, "admin.access_subs", n=len(subs))]
        for index, sub in enumerate(subs, start=1):
            lines.append(
                t(
                    lang, "admin.access_sub_item",
                    n=index, title=esc(sub_label(lang, sub, index)),
                    id=sub.chat_id or sub.username or "-",
                )
            )
    lines += ["", f"<i>{t(lang, 'admin.access_hint')}</i>"]
    return "\n".join(lines)


# --------------------------------------------------------------------- errors
def error_screen(lang: str) -> str:
    return f"{t(lang, 'error.title')}\n\n{t(lang, 'error.body')}"


def busy_screen(lang: str) -> str:
    return t(lang, "error.busy")


# --------------------------------------------------------------------- search engine
def _criteria_lines(lang: str, length: int | None, digits: bool, mask: str | None) -> str:
    lines = [
        t(lang, "search.c_length", value=length if length else t(lang, "search.any")),
        t(lang, "search.c_digits", value=t(lang, "search.on") if digits else t(lang, "search.off")),
    ]
    if mask:
        lines.append(t(lang, "search.c_mask", value=esc(mask)))
    return "\n".join(lines)


def search_target_screen(lang: str) -> str:
    return f"{t(lang, 'search.setup_title')}\n\n{t(lang, 'search.setup_body')}"


def search_setup_screen(
    lang: str, *, length: int | None, digits: bool, mask: str | None,
) -> str:
    body = _criteria_lines(lang, length, digits, mask)
    return (
        f"{t(lang, 'search.setup_title')}\n\n"
        f"{t(lang, 'search.setup_body')}\n\n"
        f"{t(lang, 'search.criteria', lines=body)}\n\n"
        f"{t(lang, 'search.premium_note')}"
    )


def premium_block(lang: str, premium) -> list[str]:
    """The five premium criteria as a tick/cross list, plus the N/5 verdict.

    A free name is worth what a buyer will pay for it, and on Fragment that
    comes down to five yes/no properties - not an averaged 0-100 number that
    hides *which* property the user is actually paying for. Five rows, one per
    criterion, make the verdict auditable: 5/5 clears every gate, 0/5 fails all
    five no matter how "average" the name looks.
    """
    lines: list[str] = []
    for attr, key in PREMIUM_KEYS:
        ok = bool(getattr(premium, attr, False))
        template = "search.premium_ok" if ok else "search.premium_no"
        lines.append(t(lang, template, label=t(lang, key)))
    lines += ["", t(lang, "search.premium_badge", value=premium.total)]
    return lines


def variants_result(lang: str, seed: str, variants: list, attempts_used: int) -> str:
    """The free alternatives to a name the user cannot have.

    This is the answer to the most common dead end in the whole product: the
    perfect name is taken, and the user is left with nothing to do.
    """
    lines = [
        t(lang, "search.result_title"),
        "",
        t(lang, "variants.body", seed=esc(seed)),
    ]
    if not variants:
        lines += ["", t(lang, "variants.none", seed=esc(seed))]
        return "\n".join(lines)

    lines.append("")
    for item in variants:
        lines.append(
            t(
                lang, "variants.line",
                icon=premium_icon(item.premium.total),
                name=esc(item.username),
                score=item.premium.total,
            )
        )
    lines += ["", t(lang, "variants.hint"), t(lang, "search.attempts", n=attempts_used)]
    return "\n".join(lines)


def find_result(lang: str, attempt, attempts_used: int) -> str:
    """Render one search outcome.

    A variants run is not a single name but a shortlist, so it gets its own
    renderer; every other outcome is either one name or one honest explanation
    of why there is no name.
    """
    if attempt.reason == "variants":
        return variants_result(
            lang, attempt.seed or "", list(attempt.variants or []), attempts_used
        )
    return _find_result_body(lang, attempt, attempts_used)


def _find_result_body(lang: str, attempt, attempts_used: int) -> str:
    if not attempt.username:
        if attempt.reason == "all_taken":
            # Every candidate this good already has an owner. Never dress an
            # occupied name up as a result - explain and point at a trap.
            return (
                f"{t(lang, 'search.result_title')}\n\n"
                f"{t(lang, 'search.all_taken', n=attempt.generated_tries)}\n\n"
                f"{t(lang, 'search.all_taken_hint')}"
            )
        if attempt.reason == "unconfirmed":
            return (
                f"{t(lang, 'search.result_title')}\n\n"
                f"{t(lang, 'search.unconfirmed', n=attempt.generated_tries)}\n\n"
                f"{t(lang, 'search.unconfirmed_hint')}"
            )
        if attempt.reason == "throttled":
            # Telegram is genuinely rate-limiting us. Do not pretend the names
            # are taken and do not leave the user on a frozen "SEARCHING...".
            return (
                f"{t(lang, 'search.result_title')}\n\n"
                f"{t(lang, 'search.throttled', n=attempt.generated_tries)}"
            )
        if attempt.reason == "no_free_found":
            return (
                f"{t(lang, 'search.result_title')}\n\n"
                f"{t(lang, 'search.no_free_found', n=attempt.generated_tries)}"
            )
        return (
            f"{t(lang, 'search.result_title')}\n\n"
            f"{t(lang, 'search.no_candidate')}"
        )

    lines = [
        t(lang, "search.result_title"),
        "",
        f"<b>@{esc(attempt.username)}</b>",
        "",
        t(lang, "search.hit_free") if attempt.hit else t(lang, "search.miss_free"),
    ]

    if attempt.basic is not None and attempt.basic.status is CheckStatus.OCCUPIED:
        if attempt.basic.entity_type:
            lines.append(t(lang, "result.type", value=esc(attempt.basic.entity_type)))
        if attempt.basic.title:
            lines.append(t(lang, "result.title_field", value=esc(attempt.basic.title)))

    # The Fragment half of the double check, stated explicitly. A confirmed-free
    # name is only ever shown when Fragment does not list it for sale, so this
    # line is the proof of the second check - and says so honestly when the
    # marketplace could not be reached.
    if attempt.hit:
        lines.append(
            t(lang, "search.fragment_ok") if attempt.fragment_checked
            else t(lang, "search.fragment_off")
        )

    if attempt.value is not None:
        val = attempt.value
        lines.append(
            t(lang, "value.estimate", low=val["band_low"], high=val["band_high"])
        )
        if val["wordlike"]:
            lines.append(t(lang, "value.wordlike"))

    # The claim kit: a free name is only useful if the user can take it, and a
    # username is first-come-first-served, so the moment of the result is the
    # moment to act. Copyable handle plus the reminder to go and do it.
    if attempt.hit:
        lines += [
            "",
            t(lang, "claim.handle", name=esc(attempt.username)),
            t(lang, "claim.note"),
        ]

    lines += [""] + premium_block(lang, attempt.premium)
    lines.append(t(lang, "search.attempts", n=attempts_used))

    if not attempt.hit:
        lines += ["", t(lang, "search.hint_short")]

    return "\n".join(lines)


# --------------------------------------------------------------------- traps
def _watch_ago(lang: str, moment: datetime | None) -> str:
    """Human-readable age of the latest persisted watch check."""
    if moment is None:
        return t(lang, "watch.never_checked")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - moment).total_seconds()))
    if seconds < 90:
        return t(lang, "watch.checked_seconds", n=seconds)
    if seconds < 5400:
        return t(lang, "watch.checked_minutes", n=seconds // 60)
    return t(lang, "watch.checked_hours", n=seconds // 3600)


def watch_screen(lang: str, watches: list, interval: int) -> str:
    if not watches:
        return (
            f"{t(lang, 'watch.title')}\n\n{t(lang, 'watch.empty')}\n\n"
            f"{t(lang, 'watch.body', interval=interval)}"
        )

    lines = [t(lang, "watch.title"), "", t(lang, "watch.body", interval=interval), ""]
    result_names = {
        "available": "available",
        "occupied": "occupied",
        "unknown": "unknown",
        "rate_limited": "rate_limited",
        "error": "error",
        "invalid": "invalid",
        "searching": "searching",
    }
    for watch in watches[:10]:
        status = t(
            lang,
            "watch.status_fired" if watch.notified_at else "watch.status_waiting",
        )
        raw_status = (watch.last_status or "").lower()
        result_key = result_names.get(raw_status, "none")
        lines.append(
            t(
                lang,
                "watch.item_line",
                status=status,
                name=esc(watch.username),
                checked=_watch_ago(lang, watch.last_checked_at),
                result=t(lang, f"watch.result_{result_key}"),
            )
        )
    lines += ["", t(lang, "watch.interval", n=interval)]
    return "\n".join(lines)


def watch_alert(lang: str, username: str) -> str:
    return t(lang, "watch.alert", name=esc(username))


def trap_collectible(lang: str, username: str, price: str | None, status: str) -> str:
    return t(
        lang,
        "trap.collectible",
        name=esc(username),
        price=esc(price or t(lang, "collectible.s_unknown")),
        status=esc(collectible_label(lang, status)),
    )


# --------------------------------------------------------------------- profile
def achievements_screen(lang: str, items: list, done: int, total: int) -> str:
    lines = [t(lang, "ach.title"), "", t(lang, "ach.summary", done=done, total=total), ""]
    for item in items:
        name = t(lang, f"ach.a_{item.code}")
        icon = emoji_for(item.percent)
        if item.unlocked:
            lines.append(t(lang, "ach.unlocked", icon=icon, name=name))
        else:
            lines.append(
                t(lang, "ach.locked", icon=icon, name=name,
                  progress=item.progress, target=item.target)
            )
    return "\n".join(lines)


def profile_screen(lang: str, user, stats: dict) -> str:
    name = esc(user.first_name or user.username or "-")
    username = f"@{esc(user.username)}" if user.username else "-"
    best = stats.get("best_find")
    return (
        f"{t(lang, 'profile.title')}\n\n"
        f"{t(lang, 'profile.id')}: <code>{user.telegram_id}</code>\n"
        f"{t(lang, 'profile.username')}: {username}\n"
        f"<b>{name}</b>\n\n"
        f"{t(lang, 'profile.privilege')}: <b>{privilege_label(lang, user.privilege)}</b>\n"
        f"{t(lang, 'profile.language')}: <b>{stats.get('language', '-')}</b>\n"
        f"{t(lang, 'profile.registered')}: {_fmt_dt(user.created_at, '%d.%m.%Y')}\n\n"
        f"{t(lang, 'profile.stats_title')}\n\n"
        f"{t(lang, 'profile.checks')}: <b>{stats.get('checks', 0)}</b>\n"
        f"{t(lang, 'profile.searches')}: <b>{stats.get('searches', 0)}</b>\n"
        f"{t(lang, 'profile.traps')}: <b>{stats.get('traps', 0)}</b>\n"
        f"{t(lang, 'profile.battles')}: <b>{stats.get('battles', 0)}</b>\n"
        f"{t(lang, 'profile.best')}: <b>{('@' + esc(best)) if best else t(lang, 'profile.best_none')}</b>\n"
        f"{t(lang, 'profile.achievements')}: <b>{stats.get('achievements_done', 0)}"
        f" / {stats.get('achievements_total', 0)}</b>"
    )


def profile_achievements(lang: str, stats: dict) -> str:
    return achievements_screen(
        lang, stats["achievements"],
        stats.get("achievements_done", 0), stats.get("achievements_total", 0),
    )


# --------------------------------------------------------------------- battle
def battle_screen(lang: str) -> str:
    return f"{t(lang, 'battle.title')}\n\n{t(lang, 'battle.body')}"


BATTLE_CRITERIA = (
    ("length", "letters"),
    ("word", "scroll"),
    ("spelling", "pencil"),
    ("digits", "numbers"),
    ("status", "eye"),
)


def _battle_side_block(lang: str, side, *, side_key: str, side_icon: str, winner: bool) -> list[str]:
    """Render one username and keep every score visually attached to it."""
    lines = [
        t(lang, side_key, icon=emoji.render(side_icon), name=esc(side.username)),
        t(lang, "battle.total_line", chart=emoji.render("chart"), score=f"{side.total:.1f}"),
    ]
    if winner:
        lines.append(t(lang, "battle.side_winner", trophy=emoji.render("trophy")))

    for key, icon_name in BATTLE_CRITERIA:
        score = side.scores.get(key, 0)
        if key == "status":
            value = f"{t(lang, f'battle.status_{side.status}')}, {score}/10"
        else:
            value = f"{score}/10"
        lines.append(
            t(
                lang,
                "battle.score_item",
                icon=emoji.render(icon_name),
                label=t(lang, f"battle.c_{key}"),
                score=value,
            )
        )
    return lines


def battle_result(lang: str, result) -> str:
    """Show two independent scorecards instead of an ambiguous arrow table."""
    left_name = result.left.username
    right_name = result.right.username
    lines = [
        t(lang, "battle.result_title"),
        "",
        *_battle_side_block(
            lang,
            result.left,
            side_key="battle.side_one",
            side_icon="person",
            winner=result.winner == "left",
        ),
        SEP,
        *_battle_side_block(
            lang,
            result.right,
            side_key="battle.side_two",
            side_icon="users",
            winner=result.winner == "right",
        ),
        "",
    ]
    if result.winner == "draw":
        lines.append(t(lang, "battle.draw", handshake=emoji.render("handshake")))
    else:
        winner_name = left_name if result.winner == "left" else right_name
        lines.append(
            t(
                lang,
                "battle.winner",
                trophy=emoji.render("trophy"),
                name=esc(winner_name),
            )
        )
    return "\n".join(lines)


def battle_challenge_text(lang: str, challenger: str, rival: str) -> str:
    return (
        f"{t(lang, 'battle.challenge_text', challenger=esc(challenger), rival=esc(rival))}\n\n"
        f"{t(lang, 'battle.challenge_waiting')}"
    )


def battle_challenge_open(lang: str, challenger: str, rival: str) -> str:
    """The message posted into the chosen chat, with an accept button."""
    return (
        f"{t(lang, 'battle.title')}\n\n"
        f"{t(lang, 'battle.challenge_text', challenger=esc(challenger), rival=esc(rival))}\n\n"
        f"{t(lang, 'battle.body')}"
    )


# --------------------------------------------------------------------- support
def support_screen(lang: str) -> str:
    return f"{t(lang, 'support.title')}\n\n{t(lang, 'support.body')}"


def faq_screen(lang: str) -> str:
    """Every FAQ entry, in order, discovered from the translation table.

    The entries are numbered keys, so the screen used to hardcode a count and a
    new question was silently invisible until someone remembered to bump it.
    Probing for the next key instead means adding ``support.faq_q11`` and
    ``support.faq_a11`` is genuinely all it takes. ``t`` returns the key itself
    for a missing one, which is the stop condition.
    """
    parts = [t(lang, "support.faq_title")]
    for index in range(1, MAX_FAQ_ENTRIES + 1):
        question_key = f"support.faq_q{index}"
        question = t(lang, question_key)
        if question == question_key:
            break
        answer_key = f"support.faq_a{index}"
        answer = t(lang, answer_key)
        if answer == answer_key:
            break
        parts += ["", question, answer]
    return "\n".join(parts)


def emoji_for(score: int) -> str:
    """A rank glyph for a 0-100 rating."""
    from app.services.emoji import emoji as _emoji

    if score >= 95:
        return _emoji.render("trophy")
    if score >= 85:
        return _emoji.render("medal")
    if score >= 70:
        return _emoji.render("star")
    return _emoji.render("seedling")


def premium_icon(total: int) -> str:
    """A rank glyph for a 0-5 premium verdict."""
    from app.services.emoji import emoji as _emoji

    if total >= 5:
        return _emoji.render("trophy")
    if total >= 4:
        return _emoji.render("medal")
    if total >= 3:
        return _emoji.render("star")
    return _emoji.render("seedling")
