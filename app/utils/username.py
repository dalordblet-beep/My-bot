"""Username normalisation and validation.

Nothing here talks to Telegram. It only turns messy user input into a clean
candidate and rejects garbage before it ever reaches the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# t.me / telegram.me links, with or without scheme, with or without @.
_LINK_RE = re.compile(
    r"^\s*(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/",
    re.IGNORECASE,
)
_ALLOWED_RE = re.compile(r"^[A-Za-z0-9_]+$")

MIN_LENGTH = 5
MAX_LENGTH = 32

# Reserved / non-username paths that live under t.me.
_RESERVED_PATHS = {
    "joinchat",
    "addstickers",
    "addemoji",
    "share",
    "proxy",
    "socks",
    "iv",
    "setlanguage",
    "bg",
    "invoice",
    "giftcode",
    "c",
    "s",
    "addlist",
    "login",
    "confirmphone",
}


@dataclass(frozen=True)
class NormalizedUsername:
    raw: str
    value: str  # canonical, lowercase, no decoration
    is_valid: bool
    reason: str | None = None

    @property
    def display(self) -> str:
        return f"@{self.value}" if self.value else self.raw


def normalize_username(raw: str) -> str:
    """Reduce any accepted input shape to a bare username.

    ``@moged`` / ``moged`` / ``https://t.me/moged`` -> ``moged``
    """
    if raw is None:
        return ""
    value = str(raw).strip()
    if not value:
        return ""

    value = _LINK_RE.sub("", value)

    # Drop query string / fragment / trailing slashes.
    for separator in ("?", "#"):
        if separator in value:
            value = value.split(separator, 1)[0]
    value = value.strip("/")

    # Only the first path segment can be a username.
    if "/" in value:
        value = value.split("/", 1)[0]

    value = value.lstrip("@").strip()
    value = value.replace(" ", "")
    return value


def validate_username(value: str) -> tuple[bool, str | None]:
    """Return ``(is_valid, reason)`` for an already normalised username."""
    if not value:
        return False, "empty_input"
    if len(value) > 64:
        return False, "suspiciously_long_input"
    if value.lower() in _RESERVED_PATHS:
        return False, "reserved_telegram_path"
    if len(value) < MIN_LENGTH:
        return False, f"too_short_min_{MIN_LENGTH}"
    if len(value) > MAX_LENGTH:
        return False, f"too_long_max_{MAX_LENGTH}"
    if not _ALLOWED_RE.match(value):
        return False, "invalid_characters"
    if not value[0].isalpha():
        return False, "must_start_with_a_letter"
    if "__" in value:
        return False, "consecutive_underscores"
    if value.endswith("_"):
        return False, "cannot_end_with_underscore"
    return True, None


def parse_username(raw: str) -> NormalizedUsername:
    """Normalise + validate in one call. Never raises."""
    value = normalize_username(raw)
    if not value:
        return NormalizedUsername(raw=raw or "", value="", is_valid=False, reason="empty_input")
    ok, reason = validate_username(value)
    return NormalizedUsername(raw=raw, value=value.lower(), is_valid=ok, reason=reason)


def looks_like_username(raw: str) -> bool:
    return parse_username(raw).is_valid
