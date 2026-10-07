"""The search mask must survive leaving the wizard.

Regression: the mask lived only in the FSM, and pressing Main menu cleared it -
so the bot said "Mask saved" and then quietly searched without a mask. The mask
is now a user setting, seeded into the wizard and persisted on set/clear.
"""

from __future__ import annotations

import pytest
from aiogram.enums import ChatMemberStatus

from app.database import repository as repo
from app.telegram import username_checker as uc_module
from tests.mock_telegram import make_update_callback, make_update_message

USER = 7500
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


async def _set_mask(dispatcher, bot, mock_session, session, mask: str) -> None:
    await _ready(session, mock_session)
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "menu:find"))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "find:filter"))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "find:mask"))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_message(USER, mask, message_id=88))


async def test_saved_mask_is_shown_on_the_search_screen(
    dispatcher, bot, mock_session, session
):
    await _set_mask(dispatcher, bot, mock_session, session, "??ged")
    # The reply is the search screen itself, so the mask is visible immediately.
    assert "??ged" in mock_session.last_sent_text()


async def test_mask_survives_leaving_to_the_main_menu(
    dispatcher, bot, mock_session, session, search_queue
):
    await _set_mask(dispatcher, bot, mock_session, session, "??ged")

    # Leaving the wizard clears the FSM - the mask must not go with it.
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "menu:home"))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "menu:find"))
    assert "??ged" in mock_session.last_sent_text()

    # And it is what the queued search actually uses.
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "find:run"))
    jobs = list(search_queue._pending.values())
    assert len(jobs) == 1
    assert jobs[0].criteria.mask == "??ged"


async def test_clearing_the_mask_persists(
    dispatcher, bot, mock_session, session, search_queue
):
    await _set_mask(dispatcher, bot, mock_session, session, "??ged")

    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "find:clear"))
    assert "??ged" not in mock_session.last_edited_text()

    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "menu:home"))
    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "menu:find"))
    assert "??ged" not in mock_session.last_sent_text()

    mock_session.reset()
    await dispatcher.feed_update(bot, make_update_callback(USER, "find:run"))
    jobs = list(search_queue._pending.values())
    assert jobs and jobs[0].criteria.mask is None


async def test_mask_is_stored_in_user_settings(dispatcher, bot, mock_session, session):
    await _set_mask(dispatcher, bot, mock_session, session, "abc???")
    user = await repo.get_user_by_telegram_id(session, USER)
    row = await repo.get_user_settings(session, user.id)
    assert row.search_mask == "abc???"
