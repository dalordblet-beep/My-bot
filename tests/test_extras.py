"""Favourites, achievements, the mask sniper and the bulk parser."""

from __future__ import annotations

import time

import pytest

from app.database import repository as repo
from app.search.traps import MASK_CANDIDATES_PER_SWEEP, TrapWatcher
from app.services.achievements import AchievementStats, evaluate, summary
from app.telegram import username_checker as uc_module
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus, CollectibleStatus
from app.utils.results import CollectibleResult
from tests.mock_telegram import FakePageProbe, make_update_callback, make_update_message


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


# --------------------------------------------------------------------------- achievements
def test_every_achievement_starts_locked():
    items = evaluate(AchievementStats())
    assert items
    assert not any(item.unlocked for item in items)
    assert all(item.progress == 0 for item in items)


def test_achievements_unlock_from_real_counters():
    stats = AchievementStats(free_found=10, traps_created=1, battles=2, battles_won=1)
    items = {item.code: item for item in evaluate(stats)}
    assert items["first_find"].unlocked
    assert items["ten_finds"].unlocked
    assert not items["fifty_finds"].unlocked
    assert items["fifty_finds"].progress == 10
    assert items["first_trap"].unlocked
    assert items["battle_win"].unlocked
    done, total = summary(stats)
    assert 0 < done < total


def test_progress_never_exceeds_the_target():
    items = evaluate(AchievementStats(free_found=999, checks=10_000))
    assert all(0 <= item.percent <= 100 for item in items)


# --------------------------------------------------------------------------- favourites
async def test_favorite_add_list_and_remove(session, mock_session):
    user, _ = await repo.get_or_create_user(session, 9001, username="favuser")
    await session.commit()

    _row, created = await repo.add_favorite(session, user, "@Moged", score=100)
    assert created is True
    await session.commit()

    # Adding again is idempotent, not a duplicate.
    _row, created_again = await repo.add_favorite(session, user, "moged", score=90)
    assert created_again is False
    assert await repo.count_favorites(session, 9001) == 1

    rows = list(await repo.list_favorites(session, user))
    assert len(rows) == 1
    assert rows[0].username == "moged"
    assert rows[0].score == 100

    assert await repo.remove_favorite(session, user, rows[0].id) is True
    await session.commit()
    assert await repo.count_favorites(session, 9001) == 0


async def test_favorites_are_per_user(session):
    first, _ = await repo.get_or_create_user(session, 9002, username="a")
    second, _ = await repo.get_or_create_user(session, 9003, username="b")
    await session.commit()

    await repo.add_favorite(session, first, "moged")
    await session.commit()

    assert await repo.count_favorites(session, 9002) == 1
    assert await repo.count_favorites(session, 9003) == 0
    assert list(await repo.list_favorites(session, second)) == []


# --------------------------------------------------------------------------- mask sniper
async def test_mask_trap_generates_and_reports_a_free_name(session, bot, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    user, _ = await repo.get_or_create_user(session, 9004, username="sniper")
    await session.commit()

    trap, created = await repo.create_trap(session, user, "???dev", kind="mask")
    await session.commit()
    assert created is True
    assert trap.kind == "mask"

    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, reply_markup=None):
            sent.append((chat_id, text))

    watcher = TrapWatcher(FakeBot(), checker, per_check_delay=0.0)
    fired = await watcher.sweep()

    assert fired == 1
    assert len(sent) == 1
    chat_id, text = sent[0]
    assert chat_id == 9004
    assert "dev" in text

    # The trap deactivates itself so a restart cannot notify twice.
    # The watcher commits in its own session, so expire ours before reading.
    trap_id = trap.id
    session.expire_all()
    fresh = await repo.get_trap(session, trap_id)
    assert fresh.active is False
    assert fresh.notified_at is not None


async def test_mask_trap_with_an_impossible_mask_is_deactivated(session, bot):
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    user, _ = await repo.get_or_create_user(session, 9005, username="badmask")
    await session.commit()

    trap, _ = await repo.create_trap(session, user, "??? dev!", kind="mask")
    await session.commit()

    watcher = TrapWatcher(None, checker, per_check_delay=0.0)
    fired = await watcher.sweep()

    assert fired == 0
    trap_id = trap.id
    session.expire_all()
    fresh = await repo.get_trap(session, trap_id)
    assert fresh.last_status == "invalid_mask"
    assert MASK_CANDIDATES_PER_SWEEP >= 1


async def test_name_trap_still_works(session, bot, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    user, _ = await repo.get_or_create_user(session, 9006, username="nametrap")
    await session.commit()

    trap, _ = await repo.create_trap(session, user, "moged", kind="name")
    await session.commit()

    sent: list[str] = []

    class FakeBot:
        async def send_message(self, chat_id, text, reply_markup=None):
            sent.append(text)

    watcher = TrapWatcher(FakeBot(), checker, per_check_delay=0.0)
    assert await watcher.sweep() == 1
    assert sent and "moged" in sent[0]
    assert "USERNAME IS FREE" in sent[0]

    trap_id = trap.id
    session.expire_all()
    fresh = await repo.get_trap(session, trap_id)
    assert fresh.active is False


# --------------------------------------------------------------------------- stats
async def test_achievement_counters_read_real_rows(session):
    user, _ = await repo.get_or_create_user(session, 9007, username="counts")
    await session.commit()

    await repo.record_username_check(
        session, username="freeone", status=CheckStatus.AVAILABLE.value,
        type_="basic", source="test",
    )
    await repo.record_username_check(
        session, username="takenone", status=CheckStatus.OCCUPIED.value,
        type_="basic", source="test",
    )
    await session.commit()

    assert await repo.count_checks_by_status(session, CheckStatus.AVAILABLE.value) == 1
    assert "freeone" in list(await repo.recent_available_usernames(session))


# --------------------------------------------------------------------------- scheduling
class CountingChecker:
    """Counts how many times each name was looked up.

    A trap on a plain name asks for ``check_for_release``, not for a one-shot
    check: a release watch is allowed to trust the public page even when strict
    availability is off. Both entry points are recorded so the schedule tests
    see every lookup regardless of which one the watcher picks.
    """

    def __init__(self, status: CheckStatus = CheckStatus.OCCUPIED) -> None:
        self.status = status
        self.calls: list[str] = []

    async def check_basic_username(self, username, use_cache: bool = True):
        return await self._record(username)

    async def check_for_release(self, username):
        return await self._record(username)

    async def _record(self, username: str):
        from app.utils.results import CheckResult

        self.calls.append(username)
        return CheckResult(username=username, status=self.status, source="test")


class RecordingBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))


async def test_a_new_trap_is_checked_on_the_next_tick(session):
    """The bug: a trap created just after a sweep waited a full interval.

    With per-trap scheduling a trap with no recorded due time is due
    immediately, so the first check happens on the very next tick.
    """
    user, _ = await repo.get_or_create_user(session, 8100, username="sched")
    await session.commit()
    await repo.create_trap(session, user, "moged")
    await session.commit()

    checker = CountingChecker()
    watcher = TrapWatcher(RecordingBot(), checker, interval=600.0, per_check_delay=0.0)

    assert await watcher.sweep() == 0
    assert checker.calls == ["moged"], "a brand new trap was not checked immediately"


async def test_a_trap_is_not_rechecked_within_the_interval(session):
    """Gentle by design: one lookup per trap per interval, not per tick."""
    user, _ = await repo.get_or_create_user(session, 8101, username="sched2")
    await session.commit()
    await repo.create_trap(session, user, "moged")
    await session.commit()

    checker = CountingChecker()
    watcher = TrapWatcher(RecordingBot(), checker, interval=600.0, per_check_delay=0.0)

    await watcher.sweep()
    for _ in range(5):
        await watcher.sweep()

    assert checker.calls == ["moged"], f"trap was rechecked too often: {checker.calls}"


async def test_force_bypasses_the_schedule(session):
    user, _ = await repo.get_or_create_user(session, 8102, username="sched3")
    await session.commit()
    await repo.create_trap(session, user, "moged")
    await session.commit()

    checker = CountingChecker()
    watcher = TrapWatcher(RecordingBot(), checker, interval=600.0, per_check_delay=0.0)

    await watcher.sweep()
    await watcher.sweep(force=True)
    await watcher.sweep(force=True)

    assert checker.calls == ["moged", "moged", "moged"]


async def test_a_deactivated_trap_stops_being_checked(session):
    user, _ = await repo.get_or_create_user(session, 8103, username="sched4")
    await session.commit()
    trap, _ = await repo.create_trap(session, user, "moged")
    await session.commit()

    checker = CountingChecker()
    watcher = TrapWatcher(RecordingBot(), checker, interval=0.0, per_check_delay=0.0)
    await watcher.sweep()
    assert checker.calls == ["moged"]

    await repo.deactivate_trap(session, user, trap.id)
    await session.commit()

    await watcher.sweep(force=True)
    assert checker.calls == ["moged"], "a removed trap was still being polled"


async def test_the_interval_has_a_floor(session):
    """A zero interval would hammer the API."""
    watcher = TrapWatcher(RecordingBot(), CountingChecker(), interval=0.0)
    assert watcher._interval >= 15


def test_default_watch_cadence_is_fast_with_a_short_scheduler_tick():
    watcher = TrapWatcher(RecordingBot(), CountingChecker())
    assert watcher._interval == 15.0
    assert watcher._tick == 1.0


async def test_due_watches_are_spaced_instead_of_bursting(session):
    first, _ = await repo.get_or_create_user(session, 8111, username="paced1")
    second, _ = await repo.get_or_create_user(session, 8112, username="paced2")
    await session.commit()
    await repo.create_trap(session, first, "firstname")
    await repo.create_trap(session, second, "secondname")
    await session.commit()

    watcher = TrapWatcher(
        RecordingBot(), CountingChecker(), interval=15.0, per_check_delay=0.02
    )
    started = time.perf_counter()
    await watcher.sweep()
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.015, "due username checks were not globally paced"


async def test_notification_is_sent_the_moment_the_name_frees(session):
    user, _ = await repo.get_or_create_user(session, 8104, username="sched5")
    await session.commit()
    await repo.create_trap(session, user, "moged")
    await session.commit()

    bot = RecordingBot()
    checker = CountingChecker(status=CheckStatus.AVAILABLE)
    watcher = TrapWatcher(bot, checker, interval=600.0, per_check_delay=0.0)

    fired = await watcher.sweep()

    assert fired == 1
    assert len(bot.sent) == 1
    chat_id, text = bot.sent[0]
    assert chat_id == 8104
    assert "moged" in text

    trap_id = (await repo.list_traps(session, user))[0].id
    session.expire_all()
    fresh = await repo.get_trap(session, trap_id)
    assert fresh.active is False
    assert fresh.notified_at is not None
    assert fresh.last_checked_at is not None


# --------------------------------------------------------------------------- release path
async def test_release_uses_the_public_page_without_mtproto():
    """Regression for "the trap still does not work".

    The public preview page answers "is this name owned?" for every kind of
    owner and needs no MTProto user session. ``check_for_release`` must use it
    directly, so a bot-only deployment can actually detect a release.
    """
    from app.telegram.public_page import PublicPageResult
    from app.telegram.username_checker import UsernameChecker

    class Probe:
        def __init__(self, result):
            self._result = result
            self.calls: list[str] = []

        async def check(self, username):
            self.calls.append(username)
            return self._result

        async def close(self):
            pass

    free_probe = Probe(PublicPageResult("free", reason="no_profile_card"))
    checker = UsernameChecker(cache=None, bot=None, page_probe=free_probe)
    result = await checker.check_for_release("moged")
    assert result.status is CheckStatus.AVAILABLE
    assert result.source == "public_page"

    taken_probe = Probe(PublicPageResult("occupied", title="Someone"))
    checker = UsernameChecker(cache=None, bot=None, page_probe=taken_probe)
    result = await checker.check_for_release("moged")
    assert result.status is CheckStatus.OCCUPIED


async def test_the_watcher_reports_a_release_via_the_public_page(session):
    """End to end: a trap fires with no MTProto and no Bot API at all."""
    from app.telegram.public_page import PublicPageResult
    from app.telegram.username_checker import UsernameChecker

    class Probe:
        async def check(self, username):
            return PublicPageResult("free", reason="no_profile_card")

        async def close(self):
            pass

    user, _ = await repo.get_or_create_user(session, 8110, username="pubtrap")
    await session.commit()
    await repo.create_trap(session, user, "moged")
    await session.commit()

    bot = RecordingBot()
    checker = UsernameChecker(cache=None, bot=None, page_probe=Probe())
    watcher = TrapWatcher(bot, checker, interval=600.0, per_check_delay=0.0)

    assert await watcher.sweep() == 1
    assert len(bot.sent) == 1
    assert bot.sent[0][0] == 8110
    assert "moged" in bot.sent[0][1]


# --------------------------------------------------------------------------- collectible traps
class FakeCollectibleChecker:
    """Answers a collectible lookup with whatever the test decides."""

    def __init__(self, status: CollectibleStatus, price: str | None = None) -> None:
        self.status = status
        self.price = price
        self.calls: list[str] = []

    async def check_collectible_username(self, username: str):
        self.calls.append(username)
        return CollectibleResult(
            username=username, status=self.status, is_collectible=True, price=self.price
        )


async def _collectible_trap(session, user_id: int, name: str = "moged"):
    user, _ = await repo.get_or_create_user(session, user_id, username=f"c{user_id}")
    await session.commit()
    trap, _ = await repo.create_trap(session, user, name, kind="collectible")
    await session.commit()
    return trap


async def test_a_collectible_trap_fires_once_and_says_the_right_thing(session):
    """Regression: the watcher used to send the alert and then a second, wrong
    "the name is free" message, because the generic notify ran after the
    collectible one.
    """
    await _collectible_trap(session, 8200)
    bot = RecordingBot()
    collectible = FakeCollectibleChecker(CollectibleStatus.LISTED, price="1500 TON")
    watcher = TrapWatcher(
        bot, CountingChecker(), collectible, interval=600.0, per_check_delay=0.0
    )

    assert await watcher.sweep() == 1
    assert len(bot.sent) == 1, f"expected one message, got {[t for _, t in bot.sent]}"

    _chat_id, text = bot.sent[0]
    assert "1500 TON" in text
    assert "moged" in text


async def test_a_collectible_trap_does_not_repeat_the_same_state(session):
    """It watches for a change, so an unchanged listing is silent."""
    await _collectible_trap(session, 8201)
    bot = RecordingBot()
    collectible = FakeCollectibleChecker(CollectibleStatus.LISTED, price="900 TON")
    watcher = TrapWatcher(
        bot, CountingChecker(), collectible, interval=0.0, per_check_delay=0.0
    )

    assert await watcher.sweep() == 1
    assert await watcher.sweep(force=True) == 0
    assert len(bot.sent) == 1
    assert collectible.calls == ["moged", "moged"]


async def test_merely_being_owned_is_not_an_alert(session):
    """Every collectible has an owner.

    Alerting on OWNED made the trap fire on its first sweep for every watch the
    user set, announcing "listed for sale" about a name that was not for sale.
    """
    await _collectible_trap(session, 8203)
    bot = RecordingBot()
    collectible = FakeCollectibleChecker(CollectibleStatus.OWNED, price="11,000 TON")
    watcher = TrapWatcher(
        bot, CountingChecker(), collectible, interval=0.0, per_check_delay=0.0
    )

    assert await watcher.sweep() == 0
    assert bot.sent == []


async def test_a_price_change_on_a_listing_is_an_alert(session):
    await _collectible_trap(session, 8204)
    bot = RecordingBot()
    collectible = FakeCollectibleChecker(CollectibleStatus.LISTED, price="900 TON")
    watcher = TrapWatcher(
        bot, CountingChecker(), collectible, interval=0.0, per_check_delay=0.0
    )

    assert await watcher.sweep() == 1
    collectible.price = "750 TON"
    assert await watcher.sweep(force=True) == 1
    assert len(bot.sent) == 2
    assert "750 TON" in bot.sent[1][1]


async def test_a_collectible_trap_stays_silent_while_the_answer_is_unknown(session):
    """UNKNOWN is not news. Reporting it would be a guess dressed as an alert."""
    await _collectible_trap(session, 8202)
    bot = RecordingBot()
    collectible = FakeCollectibleChecker(CollectibleStatus.UNKNOWN)
    watcher = TrapWatcher(
        bot, CountingChecker(), collectible, interval=0.0, per_check_delay=0.0
    )

    assert await watcher.sweep() == 0
    assert bot.sent == []


async def test_username_watch_is_created_and_manual_check_notifies(
    dispatcher, bot, mock_session, session, checker
):
    """The dedicated Watch flow creates an exact watch and fires a clear alert."""
    from tests.test_ui_flow import _ready

    user_id = 8300
    await _ready(session, mock_session, user_id)

    await dispatcher.feed_update(bot, make_update_callback(user_id, "menu:watch"))
    assert "USERNAME ALERTS" in mock_session.last_edited_text()

    await dispatcher.feed_update(bot, make_update_callback(user_id, "watch:add"))
    assert "ADD USERNAME WATCH" in mock_session.last_sent_text()

    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_message(user_id, "@Moged"))
    assert "Watching @moged" in mock_session.last_sent_text()

    user = await repo.get_user_by_telegram_id(session, user_id)
    watches = list(await repo.list_traps(session, user))
    assert len(watches) == 1
    watch_id = watches[0].id
    assert watches[0].kind == "name"
    assert watches[0].username == "moged"
    assert watches[0].active is True

    mock_session.reset()
    await dispatcher.feed_update(
        bot, make_update_callback(user_id, f"watch:check:{watch_id}")
    )
    sent_text = "\n".join(item["text"] for item in mock_session.messages)
    assert "USERNAME IS FREE" in sent_text
    assert "@moged" in sent_text

    session.expire_all()
    updated = await repo.get_trap(session, watch_id)
    assert updated.active is False
    assert updated.notified_at is not None
