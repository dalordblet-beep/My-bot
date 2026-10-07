"""Server-side CAPTCHA.

The correct answer never leaves the server: callbacks only carry a session id
and an option index. Sessions are stored in Redis when available and in a
process-local dict otherwise, so CAPTCHA keeps working without Redis.

States: pending -> passed | failed | expired.
"""

from __future__ import annotations

import json
import random
import secrets
import time
from dataclasses import asdict, dataclass, field

from app.cache.redis_cache import CacheService
from app.config import settings
from app.services.runtime_config import runtime
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

STATE_PENDING = "pending"
STATE_PASSED = "passed"
STATE_FAILED = "failed"
STATE_EXPIRED = "expired"

KIND_MATH = "math"
KIND_CHOOSE_NUMBER = "choose_number"
KIND_LOGIC = "logic"


@dataclass
class CaptchaChallenge:
    session_id: str
    kind: str
    title: str
    prompt: str
    options: list[str]
    correct_index: int
    expires_at: float
    attempts: int = 0
    state: str = STATE_PENDING

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def attempts_left(self) -> int:
        return max(0, runtime.max_captcha_attempts - self.attempts)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "CaptchaChallenge | None":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        try:
            return cls(**data)
        except TypeError:
            return None


@dataclass
class CaptchaOutcome:
    state: str
    correct: bool = False
    attempts_left: int = 0
    challenge: CaptchaChallenge | None = None


class CaptchaService:
    """Generates and verifies challenges. Answers stay on this side."""

    def __init__(self, cache: CacheService | None = None) -> None:
        self._cache = cache
        self._memory: dict[int, CaptchaChallenge] = {}

    # ------------------------------------------------------------- public API
    def create(self, user_id: int, kind: str | None = None) -> CaptchaChallenge:
        kind = kind or random.choice([KIND_MATH, KIND_CHOOSE_NUMBER, KIND_LOGIC])
        challenge = self._build(user_id, kind)
        self._store(user_id, challenge)
        logger.info("captcha created user_id=%s kind=%s", user_id, kind)
        return challenge

    def get(self, user_id: int) -> CaptchaChallenge | None:
        challenge = self._load(user_id)
        if challenge is None:
            return None
        if challenge.expired and challenge.state == STATE_PENDING:
            challenge.state = STATE_EXPIRED
            self._store(user_id, challenge)
        return challenge

    def verify(self, user_id: int, session_id: str, option_index: int) -> CaptchaOutcome:
        challenge = self._load(user_id)
        if challenge is None:
            return CaptchaOutcome(state=STATE_EXPIRED, attempts_left=0)

        if challenge.session_id != session_id:
            # Stale button from an older challenge.
            return CaptchaOutcome(
                state=challenge.state, attempts_left=challenge.attempts_left,
                challenge=challenge,
            )

        if challenge.state == STATE_FAILED:
            return CaptchaOutcome(
                state=STATE_FAILED, attempts_left=0, challenge=challenge
            )

        if challenge.expired:
            challenge.state = STATE_EXPIRED
            self._store(user_id, challenge)
            return CaptchaOutcome(
                state=STATE_EXPIRED, attempts_left=0, challenge=challenge
            )

        if challenge.state == STATE_PASSED:
            return CaptchaOutcome(
                state=STATE_PASSED, correct=True,
                attempts_left=challenge.attempts_left, challenge=challenge,
            )

        if option_index == challenge.correct_index:
            challenge.state = STATE_PASSED
            self._store(user_id, challenge)
            logger.info("captcha passed user_id=%s", user_id)
            return CaptchaOutcome(
                state=STATE_PASSED, correct=True,
                attempts_left=challenge.attempts_left, challenge=challenge,
            )

        challenge.attempts += 1
        if challenge.attempts >= runtime.max_captcha_attempts:
            challenge.state = STATE_FAILED
            self._store(user_id, challenge)
            logger.info("captcha failed (attempts exhausted) user_id=%s", user_id)
            return CaptchaOutcome(
                state=STATE_FAILED, correct=False, attempts_left=0, challenge=challenge
            )

        self._store(user_id, challenge)
        logger.info(
            "captcha wrong answer user_id=%s attempts=%s", user_id, challenge.attempts
        )
        return CaptchaOutcome(
            state=STATE_PENDING, correct=False,
            attempts_left=challenge.attempts_left, challenge=challenge,
        )

    def clear(self, user_id: int) -> None:
        self._memory.pop(user_id, None)
        if self._cache is not None:
            # Best effort; the key expires on its own anyway.
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._cache.delete(self._key(user_id)))
            except RuntimeError:
                pass

    # ------------------------------------------------------------- builders
    def _build(self, user_id: int, kind: str) -> CaptchaChallenge:
        session_id = secrets.token_urlsafe(12)
        expires_at = time.time() + runtime.captcha_ttl

        if kind == KIND_MATH:
            title, prompt, options, correct = self._math()
        elif kind == KIND_CHOOSE_NUMBER:
            title, prompt, options, correct = self._choose_number()
        else:
            title, prompt, options, correct = self._logic()

        return CaptchaChallenge(
            session_id=session_id,
            kind=kind,
            title=title,
            prompt=prompt,
            options=options,
            correct_index=correct,
            expires_at=expires_at,
        )

    @staticmethod
    def _math() -> tuple[str, str, list[str], int]:
        operator = random.choice(["+", "-", "\u00D7", "/"])
        if operator == "+":
            a, b = random.randint(2, 19), random.randint(2, 19)
            answer = a + b
        elif operator == "-":
            a, b = random.randint(10, 30), random.randint(1, 9)
            answer = a - b
        elif operator == "\u00D7":
            a, b = random.randint(2, 9), random.randint(2, 9)
            answer = a * b
        else:
            b = random.randint(2, 9)
            answer = random.randint(2, 9)
            a = b * answer

        options = {answer}
        while len(options) < 4:
            delta = random.randint(1, 4) * random.choice([-1, 1])
            candidate = answer + delta
            if candidate > 0:
                options.add(candidate)
        shuffled = random.sample(sorted(options), k=len(options))
        return (
            "MATH",
            f"{a} {operator} {b} = ?",
            [str(value) for value in shuffled],
            shuffled.index(answer),
        )

    @staticmethod
    def _choose_number() -> tuple[str, str, list[str], int]:
        target = random.randint(1, 9)
        options = {target}
        while len(options) < 4:
            options.add(random.randint(1, 9))
        shuffled = random.sample(sorted(options), k=4)
        return (
            "CHOOSE NUMBER",
            f"Tap the number {target}",
            [str(value) for value in shuffled],
            shuffled.index(target),
        )

    @staticmethod
    def _logic() -> tuple[str, str, list[str], int]:
        a, b = random.sample(range(1, 10), 2)
        bigger = max(a, b)
        shuffled = random.sample([a, b], k=2)
        return (
            "LOGIC",
            "Which number is bigger?",
            [str(value) for value in shuffled],
            shuffled.index(bigger),
        )

    # ------------------------------------------------------------- storage
    @staticmethod
    def _key(user_id: int) -> str:
        return f"captcha:session:{user_id}"

    def _store(self, user_id: int, challenge: CaptchaChallenge) -> None:
        self._memory[user_id] = challenge
        if self._cache is not None and self._cache.available:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._cache.set_json(
                        self._key(user_id),
                        json.loads(challenge.to_json()),
                        runtime.captcha_ttl + 60,
                    )
                )
            except RuntimeError:
                pass

    def _load(self, user_id: int) -> CaptchaChallenge | None:
        return self._memory.get(user_id)
