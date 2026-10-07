"""Every menu button must actually do something.

This is the smoke test that would have caught the reported bugs: a button whose
callback no handler matches does nothing at all, and nothing in the rest of the
suite notices because no other test presses it.

It walks the whole reachable UI and asserts that each press produces a visible
screen (or an explanatory toast), never silence.
"""

from __future__ import annotations

import asyncio

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatMemberStatus

from app.database import repository as repo
from app.services.captcha import CaptchaService
from app.telegram import username_checker as uc_module
from tests.mock_telegram import (
    MockTelegramSession,
    make_update_callback,
    make_update_message,
)

USER = 7100
CHANNEL = "@test_channel"
CHAT = "@test_chat"


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


async def _ready(session, mock: MockTelegramSession, user_id: int = USER) -> None:
    mock.memberships[(CHANNEL, user_id)] = ChatMemberStatus.MEMBER
    mock.memberships[(CHAT, user_id)] = ChatMemberStatus.MEMBER
    user, _ = await repo.get_or_create_user(session, user_id, username=f"u{user_id}")
    await repo.update_user_settings(session, user.id, language="en")
    await repo.set_captcha_verified(session, user)
    await repo.set_channel_verified(session, user)
    await repo.set_chat_verified(session, user)
    await session.commit()


async def _make_admin(session, user_id: int) -> None:
    from app.utils.enums import Privilege

    repo_ = repo
    user, _ = await repo_.get_or_create_user(session, user_id, username=f"u{user_id}")
    await repo_.set_privilege(session, user, Privilege.ADMIN)
    await session.commit()


async def press(dispatcher: Dispatcher, bot: Bot, mock: MockTelegramSession, data: str) -> str:
    """Press a button and return whatever became visible."""
    mock.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, data))
    return mock.last_edited_text() or mock.last_sent_text()


# Every top-level entry and every sub-button the user can reach in one or two taps.
MENU_BUTTONS = [
    ("menu:find", "SEARCH"),
    ("menu:watch", "USERNAME ALERTS"),
    ("menu:profile", "PROFILE"),
    ("menu:battle", "BATTLE"),
    ("menu:support", "SUPPORT"),
    ("menu:settings", "SETTINGS"),
    ("menu:history", "HISTORY"),
    ("menu:home", "SCANNER"),
]

SEARCH_BUTTONS = [
    ("find:len:menu", "LENGTH"),
    ("find:len:10", "SEARCH"),
    ("find:dig:1", "SEARCH"),
    ("find:dig:0", "SEARCH"),
    ("find:filter", "FILTER"),
    ("find:clear", "SEARCH"),
    ("menu:bulk", "LIST"),
    ("menu:top", "TOP"),
    ("menu:fav", "FAVOURITE"),
]

BATTLE_BUTTONS = [
    ("battle:manual", "YOUR USERNAME"),
    ("battle:challenge", "CHALLENGE"),
]

SUPPORT_BUTTONS = [
    ("support:faq", "FAQ"),
]

PROFILE_BUTTONS = [
    ("menu:ach", "ACHIEVEMENTS"),
]


@pytest.mark.parametrize("data,expect", MENU_BUTTONS + SEARCH_BUTTONS)
async def test_search_ui_buttons_all_respond(dispatcher, bot, mock_session, session, data, expect):
    await _ready(session, mock_session)
    text = await press(dispatcher, bot, mock_session, data)
    assert expect.upper() in text.upper(), f"{data} produced: {text[:200]!r}"


@pytest.mark.parametrize("data,expect", BATTLE_BUTTONS + SUPPORT_BUTTONS + PROFILE_BUTTONS)
async def test_feature_buttons_all_respond(dispatcher, bot, mock_session, session, data, expect):
    await _ready(session, mock_session)
    text = await press(dispatcher, bot, mock_session, data)
    assert expect.upper() in text.upper(), f"{data} produced: {text[:200]!r}"


async def test_achievements_button_is_a_plain_label(dispatcher, bot, mock_session, session):
    """Regression: the label was a full message template, so it rendered raw markup."""
    from app.bot.keyboards.features_kb import profile_keyboard

    for lang in ("en", "ru"):
        markup = profile_keyboard(lang)
        for button in (b for row in markup.inline_keyboard for b in row):
            assert "<" not in button.text, f"button label contains markup: {button.text!r}"
            assert "tg-emoji" not in button.text
            assert "{" not in button.text, f"unformatted placeholder: {button.text!r}"


async def test_every_button_label_is_plain_text():
    """No keyboard anywhere may put HTML or a template into a button label."""
    from tests.test_keyboards import _every_keyboard
    from app.services.i18n import TRANSLATIONS

    for lang in TRANSLATIONS:
        for name, markup in _every_keyboard(lang).items():
            for row in markup.inline_keyboard:
                for button in row:
                    assert "<" not in button.text, f"{name}: {button.text!r}"
                    assert "{" not in button.text, f"{name}: {button.text!r}"
                    assert "tg-emoji" not in button.text, f"{name}: {button.text!r}"


async def test_search_run_answers_at_once_with_a_queue_position(
    dispatcher, bot, mock_session, session, monkeypatch
):
    """Pressing Run must not block on Telegram pacing.

    The search is rate-limited to a safe ~20 calls/min, so doing the work inline
    would leave the user staring at a spinner for up to half a minute. The
    handler acknowledges the job instead and the worker delivers later.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await _ready(session, mock_session)

    await press(dispatcher, bot, mock_session, "menu:find")
    text = await press(dispatcher, bot, mock_session, "find:run")

    assert "QUEUED" in text.upper()


async def test_queue_worker_delivers_the_result_into_the_same_message(
    dispatcher, bot, mock_session, session, search_queue, monkeypatch
):
    """The queued job must actually run and land where the user is looking."""
    from app.config import settings

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await _ready(session, mock_session)

    search_queue.start()
    try:
        await press(dispatcher, bot, mock_session, "menu:find")
        await press(dispatcher, bot, mock_session, "find:run")

        for _ in range(100):
            if search_queue.done:
                break
            await asyncio.sleep(0.05)
        assert search_queue.done == 1
    finally:
        await search_queue.stop()

    # The result replaced the "queued" text in the very same message.
    assert "RESULT" in mock_session.last_edited_text().upper()


async def test_queue_does_not_duplicate_an_identical_pending_search(
    dispatcher, bot, mock_session, session, search_queue, monkeypatch
):
    """Pressing Run twice must not queue the same work twice."""
    from app.config import settings

    monkeypatch.setattr(settings, "allow_bot_api_availability", True)
    await _ready(session, mock_session)

    await press(dispatcher, bot, mock_session, "menu:find")
    await press(dispatcher, bot, mock_session, "find:run")
    assert search_queue.pending == 1

    # Same user, same criteria - already waiting.
    await press(dispatcher, bot, mock_session, "find:run")
    assert search_queue.pending == 1


# --------------------------------------------------------------------------- battle
async def test_challenge_posts_into_the_chosen_chat(dispatcher, bot, mock_session, session):
    """The challenge must land in the chat the user picked, with an accept button."""
    from tests.mock_telegram import make_update_chat_shared

    await _ready(session, mock_session)
    user = await repo.get_user_by_telegram_id(session, USER)
    user.username = "challenger"
    await session.commit()

    mock_session.reset()
    await dispatcher.feed_update(
        bot, make_update_callback(USER, "battle:challenge", username="challenger")
    )

    # A reply keyboard carrying Telegram's native chat picker.
    markup = mock_session.messages[-1]["reply_markup"]
    buttons = markup["keyboard"][0]
    assert buttons[0]["request_chat"]["bot_is_member"] is True
    assert buttons[0]["request_chat"]["chat_is_channel"] is False

    mock_session.reset()
    await dispatcher.feed_update(
        bot, make_update_chat_shared(USER, -100999, username="challenger")
    )

    posted = [m for m in mock_session.messages if m["chat_id"] == -100999]
    assert posted, "the challenge was not posted into the chosen chat"
    assert "challenger" in posted[0]["text"]

    keyboard = posted[0]["reply_markup"]["inline_keyboard"][0][0]
    assert keyboard["callback_data"].startswith("battle:accept:")


async def test_accepting_a_challenge_runs_the_battle(
    dispatcher, bot, mock_session, session, monkeypatch
):
    """Anyone can accept, and the comparison runs once in the same chat."""
    from app.bot.handlers import battle as battle_handlers
    from app.database import repository as repo
    from app.search.battle import BattleResult, Side

    calls = 0

    async def one_comparison(left, right, _checker, _collectible):
        nonlocal calls
        calls += 1
        return BattleResult(
            left=Side(left, {"length": 10, "word": 9, "spelling": 8, "digits": 7, "status": 6}, "taken"),
            right=Side(right, {"length": 1, "word": 2, "spelling": 3, "digits": 4, "status": 5}, "unknown"),
            winner="left",
        )

    monkeypatch.setattr(battle_handlers, "compare", one_comparison)

    await _ready(session, mock_session)
    challenger = await repo.get_user_by_telegram_id(session, USER)
    challenger.username = "challenger"
    await session.commit()

    battle = await repo.create_battle(session, USER, "challenger", status="pending")
    await session.commit()

    rival_id = 7200
    await _ready(session, mock_session, rival_id)
    rival = await repo.get_user_by_telegram_id(session, rival_id)
    rival.username = "rival"
    await session.commit()

    mock_session.reset()
    await dispatcher.feed_update(
        bot, make_update_callback(rival_id, f"battle:accept:{battle.id}", username="rival")
    )

    assert calls == 1
    text = mock_session.last_edited_text() or mock_session.last_sent_text()
    assert "BATTLE" in text.upper()
    assert "rival" in text
    assert "challenger" in text

    battle_id = battle.id          # capture before expiring
    session.expire_all()
    fresh = await repo.get_battle(session, battle_id)
    assert fresh.status == "done"
    assert fresh.rival_id == rival_id
    assert fresh.winner_id is not None


async def test_accept_is_not_blocked_by_the_access_gate(dispatcher, bot, mock_session, session):
    """A group member who never onboarded must still be able to accept."""
    from app.database import repository as repo

    await _ready(session, mock_session)
    challenger = await repo.get_user_by_telegram_id(session, USER)
    challenger.username = "challenger"
    await session.commit()
    battle = await repo.create_battle(session, USER, "challenger", status="pending")
    await session.commit()

    stranger = 7300
    user, _ = await repo.get_or_create_user(session, stranger, username="stranger")
    await repo.update_user_settings(session, user.id, language="en")
    await session.commit()

    mock_session.reset()
    await dispatcher.feed_update(
        bot, make_update_callback(stranger, f"battle:accept:{battle.id}", username="stranger")
    )

    text = mock_session.last_edited_text() or mock_session.last_sent_text()
    assert "SECURITY CHECK" not in text, "the onboarding gate leaked into a group chat"
    assert "BATTLE" in text.upper()


# --------------------------------------------------------------------------- dead buttons
# The list above is hand-maintained, which is exactly how "watch a collectible"
# shipped as a button with no handler behind it: the button was added to the
# keyboard and never added here. This walks the real keyboards instead.
SCREENS = [
    "menu:home",
    "menu:find",
    "menu:watch",
    "menu:profile",
    "menu:settings",
    "set:digest:menu",
    "menu:support",
    "menu:history",
    "adm:root",
    "adm:users",
    "adm:logs",
    "adm:stats",
    "adm:system",
    "adm:blacklist",
    "adm:settings",
    "adm:restrictions",
    "adm:privileges",
]


async def _buttons_on_screen(dispatcher, bot, mock, entry: str) -> list[str]:
    mock.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, entry))
    payload = mock.edits[-1] if mock.edits else (mock.messages[-1] if mock.messages else None)
    if payload is None:
        return []
    markup = payload.get("reply_markup")
    rows = markup.get("inline_keyboard") if isinstance(markup, dict) else None
    if rows is None:
        rows = getattr(markup, "inline_keyboard", None) or []
    return [b.get("callback_data") for row in rows for b in row if b.get("callback_data")]


@pytest.mark.parametrize("entry", SCREENS)
async def test_every_button_on_a_screen_has_a_handler(
    dispatcher, bot, mock_session, session, entry
):
    """A button no handler matches does nothing at all - silence, not an error."""
    await _ready(session, mock_session)
    if entry.startswith("adm:"):
        await _make_admin(session, USER)

    buttons = await _buttons_on_screen(dispatcher, bot, mock_session, entry)
    assert buttons, f"{entry} rendered no buttons"

    dead: list[str] = []
    for data in buttons:
        mock_session.reset()
        await dispatcher.feed_update(bot, make_update_callback(USER, data))
        if not (mock_session.edits or mock_session.messages or mock_session.answers):
            dead.append(data)

    assert not dead, f"buttons on {entry} with no handler: {dead}"


async def test_home_cancels_pending_watch_input(dispatcher, bot, mock_session, session):
    """Leaving the Watch prompt must not consume the next normal message."""
    await _ready(session, mock_session)
    await press(dispatcher, bot, mock_session, "menu:watch")
    await press(dispatcher, bot, mock_session, "watch:add")
    await press(dispatcher, bot, mock_session, "menu:home")
    mock_session.reset()

    await dispatcher.feed_update(bot, make_update_message(USER, "moged", message_id=40))

    user = await repo.get_user_by_telegram_id(session, USER)
    assert list(await repo.list_traps(session, user)) == []


async def test_manual_battle_compares_once_and_replaces_comparing_screen(
    dispatcher, bot, mock_session, session, monkeypatch
):

    """A manual duel must not run the same slow Telegram lookups twice."""
    from app.bot.handlers import battle as battle_handlers
    from app.search.battle import BattleResult, Side

    await _ready(session, mock_session)
    calls = 0

    async def one_comparison(left, right, _checker, _collectible):
        nonlocal calls
        calls += 1
        return BattleResult(
            left=Side(
                username=left,
                scores={"length": 10, "word": 9, "spelling": 8, "digits": 7, "status": 6},
                status="taken",
            ),
            right=Side(
                username=right,
                scores={"length": 1, "word": 2, "spelling": 3, "digits": 4, "status": 5},
                status="unknown",
            ),
            winner="left",
        )

    monkeypatch.setattr(battle_handlers, "compare", one_comparison)

    await press(dispatcher, bot, mock_session, "battle:manual")
    await dispatcher.feed_update(bot, make_update_message(USER, "crane", message_id=31))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_message(USER, "mogeddev", message_id=32))

    assert calls == 1
    rendered = mock_session.last_edited_text()
    assert "BATTLE RESULT" in rendered
    assert "FIRST USERNAME" in rendered
    assert "SECOND USERNAME" in rendered
    assert "COMPARING..." not in rendered
