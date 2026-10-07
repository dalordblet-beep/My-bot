"""Username candidate generation.

Two jobs, deliberately separate:

* :class:`UsernameGenerator` - given a *seed* the user typed, build real,
  brandable variants (``moged`` -> ``mogedhq``, ``mogeddev``, ``moged_shop``).
  This is the "I have a word, give me something sellable" path.
* :func:`beautiful_candidates` - given nothing but a length / digit
  preference, produce candidates that are *already worth something*: real
  English words first, then word+suffix brands, then clean pronounceable
  coinages. Random letter soup is the last resort, never the first move.

The whole point is that a search result should be a handle a person would
actually want, not a collision of syllables that happens to be unoccupied.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Iterator

from app.search.pattern import (
    BRAND_SUFFIXES,
    LETTERS,
    MAX_LENGTH,
    MIN_LENGTH,
    _WORD_SET,
    rate,
)
from app.utils.username import parse_username

TECH_SUFFIXES = [
    "dev", "code", "tech", "lab", "hub", "app", "ai", "bot", "cloud", "data",
    "api", "ops", "sys", "net", "byte", "stack", "core", "pro", "x", "io",
]
GAMING_SUFFIXES = [
    "gg", "play", "game", "pro", "sniper", "king", "boss", "ace", "win", "clutch",
]
AI_SUFFIXES = [
    "ai", "gpt", "neural", "ml", "deep", "vision", "nlp", "agent", "llm", "synth",
]
PREFIXES = [
    "the", "get", "use", "my", "real", "its", "go", "hey", "mr", "iam",
]
ABBREVIATIONS = {
    "and": "n",
    "with": "w",
    "developer": "dev",
    "application": "app",
    "artificial": "ai",
    "intelligence": "ai",
}

_SEPARATOR_RE = re.compile(r"[\s\-\.]+")


@dataclass
class GeneratorOptions:
    include_numbers: bool = True
    include_underscore: bool = True
    include_tech: bool = True
    include_developer: bool = True
    include_gaming: bool = False
    include_ai: bool = True
    include_prefix: bool = False
    include_random: bool = True
    max_number: int = 99


class UsernameGenerator:
    def __init__(self, options: GeneratorOptions | None = None) -> None:
        self.options = options or GeneratorOptions()

    def generate(self, seed: str, count: int = 10) -> list[str]:
        base = self._base(seed)
        if not base:
            return []

        candidates: list[str] = []

        def add(value: str) -> None:
            value = value.strip("_")
            if not value:
                return
            parsed = parse_username(value)
            if parsed.is_valid:
                candidates.append(parsed.value)

        add(base)

        suffixes: list[str] = []
        if self.options.include_tech:
            suffixes += TECH_SUFFIXES
        if self.options.include_developer:
            suffixes += ["dev", "coder", "engineer", "builds"]
        if self.options.include_gaming:
            suffixes += GAMING_SUFFIXES
        if self.options.include_ai:
            suffixes += AI_SUFFIXES
        suffixes = self._dedupe(suffixes)

        for suffix in suffixes:
            add(base + suffix)
            if self.options.include_underscore:
                add(f"{base}_{suffix}")

        if self.options.include_prefix:
            for prefix in PREFIXES:
                add(prefix + base)

        if self.options.include_numbers:
            for number in self._numbers(base):
                add(base + number)
                if self.options.include_underscore:
                    add(f"{base}_{number}")

        if self.options.include_random:
            candidates += self._random_variants(base, count)

        result = self._dedupe(candidates)

        # Top up with random variants if we still have not reached the target.
        if len(result) < count and self.options.include_random:
            result = self._dedupe(result + self._random_variants(base, count * 3))

        return result[:count]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _base(seed: str) -> str:
        value = seed.strip().lower().lstrip("@")
        value = _SEPARATOR_RE.sub("", value)
        for word, short in ABBREVIATIONS.items():
            if word in value:
                value = value.replace(word, short)
        value = re.sub(r"[^a-z0-9_]", "", value)
        return value.strip("_")

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                ordered.append(value)
        return ordered

    def _numbers(self, base: str) -> list[str]:
        pool = ["1", "7", "11", "21", "42", "99", "123", "777", "2024", "2025"]
        if self.options.max_number > 0:
            pool += [str(random.randint(1, self.options.max_number)) for _ in range(4)]
        return self._dedupe(pool)

    def _random_variants(self, base: str, count: int) -> list[str]:
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        out: list[str] = []
        attempts = max(count, 10)
        for _ in range(attempts):
            mode = random.randint(0, 3)
            if mode == 0:
                out.append(base + "".join(random.choice(alphabet) for _ in range(2)))
            elif mode == 1:
                out.append(base + str(random.randint(1, 9999)))
            elif mode == 2:
                out.append(f"{base}_{random.choice(TECH_SUFFIXES)}{random.randint(1, 99)}")
            else:
                out.append(random.choice(PREFIXES) + base + random.choice(alphabet))
        return out


# --------------------------------------------------------------------------- beautiful
def _fits(name: str, length: int | None, allow_digits: bool) -> bool:
    if not (MIN_LENGTH <= len(name) <= MAX_LENGTH):
        return False
    if not allow_digits and any(ch.isdigit() for ch in name):
        return False
    if length is not None and len(name) != length:
        return False
    if any(ch not in LETTERS and ch != "_" for ch in name):
        return False
    return True


# Letters a coinage is built from. The "ugly" ones (q, x, j, w, z - the ones
# `pattern.sound_score` penalises) are excluded on purpose: a coinage without
# them reads cleanly, so it scores as *readable* and keeps its premium points.
_COINAGE_VOWELS = "aeiou"
_COINAGE_CONSONANTS = "bcdfghklmnprstv"


def _coinage(rng: random.Random, length: int) -> str:
    """Build a pronounceable, brandable string of the given length.

    Strict consonant/vowel alternation with a clean alphabet, so the result is
    always sayable - and, being a coinage, almost always still free.
    """
    out: list[str] = []
    want_vowel = rng.random() < 0.5
    while len(out) < length:
        pool = _COINAGE_VOWELS if want_vowel else _COINAGE_CONSONANTS
        out.append(rng.choice(pool))
        want_vowel = not want_vowel
    return "".join(out)


def _blend(word: str, other: str, rng: random.Random, target: int | None) -> list[str]:
    """Merge two real words into brandable hybrids that keep a readable root.

    ``money`` + ``motor`` -> ``moneytor``, ``motoney``. Hybrids stay word-like
    (so they still rate well) while moving out of the saturated space of exact
    dictionary words, which is where free names actually live.
    """
    out: list[str] = []
    for cut_a in range(3, len(word) - 1):
        head = word[:cut_a]
        for cut_b in range(2, len(other) - 1):
            tail = other[cut_b:]
            if target is not None and len(head) + len(tail) != target:
                continue
            out.append(head + tail)
    rng.shuffle(out)
    return out


def _compound(word: str, other: str, target: int | None) -> str | None:
    """Concatenate two short words into one long handle (``home``+``shop``)."""
    joined = word + other
    if target is not None and len(joined) != target:
        return None
    return joined


# How many "valuable" (word-like) candidates are offered before one coinage is
# mixed in. The exact dictionary words are the most desirable *and* the most
# taken, so a stream of nothing but words burns the entire lookup budget on
# occupied names and the search ends with "all taken" - which is exactly what it
# did. Interleaving guarantees a readable, almost-always-free name appears in
# the very first screen batch.
_VALUABLE_PER_COINAGE = 2


def beautiful_candidates(
    *,
    seed: str | None = None,
    length: int | None = None,
    allow_digits: bool = False,
    min_score: int = 0,
    rng: random.Random | None = None,
    limit: int = 400,
    include_coinages: bool = True,
) -> Iterator[str]:
    """Yield candidates ordered from most to least *findable and valuable*.

    Two streams are merged rather than run one after the other:

    * **valuable** - real words, word + a letter, word + brand suffix, hybrids.
      These are what a user wants, and almost all of them are already taken.
    * **coinages** - readable, brandable strings that are almost always free.

    The old order emitted the whole valuable stream first, so the finder spent
    its budget on saturated names and reported "everything is taken". Merging
    them means a free name shows up within the first few candidates, while the
    list stays full of genuinely desirable handles.

    ``include_coinages=False`` keeps a stream strictly seed-like - used by the
    variants search, where a random coinage would not be a "close alternative".
    """
    rng = rng or random.Random()
    emitted: set[str] = set()
    count = 0

    def offer(name: str) -> str | None:
        nonlocal count
        if not name or name in emitted:
            return None
        if not _fits(name, length, allow_digits):
            return None
        if rate(name).total < min_score:
            return None
        emitted.add(name)
        count += 1
        return name

    if seed:
        base = UsernameGenerator._base(seed)
        if not base:
            return
        yield from _seed_family(
            base, length, allow_digits, rng, limit, offer, lambda: count, include_coinages
        )
        return

    valuable = iter(_valuable_stream(length, allow_digits, rng, limit))
    coinages = iter(_coinage_stream(length, rng, limit) if include_coinages else ())
    valuable_done = coinages_done = False

    while count < limit and not (valuable_done and coinages_done):
        for _ in range(_VALUABLE_PER_COINAGE):
            if count >= limit:
                break
            candidate = _take(valuable, offer)
            if candidate is None:
                valuable_done = True
                break
            yield candidate
        if count >= limit:
            break

        candidate = _take(coinages, offer)
        if candidate is None:
            coinages_done = True
        else:
            yield candidate


def _take(iterator: Iterator[str], offer) -> str | None:
    """Pull the next candidate ``offer`` accepts, or None once exhausted."""
    for name in iterator:
        accepted = offer(name)
        if accepted is not None:
            return accepted
    return None


def _valuable_stream(
    length: int | None, allow_digits: bool, rng: random.Random, limit: int
) -> Iterator[str]:
    """Word-like candidates, most valuable first - and most taken."""
    words = [w for w in _WORD_SET if _fits(w, length, allow_digits)]
    rng.shuffle(words)
    yield from words

    # word + one letter: still reads as a real name, far more available
    for word in words:
        for _ in range(2):
            yield _letter_variant(word, rng)

    # word + brand suffix ("crane" -> "cranehq")
    base_words = [w for w in _WORD_SET if 4 <= len(w) <= 7]
    rng.shuffle(base_words)
    for word in base_words:
        for suffix in BRAND_SUFFIXES:
            yield word + suffix

    # hybrids of two real words ("money"+"motor" -> "moneytor")
    short_words = [w for w in _WORD_SET if 3 <= len(w) <= 6]
    if short_words:
        rng.shuffle(short_words)
        for _ in range(max(1, limit) * 4):
            first = rng.choice(short_words)
            second = rng.choice(short_words)
            if first == second:
                continue
            yield from _blend(first, second, rng, length)[:2]

        # two short words joined ("home"+"shop")
        if length is None or length >= 8:
            for _ in range(max(1, limit) * 2):
                first = rng.choice(short_words)
                second = rng.choice(short_words)
                joined = _compound(first, second, length)
                if joined is not None:
                    yield joined


def coinage_candidates(
    *,
    length: int | None = None,
    allow_digits: bool = False,
    min_score: int = 0,
    rng: random.Random | None = None,
    limit: int = 400,
) -> Iterator[str]:
    """Pure pronounceable coinages - the stream that makes a free name certain.

    ``beautiful_candidates`` interleaves these with real words so a search has
    something desirable to offer first. This is the same generator standing on
    its own: an effectively unlimited supply of clean, readable names that are
    almost never registered.

    The finder's guarantee pass uses it: once the desirable real-word stream has
    had its chance, a search given a length and a digit preference keeps going
    here until it lands a genuinely free name, instead of stopping at "all
    taken". Every emitted name clears the same length / digit / score gates as
    any other candidate, so the guarantee cannot produce a name the bot would
    otherwise have rejected.
    """
    rng = rng or random.Random()
    emitted = 0
    seen: set[str] = set()
    while emitted < limit:
        name = _coinage(rng, length or 6)
        if name in seen:
            continue
        seen.add(name)
        if not _fits(name, length, allow_digits):
            continue
        if rate(name).total < min_score:
            continue
        emitted += 1
        yield name


def _coinage_stream(length: int | None, rng: random.Random, limit: int) -> Iterator[str]:
    """Readable coinages - the stream that actually guarantees a free name.

    The supply is effectively unlimited, so it is bounded generously and merged
    into the valuable stream rather than parked at the end of it.
    """
    target = length or 6
    for _ in range(max(1, limit) * 20):
        yield _coinage(rng, target)


def _letter_variant(word: str, rng: random.Random) -> str:
    """Add or swap one letter so a real word becomes a plausible, freer handle."""
    if rng.random() < 0.5:
        return word + rng.choice(LETTERS)
    if len(word) < 3:
        return word
    position = rng.randrange(len(word))
    replacement = rng.choice(LETTERS)
    if replacement == word[position]:
        return word
    return word[:position] + replacement + word[position + 1:]


def _root_variant(base: str, rng: random.Random, length: int | None) -> str:
    """A name built around ``base``: append a short pronounceable tail, swap one
    letter for a similar one, or lead with a consonant. It still reads like the
    seed but is almost always unclaimed - and, because the pool is shuffled by
    the caller, a different twist comes out every run.
    """
    target = length or (len(base) + rng.choice([1, 2]))
    target = max(MIN_LENGTH, min(MAX_LENGTH, target))

    if len(base) < target:
        # Append a short pronounceable tail - the most "similar" twist.
        name = base + _coinage(rng, target - len(base))
    elif len(base) >= 3:
        # Swap one letter for a similar-sounding one.
        pos = rng.randrange(len(base))
        pool = _COINAGE_CONSONANTS if base[pos] in _COINAGE_CONSONANTS else _COINAGE_VOWELS
        name = base[:pos] + rng.choice(pool) + base[pos + 1:]
    else:
        name = _coinage(rng, target)
    return name[:target]


def _seed_family(
    base: str,
    length: int | None,
    allow_digits: bool,
    rng: random.Random,
    limit: int,
    offer,
    count,
    include_coinages: bool = True,
) -> Iterator[str]:
    """Candidates built around a user-supplied base word.

    Shuffled and sub-sampled on purpose: "find similar" must hand back a
    *different* beautiful set every time it is pressed, not the same fixed
    scenario. A handful of near-root coinages keeps the names similar to the
    seed while almost always being free.
    """
    # Random pool sizes so each run picks different affixes from the seed.
    suffixes = list(TECH_SUFFIXES) + ["coder", "engineer", "builds", "shop", "store", "team", "hq", "x"]
    rng.shuffle(suffixes)
    suffixes = suffixes[: rng.randint(5, min(9, len(suffixes)))]

    prefixes = list(PREFIXES)
    rng.shuffle(prefixes)
    prefixes = prefixes[: rng.randint(2, min(4, len(prefixes)))]

    numbers = ["1", "7", "21", "42", "99", "777"]
    rng.shuffle(numbers)
    numbers = numbers[: rng.randint(2, len(numbers))]

    emitted = 0

    def valuable() -> Iterator[str]:
        yield base
        for suffix in suffixes:
            yield base + suffix
            if allow_digits:
                yield f"{base}_{suffix}"
        for prefix in prefixes:
            yield prefix + base
        for number in numbers:
            yield base + number
        # Near-root coinages: same root, one twist - similar *and* usually free.
        for _ in range(rng.randint(4, 10)):
            yield _root_variant(base, rng, length)

    coinage_length = length or max(MIN_LENGTH, min(MAX_LENGTH, len(base) + 2))

    def coinages() -> Iterator[str]:
        for _ in range(max(1, limit) * 20):
            yield _coinage(rng, coinage_length)

    valuable_it = iter(valuable())
    coinage_it = iter(coinages()) if include_coinages else iter(())
    valuable_done = False
    coinages_done = not include_coinages

    while emitted < limit and not (valuable_done and coinages_done):
        for _ in range(_VALUABLE_PER_COINAGE):
            if emitted >= limit:
                break
            candidate = _take(valuable_it, offer)
            if candidate is None:
                valuable_done = True
                break
            emitted += 1
            yield candidate
        if emitted >= limit:
            break

        candidate = _take(coinage_it, offer)
        if candidate is None:
            coinages_done = True
        else:
            emitted += 1
            yield candidate
