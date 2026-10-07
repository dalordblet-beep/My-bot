"""Achievements.

Everything here is computed from rows that already exist in the database - no
counters are invented and no achievement can unlock without real activity. Each
one carries its own progress so the UI can show "7 / 10" instead of a bare lock.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.utils.enums import CheckStatus


@dataclass
class Achievement:
    code: str
    icon: str
    unlocked: bool
    progress: int
    target: int

    @property
    def percent(self) -> int:
        if self.target <= 0:
            return 100 if self.unlocked else 0
        return min(100, int(self.progress / self.target * 100))


@dataclass
class AchievementStats:
    """Real counters, gathered once per render."""

    checks: int = 0
    searches: int = 0
    free_found: int = 0
    collectible_found: int = 0
    traps_created: int = 0
    traps_fired: int = 0
    battles: int = 0
    battles_won: int = 0
    best_score: int = 0
    favorites: int = 0


def evaluate(stats: AchievementStats) -> list[Achievement]:
    """Return every achievement with its live progress."""
    return [
        Achievement("first_find", "seedling", stats.free_found >= 1, stats.free_found, 1),
        Achievement("ten_finds", "star", stats.free_found >= 10, stats.free_found, 10),
        Achievement("fifty_finds", "trophy", stats.free_found >= 50, stats.free_found, 50),
        Achievement(
            "first_collectible", "gem", stats.collectible_found >= 1, stats.collectible_found, 1
        ),
        Achievement("first_trap", "bell", stats.traps_created >= 1, stats.traps_created, 1),
        Achievement("trap_fired", "target", stats.traps_fired >= 1, stats.traps_fired, 1),
        Achievement("first_battle", "battle", stats.battles >= 1, stats.battles, 1),
        Achievement("battle_win", "medal", stats.battles_won >= 1, stats.battles_won, 1),
        Achievement("perfect_score", "crown", stats.best_score >= 100, stats.best_score, 100),
        Achievement("hundred_checks", "rocket", stats.checks >= 100, stats.checks, 100),
        Achievement("collector", "palette", stats.favorites >= 10, stats.favorites, 10),
    ]


def unlocked(stats: AchievementStats) -> list[Achievement]:
    return [item for item in evaluate(stats) if item.unlocked]


def summary(stats: AchievementStats) -> tuple[int, int]:
    """(unlocked, total)."""
    items = evaluate(stats)
    return sum(1 for item in items if item.unlocked), len(items)


def count_free(rows: list[tuple[str, str]]) -> int:
    """Helper for callers holding (username, status) pairs."""
    return sum(1 for _name, status in rows if status == CheckStatus.AVAILABLE.value)
