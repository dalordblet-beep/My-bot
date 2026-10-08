"""Comparables-based price estimate for a username - one number, not a range.

The estimate comes from the *live* Fragment market, but is built so it can
never be overvalued or upside-down:

* only names of the **same length** are considered - length is the loudest
  price driver, so comparing across lengths would be meaningless;
* among those, only names with a **similar premium rating** (our own ``rate``
  rubric, 0-100, which rewards real words and clean spelling) AND the same
  digit/digit-free shape count as comparables. This is the key guard: an
  ordinary, random handle is *not* the same market as a premium collectible,
  so it must not borrow the price of one. If there are too few similar-quality
  comparables, the name is simply outside the traded collectible band and gets
  a short, conservative floor - not a premium median;
* the answer is the median of those comparables, rounded to two significant
  figures.

Net effect: rarer names (shorter, cleaner, real words) are priced higher and
ordinary names are priced low, both in line with what Fragment actually trades.
It is honest: "about what a similar name costs on Fragment right now". If there
is no market data at all, there is no estimate.
"""

from __future__ import annotations

import math

from app.collectible.fragment import _ton_value
from app.search.pattern import rate

# How many nearest-by-quality comparables feed the median. Broad enough to be
# stable, narrow enough to stay specific to names like the target.
MAX_COMPS = 25

# A listing only counts as a comparable to ``name`` if its premium rating is
# within this distance (on the 0-100 scale). This stops a random/ordinary name
# from inheriting the price of a premium collectible it is nothing like, and
# keeps the estimate monotonic in rarity.
QUALITY_BAND = 18

# Minimum number of similar-quality comparables before we trust the live
# market; below this the name is treated as a non-collectible and floored.
MIN_COMPS = 3

# Conservative floor (TON) when there is no real comparable on Fragment: the
# name is not a traded collectible, so its real value is small. Scales with
# length so it stays monotonic (shorter = a bit more) but never pretends a
# free random handle is worth thousands.
_LENGTH_FLOOR = {4: 150, 5: 25, 6: 8, 7: 3, 8: 1}


def _quality(name: str) -> float:
    """Premium rating 0-100: length is fixed here, so this is word/spelling/digits."""
    return float(rate(name).total)


def _has_digit(name: str) -> bool:
    return any(ch.isdigit() for ch in name)


def _round_price(value: float) -> int:
    """Round to two significant figures - it is an estimate, not a quote."""
    if value <= 0:
        return 0
    magnitude = 10 ** (math.floor(math.log10(value)) - 1)
    return int(round(value / magnitude) * magnitude)


def _floor(length: int, quality: float) -> int:
    """Conservative value for a name with no real comparable on Fragment."""
    base = _LENGTH_FLOOR.get(length, 1)
    # quality 0-100: an ordinary name gets ~40% of the floor, a premium one the
    # full amount - keeps the floor monotonic without inventing a large value.
    factor = 0.4 + 0.6 * (quality / 100.0)
    return max(1, int(round(base * factor)))


def estimate_price(name: str, listings) -> int | None:
    """A single estimated TON price for ``name`` from live listings, or ``None``.

    ``listings`` is the Fragment listing set (``FragmentListing`` items with a
    ``name`` and a ``min_bid`` string).
    """
    length = len(name)
    target_quality = _quality(name)
    target_has_digit = _has_digit(name)

    pool: list[tuple[str, float]] = []
    for item in listings:
        if len(item.name) != length:
            continue
        price = _ton_value(item.min_bid)
        if price and price > 0:
            pool.append((item.name, price))
    if not pool:
        return None

    # Only names whose premium rating is close to the target's AND that share
    # its digit/digit-free shape are real comparables. This is what prevents
    # ordinary/free names from being priced like premium collectibles.
    comps = [
        (item_name, price)
        for item_name, price in pool
        if _has_digit(item_name) == target_has_digit
        and abs(_quality(item_name) - target_quality) <= QUALITY_BAND
    ]
    if len(comps) < MIN_COMPS:
        # Outside the traded collectible band: not worth a premium price.
        return _floor(length, target_quality)

    comps.sort(key=lambda pair: abs(_quality(pair[0]) - target_quality))
    prices = sorted(price for _, price in comps[:MAX_COMPS])
    mid = prices[len(prices) // 2]
    return _round_price(mid)
