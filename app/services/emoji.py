"""Emoji rendering.

Custom Telegram emoji are a decoration, never a requirement. The renderer only
emits a ``<tg-emoji>`` entity when a *real* id is configured through
``CUSTOM_EMOJI_IDS``. We never invent ids - an unknown id makes Telegram reject
the whole message, so the default path is plain Unicode.
"""

from __future__ import annotations

from app.config import settings

# Symbolic name -> plain Unicode fallback. Every key used by the UI lives here.
PLAIN: dict[str, str] = {
    "shield": "\U0001F6E1\uFE0F",
    "search": "\U0001F50E",
    "channel": "\U0001F4E2",
    "chat": "\U0001F4AC",
    "available": "\U0001F7E2",
    "occupied": "\U0001F534",
    "collectible": "\U0001F48E",
    "bolt": "\u26A1",
    "history": "\U0001F4DA",
    "settings": "\u2699\uFE0F",
    "crown": "\U0001F451",
    "check": "\u2705",
    "cross": "\u274C",
    "warn": "\u26A0\uFE0F",
    "sparkle": "\u2728",
    "wave": "\U0001F44B",
    "person": "\U0001F464",
    "users": "\U0001F465",
    "ban": "\U0001F6AB",
    "hourglass": "\u23F3",
    "gift": "\U0001F381",
    "chart": "\U0001F4CA",
    "wrench": "\U0001F6E0\uFE0F",
    "clipboard": "\U0001F4CB",
    "arrow_left": "\u25C0\uFE0F",
    "arrow_right": "\u25B6\uFE0F",
    "fire": "\U0001F525",
    "robot": "\U0001F916",
    "database": "\U0001F5C4",
    "antenna": "\U0001F4E1",
    "lock": "\U0001F512",
    "key": "\U0001F511",
    # --- button icons -----------------------------------------------------
    # Characterful, action-specific glyphs. Telegram's Bot API only supports
    # three button colours (primary/success/danger), so personality is carried
    # by the icon and the colour carries the meaning.
    "seedling": "\U0001F331",
    "gem": "\U0001F48E",
    "clock": "\U0001F570\uFE0F",
    "hammer": "\U0001F528",
    "dove": "\U0001F54A\uFE0F",
    "broom": "\U0001F9F9",
    "scroll": "\U0001F4DC",
    "folder": "\U0001F5C2\uFE0F",
    "monitor": "\U0001F5A5\uFE0F",
    "pencil": "\U0001F4DD",
    "receipt": "\U0001F9FE",
    "refresh": "\U0001F504",
    "home": "\U0001F3E0",
    "cross_mark": "\u2716\uFE0F",
    "numbers": "\U0001F522",
    "satellite": "\U0001F4E1",
    "shield_lock": "\U0001F510",
    "target": "\U0001F3AF",
    "ticket": "\U0001F39F\uFE0F",
    "compass": "\U0001F9ED",
    "globe": "\U0001F30D",
    "stopwatch": "\u23F1\uFE0F",
    "back": "\u21A9\uFE0F",
    "gear": "\u2699\uFE0F",
    # --- feature icons ----------------------------------------------------
    "battle": "\u2694\uFE0F",
    "trophy": "\U0001F3C6",
    "bell": "\U0001F514",
    "target": "\U0001F3AF",
    "filter": "\U0001F39A\uFE0F",
    "letters": "\U0001F524",
    "question": "\u2753",
    "envelope": "\u2709\uFE0F",
    "rocket": "\U0001F680",
    "star": "\u2B50",
    "medal": "\U0001F3C5",
    "handshake": "\U0001F91D",
    "info": "\u2139\uFE0F",
    "calendar": "\U0001F4C5",
    "money": "\U0001F4B0",
    "tag": "\U0001F3F7\uFE0F",
    "palette": "\U0001F3A8",
    "scales": "\u2696\uFE0F",
    "eye": "\U0001F441\uFE0F",
    "link": "\U0001F517",
    "boom": "\U0001F4A5",
}


class EmojiRenderer:
    """Builds message fragments that are safe in HTML parse mode."""

    def __init__(self, ids: dict[str, str] | None = None) -> None:
        self._ids = ids if ids is not None else settings.emoji_id_map

    def has_custom(self, name: str) -> bool:
        return name in self._ids and bool(self._ids[name])

    def render(self, name: str) -> str:
        """Return an HTML fragment: custom entity when configured, else plain."""
        fallback = PLAIN.get(name, "")
        custom_id = self._ids.get(name)
        if custom_id:
            # Wrap the unicode glyph so clients without the pack still render it.
            glyph = fallback or "\u2B50"
            return f'<tg-emoji emoji-id="{custom_id}">{glyph}</tg-emoji>'
        return fallback

    def text(self, *names: str) -> str:
        return " ".join(self.render(name) for name in names if name in PLAIN)

    def plain(self, name: str) -> str:
        """Plain Unicode only - required for button labels (no HTML there)."""
        return PLAIN.get(name, "")

    def custom_id(self, name: str) -> str | None:
        """The configured custom-emoji id for a name, or None.

        Used for ``InlineKeyboardButton.icon_custom_emoji_id``, which requires
        the bot owner to have Telegram Premium (or a Fragment-purchased
        username). Absent that, the plain glyph is used instead.
        """
        value = self._ids.get(name)
        return value or None


emoji = EmojiRenderer()
