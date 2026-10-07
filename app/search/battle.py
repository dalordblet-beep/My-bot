"""Username battle.

Two usernames are compared on **five criteria that can actually be measured**,
and - crucially - the same criteria the stand-alone rating uses. A user who
sees "78/100" on the search screen and "7.8/10" in a battle must be looking at
the same judgement, not two unrelated ones.

    1. Length      shorter is better
    2. Word        is it a real, brandable word
    3. Spelling    pronounceable, no clusters, no repeats
    4. Digits      fewer is better
    5. Status      what the name actually is right now:
                   collectible (10) > taken by a channel/bot/user (7) > free (3)

The four string criteria are the rating's own components, rescaled to 0..10
(``pattern.rate`` maxes at 30/25/20/15/10 respectively). The totals are averages
out of 10. "Better" is a scoring model, not a market valuation - the UI says so
rather than implying a price.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.collectible.checker import CollectibleChecker
from app.search.pattern import rate
from app.telegram.username_checker import UsernameChecker
from app.utils.enums import CheckStatus, CollectibleStatus
from app.utils.logging_setup import get_logger
from app.utils.username import parse_username

logger = get_logger(__name__)

CRITERIA = ("length", "word", "spelling", "digits", "status")

STATUS_SCORES = {
    "collectible": 10,
    "taken": 7,
    "free": 3,
    "unknown": 5,
}

# The rating's component maximums, so a raw score converts to 0..10 faithfully.
_PART_MAX = {"length": 30, "word": 25, "spelling": 20, "digits": 15, "separators": 10}


@dataclass
class Side:
    username: str
    scores: dict[str, int] = field(default_factory=dict)
    status: str = "unknown"

    @property
    def total(self) -> float:
        if not self.scores:
            return 0.0
        return round(sum(self.scores.values()) / len(self.scores), 1)


@dataclass
class BattleResult:
    left: Side
    right: Side
    winner: str  # "left" | "right" | "draw"

    def to_dict(self) -> dict:
        return {
            "left": {"username": self.left.username, "total": self.left.total,
                     "scores": self.left.scores, "status": self.left.status},
            "right": {"username": self.right.username, "total": self.right.total,
                      "scores": self.right.scores, "status": self.right.status},
            "winner": self.winner,
        }


def _scale(value: int, part: str) -> int:
    """Rescale a rating component to a 0..10 battle score."""
    maximum = _PART_MAX.get(part, 10) or 10
    return max(0, min(10, round(value / maximum * 10)))


def score_side(username: str, status: str) -> Side:
    name = username.strip().lstrip("@").lower()
    parts = rate(name).parts
    return Side(
        username=name,
        status=status,
        scores={
            "length": _scale(parts.get("length", 0), "length"),
            "word": _scale(parts.get("word", 0), "word"),
            "spelling": _scale(parts.get("spelling", 0), "spelling"),
            "digits": _scale(parts.get("digits", 0), "digits"),
            "status": STATUS_SCORES.get(status, STATUS_SCORES["unknown"]),
        },
    )


async def _resolve_status(
    name: str,
    checker: UsernameChecker,
    collectible: CollectibleChecker | None,
) -> str:
    if collectible is not None:
        try:
            info = await collectible.check_collectible_username(name)
            if info.status in (
                CollectibleStatus.OWNED,
                CollectibleStatus.AVAILABLE_FOR_PURCHASE,
                CollectibleStatus.LISTED,
            ):
                return "collectible"
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("collectible check failed for %s: %s", name, exc)

    try:
        basic = await checker.check_basic_username(name, use_cache=False)
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("basic check failed for %s: %s", name, exc)
        return "unknown"

    if basic.status is CheckStatus.OCCUPIED:
        return "taken"
    if basic.status is CheckStatus.AVAILABLE:
        return "free"
    return "unknown"


async def compare(
    left_name: str,
    right_name: str,
    checker: UsernameChecker,
    collectible: CollectibleChecker | None = None,
) -> BattleResult | None:
    """Compare two usernames. Returns None when either input is unusable."""
    left = parse_username(left_name)
    right = parse_username(right_name)
    if not left.is_valid or not right.is_valid:
        return None
    if left.value == right.value:
        return None

    left_status = await _resolve_status(left.value, checker, collectible)
    right_status = await _resolve_status(right.value, checker, collectible)

    left_side = score_side(left.value, left_status)
    right_side = score_side(right.value, right_status)

    if left_side.total > right_side.total:
        winner = "left"
    elif right_side.total > left_side.total:
        winner = "right"
    else:
        winner = "draw"

    return BattleResult(left=left_side, right=right_side, winner=winner)


def quick_rating(username: str) -> int:
    """String-only rating, used for previews before any lookup."""
    return rate(username).total
