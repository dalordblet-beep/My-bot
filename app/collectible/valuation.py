"""Comparables-based price estimate for a username - one number, not a range.

The estimate comes from the *live* Fragment market, and is built so it can never
be overvalued or upside-down:

* only names of the **same length** are considered - length is the loudest price
  driver, so comparing across lengths would be meaningless;
* among those, only names with a **similar premium rating** (our own ``rate``
  rubric, 0-100, which rewards real words and clean spelling) AND the same
  digit/digit-free shape count as comparables. This is the key guard: an
  ordinary, random handle is *not* the same market as a premium collectible, so
  it must not borrow the price of one;
* the answer is the median of those comparables, rounded to two significant
  figures.

**There is no fallback number.** A name with too few real comparables is simply
not a traded collectible, and the honest answer is "no market data" rather than a
figure invented from a table - which is exactly the kind of made-up price a
valuation must never print. :func:`price_basis` also returns the spread and the
number of listings behind the median, so the screen can show the reader what the
number actually rests on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.collectible.fragment import _ton_value
from app.search.pattern import is_real_word, rate

# How many nearest-by-quality comparables feed the median. Broad enough to be
# stable, narrow enough to stay specific to names like the target.
MAX_COMPS = 25

# A listing only counts as a comparable to ``name`` if its premium rating is
# within this distance (on the 0-100 scale). This stops a random/ordinary name
# from inheriting the price of a premium collectible it is nothing like, and
# keeps the estimate monotonic in rarity.
QUALITY_BAND = 18

# Minimum number of similar-quality comparables before we trust the live market.
# Below this the name is outside the traded band and gets no estimate at all.
MIN_COMPS = 3


@dataclass(frozen=True)
class PriceBasis:
    """The real listings a price rests on - so the screen can show its work."""

    low: float
    median: float
    high: float
    count: int


def _quality(name: str) -> float:
    """Premium rating 0-100: length is fixed here, so this is word/spelling/digits."""
    return float(rate(name).total)


def _has_digit(name: str) -> bool:
    return any(ch.isdigit() for ch in name)


def _word_class(name: str) -> bool:
    """Is this a real dictionary word?

    The single biggest price driver on Fragment - a word can serve a business, a
    random string cannot - and therefore the class boundary for comparables. It
    is also the one criterion the result screen states outright, so pricing a
    non-word against word listings would contradict what the user is reading.
    """
    return is_real_word(name)


def _round_price(value: float) -> int:
    """Round to two significant figures - it is an estimate, not a quote."""
    if value <= 0:
        return 0
    magnitude = 10 ** (math.floor(math.log10(value)) - 1)
    return int(round(value / magnitude) * magnitude)


def comparables(name: str, listings) -> list[float]:
    """Live Fragment asking prices genuinely comparable to ``name``.

    ``listings`` is the Fragment listing set (``FragmentListing`` items with a
    ``name`` and a ``min_bid`` string). Returns an empty list when nothing on the
    market is really like this name - which is the normal case for an ordinary
    handle, and must not be papered over with a guess.
    """
    length = len(name)
    target_quality = _quality(name)
    target_has_digit = _has_digit(name)
    target_is_word = _word_class(name)

    matched: list[tuple[float, float]] = []
    for item in listings:
        if len(item.name) != length:
            continue
        if _has_digit(item.name) != target_has_digit:
            continue
        # Same word class. A random string must not borrow the asking price of
        # dictionary words that merely happen to share its length - that is how
        # an ordinary handle came to be quoted at collectible prices.
        if _word_class(item.name) != target_is_word:
            continue
        distance = abs(_quality(item.name) - target_quality)
        if distance > QUALITY_BAND:
            continue
        price = _ton_value(item.min_bid)
        if price and price > 0:
            matched.append((distance, price))

    if len(matched) < MIN_COMPS:
        return []
    # The closest-by-quality listings are the real comparables; MAX_COMPS keeps
    # the median stable without letting a distant name drag it.
    matched.sort(key=lambda pair: pair[0])
    return [price for _, price in matched[:MAX_COMPS]]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def price_basis(name: str, listings) -> PriceBasis | None:
    """The comparables behind the estimate, or ``None`` when there are none.

    ``None`` is a real answer, not a failure: it means the name is not a traded
    collectible, so no honest price exists.
    """
    comps = comparables(name, listings)
    if not comps:
        return None
    ordered = sorted(comps)
    return PriceBasis(
        low=ordered[0],
        median=_median(comps),
        high=ordered[-1],
        count=len(comps),
    )


def estimate_price(name: str, listings) -> int | None:
    """A single estimated TON price for ``name`` from live listings, or ``None``.

    ``None`` when the market holds nothing comparable - never a substituted
    number, because a price that is not based on a listing is a fabrication.
    """
    basis = price_basis(name, listings)
    if basis is None:
        return None
    return _round_price(basis.median)
