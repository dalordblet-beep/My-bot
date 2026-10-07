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
    VOWELS,
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


def _coinage(rng: random.Random, length: int) -> str:
    """Build a pronounceable, vaguely brandable string of the given length."""
    out: list[str] = []
    want_vowel = rng.random() < 0.5
    while len(out) < length:
        pool = "".join(ch for ch in LETTERS if (ch in VOWELS) == want_vowel) or LETTERS
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


def beautiful_candidates(
    *,
    seed: str | None = None,
    length: int | None = None,
    allow_digits: bool = False,
    min_score: int = 0,
    rng: random.Random | None = None,
    limit: int = 400,
) -> Iterator[str]:
    """Yield candidates ordered from most to least *findable and valuable*.

    Order matters: the finder spends one real lookup per candidate, so the
    stream has to balance two goals that pull in opposite directions - a name
    must be worth having, and it must have a real chance of being free.

    The old order (every dictionary word, then brands, then coinages) failed
    the second goal badly: the top dictionary words are all long taken, so a
    search burned its whole budget on occupied names and reported nothing. The
    order now walks tiers of *decreasing scarcity*:

    1. real words of the requested length (the most valuable, mostly taken);
    2. real words with one letter added - still word-like, far more available;
    3. word + brand suffix (``cranehq``, ``shopapp``);
    4. pronounceable coinages of the requested length.

    "Valuable" is still decided by :func:`app.search.pattern.rate` - the tier is
    only a search-order heuristic, never a second scoring system.
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
        yield from _seed_family(base, length, allow_digits, rng, limit, offer, lambda: count)
        return

    # 1. real words of the requested length, shuffled so repeated presses do not
    #    return the same handle forever
    words = [w for w in _WORD_SET if _fits(w, length, allow_digits)]
    rng.shuffle(words)
    for word in words:
        if count >= limit:
            return
        candidate = offer(word)
        if candidate:
            yield candidate

    # 2. word + one letter. Still reads as a real name, but the extra letter
    #    moves it out of the saturated "exact dictionary word" space and into
    #    one where free names genuinely exist.
    for word in words:
        for _ in range(2):
            if count >= limit:
                return
            variant = _letter_variant(word, rng)
            candidate = offer(variant)
            if candidate:
                yield candidate

    # 3. word + brand suffix ("crane" -> "cranehq", "shop" -> "shopapp")
    base_words = [w for w in _WORD_SET if 4 <= len(w) <= 7]
    rng.shuffle(base_words)
    for word in base_words:
        for suffix in BRAND_SUFFIXES:
            if count >= limit:
                return
            candidate = offer(word + suffix)
            if candidate:
                yield candidate

    # 4. hybrids of two real words ("money"+"motor" -> "moneytor"). Word-like
    #    enough to rate well, but no longer an exact dictionary word, so the
    #    supply of free candidates is far larger.
    short_words = [w for w in _WORD_SET if 3 <= len(w) <= 6]
    rng.shuffle(short_words)
    for _ in range(limit * 4):
        if count >= limit:
            return
        first = rng.choice(short_words)
        second = rng.choice(short_words)
        if first == second:
            continue
        for hybrid in _blend(first, second, rng, length)[:2]:
            if count >= limit:
                return
            candidate = offer(hybrid)
            if candidate:
                yield candidate

    # 5. two short words joined (only when the requested length allows it)
    if length is None or length >= 8:
        for _ in range(limit * 2):
            if count >= limit:
                return
            first = rng.choice(short_words)
            second = rng.choice(short_words)
            joined = _compound(first, second, length)
            if joined is None:
                continue
            candidate = offer(joined)
            if candidate:
                yield candidate

    # 6. pronounceable coinages of the requested length
    target = length or 6
    for _ in range(limit * 3):
        if count >= limit:
            return
        candidate = offer(_coinage(rng, target))
        if candidate:
            yield candidate


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


def _seed_family(
    base: str,
    length: int | None,
    allow_digits: bool,
    rng: random.Random,
    limit: int,
    offer,
    count,
) -> Iterator[str]:
    """Candidates built around a user-supplied base word."""
    emitted = 0

    name = offer(base)
    if name:
        yield name
        emitted += 1

    suffixes: list[str] = list(TECH_SUFFIXES)
    suffixes += ["coder", "engineer", "builds", "shop", "store", "team"]
    for suffix in suffixes:
        if emitted >= limit:
            return
        candidate = offer(base + suffix)
        if candidate:
            yield candidate
            emitted += 1
        if not allow_digits:
            continue
        spaced = offer(f"{base}_{suffix}")
        if spaced:
            yield spaced
            emitted += 1

    for prefix in PREFIXES:
        if emitted >= limit:
            return
        candidate = offer(prefix + base)
        if candidate:
            yield candidate
            emitted += 1

    if allow_digits:
        for number in ("1", "7", "21", "42", "99", "777"):
            if emitted >= limit:
                return
            candidate = offer(base + number)
            if candidate:
                yield candidate
                emitted += 1

    # Pronounceable coinages of the requested length, still filtered by score.
    if length:
        for _ in range(limit):
            if emitted >= limit:
                return
            candidate = offer(_coinage(rng, length))
            if candidate:
                yield candidate
                emitted += 1
