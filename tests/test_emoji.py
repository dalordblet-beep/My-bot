"""Emoji vocabulary consistency.

The premium custom-emoji pack is configured through CUSTOM_EMOJI_IDS. Different
UI concepts must not render the *same* premium emoji - that is the "mix" the
user reported. This module locks in two invariants:

* within any group of concepts that used to share one id, every name now maps
  to a distinct id;
* every icon in the plain fallback vocabulary renders to a non-empty glyph.
"""

from __future__ import annotations

from app.config import settings
from app.services.emoji import PLAIN, emoji

# Groups that historically collapsed onto a single premium id. After the
# redesign each name in a group must keep its own id.
_ORIGINAL_COLLISION_GROUPS = [
    ["fire", "battle", "boom"],
    ["gear", "wrench", "filter", "settings"],
    ["cross", "cross_mark"],
    ["warn", "hourglass", "stopwatch"],
    ["channel", "satellite", "antenna"],
    ["gift", "ticket"],
    ["monitor", "database"],
    ["receipt", "clipboard", "folder", "scroll", "tag"],
    ["refresh", "clock", "history"],
    ["sparkle", "dove", "wave"],
    ["arrow_left", "back"],
    ["target", "compass"],
    ["link", "globe"],
]


def test_collision_groups_now_map_to_distinct_ids():
    ids = settings.emoji_id_map
    for group in _ORIGINAL_COLLISION_GROUPS:
        assigned = {ids.get(name) for name in group if name in ids}
        # Every name in the group must be present and resolve to a unique id.
        assert len(assigned) == len([n for n in group if n in ids]), (
            f"group {group} still shares a premium emoji id: {assigned}"
        )


def test_plain_fallback_renders_for_every_icon():
    # No icon should resolve to an empty string - an empty glyph is invisible.
    empty = [name for name in PLAIN if not emoji.plain(name)]
    assert not empty, f"icons with empty fallback: {empty}"


def test_emoji_for_ranks_returns_a_glyph():
    for score in (100, 90, 75, 10):
        assert emoji.render("trophy" if score >= 95 else "medal" if score >= 85
                            else "star" if score >= 70 else "seedling")
