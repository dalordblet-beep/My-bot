"""Keyboard design contract.

Telegram's Bot API accepts exactly three button styles. Verified against the
live API: 'primary', 'success' and 'danger' are accepted; aiogram also exposes
ButtonStyle.LINK but Telegram rejects it for InlineKeyboardButton with
"Invalid button style specified". These tests lock the palette down so a stray
value can never reach a user.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards.admin_kb import (
    admin_back_keyboard,
    admin_root_keyboard,
    blacklist_keyboard,
    logs_keyboard,
    privilege_picker_keyboard,
    user_list_keyboard,
    user_profile_keyboard,
    user_search_keyboard,
)
from app.bot.keyboards.captcha_kb import captcha_keyboard, captcha_retry_keyboard
from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.history_kb import (
    digest_keyboard,
    history_keyboard,
    search_count_keyboard,
    settings_keyboard,
    value_picker_keyboard,
)
from app.bot.keyboards.features_kb import (
    back_home_keyboard,
    battle_accept_keyboard,
    battle_keyboard,
    claim_kit_keyboard,
    favorite_toggle_keyboard,
    favorites_keyboard,
    filter_keyboard,
    length_keyboard,
    profile_keyboard,
    search_setup_keyboard,
    support_keyboard,
    watch_keyboard,
    variants_keyboard,
)
from app.bot.keyboards.main_menu import (
    admin_entry_keyboard,
    back_to_menu_keyboard,
    language_keyboard,
    main_menu_keyboard,
)
from app.bot.keyboards.subscription_kb import (
    channel_keyboard,
    chat_keyboard,
    subscriptions_keyboard,
)
from app.database.models import User
from app.services.captcha import CaptchaChallenge
from app.services.i18n import TRANSLATIONS
from app.services.subscriptions import RequiredSub

ALLOWED_STYLES = {"primary", "success", "danger", None}
USER = User(
    id=1,
    telegram_id=42,
    first_name="Test",
    username="tester",
    privilege="ADMIN",
    created_at=datetime.now(timezone.utc),
)


def _all_buttons(markup: InlineKeyboardMarkup):
    return [button for row in markup.inline_keyboard for button in row]


def _every_keyboard(lang: str) -> dict[str, InlineKeyboardMarkup]:
    return {
        "main_menu": main_menu_keyboard(lang),
        "main_menu_admin": main_menu_keyboard(lang, is_admin=True),
        "language": language_keyboard(lang),
        "settings": settings_keyboard(lang, 8, False, lang),
        "settings_lengths": value_picker_keyboard(
            lang, cb.SETTINGS_LENGTH_PREFIX, [5, 6, 7, 8], 8
        ),
        "admin_root": admin_root_keyboard(lang),
        "user_profile": user_profile_keyboard(lang, USER),
        "user_list": user_list_keyboard(lang, [USER], 0, 1, "adm:ulpage"),
        "channel": channel_keyboard(lang, "https://t.me/+abc"),
        "chat": chat_keyboard(lang, "https://t.me/+abc"),
        "subscriptions": subscriptions_keyboard(
            lang,
            [
                (RequiredSub(key="channel", username="chan", label="Main channel"),
                 False, "https://t.me/+abc"),
                (RequiredSub(key="chat", username="chat", label="Chat"),
                 True, "https://t.me/+def"),
            ],
        ),
        "digest": digest_keyboard(lang, True),
        "digest_off": digest_keyboard(lang, False),
        "scan_counts": search_count_keyboard(lang, [10, 50]),
        "captcha_retry": captcha_retry_keyboard(lang),
        "search_setup": search_setup_keyboard(
            lang, length=8, digits=False, mask=None,
        ),
        "search_length": length_keyboard(lang, 8),
        "search_filter": filter_keyboard(lang, "??ged"),
        "watch": watch_keyboard(lang, [SimpleNamespace(id=7, username="moged")]),
        "battle": battle_keyboard(lang),
        "support": support_keyboard(lang, "https://t.me/mogeds2"),
        # --- every remaining keyboard ---------------------------------------
        "admin_entry": admin_entry_keyboard(lang),
        "admin_back": admin_back_keyboard(lang),
        "back_home": back_home_keyboard(lang),
        "back_to_menu": back_to_menu_keyboard(lang),
        "profile": profile_keyboard(lang),
        "history": history_keyboard(lang, 1, 3),
        "user_search": user_search_keyboard(lang),
        "blacklist": blacklist_keyboard(lang, [USER], 0, 1),
        "privilege_picker": privilege_picker_keyboard(lang, 42),
        "logs": logs_keyboard(lang, 0, 3, "adm:page"),
        "battle_accept": battle_accept_keyboard(lang, 7),
        "favorite_toggle": favorite_toggle_keyboard(lang, "moged", 4),
        "favorites": favorites_keyboard(lang, []),
        "claim_kit": claim_kit_keyboard(lang, "love", 5),
        "variants": variants_keyboard(lang, "love"),
        "captcha": captcha_keyboard(_challenge(), lang),
    }


def _challenge() -> CaptchaChallenge:
    return CaptchaChallenge(
        session_id="s",
        kind="math",
        title="t",
        prompt="p",
        options=["1", "2", "3", "4"],
        correct_index=2,
        expires_at=0.0,
    )


@pytest.mark.parametrize("lang", sorted(TRANSLATIONS))
def test_only_supported_styles_are_used(lang: str):
    for name, markup in _every_keyboard(lang).items():
        for button in _all_buttons(markup):
            assert button.style in ALLOWED_STYLES, (
                f"{name}: button {button.text!r} uses unsupported style {button.style!r}"
            )


@pytest.mark.parametrize("lang", sorted(TRANSLATIONS))
def test_link_style_is_never_used(lang: str):
    """Telegram rejects 'link' for inline buttons - it must never appear."""
    for name, markup in _every_keyboard(lang).items():
        for button in _all_buttons(markup):
            assert button.style != "link", f"{name}: {button.text!r} uses 'link'"


@pytest.mark.parametrize("lang", sorted(TRANSLATIONS))
def test_every_button_has_text_and_an_action(lang: str):
    for name, markup in _every_keyboard(lang).items():
        for button in _all_buttons(markup):
            assert button.text.strip(), f"{name}: empty button label"
            assert button.callback_data or button.url, (
                f"{name}: {button.text!r} has neither callback_data nor url"
            )


@pytest.mark.parametrize("lang", sorted(TRANSLATIONS))
def test_callback_data_is_within_telegram_limit(lang: str):
    for name, markup in _every_keyboard(lang).items():
        for button in _all_buttons(markup):
            if button.callback_data:
                size = len(button.callback_data.encode())
                assert size <= 64, f"{name}: {button.callback_data!r} is {size} bytes (max 64)"


def test_main_menu_colours_are_semantic():
    markup = main_menu_keyboard("en")
    by_label = {button.text: button.style for button in _all_buttons(markup)}

    def style_of(key: str) -> str | None:
        return next(
            style for text, style in by_label.items() if text.endswith(key)
        )

    assert style_of("Search") == "primary"
    assert style_of("Battle") == "danger"
    assert style_of("Profile") == "primary"
    assert style_of("Support") is None
    assert style_of("Settings") is None


def test_check_a_username_button_is_gone():
    """The standalone "check a username" entry was removed by request."""
    labels = [b.text for b in _all_buttons(main_menu_keyboard("en"))]
    assert not any("Check a username" in text for text in labels)
    assert not any("Проверить username" in text for text in _all_buttons(main_menu_keyboard("ru")))


def test_admin_button_only_for_admins():
    labels = [b.text for b in _all_buttons(main_menu_keyboard("en", is_admin=False))]
    assert not any("Admin" in text for text in labels)

    labels = [b.text for b in _all_buttons(main_menu_keyboard("en", is_admin=True))]
    assert any("Admin" in text for text in labels)


def test_history_is_reachable_from_the_main_menu():
    """The screen and its handler existed, but no button led to it."""
    for lang in TRANSLATIONS:
        data = {button.callback_data for button in _all_buttons(main_menu_keyboard(lang))}
        assert cb.MENU_HISTORY in data, f"{lang}: no way to open history"


def test_username_watch_has_its_own_main_menu_entry():
    for lang in TRANSLATIONS:
        main_data = {button.callback_data for button in _all_buttons(main_menu_keyboard(lang))}
        search_data = {
            button.callback_data
            for button in _all_buttons(
                search_setup_keyboard(
                    lang, length=8, digits=False, mask=None
                )
            )
        }
        assert cb.MENU_WATCH in main_data
        assert cb.MENU_WATCH not in search_data
        assert cb.WATCH_ADD not in search_data


def test_destructive_actions_are_red():
    markup = user_profile_keyboard("en", USER)
    by_label = {button.text: button.style for button in _all_buttons(markup)}
    block = next(style for text, style in by_label.items() if text.endswith("Block"))
    assert block == "danger"


def test_buttons_are_iconed():
    """Every menu button carries an icon (or a custom-emoji id)."""
    for button in _all_buttons(main_menu_keyboard("en")):
        first = button.text.split(" ", 1)[0]
        assert not first.isalnum() or button.icon_custom_emoji_id, (
            f"button {button.text!r} has no icon"
        )


def test_settings_shows_each_value_once():
    """One row per setting, showing its current value.

    The screen used to list every possible value as its own button - sixteen of
    them, six sharing one icon. Values now live in their own pickers.
    """
    markup = settings_keyboard("en", 8, False, "en")
    labels = [b.text for b in _all_buttons(markup)]

    assert any("8" in text for text in labels), "length value missing"
    assert any("no" in text.lower() for text in labels), "digits value missing"

    # The active language is the only thing that still needs a tick.
    marked = [text for text in labels if "\u2713" in text]
    assert len(marked) == 1

    # And no row repeats an icon.
    for row in markup.inline_keyboard:
        icons = [b.icon_custom_emoji_id for b in row if b.icon_custom_emoji_id]
        assert len(icons) == len(set(icons)), f"duplicate icon in row: {[b.text for b in row]}"


# --------------------------------------------------------------------------- layout
def test_no_row_mixes_iconed_and_plain_buttons():
    """A row is either fully iconed or fully plain.

    Mixing inside a row is the single biggest source of "this looks
    unfinished": half the buttons carry a glyph and half do not, so the eye
    reads it as a mistake rather than a choice.
    """
    from app.services.i18n import TRANSLATIONS

    offenders: list[str] = []
    for lang in TRANSLATIONS:
        for name, markup in _every_keyboard(lang).items():
            for index, row in enumerate(markup.inline_keyboard):
                iconed = sum(1 for b in row if b.icon_custom_emoji_id)
                if 0 < iconed < len(row):
                    offenders.append(
                        f"{lang}:{name} row {index}: {iconed}/{len(row)} iconed "
                        f"({[b.text for b in row]})"
                    )
    assert not offenders, "rows mixing iconed and plain buttons://n" + "\n".join(offenders)


def test_a_row_is_either_uniform_or_all_distinct_icons():
    """Repeating one glyph across a row is a parameter set; mixing is a mistake.

    ``10 min / 1 hour / 24 hours`` all share a stopwatch on purpose - they are
    the same action with a different parameter. What looks like a bug is a row
    where *some* buttons repeat an icon and others do not, because then the eye
    cannot tell intent from accident.
    """
    from app.services.i18n import TRANSLATIONS

    offenders: list[str] = []
    for lang in TRANSLATIONS:
        for name, markup in _every_keyboard(lang).items():
            for index, row in enumerate(markup.inline_keyboard):
                icons = [b.icon_custom_emoji_id for b in row if b.icon_custom_emoji_id]
                if not icons:
                    continue
                distinct = set(icons)
                if len(distinct) == 1:
                    continue          # uniform parameter row - intentional
                if len(distinct) == len(icons):
                    continue          # every button distinct - intentional
                offenders.append(
                    f"{lang}:{name} row {index}: {[b.text for b in row]}"
                )
    assert not offenders, "rows with an ambiguous icon mix://n" + "\n".join(offenders)


def test_value_pickers_are_plain():
    """Numbers are data, not actions - a picker carries no icons."""
    from app.services.i18n import TRANSLATIONS

    for lang in TRANSLATIONS:
        for name in ("settings_lengths",):
            markup = _every_keyboard(lang)[name]
            for row in markup.inline_keyboard:
                # only the trailing navigation row may carry an icon
                if any(b.text.startswith("\u2713") or b.text[0].isdigit() for b in row):
                    assert not any(b.icon_custom_emoji_id for b in row), (
                        f"{lang}:{name} value row has icons"
                    )


def test_colour_roles_are_the_only_styles_used():
    """Every style in the UI must come from the design tokens."""
    from app.bot.keyboards.design import STYLE_FOR_ROLE

    allowed = set(STYLE_FOR_ROLE.values())
    from app.services.i18n import TRANSLATIONS

    for lang in TRANSLATIONS:
        for name, markup in _every_keyboard(lang).items():
            for row in markup.inline_keyboard:
                for button in row:
                    assert button.style in allowed, (
                        f"{lang}:{name} -> {button.text!r} uses {button.style!r}, "
                        f"which is not a design-token style"
                    )
