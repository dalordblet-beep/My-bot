"""Feature tests for the user-requested additions.

These pin the behaviour of the three initiatives the user asked for:

* the rebuilt rating rubric (grades, length-aware ceiling, position-aware
  digit/symbol scoring, strength/weakness);
* the variants search - free alternatives to a taken seed;
* the Daily Drop digest - one search a day, enqueued through the same queue.

The keyboard *contract* (styles, icons, callback size) is covered separately in
``test_keyboards.py``; here we assert the feature-specific logic and the wiring
through the live dispatcher and the search queue.
"""

from __future__ import annotations

import asyncio

import pytest
from aiogram import Bot, Dispatcher

from app.bot.keyboards import callbacks as cb
from app.bot.keyboards.features_kb import claim_kit_keyboard, variants_keyboard
from app.config import settings
from app.database import repository as repo
from app.database.database import session_scope
from app.search.finder import (
    SearchCriteria,
    TARGET_VARIANTS,
    FindAttempt,
    UsernameFinder,
)
from app.search.pattern import (
    PART_MAX,
    best_possible,
    digits_score,
    grade_for,
    rate,
    symbols_score,
)
from app.services.daily_drop import DailyDropService
from app.telegram import username_checker as uc_module
from app.telegram.username_checker import UsernameChecker
from tests.mock_telegram import FakePageProbe, make_update_callback, make_update_message


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


# --------------------------------------------------------------------------- rubric
def test_grade_bands_are_disjoint_and_ordered():
    """S at 90, A at 80, B at 65, C at 45, D below - no gaps, no overlaps."""
    assert grade_for(100) == "S"
    assert grade_for(90) == "S"
    assert grade_for(89) == "A"
    assert grade_for(80) == "A"
    assert grade_for(79) == "B"
    assert grade_for(65) == "B"
    assert grade_for(64) == "C"
    assert grade_for(45) == "C"
    assert grade_for(44) == "D"
    assert grade_for(0) == "D"


def test_rating_total_is_the_sum_of_its_parts_and_bounded():
    for name in ("crane", "moged", "shop7", "a_b_c", "xqzwtf", ""):
        rating = rate(name)
        assert 0 <= rating.total <= 100
        assert rating.total == sum(rating.parts.values())
        assert set(rating.parts) == set(PART_MAX)


def test_a_real_short_word_fills_its_length_ceiling():
    """A five-letter dictionary word is the best a 5-char name can be."""
    rating = rate("crane")
    assert rating.total == 97
    assert rating.grade == "S"
    assert rating.ceiling == best_possible(5) == 97
    # It reaches the whole of what a 5-letter name can score.
    assert rating.fill == 100
    # "crane" means something (word part full) and is the right length.
    assert rating.strength in ("word", "length")
    # A perfect name (every part at its ceiling) has no weakness.
    assert rating.weakness is None


def test_digit_scoring_is_position_aware():
    """One trailing digit is tolerated; a leading one costs more; a run kills it."""
    assert digits_score("shop") == PART_MAX["digits"]           # no digit
    assert digits_score("shop7") == 11                          # single, trailing
    assert digits_score("7shop") == 7                           # single, leading
    assert digits_score("shop77") == 4                           # two digits
    assert digits_score("shop7777") == 0                         # run of digits


def test_symbol_scoring_is_position_aware():
    """An interior underscore is fine; a trailing one is worse; three kills it."""
    assert symbols_score("abcde") == PART_MAX["separators"]      # no symbol
    assert symbols_score("ab_cd") == 6                           # one, interior
    assert symbols_score("abc_") == 4                            # one, trailing
    assert symbols_score("a_b_c") == 2                           # two
    assert symbols_score("a_b_c_d") == 0                         # three


def test_a_name_with_a_weak_part_reports_it():
    """A coinage with a digit is not a word - that is what caps its score."""
    rating = rate("shop7")
    assert rating.weakness == "word"
    assert rating.strength == "length"


# --------------------------------------------------------------------------- variants finder
async def _variants_finder(bot, monkeypatch):
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    return UsernameFinder(checker, None)


async def test_variants_returns_free_alternatives(bot, monkeypatch):
    """Given a taken seed, screen+confirm produces a shortlist of free names."""
    finder = await _variants_finder(bot, monkeypatch)
    attempt = await finder.find_one(SearchCriteria(target=TARGET_VARIANTS, seed="crane"))

    assert attempt.reason == "variants"
    assert attempt.seed == "crane"
    assert attempt.hit is False
    assert isinstance(attempt.variants, list)
    assert len(attempt.variants) > 0
    for variant in attempt.variants:
        assert isinstance(variant, FindAttempt)
        assert variant.hit is True
        assert variant.username
        assert variant.premium.total > 0
    # The search actually looked at candidates.
    assert attempt.generated_tries > 0


async def test_variants_never_includes_the_seed_itself(bot, monkeypatch):
    finder = await _variants_finder(bot, monkeypatch)
    attempt = await finder.find_one(SearchCriteria(target=TARGET_VARIANTS, seed="crane"))

    assert attempt.reason == "variants"
    names = [v.username for v in attempt.variants]
    assert "crane" not in names


async def test_variants_rejects_a_too_short_seed(bot, monkeypatch):
    finder = await _variants_finder(bot, monkeypatch)
    attempt = await finder.find_one(SearchCriteria(target=TARGET_VARIANTS, seed="ab"))

    assert attempt.hit is False
    assert attempt.reason == "variants_invalid"
    assert attempt.variants is None


async def test_variants_respects_the_screening_cap(bot, monkeypatch):
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    monkeypatch.setattr(finder_module, "VARIANT_SCREEN_CAP", 7)
    monkeypatch.setattr(finder_module, "VARIANT_CONFIRM_BUDGET", 20)
    probe = FakePageProbe(state="free")
    checker = UsernameChecker(cache=None, bot=bot, page_probe=probe)
    confirmations = 0

    async def occupied(name):
        nonlocal confirmations
        confirmations += 1
        return CheckResult(username=name, status=CheckStatus.OCCUPIED, source="mtproto")

    checker.confirm_availability = occupied
    attempt = await UsernameFinder(checker, None).find_one(
        SearchCriteria(target=TARGET_VARIANTS, seed="crane")
    )

    assert attempt.reason == "variants"
    assert attempt.generated_tries == 7
    assert len(probe.calls) == 7
    assert confirmations == 7


async def test_variants_stops_on_flood_wait(bot, monkeypatch):
    from app.search import finder as finder_module
    from app.utils.enums import CheckStatus
    from app.utils.results import CheckResult

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    monkeypatch.setattr(finder_module, "VARIANT_CONFIRM_BUDGET", 20)
    checker = UsernameChecker(cache=None, bot=bot, page_probe=FakePageProbe(state="free"))
    confirmations = 0

    async def throttled(name):
        nonlocal confirmations
        confirmations += 1
        return CheckResult(
            username=name, status=CheckStatus.RATE_LIMITED,
            source="mtproto", reason="flood_wait",
        )

    checker.confirm_availability = throttled
    attempt = await UsernameFinder(checker, None).find_one(
        SearchCriteria(target=TARGET_VARIANTS, seed="crane")
    )

    assert attempt.reason == "variants"
    assert confirmations == 1
    assert attempt.variants == []


# --------------------------------------------------------------------------- daily drop
async def test_daily_drop_subscribers_are_filtered(session):
    """Only enabled, non-banned users are returned, with their language."""
    sub, _ = await repo.get_or_create_user(session, 9001, username="sub")
    banned, _ = await repo.get_or_create_user(session, 9002, username="banned")
    ghost, _ = await repo.get_or_create_user(session, 9003, username="ghost")
    await repo.update_user_settings(session, sub.id, daily_drop=True, language="ru")
    await repo.update_user_settings(session, banned.id, daily_drop=True, language="en")
    await repo.ban_user(session, banned, reason="test", admin_id=9001)
    await session.commit()

    subs = await repo.list_daily_drop_subscribers(session)
    by_id = {tg: lang for tg, lang in subs}

    assert 9001 in by_id
    assert by_id[9001] == "ru"
    assert 9002 not in by_id          # banned - excluded
    assert 9003 not in by_id          # not subscribed - excluded


async def test_daily_drop_sweep_enqueues_once_per_subscriber(session, search_queue, bot):
    """A forced sweep enqueues exactly one search and stamps the subscriber."""
    sub, _ = await repo.get_or_create_user(session, 9100, username="dailysub")
    await repo.update_user_settings(
        session, sub.id, daily_drop=True, language="en",
        search_length=6, search_digits=False,
    )
    await session.commit()

    service = DailyDropService(bot, search_queue, hour=9, tick=900.0)
    before = search_queue.pending

    delivered = await service.sweep(force=True)

    assert delivered == 1
    assert search_queue.pending == before + 1

    # The stamp is what guarantees at most one drop per day.
    async with session_scope() as s2:
        row = await repo.get_user_settings(s2, sub.id)
        assert row.daily_drop_last is not None

    # A second forced sweep on the same day delivers nothing - already dropped.
    assert await service.sweep(force=True) == 0


async def test_daily_drop_sweep_is_a_noop_with_no_subscribers(session, search_queue, bot):
    service = DailyDropService(bot, search_queue)
    assert await service.sweep(force=True) == 0
    assert search_queue.pending == 0


# --------------------------------------------------------------------------- command + callback
async def _ready(session, mock) -> int:
    from aiogram.enums import ChatMemberStatus

    user_id = 7100
    mock.memberships[("@test_channel", user_id)] = ChatMemberStatus.MEMBER
    mock.memberships[("@test_chat", user_id)] = ChatMemberStatus.MEMBER
    user, _ = await repo.get_or_create_user(session, user_id, username="u7100")
    await repo.update_user_settings(session, user.id, language="en")
    await repo.set_captcha_verified(session, user)
    await repo.set_channel_verified(session, user)
    await repo.set_chat_verified(session, user)
    await session.commit()
    return user_id


async def test_variants_command_queues_a_search(dispatcher, bot, mock_session, session, monkeypatch):
    """/variants must acknowledge at once (queued) and enqueue one job."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    user_id = await _ready(session, mock_session)
    mock_session.reset()

    await dispatcher.feed_update(bot, make_update_message(user_id, "/variants crane"))

    visible = mock_session.last_sent_text() + "\n" + mock_session.last_edited_text()
    assert "variant" in visible.lower()
    assert dispatcher.get("search_queue").pending == 1


async def test_variants_callback_enqueues_and_edits_in_place(
    dispatcher, bot, mock_session, session, monkeypatch
):
    """The "Variants" button on a result must re-hunt without leaving the message."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    user_id = await _ready(session, mock_session)
    mock_session.reset()

    await dispatcher.feed_update(
        bot, make_update_callback(user_id, f"{cb.FIND_VARIANTS_PREFIX}:crane")
    )

    visible = mock_session.last_sent_text() + "\n" + mock_session.last_edited_text()
    assert "variant" in visible.lower()
    assert dispatcher.get("search_queue").pending == 1


async def test_queue_worker_delivers_variants_result(
    dispatcher, bot, mock_session, session, search_queue, monkeypatch
):
    """End to end: a variants job runs and lands its shortlist in the message."""
    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    user_id = await _ready(session, mock_session)

    search_queue.start()
    try:
        mock_session.reset()
        await dispatcher.feed_update(
            bot, make_update_message(user_id, "/variants crane")
        )
        for _ in range(200):
            if search_queue.done:
                break
            await asyncio.sleep(0.05)
        assert search_queue.done == 1
    finally:
        await search_queue.stop()

    text = mock_session.last_edited_text().upper()
    assert "VARIANT" in text


# --------------------------------------------------------------------------- keyboards
def test_claim_kit_keyboard_open_url_and_actions():
    markup = claim_kit_keyboard("en", "love", 5)
    buttons = [b for row in markup.inline_keyboard for b in row]

    open_btn = next(b for b in buttons if b.url)
    assert open_btn.url == "https://t.me/love"
    assert open_btn.style == "success"

    save_btn = next(b for b in buttons if b.callback_data and b.callback_data.startswith(cb.FAV_ADD_PREFIX))
    assert "love" in save_btn.callback_data
    assert save_btn.callback_data.endswith(":5")
    assert save_btn.style == "primary"

    variants_btn = next(b for b in buttons if b.callback_data and b.callback_data.startswith(cb.FIND_VARIANTS_PREFIX))
    assert variants_btn.callback_data.endswith("love")
    assert variants_btn.style == "primary"

    new_btn = next(b for b in buttons if b.callback_data == cb.MENU_SEARCH_ENGINE)
    assert new_btn.style is None          # NEUTRAL renders as no style

    styles = {b.style for b in buttons}
    assert styles <= {"primary", "success", "danger", None}


def test_variants_keyboard_reroll_and_exit():
    markup = variants_keyboard("en", "love")
    buttons = [b for row in markup.inline_keyboard for b in row]

    new_btn = next(b for b in buttons if b.callback_data == cb.MENU_SEARCH_ENGINE)
    assert new_btn.style == "primary"

    reroll = next(b for b in buttons if b.callback_data and b.callback_data.startswith(cb.FIND_VARIANTS_PREFIX))
    assert reroll.callback_data.endswith("love")
    assert reroll.style is None            # NEUTRAL

    home = next(b for b in buttons if b.callback_data == cb.MENU_HOME)
    assert home.style is None              # NEUTRAL
