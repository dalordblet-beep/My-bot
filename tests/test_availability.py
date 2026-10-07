"""Availability classification - the false-positive regression suite.

The bug this locks down: the Bot API's ``getChat`` can only resolve channels,
supergroups and bots. For a username owned by a personal account it answers
"chat not found" - identical to a genuinely free name. The checker used to
report those as AVAILABLE.

Reproduced against the live API before the fix:

    @mogeds2 (owned by a person) -> getChat: "chat not found" -> reported FREE

The fix is a second, independent confirmation from the public preview page.
These tests pin the whole decision table down.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.telegram import username_checker as uc_module
from app.telegram.public_page import FREE, OCCUPIED, UNKNOWN, PublicPageProbe
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus
from tests.mock_telegram import FakePageProbe


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


def make_checker(bot, page_state: str, page_title: str | None = None) -> tuple[UsernameChecker, FakePageProbe]:
    probe = FakePageProbe(state=page_state, title=page_title)
    return UsernameChecker(cache=None, bot=bot, page_probe=probe), probe


# --------------------------------------------------------------------------- the bug
async def test_personal_account_is_not_reported_free(bot, monkeypatch):
    """The exact regression: Bot API says "not found", the page says owned."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker, probe = make_checker(bot, OCCUPIED, page_title="Mogeds")

    result = await checker.check_basic_username("mogeds2", use_cache=False)

    assert result.status is CheckStatus.OCCUPIED
    assert result.source == "public_page"
    assert result.title == "Mogeds"
    assert probe.calls == ["mogeds2"]


async def test_free_name_requires_page_confirmation(bot, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker, probe = make_checker(bot, FREE)

    result = await checker.check_basic_username("zzqxwvutrpykfmnb", use_cache=False)

    assert result.status is CheckStatus.AVAILABLE
    assert result.source == "public_page"
    assert probe.calls == ["zzqxwvutrpykfmnb"]


async def test_unconfirmed_free_name_is_unknown(bot, monkeypatch):
    """No page confirmation means no claim - even with the fallback enabled."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker, _ = make_checker(bot, UNKNOWN)

    result = await checker.check_basic_username("somebody", use_cache=False)

    assert result.status is CheckStatus.UNKNOWN
    assert result.status is not CheckStatus.AVAILABLE


async def test_strict_mode_never_claims_available(bot, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", False)
    checker, _ = make_checker(bot, FREE)

    result = await checker.check_basic_username("somebody", use_cache=False)

    assert result.status is CheckStatus.UNKNOWN
    assert result.reason == "mtproto_required_for_availability"


async def test_channel_is_resolved_by_bot_api_without_the_page(bot):
    from aiogram.enums import ChatType
    from aiogram.types import Chat

    checker, probe = make_checker(bot, FREE)
    checker._bot = bot
    # The mock session resolves this chat, so no page probe should be needed.
    bot.session.chats["@takenchannel"] = Chat(
        id=-100555, type=ChatType.CHANNEL, title="Taken"
    )

    result = await checker.check_basic_username("takenchannel", use_cache=False)

    assert result.status is CheckStatus.OCCUPIED
    assert result.source == "bot_api"
    assert probe.calls == []


# --------------------------------------------------------------------------- parsing
REAL_OCCUPIED_PAGE = (
    '<html><head><meta property="og:title" content="Mogeds">'
    "</head><body><div class=\"tgme_page_title\">Mogeds</div></body></html>"
)
# The generic "contact @name" invitation. Verified live: owned accounts without
# a public card render exactly this, so it must NOT be read as "free".
CONTACT_PLACEHOLDER_PAGE = (
    '<html><head><meta property="og:title" content="Telegram: Contact @nobody">'
    "</head><body><div class=\"tgme_page_icon\"><i class=\"tgme_icon_user\"></i></div>"
    "<div class=\"tgme_page_description\">If you have <strong>Telegram</strong>, "
    "you can contact <a class=\"tgme_username_link\" href=\"tg://resolve?domain=x\">"
    "@nobody</a> right away.</div></body></html>"
)
# A genuinely unclaimed handle is pushed into the signup/login flow.
REAL_FREE_PAGE = (
    '<html><head><meta property="og:title" content="Telegram">'
    "</head><body><div class=\"tgme_page_action\">"
    "<a href=\"/login\">Log in</a></div></body></html>"
)
UNKNOWN_PAGE = "<html><head><title>Telegram</title></head><body></body></html>"


def test_parse_detects_an_owned_username():
    result = PublicPageProbe.parse(REAL_OCCUPIED_PAGE)
    assert result.state == OCCUPIED
    assert result.title == "Mogeds"


def test_parse_never_reads_the_contact_placeholder_as_free():
    """Regression: this placeholder made the bot report taken names as free.

    Live proof - ``love``, ``crane`` and ``money`` all serve this page despite
    being owned, because it only means "no public profile card".
    """
    result = PublicPageProbe.parse(CONTACT_PLACEHOLDER_PAGE)
    assert result.state == UNKNOWN
    assert result.state != FREE
    assert result.reason == "no_profile_card"


def test_parse_detects_a_free_username():
    result = PublicPageProbe.parse(REAL_FREE_PAGE)
    assert result.state == FREE
    assert result.reason == "signup_flow"


def test_parse_refuses_to_guess_on_an_unknown_layout():
    result = PublicPageProbe.parse(UNKNOWN_PAGE)
    assert result.state == UNKNOWN
    assert result.reason == "unrecognised_page"


async def test_probe_fails_closed_without_a_network(monkeypatch):
    """An unreachable page must never become an AVAILABLE verdict."""
    probe = PublicPageProbe(timeout=0.001)

    async def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(probe, "_get_session", boom)
    result = await probe.check("someone")

    assert result.state == UNKNOWN
    assert not result.is_free


# --------------------------------------------- MTProto "invalid" is never free
async def test_mtproto_invalid_is_never_a_free_verdict(monkeypatch):
    """USERNAME_INVALID must never become AVAILABLE - not even for a valid shape.

    Telethon documents INVALID as "nobody is using this username, or the
    username is unacceptable", and for a long time the second half was read as
    "so a shape-valid INVALID means free". Live evidence says otherwise: the
    account that separates "unowned" from "unassignable" (account.checkUsername)
    is user-only - BotMethodInvalidError for bots, verified - and Telegram does
    refuse to hand out shape-valid names it reports INVALID for (``emanim``:
    resolve says INVALID, no owner anywhere, yet the claim screen answers
    "username is invalid"). Handing such a name to the user as AVAILABLE is the
    worst verdict this bot can emit: it sends him to claim a name Telegram will
    not give him. So INVALID stays INVALID; the search skips it and keeps
    hunting for USERNAME_NOT_OCCUPIED, the only answer Telegram honours at
    claim time.
    """
    from telethon.errors import UsernameInvalidError

    from app.telegram import mtproto as mtproto_module

    class FakeClient:
        async def __call__(self, request):
            raise UsernameInvalidError(request=None)

    client = mtproto_module.mtproto_client
    monkeypatch.setattr(client, "_client", FakeClient(), raising=False)
    monkeypatch.setattr(client, "_ready", True, raising=False)

    verdict = await client.resolve_username("usano")
    assert verdict.kind == "invalid"

    # A malformed one stays invalid - it could not be registered anyway.
    malformed = await client.resolve_username("ab")
    assert malformed.kind == "invalid"
