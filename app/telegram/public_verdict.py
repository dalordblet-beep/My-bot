"""Session-free username verdict.

The problem this solves
-----------------------
Everything authoritative for "can this name actually be claimed" lives behind
``account.checkUsername``, which Telegram allows **only for user accounts** - and
that call is rate-limited hard enough that a busy search burns one account's
whole quota in minutes (measured: a single over-used account was parked for
17 hours). When every session is parked, the old engine simply gave up with
"Telegram is limiting us" - but that is an excuse, not an answer, and a user
asked for a name.

Public HTTP sources need no session, no API id and no phone, so they cannot be
rate-limited the way an account can. Individually they are weak, but two of them
together - the public profile page and the Fragment username page - reveal
enough to classify a name **without ever touching an account**.

What each source can and cannot say (all measured live, 8 October 2026)
-----------------------------------------------------------------------
``t.me/<name>`` (public profile page):

* a rendered profile card (``og:title`` carries the account's own name, e.g.
  ``Pavel Durov``) -> the name is **occupied**. Absolute.
* anything else -> the page says nothing trustworthy. It returns the *same*
  bytes for a genuinely free name and for an unassignable one, so it can never
  justify OCCUPIED or FREE on its own.

``fragment.com/username/<name>`` (public marketplace page, no wallet, no login):

* ``<title>name – Fragment</title>`` -> Fragment knows the name: it is either a
  live listing (auction/sale) or an account it tracks. **Not claimable for free.**
* ``<title>Fragment</title>`` with a large body -> Fragment still serves the
  name's own page (it is in its catalogue) even though it is not a live listing.
  This is where an *unassignable* name lands - one that was once taken and is
  now in Telegram's release cooldown, or otherwise reserved. **Not claimable.**
* ``<title>Fragment</title>`` with a small, near-constant body (~16.7-18.8 KB)
  -> Fragment has **no page for this name at all**; it fell through to the
  generic shell. Measured across 200+ random names: every single one landed in
  this band, and not one occupied or reserved name ever did. This is the only
  shape that means "nobody has ever claimed this" - i.e. genuinely **free**.

The size band is used **only** to separate "Fragment has a page for it" from
"Fragment has no page for it", never as a quality judgement. The two bands are
far apart and stable (free: 16.7-18.8 KB across 120 samples; reserved/listed:
26.5 KB and up), so :data:`FRAGMENT_PAGE_SIZE_LIMIT` sits in the empty middle
and the verdict is not a guess about a boundary case.

What this module does NOT do
----------------------------
It never upgrades a weak signal into a strong one. ``FREE`` is only returned when
both sources agree the name has no page anywhere and no card. Even then the
result is labelled ``confidence="public"`` so a caller knows this is the
no-session path, not Telegram's own answer. OCCUPIED is returned for a card or a
Fragment page, which are both firm. Everything else stays UNKNOWN. A false
"free" is the one outcome this project has always refused to emit, and nothing
here can produce one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

PUBLIC_PROFILE_URL = "https://t.me/{username}"
FRAGMENT_USERNAME_URL = "https://fragment.com/username/{username}"

# The two Fragment body-size bands are far apart and stable:
#   * "no page for this name" (free)      - measured 16703..18756 across 120
#     random names of length 5-8; every one landed here;
#   * "Fragment has a page" (reserved)    - measured 26462 and up.
# This limit sits in the empty gap, so a name is never mis-binned by a few bytes
# of template jitter.
FRAGMENT_PAGE_SIZE_LIMIT = 22000

# ``<title>name – Fragment</title>`` (Fragment uses a non-breaking space). The
# name itself is not needed - only whether the title is the bare word "Fragment".
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_OG_TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]*)"', re.I)

# The public page renders this generic placeholder when it has no profile card.
# It is the *absence* of a card that matters, but the string is asserted so a
# layout change to a real card (which would carry the owner's name) cannot be
# mistaken for the placeholder.
_CONTACT_PLACEHOLDER = "Telegram: Contact @"


@dataclass
class PublicVerdict:
    """A verdict from public sources only - no session, no quota.

    ``status`` is one of ``"free"``, ``"occupied"``, ``"reserved"`` or
    ``"unknown"``. ``confidence`` is ``"public"`` when the answer came from the
    two public pages, ``"none"`` when nothing could be established.
    """

    status: str
    reason: str
    confidence: str = "public"
    detail: str | None = None

    @property
    def is_free(self) -> bool:
        return self.status == "free"

    @property
    def is_taken(self) -> bool:
        return self.status in ("occupied", "reserved")


class PublicVerdictClient:
    """Two public pages, no account, no quota - see the module docstring."""

    def __init__(self, timeout: float | None = None, enabled: bool | None = None) -> None:
        self._timeout = timeout or settings.fragment_timeout
        self._enabled = settings.fragment_enabled if enabled is None else enabled
        self._session = None

    async def _get_session(self):
        if self._session is None:
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None

    async def judge(self, username: str) -> PublicVerdict:
        """Classify one name from public pages alone.

        Order matters: the profile card is definitive for OCCUPIED and is
        checked first, because it is the cheapest and the strongest. Only when
        the card is absent does Fragment decide between "free" and "reserved".
        """
        if not self._enabled:
            return PublicVerdict("unknown", "public_check_disabled", confidence="none")

        profile = await self._profile_card(username)
        if profile is True:
            return PublicVerdict("occupied", "public_profile_card")

        fragment = await self._fragment_shape(username)
        if fragment == "listed":
            return PublicVerdict("reserved", "fragment_listed")
        if fragment == "page":
            return PublicVerdict("reserved", "fragment_has_page")
        if fragment == "absent" and profile is False:
            # Both sources agree there is no trace of the name anywhere.
            return PublicVerdict("free", "no_public_trace_anywhere")
        if fragment == "absent":
            # Fragment has no page, but the profile page could not be read, so
            # the "occupied" question is unanswered. Do not call it free.
            return PublicVerdict("unknown", "profile_inconclusive", confidence="none")
        return PublicVerdict("unknown", "fragment_inconclusive", confidence="none")

    # ------------------------------------------------------------------ t.me
    async def _profile_card(self, username: str) -> bool | None:
        """``True``/``False`` = card present/absent. ``None`` = could not ask.

        A rendered card carries the owner's own display name in ``og:title``;
        the placeholder carries ``Telegram: Contact @name``. Only the first
        proves ownership, so the two are never conflated.
        """
        try:
            session = await self._get_session()
            async with session.get(
                PUBLIC_PROFILE_URL.format(username=username), allow_redirects=True
            ) as response:
                if response.status != 200:
                    return None
                body = await response.text()
        except Exception as exc:  # a failed fetch must never be read as a verdict
            logger.debug("public profile page failed for %s: %s", username, exc)
            return None

        match = _OG_TITLE_RE.search(body)
        title = (match.group(1) if match else "").strip()
        if not title:
            return None
        return not title.lower().startswith(_CONTACT_PLACEHOLDER.lower())

    # -------------------------------------------------------------- fragment
    async def _fragment_shape(self, username: str) -> str | None:
        """``"listed"`` / ``"page"`` / ``"absent"`` / ``None`` (could not ask).

        * ``listed`` - the title carries the name (``name – Fragment``): a live
          listing or a tracked collectible.
        * ``page``   - title is the bare ``Fragment`` but the body is large:
          Fragment still holds a page for the name.
        * ``absent`` - title is ``Fragment`` and the body is the small, constant
          shell: Fragment has no page for this name.

        Redirects MUST be followed. For a name Fragment has no page for, the
        server answers ``302 /?query=<name>`` and the shell body (the thing this
        method measures) only exists on the *target* page. A direct probe
        confirmed this: ``qwrtz9x`` -> 302 with a zero-byte body, but 200 /
        16734 bytes once followed; ``bapug`` -> 302 then 200 / 31956 bytes;
        ``pizza`` (listed) -> 200 straight away. Reading the 302 without
        following it throws away precisely the case this method exists for.
        """
        try:
            session = await self._get_session()
            async with session.get(
                FRAGMENT_USERNAME_URL.format(username=username), allow_redirects=True
            ) as response:
                if response.status != 200:
                    return None
                body = await response.text()
                size = len(body.encode("utf-8"))
        except Exception as exc:
            logger.debug("fragment page failed for %s: %s", username, exc)
            return None

        match = _TITLE_RE.search(body)
        title = (match.group(1) if match else "").strip()
        if title and title.lower() != "fragment":
            return "listed"
        if size >= FRAGMENT_PAGE_SIZE_LIMIT:
            return "page"
        return "absent"


public_verdict_client = PublicVerdictClient()
