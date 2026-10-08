"""Daily Drop: it must explain itself and actually do something.

Regression: the feature was a bare on/off switch with no explanation, and the
only way to see it work was to wait for the next 09:00 - so it looked like it
did nothing. It now has a screen that says what it is, and a "Get one now"
button that runs one immediately.
"""

from __future__ import annotations

import asyncio

import pytest
from aiogram.enums import ChatMemberStatus

from app.database import repository as repo
from app.telegram import username_checker as uc_module
from tests.mock_telegram import make_update_callback

USER = 7600
CHANNEL = "@test_channel"
CHAT = "@test_chat"


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(uc_module.shared_rate_limiter, "min_interval", 0.0)


async def _ready(session, mock) -> None:
    mock.memberships[(CHANNEL, USER)] = ChatMemberStatus.MEMBER
    mock.memberships[(CHAT, USER)] = ChatMemberStatus.MEMBER
    user, _ = await repo.get_or_create_user(session, USER, username=f"u{USER}")
    await repo.update_user_settings(session, user.id, language="en")
    await repo.set_captcha_verified(session, user)
    await repo.set_channel_verified(session, user)
    await repo.set_chat_verified(session, user)
    await session.commit()


async def _open_digest(dispatcher, bot, mock_session, session) -> None:
    await _ready(session, mock_session)
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "menu:settings"))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "set:digest:menu"))


async def test_digest_screen_explains_what_it_is(dispatcher, bot, mock_session, session):
    await _open_digest(dispatcher, bot, mock_session, session)
    text = mock_session.last_edited_text()
    assert "DAILY DROP" in text
    # It must say what the feature is, not just show a switch.
    assert "once a day" in text.lower()
    assert "OFF" in text.upper()

    labels = [
        button["text"]
        for row in mock_session.edits[-1]["reply_markup"]["inline_keyboard"]
        for button in row
    ]
    assert any("Turn on" in label for label in labels)
    assert any("Get one now" in label for label in labels)


async def test_digest_toggle_updates_the_setting(dispatcher, bot, mock_session, session):
    await _open_digest(dispatcher, bot, mock_session, session)
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "set:digest:1"))

    user = await repo.get_user_by_telegram_id(session, USER)
    row = await repo.get_user_settings(session, user.id)
    assert row.daily_drop is True
    assert "ON" in mock_session.last_edited_text().upper()


async def test_get_one_now_queues_a_digest_job(
    dispatcher, bot, mock_session, session, search_queue
):
    await _open_digest(dispatcher, bot, mock_session, session)
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "digest:now"))

    assert "RUNNING" in mock_session.last_edited_text().upper()
    jobs = list(search_queue._pending.values())
    assert len(jobs) == 1
    assert jobs[0].kind == "digest"


async def test_digest_result_is_branded(
    dispatcher, bot, mock_session, session, search_queue
):
    await _open_digest(dispatcher, bot, mock_session, session)

    search_queue.start()
    try:
        mock_session.reset()
        await dispatcher.feed_update(bot, make_update_callback(USER, "digest:now"))
        for _ in range(100):
            if search_queue.done:
                break
            await asyncio.sleep(0.05)
        assert search_queue.done == 1
    finally:
        await search_queue.stop()

    # The delivered message carries the Daily Drop banner, not a bare result.
    assert "DAILY DROP" in mock_session.last_edited_text()
