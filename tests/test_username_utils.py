"""Username normalisation and validation."""

from __future__ import annotations

import pytest

from app.utils.username import normalize_username, parse_username, validate_username


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("@moged", "moged"),
        ("moged", "moged"),
        ("https://t.me/moged", "moged"),
        ("http://t.me/moged", "moged"),
        ("t.me/moged", "moged"),
        ("  @Moged  ", "Moged"),
        ("https://t.me/moged?start=1", "moged"),
        ("https://t.me/moged/", "moged"),
        ("telegram.me/moged", "moged"),
        ("@ mo ged", "moged"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize_username(raw) == expected


@pytest.mark.parametrize(
    "value",
    ["moged", "a_b_c", "username123", "abcdef", "x" * 32],
)
def test_validate_ok(value):
    ok, reason = validate_username(value)
    assert ok, reason


@pytest.mark.parametrize(
    "value,reason",
    [
        ("", "empty_input"),
        ("abc", "too_short_min_5"),
        ("x" * 33, "too_long_max_32"),
        ("has space", "invalid_characters"),
        ("has-dash", "invalid_characters"),
        ("1abcde", "must_start_with_a_letter"),
        ("ab__cd", "consecutive_underscores"),
        ("abcde_", "cannot_end_with_underscore"),
        ("joinchat", "reserved_telegram_path"),
    ],
)
def test_validate_rejects(value, reason):
    ok, actual = validate_username(value)
    assert not ok
    assert actual == reason


def test_parse_lowercases_and_flags():
    parsed = parse_username("@MoGeD")
    assert parsed.is_valid
    assert parsed.value == "moged"
    assert parsed.display == "@moged"


def test_parse_invalid_keeps_reason():
    parsed = parse_username("@ab")
    assert not parsed.is_valid
    assert parsed.reason == "too_short_min_5"
