"""Guards against a whole class of configuration bugs.

The bug this exists for: a key was added to ``OVERRIDABLE`` but the matching
typed accessor on ``RuntimeConfig`` was never written. Nothing failed at import
time - the bot started, connected, and only crashed when ``main.py`` reached the
line that read ``runtime.trap_interval``.

Two invariants are enforced here:

1. every ``runtime.<name>`` referenced anywhere in ``app/`` really exists;
2. every ``OVERRIDABLE`` key has a typed accessor, so the admin panel can never
   expose a setting that the code cannot read back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.runtime_config import OVERRIDABLE, RuntimeConfig

APP_DIR = Path(__file__).resolve().parent.parent / "app"

RUNTIME_ATTR_RE = re.compile(r"\bruntime\.([a-z_][a-z0-9_]*)")

# Attributes that belong to the class API rather than to configuration.
METHOD_NAMES = {"get", "set", "load", "reset", "snapshot"}


def _referenced_attributes() -> dict[str, list[str]]:
    """Every ``runtime.<name>`` used in the codebase, with the files using it."""
    found: dict[str, list[str]] = {}
    for path in APP_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in RUNTIME_ATTR_RE.findall(text):
            found.setdefault(name, []).append(str(path.relative_to(APP_DIR)))
    return found


def test_every_runtime_attribute_used_exists():
    """The regression guard: an accessor referenced in code must be defined."""
    missing = {
        name: files
        for name, files in _referenced_attributes().items()
        if name not in METHOD_NAMES and not hasattr(RuntimeConfig, name)
    }
    assert not missing, f"runtime attributes used but not defined: {missing}"


def test_every_overridable_key_has_an_accessor():
    """An admin-editable key the code cannot read is a trap."""
    missing = [key for key in OVERRIDABLE if not hasattr(RuntimeConfig, key)]
    assert not missing, f"OVERRIDABLE keys without an accessor: {missing}"


def test_overridable_entries_are_well_formed():
    for key, entry in OVERRIDABLE.items():
        assert len(entry) == 3, f"{key}: expected (parser, label, settings attr)"
        parser, label, attr = entry
        assert callable(parser), f"{key}: parser is not callable"
        assert label and isinstance(label, str), f"{key}: missing label"
        assert attr and isinstance(attr, str), f"{key}: missing settings attribute"


def test_snapshot_reads_every_key():
    """Every key must resolve without raising, overrides or not."""
    snapshot = RuntimeConfig().snapshot()
    assert set(snapshot) == set(OVERRIDABLE)


def test_no_secrets_are_overridable():
    """Tokens and hashes must never be editable from the admin panel."""
    forbidden = {"bot_token", "api_hash", "api_id", "database_url", "redis_url"}
    leaked = forbidden & set(OVERRIDABLE)
    assert not leaked, f"secrets exposed as overridable: {leaked}"


def test_trap_interval_cannot_be_set_to_a_spin():
    """A zero interval would hammer Telegram; the accessor clamps it.

    The floor is low enough that "instant" notifications are possible, but high
    enough that the watcher can never spin.
    """
    config = RuntimeConfig()
    config._overrides["trap_interval"] = 0
    assert config.trap_interval >= 15

    config._overrides["trap_interval"] = -100
    assert config.trap_interval >= 15

    # And it is capped, so a typo cannot turn it into a once-a-day job.
    config._overrides["trap_interval"] = 999_999
    assert config.trap_interval <= 3600


def test_support_username_is_normalised():
    config = RuntimeConfig()
    config._overrides["support_username"] = "@Somebody"
    assert config.support_username == "Somebody"

    config._overrides["support_username"] = ""
    assert config.support_username == "mogeds2"


@pytest.mark.parametrize("key", sorted(OVERRIDABLE))
def test_each_accessor_is_reachable(key: str):
    """Touching the accessor must not raise for any key."""
    getattr(RuntimeConfig(), key)
