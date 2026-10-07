"""CAPTCHA service: correctness, attempts, expiry, retry."""

from __future__ import annotations

import time

import pytest

from app.config import settings
from app.services.captcha import (
    STATE_EXPIRED,
    STATE_FAILED,
    STATE_PASSED,
    STATE_PENDING,
    CaptchaService,
)

USER = 1001


def test_challenge_options_are_distinct_and_indexed(captcha_service: CaptchaService):
    challenge = captcha_service.create(USER)
    # Logic tasks offer 2 options, the other two kinds offer 4.
    assert 2 <= len(challenge.options) <= 4
    assert len(set(challenge.options)) == len(challenge.options)
    assert 0 <= challenge.correct_index < len(challenge.options)
    assert challenge.state == STATE_PENDING
    assert challenge.attempts_left == settings.max_captcha_attempts


@pytest.mark.parametrize("kind", ["math", "choose_number", "logic"])
def test_every_captcha_kind_is_solvable(captcha_service: CaptchaService, kind: str):
    challenge = captcha_service.create(USER, kind=kind)
    assert challenge.kind == kind
    assert challenge.options
    assert 0 <= challenge.correct_index < len(challenge.options)

    outcome = captcha_service.verify(USER, challenge.session_id, challenge.correct_index)
    assert outcome.correct
    assert outcome.state == STATE_PASSED


def test_correct_answer_passes(captcha_service: CaptchaService):
    challenge = captcha_service.create(USER)
    outcome = captcha_service.verify(USER, challenge.session_id, challenge.correct_index)
    assert outcome.correct
    assert outcome.state == STATE_PASSED


def test_callback_payload_does_not_carry_the_answer():
    """Callbacks are uniform: only a session id and a position, nothing else.

    The correctness of an option is not encoded anywhere in the payload - it
    lives exclusively in the server-side session, so a fresh process cannot
    resolve it even with the exact payload.
    """
    from app.bot.keyboards.captcha_kb import captcha_keyboard

    service = CaptchaService(cache=None)
    challenge = service.create(USER)
    keyboard = captcha_keyboard(challenge, "en")

    payloads = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert len(payloads) == len(challenge.options)
    assert 2 <= len(challenge.options) <= 4  # logic tasks have 2, the rest 4

    prefixes = {payload.rsplit(":", 1)[0] for payload in payloads}
    positions = {payload.rsplit(":", 1)[1] for payload in payloads}
    assert len(prefixes) == 1, "all options must share one opaque session id"
    assert positions == {str(index) for index in range(len(challenge.options))}

    # Payload format is exactly <namespace>:<session>:<position> - nothing else
    # travels with it, so nothing can distinguish the correct option.
    for position, payload in enumerate(payloads):
        assert payload == f"captcha:ans:{challenge.session_id}:{position}"

    # The answer is reachable only through the server-side store.
    assert service.get(USER).correct_index == challenge.correct_index

    # A process with no session for this user cannot verify anything.
    fresh = CaptchaService(cache=None)
    outcome = fresh.verify(USER, challenge.session_id, challenge.correct_index)
    assert outcome.state == STATE_EXPIRED
    assert not outcome.correct


def test_wrong_answers_decrement_attempts_then_fail(captcha_service: CaptchaService):
    challenge = captcha_service.create(USER)
    wrong = (challenge.correct_index + 1) % 4

    first = captcha_service.verify(USER, challenge.session_id, wrong)
    assert not first.correct
    assert first.state == STATE_PENDING
    assert first.attempts_left == settings.max_captcha_attempts - 1

    second = captcha_service.verify(USER, challenge.session_id, wrong)
    assert second.state == STATE_PENDING
    assert second.attempts_left == settings.max_captcha_attempts - 2

    third = captcha_service.verify(USER, challenge.session_id, wrong)
    assert third.state == STATE_FAILED
    assert third.attempts_left == 0

    # Even the right answer no longer works on a failed session.
    after = captcha_service.verify(USER, challenge.session_id, challenge.correct_index)
    assert after.state == STATE_FAILED
    assert not after.correct


def test_expired_challenge(captcha_service: CaptchaService):
    challenge = captcha_service.create(USER)
    challenge.expires_at = time.time() - 1
    captcha_service._store(USER, challenge)

    outcome = captcha_service.verify(USER, challenge.session_id, challenge.correct_index)
    assert outcome.state == STATE_EXPIRED
    assert not outcome.correct


def test_new_challenge_replaces_old(captcha_service: CaptchaService):
    first = captcha_service.create(USER)
    second = captcha_service.create(USER)
    assert first.session_id != second.session_id

    stale = captcha_service.verify(USER, first.session_id, first.correct_index)
    assert stale.state == STATE_PENDING  # stale button ignored

    fresh = captcha_service.verify(USER, second.session_id, second.correct_index)
    assert fresh.state == STATE_PASSED
