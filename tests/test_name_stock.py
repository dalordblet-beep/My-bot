"""The ready supply of verified-free names, and serving from it.

The promise under test is the product's central one: a search answers with a
name that is *actually* free. The stock is how that promise survives load, so
the tests here are about honesty, not speed - a stored name is never handed over
on the strength of an old verdict, and a stale one is thrown away.
"""

from __future__ import annotations

import random

import pytest

from app.config import settings
from app.database import repository as repo
from app.database.database import session_scope
from app.search.finder import SearchCriteria, UsernameFinder
from app.services.name_stock import NameStock
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus
from app.utils.results import CheckResult
from tests.mock_telegram import FakePageProbe


def _checker(bot, page_state: str = "unknown") -> UsernameChecker:
    return UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state=page_state))


# ------------------------------------------------------------------ repository
async def test_stored_names_are_reserved_so_two_searches_never_share_one():
    """Two concurrent searches must never be handed the same username."""
    async with session_scope() as session:
        await repo.add_free_name(session, "qabux", length=5, has_digits=False, score=60)

    async with session_scope() as session:
        first = await repo.take_free_name(session, length=5, allow_digits=False)
    async with session_scope() as session:
        second = await repo.take_free_name(session, length=5, allow_digits=False)

    assert first == "qabux"
    assert second is None  # reserved by the first call, not handed out twice


async def test_a_reserved_name_comes_back_when_delivery_fails():
    """A delivery that cannot be completed must not burn the stored name."""
    async with session_scope() as session:
        await repo.add_free_name(session, "qabux", length=5, has_digits=False, score=60)
    async with session_scope() as session:
        assert await repo.take_free_name(session, length=5) == "qabux"
    async with session_scope() as session:
        await repo.release_free_name(session, "qabux")

    async with session_scope() as session:
        assert await repo.take_free_name(session, length=5) == "qabux"


async def test_stock_respects_the_requested_shape():
    """Length and digits are the user's filters, so a stored name must match."""
    async with session_scope() as session:
        await repo.add_free_name(session, "vohuto", length=6, has_digits=False, score=55)
        await repo.add_free_name(session, "iduc9", length=5, has_digits=True, score=50)

    async with session_scope() as session:
        # A 5-letter search must never be handed a 6-letter name.
        assert await repo.take_free_name(session, length=5, allow_digits=True) == "iduc9"
    async with session_scope() as session:
        # Digits off must never be handed a name carrying digits.
        assert await repo.take_free_name(session, length=5, allow_digits=False) is None
    async with session_scope() as session:
        assert await repo.take_free_name(session, length=6, allow_digits=False) == "vohuto"


async def test_stale_names_are_pruned():
    """A free name can be claimed by anybody, so old rows must go."""
    from datetime import timedelta

    from app.database.models import FreeName, utcnow

    async with session_scope() as session:
        await repo.add_free_name(session, "oldname", length=7, has_digits=False, score=50)
        row = (
            await session.execute(
                __import__("sqlalchemy").select(FreeName).where(FreeName.username == "oldname")
            )
        ).scalar_one()
        row.verified_at = utcnow() - timedelta(seconds=7200)

    async with session_scope() as session:
        removed = await repo.prune_free_names(session, older_than_seconds=3600)
    assert removed == 1

    async with session_scope() as session:
        assert await repo.count_free_names(session) == 0


# ------------------------------------------------------------------- harvesting
async def test_harvester_stores_only_names_telegram_confirmed_claimable(bot, monkeypatch):
    """Nothing reaches the stock without the authoritative "claimable" verdict.

    This is the whole point of the store: it may only ever contain names the
    same check the app itself uses has accepted. A name that merely "nobody
    owns" must not get in - that is the false "free" this bot must never emit.
    """
    monkeypatch.setattr(settings, "name_stock_harvest_seconds", 1.0)
    checker = _checker(bot)
    stock = NameStock(checker, None, rng=random.Random(3))

    # A plausible name that resolves but cannot be proven claimable.
    async def unverified(name):
        return CheckResult(
            username=name, status=CheckStatus.AVAILABLE, source="mtproto",
            detail="claimability_unverified",
        )

    checker.confirm_availability = unverified
    assert await stock.harvest_once() is None
    assert await stock.size() == 0

    # And now a genuinely claimable one.
    async def verified(name):
        return CheckResult(
            username=name, status=CheckStatus.AVAILABLE, source="mtproto",
            detail="claimability_verified",
        )

    checker.confirm_availability = verified
    stored = await stock.harvest_once()
    assert stored
    assert await stock.size() == 1


async def test_harvester_yields_to_a_live_search(bot, monkeypatch):
    """Background work must never take quota from a user who is waiting."""
    checker = _checker(bot)
    stock = NameStock(checker, None)

    class BusyQueue:
        busy = True

    class IdleQueue:
        busy = False

    async def verified(name):
        return CheckResult(
            username=name, status=CheckStatus.AVAILABLE, source="mtproto",
            detail="claimability_verified",
        )

    checker.confirm_availability = verified

    stock.attach_queue(BusyQueue())
    await stock._tick()
    assert await stock.size() == 0  # stood down

    stock.attach_queue(IdleQueue())
    await stock._tick()
    assert await stock.size() == 1  # idle, so it filled a slot


async def test_harvester_stops_at_the_target(bot, monkeypatch):
    monkeypatch.setattr(settings, "name_stock_target", 1)
    checker = _checker(bot)
    stock = NameStock(checker, None)

    async def verified(name):
        return CheckResult(
            username=name, status=CheckStatus.AVAILABLE, source="mtproto",
            detail="claimability_verified",
        )

    checker.confirm_availability = verified

    await stock._tick()
    assert await stock.size() == 1
    # Already at target: another tick must not spend any more quota.
    await stock._tick()
    assert await stock.size() == 1


# ---------------------------------------------------------------- serving a search
async def test_search_serves_a_stored_name_after_reconfirming_it(bot, monkeypatch):
    """A busy bot answers from the stock - but only after Telegram says "still
    claimable". One call instead of a whole hunt, and the same certainty."""
    monkeypatch.setattr(settings, "name_stock_target", 5)
    checker = _checker(bot)
    stock = NameStock(checker, None)

    async with session_scope() as session:
        await repo.add_free_name(session, "qabux", length=5, has_digits=False, score=60)

    calls = 0

    async def claimable(name):
        nonlocal calls
        calls += 1
        return CheckResult(
            username=name, status=CheckStatus.AVAILABLE, source="mtproto_user",
            detail="claimability_verified",
        )

    checker.confirm_availability = claimable
    finder = UsernameFinder(checker, None, rng=random.Random(1), stock=stock)

    attempt = await finder.find_one(SearchCriteria(length=5))

    assert attempt.hit is True
    assert attempt.username == "qabux"
    assert attempt.reason == "free_found"
    assert calls == 1, "serving from the stock must cost a single confirmation"
    assert await stock.size() == 0  # it was delivered, not left behind


async def test_a_stored_name_taken_meanwhile_is_never_delivered(bot, monkeypatch):
    """The central guarantee: a stale entry is thrown away, not handed over.

    A free name can be claimed by anybody at any moment, so the stored verdict
    is never trusted on its own - if Telegram no longer says "claimable", the
    name is dropped and the search carries on rather than reporting it free.
    """
    monkeypatch.setattr(settings, "name_stock_target", 5)
    checker = _checker(bot)
    stock = NameStock(checker, None)

    async with session_scope() as session:
        await repo.add_free_name(session, "qabux", length=5, has_digits=False, score=60)

    served = 0

    async def taken_now(name):
        nonlocal served
        served += 1
        if name == "qabux":
            return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")
        return CheckResult(
            username=name, status=CheckStatus.AVAILABLE, source="mtproto",
            detail="claimability_verified",
        )

    checker.confirm_availability = taken_now
    finder = UsernameFinder(checker, None, rng=random.Random(2), stock=stock)

    attempt = await finder.find_one(SearchCriteria(length=5))

    # It did not stop at the stale entry - it dropped it and hunted a real one.
    assert attempt.hit is True
    assert attempt.username != "qabux"
    assert stock.discarded == 1
    assert served > 1


async def test_a_throttled_reconfirmation_gives_the_name_back(bot, monkeypatch):
    """If the re-confirmation cannot run, the stored name is not lost."""
    monkeypatch.setattr(settings, "name_stock_target", 5)
    monkeypatch.setattr(settings, "name_stock_harvest_seconds", 1.0)
    from app.search import finder as finder_module

    monkeypatch.setattr(finder_module, "FLOOD_RETRY_PAUSE", 0.01)
    monkeypatch.setattr(finder_module, "MAX_SEARCH_SECONDS", 0.05)

    checker = _checker(bot)
    stock = NameStock(checker, None)

    async with session_scope() as session:
        await repo.add_free_name(session, "qabux", length=5, has_digits=False, score=60)

    async def always_limited(name):
        return CheckResult(
            username=name, status=CheckStatus.RATE_LIMITED,
            source="mtproto", reason="flood_wait",
        )

    checker.confirm_availability = always_limited
    finder = UsernameFinder(checker, None, rng=random.Random(4), stock=stock)

    attempt = await finder.find_one(SearchCriteria(length=5))

    assert attempt.hit is False
    # Released, not burned: it will be served once Telegram answers again.
    async with session_scope() as session:
        assert await repo.count_free_names(session) == 1


async def test_stock_disabled_is_transparent(bot):
    """NAME_STOCK_TARGET=0 must degrade to plain hunting, not break anything."""
    checker = _checker(bot)
    stock = NameStock(checker, None)

    async with session_scope() as session:
        await repo.add_free_name(session, "qabux", length=5, has_digits=False, score=60)

    stock.enabled  # property exists
    import app.config as config_module

    original = settings.name_stock_target
    try:
        settings.name_stock_target = 0
        assert stock.enabled is False
        assert await stock.take(5, True) is None
    finally:
        settings.name_stock_target = original
    assert config_module.settings is settings
