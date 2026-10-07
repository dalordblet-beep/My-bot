"""Username variant generator."""

from __future__ import annotations

from app.search.generator import GeneratorOptions, UsernameGenerator
from app.utils.username import parse_username


def test_generates_requested_amount():
    generator = UsernameGenerator()
    variants = generator.generate("moged", count=50)
    assert len(variants) == 50


def test_every_variant_is_valid_and_unique():
    generator = UsernameGenerator()
    variants = generator.generate("moged", count=100)
    assert len(variants) == len(set(variants))
    for variant in variants:
        assert parse_username(variant).is_valid, variant


def test_base_word_comes_first():
    generator = UsernameGenerator()
    variants = generator.generate("moged", count=10)
    assert variants[0] == "moged"


def test_expected_families_are_present():
    generator = UsernameGenerator()
    variants = generator.generate("moged", count=100)
    joined = " ".join(variants)
    assert "mogeddev" in joined
    assert "mogedai" in joined
    assert "mogedtech" in joined


def test_seed_is_normalised():
    generator = UsernameGenerator()
    variants = generator.generate("@MoGeD", count=10)
    assert all(variant.islower() for variant in variants)
    assert variants[0] == "moged"


def test_options_toggle_families():
    generator = UsernameGenerator(
        GeneratorOptions(
            include_numbers=False,
            include_underscore=False,
            include_tech=True,
            include_developer=False,
            include_gaming=False,
            include_ai=False,
            include_prefix=False,
            include_random=False,
        )
    )
    variants = generator.generate("moged", count=200)
    assert "moged" in variants
    assert "mogeddev" in variants
    assert "moged_" not in " ".join(variants)
    assert all(not any(char.isdigit() for char in variant) for variant in variants)


def test_short_seed_is_padded_into_valid_names():
    generator = UsernameGenerator()
    variants = generator.generate("abc", count=20)
    assert variants
    for variant in variants:
        assert parse_username(variant).is_valid, variant


def test_empty_seed_yields_nothing():
    generator = UsernameGenerator()
    assert generator.generate("", count=10) == []
    assert generator.generate("!!!", count=10) == []


# ----------------------------------------------------- search-order regression
def test_beautiful_candidates_mix_free_names_into_the_first_batch():
    """A stream of nothing but dictionary words burns the whole lookup budget.

    The exact words are the most desirable *and* the most taken, so a coinage
    has to appear almost immediately - within the first screen batch.
    """
    import random

    from app.search.generator import beautiful_candidates
    from app.search.pattern import is_real_word

    names = list(beautiful_candidates(length=6, rng=random.Random(1), limit=40))
    assert len(names) >= 6
    # At least one non-dictionary (i.e. plausibly free) name in the first six.
    assert any(not is_real_word(name) for name in names[:6]), names[:6]


def test_coinages_avoid_the_ugly_letters():
    """q/x/j/w/z are penalised by sound_score - a coinage must not use them."""
    import random

    from app.search.generator import _coinage

    rng = random.Random(5)
    for length in (5, 6, 8, 10):
        for _ in range(50):
            name = _coinage(rng, length)
            assert len(name) == length
            assert not (set(name) & set("qxjwz")), name
