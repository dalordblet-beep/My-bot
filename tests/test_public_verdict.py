"""The session-free classifier, and the search path that uses it.

Two things are under test, and they are really one promise: when Telegram's own
channels are unavailable, the bot must still tell the truth about a real name
rather than answer with an excuse ("Telegram is limiting us") or invent a result.

The classifier is the mechanism. These tests pin its decision table against
*recorded* page shapes - the exact bodies measured live from ``t.me`` and
``fragment.com`` - so the mapping from bytes to verdict cannot silently drift.
No test here touches the network: the HTTP layer is stubbed with the measured
responses.
"""

from __future__ import annotations

import pytest

from app.telegram import public_verdict as pv
from app.telegram.public_verdict import (
    FRAGMENT_PAGE_SIZE_LIMIT,
    PublicVerdict,
    PublicVerdictClient,
)


# --------------------------------------------------------------- page shapes
def _profile_card(owner: str) -> str:
    """A real profile page: ``og:title`` carries the owner's own name."""
    return (
        "<html><head>"
        f'<meta property="og:title" content="{owner}">'
        "</head><body></body></html>"
    )


def _profile_placeholder(name: str) -> str:
    """A page with no account behind it - the generic contact shell."""
    return (
        "<html><head>"
        f'<meta property="og:title" content="Telegram: Contact @{name}">'
        "</head><body></body></html>"
    )


def _fragment_listed(name: str) -> str:
    """A live listing / tracked collectible: the title carries the name."""
    return f"<html><head><title>{name} \u2013 Fragment</title></head><body>{'x' * 30000}</body></html>"


def _fragment_page(reserved: bool = True) -> str:
    """Fragment serves a real page for the name, but it is not a live listing."""
    size = 31953 if reserved else 20000
    return f"<html><head><title>Fragment</title></head><body>{'x' * size}</body></html>"


def _fragment_absent() -> str:
    """The small, near-constant shell Fragment shows when it has no page."""
    return "<html><head><title>Fragment</title></head><body>" + "x" * 16000 + "</body></html>"


class _Response:
    def __init__(self, status: int, body: str, history: tuple = ()) -> None:
        self.status = status
        self._body = body
        # aiohttp's final response carries the redirect trail here. Fragment
        # answers "no page" with a 302, so a genuine absent shell always has
        # one; an anti-bot shell answers a direct 200 with an empty trail.
        self.history = history

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


_REDIRECT = (_Response(302, ""),)


class _FakeSession:
    """Routes the two public URLs to canned bodies, per name."""

    def __init__(self, profile: dict[str, str], fragment: dict[str, str]) -> None:
        self._profile = profile
        self._fragment = fragment

    def get(self, url: str, allow_redirects: bool = True):
        if url.startswith(pv.PUBLIC_PROFILE_URL.split("{")[0]):
            name = url.rsplit("/", 1)[-1]
            body = self._profile.get(name)
            return _Response(200, body) if body is not None else _Response(404, "")
        if url.startswith(pv.FRAGMENT_USERNAME_URL.split("{")[0]):
            name = url.rsplit("/", 1)[-1]
            body = self._fragment.get(name)
            # Fragment follows a 302 for names it has no page for, so canned
            # fragment bodies arrive as the redirect target by default.
            return (
                _Response(200, body, history=_REDIRECT)
                if body is not None
                else _Response(404, "")
            )
        return _Response(404, "")


async def _client(profile, fragment) -> PublicVerdictClient:
    client = PublicVerdictClient(enabled=True)
    client._session = _FakeSession(profile, fragment)  # noqa: SLF001 - test seam
    return client


# ------------------------------------------------------------------- mapping
async def test_a_profile_card_means_occupied():
    """The owner's own name in og:title is absolute proof of ownership."""
    client = await _client({"durov": _profile_card("Pavel Durov")}, {})
    verdict = await client.judge("durov")
    assert verdict.status == "occupied"
    assert verdict.reason == "public_profile_card"


async def test_a_listing_means_reserved():
    """Fragment knows the name as a listing - it cannot be claimed for free."""
    client = await _client(
        {"pizza": _profile_placeholder("pizza")}, {"pizza": _fragment_listed("pizza")}
    )
    verdict = await client.judge("pizza")
    assert verdict.status == "reserved"
    assert verdict.reason == "fragment_listed"


async def test_a_large_bare_page_means_reserved():
    """Fragment has a page but no listing: an unassignable / tracked name."""
    client = await _client(
        {"bapug": _profile_placeholder("bapug")}, {"bapug": _fragment_page()}
    )
    verdict = await client.judge("bapug")
    assert verdict.status == "reserved"
    assert verdict.reason == "fragment_has_page"


async def test_the_small_shell_on_both_sources_means_free():
    """No card and no Fragment page is the only shape that can mean free."""
    client = await _client(
        {"qwrtz9x": _profile_placeholder("qwrtz9x")}, {"qwrtz9x": _fragment_absent()}
    )
    verdict = await client.judge("qwrtz9x")
    assert verdict.status == "free"
    assert verdict.reason == "no_public_trace_anywhere"
    assert verdict.is_free is True


async def test_a_direct_small_shell_is_never_free():
    """The false-free hole, pinned shut.

    Anti-bot / captcha shells are the same small size with the same bare
    "Fragment" title as a genuine no-page answer. The difference is the
    redirect: Fragment answers 302 for a name it has no page for, while a
    challenge shell answers a direct 200. A direct 200 small shell must
    therefore stay inconclusive - it can never be reported as free.
    """
    shell = _fragment_absent()
    client = PublicVerdictClient(enabled=True)
    client._session = _FakeSession(  # noqa: SLF001 - test seam
        {"shellup": _profile_placeholder("shellup")}, {}
    )
    # Serve the shell as a direct 200 with no redirect trail - exactly how a
    # challenge page answers, unlike Fragment's own 302-then-shell.
    client._session.get = lambda url, allow_redirects=True: (  # noqa: SLF001
        _Response(200, shell)
        if url.startswith(pv.FRAGMENT_USERNAME_URL.split("{")[0])
        else _Response(200, _profile_placeholder("shellup"))
    )

    verdict = await client.judge("shellup")
    assert verdict.status != "free"
    assert verdict.is_taken is False


async def test_a_bare_placeholder_with_no_fragment_answer_is_never_free():
    """A dead Fragment must leave the verdict unknown, not optimistic."""
    client = await _client({"x9k2qq": _profile_placeholder("x9k2qq")}, {})
    verdict = await client.judge("x9k2qq")
    assert verdict.status not in ("free",)
    assert verdict.confidence == "none"


async def test_the_size_limit_sits_in_the_empty_gap_between_the_bands():
    """The threshold separates "Fragment has a page" from "it does not".

    Measured: free/no-page bodies stay at or below ~18.8 KB, and a real page
    starts at 26.5 KB, so anything either side of the size limit is far from
    template jitter. This pins the direction of the comparison: just above is a
    page, just below is not.
    """
    big = "<html><head><title>Fragment</title></head><body>" + "x" * (
        FRAGMENT_PAGE_SIZE_LIMIT + 100
    ) + "</body></html>"
    client = await _client({"edgehi": _profile_placeholder("edgehi")}, {"edgehi": big})
    assert (await client.judge("edgehi")).status == "reserved"

    small = "<html><head><title>Fragment</title></head><body>" + "x" * (
        FRAGMENT_PAGE_SIZE_LIMIT - 100
    ) + "</body></html>"
    client = await _client({"edgelo": _profile_placeholder("edgelo")}, {"edgelo": small})
    assert (await client.judge("edgelo")).status == "free"


async def test_the_classifier_is_disabled_when_fragment_is_disabled():
    """With the public source switched off, nothing is claimed."""
    client = PublicVerdictClient(enabled=False)
    verdict = await client.judge("anything")
    assert verdict.status == "unknown"
    assert verdict.confidence == "none"


def test_a_public_verdict_knows_whether_it_is_free_or_taken():
    assert PublicVerdict("free", "r").is_free is True
    assert PublicVerdict("occupied", "r").is_taken is True
    assert PublicVerdict("reserved", "r").is_taken is True
    assert PublicVerdict("unknown", "r", confidence="none").is_taken is False
