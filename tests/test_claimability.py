"""Claimability honesty: 'not occupied' must never silently become 'free'.

``contacts.resolveUsername`` answers "not occupied" for names Telegram will
still refuse to assign (reserved / cooldown / anti-abuse). Only the user-only
``account.checkUsername`` separates the two - and when that check is
unavailable, the result must say so, and the search must not stop for the
unverifiable name as if it were a proven win.
"""

from __future__ import annotations

import pytest

from app.search import finder as finder_module
from app.search.finder import SearchCriteria, UsernameFinder
from app.telegram import mtproto as mtproto_module
from app.telegram.mtproto import MtprotoResult
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus
from app.utils.results import CheckResult
from tests.mock_telegram import FakePageProbe


def _available(name: str, detail: str | None) -> CheckResult:
    return CheckResult(
        username=name, status=CheckStatus.AVAILABLE, source="mtproto", detail=detail,
    )


# ------------------------------------------------------------------- checker
async def test_check_username_none_means_unverified(monkeypatch):
    """A rate-limited user session answers nothing - the verdict must say so."""
    client = mtproto_module.mtproto_client

    async def fake_resolve(name):
        return MtprotoResult("not_occupied")

    async def no_verdict(name):
        return None  # session parked / flooded

    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "resolve_username", fake_resolve, raising=False)
    monkeypatch.setattr(client, "check_username", no_verdict, raising=False)
    monkeypatch.setattr(
        client, "_user_clients",
        [{"name": "t", "client": None, "ready": True, "cooldown_until": 0.0}],
        raising=False,
    )

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("recap")

    assert result.status is CheckStatus.AVAILABLE
    assert result.detail == "claimability_unverified"


async def test_check_username_true_means_verified(monkeypatch):
    client = mtproto_module.mtproto_client

    async def fake_resolve(name):
        return MtprotoResult("not_occupied")

    async def yes(name):
        return True

    monkeypatch.setattr(client, "_ready", True, raising=False)
    monkeypatch.setattr(client, "resolve_username", fake_resolve, raising=False)
    monkeypatch.setattr(client, "check_username", yes, raising=False)
    monkeypatch.setattr(
        client, "_user_clients",
        [{"name": "t", "client": None, "ready": True, "cooldown_until": 0.0}],
        raising=False,
    )

    checker = UsernameChecker(cache=None, bot=None)
    result = await checker.confirm_availability("iduc9")

    assert result.status is CheckStatus.AVAILABLE
    assert result.detail == "claimability_verified"


# -------------------------------------------------------------------- finder
async def test_unverified_names_are_never_delivered_as_results(monkeypatch):
    """When claimability cannot be verified, the run says so instead of
    inventing a "free" name - the exact failure the user kept hitting."""
    monkeypatch.setattr(settings_, "allow_bot_api_availability", True)

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    confirmed = 0

    async def unverified(name):
        nonlocal confirmed
        confirmed += 1
        return _available(name, "claimability_unverified")

    checker.confirm_availability = unverified
    attempt = await UsernameFinder(checker, None).find_one(SearchCriteria(length=8))

    # The run kept hunting (it did not stop at the first unverifiable name)...
    assert confirmed > 1
    # ...and in the end refused to invent a result: no username, honest reason.
    assert attempt.hit is False
    assert attempt.username == ""
    assert attempt.reason == "claim_unavailable"


async def test_verified_hit_stops_the_search_immediately(monkeypatch):
    monkeypatch.setattr(settings_, "allow_bot_api_availability", True)

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    confirmed = 0

    async def verified(name):
        nonlocal confirmed
        confirmed += 1
        return _available(name, "claimability_verified")

    checker.confirm_availability = verified
    attempt = await UsernameFinder(checker, None).find_one(SearchCriteria(length=8))

    assert attempt.hit is True
    assert confirmed == 1


async def test_search_refuses_to_run_without_the_claimability_gate():
    """No user session -> no search at all: every verdict would be a guess."""
    from app.telegram import mtproto as mtproto_module

    checker = UsernameChecker(
        cache=None, bot=None, page_probe=FakePageProbe(state="free")
    )
    finder = UsernameFinder(checker, None)

    async def broken_confirm(name):  # must never be reached
        raise AssertionError("the search must refuse before confirming anything")

    checker.confirm_availability = broken_confirm
    saved = mtproto_module.mtproto_client._user_clients
    mtproto_module.mtproto_client._user_clients = []
    try:
        attempt = await finder.find_one(SearchCriteria(length=8))
    finally:
        mtproto_module.mtproto_client._user_clients = saved

    assert attempt.hit is False
    assert attempt.reason == "claim_unavailable"
    assert attempt.generated_tries == 0


async def test_result_screen_carries_the_caveat():
    from app.bot import texts
    from app.search.pattern import premium_rating

    class _Attempt:
        username = "recap"
        premium = premium_rating("recap")
        hit = True
        reason = "free_found"
        basic = _available("recap", "claimability_unverified")
        value = None
        generated_tries = 3
        seed = None
        variants = None
        fragment_clear = True
        fragment_checked = True

    body = texts._find_result_body("en", _Attempt(), 1)
    assert "not verified" in body.lower()


from app.config import settings as settings_  # noqa: E402  (used via alias above)
