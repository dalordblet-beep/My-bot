"""Rough, honest market-value estimate for a username.

This is NOT a quote. It is a heuristic grounded in what the Fragment market
actually prices:

* **Length dominates.** Three- and four-character handles are structurally
  scarce and command the strongest premiums; every extra character multiplies
  the supply of alternatives and softens demand.
* **A real word beats a random same-length string** by an order of magnitude,
  because it can serve a business rather than merely look tidy.
* **Clean spelling wins.** No digits, no underscores, pronounceable - easier to
  say aloud in an advert.

The bands below are calibrated against observed Fragment listings: long,
random, digit-bearing names floor out around the minimum bid (a few TON),
while short semantic words climb into the tens of thousands. The rating that
drives the score comes from :mod:`app.search.pattern`, so the two numbers can
never drift apart.

The number is an *illustrative TON band*, shown only as a conversation starter.
Real pricing needs Fragment comparables of the same length and semantic class.
"""

from __future__ import annotations

from app.search.pattern import is_pronounceable, is_real_word, rate

VOWELS = set("aeiouy")


def is_wordlike(name: str) -> bool:
    """Heuristic: looks like a real (pronounceable) word, not a random string."""
    letters = [c for c in name if c.isalpha()]
    if not letters:
        return False
    if any(c.isdigit() for c in name) or "_" in name:
        return False
    ratio = sum(1 for c in letters if c.lower() in VOWELS) / len(letters)
    # natural-language words sit in a vowel band; random strings rarely do
    return 0.2 <= ratio <= 0.6


def estimate_value(name: str) -> dict:
    """Return a rarity score (0-100) and an illustrative TON band.

    ``band_low`` / ``band_high`` are strings with thousands separators. The
    score is exactly :func:`app.search.pattern.rate` - one rubric, shown both
    in the search result and in the valuation line, so a user can never see two
    different quality numbers for the same handle.
    """
    clean = (name or "").strip().lower()
    length = len(clean)
    real_word = is_real_word(clean)
    score = rate(clean).total

    # Illustrative TON band by length. A real word lifts the high end; a merely
    # pronounceable name lifts both ends; an unpronounceable one caps out low,
    # because a string nobody can say is a name, not a brand.
    if length <= 4:
        low, high = 1000, 50000
    elif length == 5:
        low, high = 300, 5000
    elif length == 6:
        low, high = 80, 1200
    elif length == 7:
        low, high = 30, 400
    else:
        low, high = 5, 150

    if real_word:
        high *= 3
    elif is_pronounceable(clean):
        low = max(5, int(low * 0.6))
        high = int(high * 1.4)
    else:
        low = min(low, 5)
        high = min(high, 60)

    return {
        "score": score,
        "wordlike": real_word,
        "band_low": f"{low:,}",
        "band_high": f"{high:,}",
    }
