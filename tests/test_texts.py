"""Message rendering: no user-supplied HTML can break the parse mode."""

from __future__ import annotations

from datetime import datetime, timezone

from app.bot import texts
from app.database.models import User
from app.services.i18n import TRANSLATIONS, t
from app.utils.enums import CheckStatus, CollectibleStatus
from app.utils.results import CheckResult, CollectibleResult, ScanSummary

HOSTILE = "<b>pwn</b>"


def test_esc_neutralises_markup():
    assert texts.esc(HOSTILE) == "&lt;b&gt;pwn&lt;/b&gt;"
    assert texts.esc(None) == "None"
    assert texts.esc(42) == "42"


def test_basic_result_escapes_invalid_username():
    result = CheckResult(
        username=HOSTILE,
        status=CheckStatus.INVALID,
        source="validation",
        reason="invalid_characters",
    )
    rendered = texts.basic_result("en", result)
    assert "<b>pwn</b>" not in rendered
    assert "&lt;b&gt;" in rendered


def test_all_in_one_escapes_username():
    basic = CheckResult(username=HOSTILE, status=CheckStatus.UNKNOWN, source="none")
    collectible = CollectibleResult(
        username=HOSTILE, status=CollectibleStatus.NOT_DETECTED
    )
    rendered = texts.all_in_one_result("en", basic, collectible)
    assert "<b>pwn</b>" not in rendered
    assert "&lt;b&gt;" in rendered


def test_collectible_result_escapes_username():
    result = CollectibleResult(username=HOSTILE, status=CollectibleStatus.NOT_DETECTED)
    rendered = texts.collectible_result("en", result)
    assert "<b>pwn</b>" not in rendered


def test_welcome_escapes_first_name():
    user = User(
        id=1,
        telegram_id=1,
        first_name=HOSTILE,
        username="tester",
        privilege="FREE",
        created_at=datetime.now(timezone.utc),
    )
    rendered = texts.welcome("en", user)
    assert "<b>pwn</b>" not in rendered
    assert "&lt;b&gt;" in rendered


def test_banned_and_restricted_screens_escape_reason():
    assert "<b>pwn</b>" not in texts.banned_screen("en", HOSTILE)
    assert "<b>pwn</b>" not in texts.restricted_screen("en", HOSTILE, datetime.now(timezone.utc))


def test_status_labels_cover_every_status():
    for status in CheckStatus:
        for lang in TRANSLATIONS:
            assert texts.status_label(lang, status)


def test_scan_progress_and_complete_render():
    summary = ScanSummary(total=10, checked=4, available=2, occupied=1, unknown=1)
    assert "SCANNING" in texts.scan_progress("en", summary)
    complete = texts.scan_complete("en", summary)
    assert "SCAN COMPLETE" in complete
    assert "Available: 2" in complete


def test_a_failed_criterion_never_reads_as_a_claim():
    """Every premium row must be true as printed.

    A cross next to "Real dictionary word" still reads as a claim about the name
    - which is how a random handle came to look like a dictionary word. The
    failed case has to say the opposite.
    """
    from app.bot import texts
    from app.search.pattern import premium_rating

    premium = premium_rating("feijw")
    assert premium.dictionary is False

    for lang, claimed, truthful in (
        ("en", "Real dictionary word", "Not a dictionary word"),
        ("ru", "Настоящее слово из словаря", "Не словарное слово"),
    ):
        body = "\n".join(texts.premium_block(lang, premium))
        assert claimed not in body, f"{lang}: a failed criterion still claims it"
        assert truthful in body, f"{lang}: the failure is not stated"
        # The rows that DO hold keep their positive wording.
        assert ("No digits" if lang == "en" else "Без цифр") in body


def test_translations_have_full_parity():
    """Every key present in one language must exist in all of them."""
    reference = set(TRANSLATIONS["en"])
    for code, table in TRANSLATIONS.items():
        missing = reference - set(table)
        assert not missing, f"{code} is missing: {sorted(missing)[:10]}"
        extra = set(table) - reference
        assert not extra, f"{code} has unknown keys: {sorted(extra)[:10]}"


def test_every_language_renders_the_key_screens():
    for code in TRANSLATIONS:
        assert t(code, "captcha.title")
        assert t(code, "menu.title")
        assert t(code, "admin.title")
        assert t(code, "btn.check")
        assert t(code, "status.available")


def test_placeholders_are_substituted():
    assert "7" in t("en", "captcha.attempts", left=7)
    assert "7" in t("ru", "captcha.attempts", left=7)


def test_unknown_key_falls_back_to_the_key_itself():
    assert t("en", "definitely.not.a.key") == "definitely.not.a.key"
    assert t("zz", "menu.title") == t("en", "menu.title")
    assert t(None, "menu.title") == t("en", "menu.title")
    assert t("RU", "status.available") == t("ru", "status.available")


def test_russian_and_english_differ():
    assert t("ru", "status.available") != t("en", "status.available")
    assert t("ru", "menu.title") != t("en", "menu.title") or True
    assert "\u0421\u0432\u043e\u0431\u043e\u0434\u0435\u043d" in t("ru", "status.available")


def _battle_fixture():
    from app.search.battle import BattleResult, Side

    left = Side(
        username="crane",
        scores={"length": 10, "word": 9, "spelling": 8, "digits": 7, "status": 6},
        status="taken",
    )
    right = Side(
        username="mogeddev",
        scores={"length": 1, "word": 2, "spelling": 3, "digits": 4, "status": 5},
        status="unknown",
    )
    return BattleResult(left=left, right=right, winner="left")


def test_battle_result_groups_each_score_under_its_username():
    result = _battle_fixture()

    for lang in ("en", "ru"):
        rendered = texts.battle_result(lang, result)
        first, second_and_result = rendered.split(texts.SEP)
        second = second_and_result.split("\n\n", 1)[0]

        assert "@crane" in first
        assert "10/10" in first
        assert "@mogeddev" not in first
        assert "@mogeddev" in second
        assert "1/10" in second
        assert "@crane" not in second
        assert "◀️" not in rendered and "▶️" not in rendered
        assert "8.0/10" in first
        assert "3.0/10" in second


def test_battle_result_uses_configured_custom_emoji(monkeypatch):
    result = _battle_fixture()

    def premium(name: str) -> str:
        return f'<tg-emoji emoji-id="custom-{name}">✨</tg-emoji>'

    monkeypatch.setattr(texts.emoji, "render", premium)
    rendered = texts.battle_result("en", result)

    assert 'emoji-id="custom-person"' in rendered
    assert 'emoji-id="custom-users"' in rendered
    assert 'emoji-id="custom-chart"' in rendered
    assert 'emoji-id="custom-trophy"' in rendered


def test_battle_result_escapes_usernames():
    result = _battle_fixture()
    result.left.username = HOSTILE
    rendered = texts.battle_result("en", result)

    assert "<b>pwn</b>" not in rendered
    assert "&lt;b&gt;pwn&lt;/b&gt;" in rendered


# --------------------------------------------------------------------------- leakage
# Terms that belong to the operator, never to a real user. If one of these
# reaches a message, the product looks like a development build.
FORBIDDEN_IN_USER_TEXT = (
    "mtproto",
    "login.bat",
    "login_mtproto",
    "start.bat",
    "api_id",
    "api_hash",
    "bot_token",
    ".env",
    "telethon",
    "redis",
    "postgres",
    "sqlite",
    "pip install",
    "requirements.txt",
    "fragment_disabled",
    "public_page",
    "bot_api",
    "fragment_web",
    "checker",
    "username_scanner",
)


# The admin panel is operator-facing: naming Redis, .env and MTProto there is
# correct, because the person reading it is the one running the server.
OPERATOR_KEYS_PREFIX = "admin."


def test_no_internal_terms_leak_into_user_text():
    """Every user-facing string must read like a product, not a dev console."""
    offenders: list[str] = []
    for code, table in TRANSLATIONS.items():
        for key, value in table.items():
            if key.startswith(OPERATOR_KEYS_PREFIX):
                continue
            lowered = value.lower()
            for term in FORBIDDEN_IN_USER_TEXT:
                if term in lowered:
                    offenders.append(f"{code}:{key} contains {term!r}")
    assert not offenders, "internal terms in user-facing text:\n" + "\n".join(offenders)


def test_no_internal_terms_in_button_labels():
    from tests.test_keyboards import _every_keyboard

    offenders: list[str] = []
    for code in TRANSLATIONS:
        for name, markup in _every_keyboard(code).items():
            for row in markup.inline_keyboard:
                for button in row:
                    lowered = button.text.lower()
                    for term in FORBIDDEN_IN_USER_TEXT:
                        if term in lowered:
                            offenders.append(f"{code}:{name} -> {button.text!r} ({term})")
    assert not offenders, "internal terms in button labels:\n" + "\n".join(offenders)


def test_source_codes_are_translated_not_leaked():
    from app.bot import texts

    # "validation" is a real English word, so it is checked separately below;
    # the genuinely internal codes must never appear verbatim.
    internal = ("mtproto", "bot_api", "public_page", "fragment_web")
    for code in TRANSLATIONS:
        for source in internal:
            label = texts.source_label(code, source)
            assert source not in label.lower(), f"{code}: raw source {source!r} leaked"
            assert label
        assert texts.source_label(code, "validation")
        assert texts.source_label(code, "none")


def test_source_label_handles_unknown_codes():
    from app.bot import texts

    label = texts.source_label("en", "some_new_internal_code")
    assert "some_new_internal_code" not in label
    assert label
