"""Public t.me page probe - a second, independent availability signal.

Why this exists
---------------
The Bot API's ``getChat`` can only resolve channels, supergroups and bots. For a
username owned by a *personal account* it answers "chat not found", which looks
exactly like a free username. Verified against the live API:

    @mogeds2 (owned by a person) -> getChat: "chat not found"

Treating that as AVAILABLE is wrong, and it was the source of false positives.

What the page actually means
----------------------------
Verified against the live pages. There are two distinct layouts:

**Taken - a real profile card.** ``tgme_page_title`` is present and the
``og:title`` is the person's/channel's *display name* (not the handle):

    mogeds2 -> og:title = "Mogeds"
    durov   -> og:title = "Pavel Durov"

**The "Contact" placeholder.** No ``tgme_page_title``; the body is the generic
"You can contact @name right away" invitation with a ``tgme_icon_user`` icon.

That placeholder is **not proof that the name is free** - Telegram shows it for
any name that has no public profile card, regardless of whether somebody owns it
(verified: ``love``, ``crane`` and ``money`` all render it despite being owned).
So the placeholder is reported as ``UNKNOWN``, never as FREE. A name is only
reported free when the page is *positively* shaped like a free handle (a
redirect to the signup flow), and confirmation of availability is left to
MTProto, which is the only channel that can answer it authoritatively.

This is a *confirmation* layer, never a primary source: it can rule a name out
(mark it occupied) but it never invents a "free" verdict out of a placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import aiohttp

from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

PREVIEW_URL = "https://t.me/{username}"
TIMEOUT_SECONDS = 8.0

_PROFILE_MARKER = re.compile(r'class="tgme_page_title"')
_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')
# The generic "you can contact @name" invitation. It means "no profile card",
# which is *not* the same thing as "nobody owns this name".
_CONTACT_PLACEHOLDER = re.compile(r"You can contact\s*<a[^>]*>@", re.IGNORECASE)
_CONTACT_PLACEHOLDER_ALT = re.compile(r"Telegram:\s*Contact\s*@", re.IGNORECASE)
# A free handle is sent to the signup/login flow instead of a preview card.
_SIGNUP_MARKER = re.compile(r"tgme_page_action|/login\b|tg://login", re.IGNORECASE)

OCCUPIED = "occupied"
FREE = "free"
UNKNOWN = "unknown"


@dataclass
class PublicPageResult:
    state: str
    title: str | None = None
    reason: str | None = None

    @property
    def is_occupied(self) -> bool:
        return self.state == OCCUPIED

    @property
    def is_free(self) -> bool:
        return self.state == FREE


class PublicPageProbe:
    """Reuses one HTTP session; fails closed on anything unexpected."""

    def __init__(self, timeout: float = TIMEOUT_SECONDS) -> None:
        self._timeout = timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
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
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass
        self._session = None

    async def check(self, username: str) -> PublicPageResult:
        url = PREVIEW_URL.format(username=username)
        try:
            session = await self._get_session()
            async with session.get(url, allow_redirects=False) as response:
                if response.status in (301, 302):
                    # Short/invalid names redirect instead of rendering a page.
                    return PublicPageResult(UNKNOWN, reason="redirect")
                if response.status == 404:
                    return PublicPageResult(FREE, reason="http_404")
                if response.status != 200:
                    return PublicPageResult(UNKNOWN, reason=f"http_{response.status}")
                body = await response.text()
        except Exception as exc:
            logger.debug("public page probe failed for %s: %s", username, exc)
            return PublicPageResult(UNKNOWN, reason="request_failed")

        return self.parse(body)

    @staticmethod
    def parse(body: str) -> PublicPageResult:
        # 1. A rendered profile card is decisive: somebody owns the name.
        if _PROFILE_MARKER.search(body):
            title_match = _TITLE_RE.search(body)
            title = title_match.group(1).strip() if title_match else None
            return PublicPageResult(OCCUPIED, title=title)

        # 2. The generic "contact @name" placeholder means only that there is no
        #    public card. Real, owned accounts render it too, so it must never be
        #    promoted to FREE - that was the bug behind "it finds taken names".
        if _CONTACT_PLACEHOLDER.search(body) or _CONTACT_PLACEHOLDER_ALT.search(body):
            return PublicPageResult(UNKNOWN, reason="no_profile_card")

        # 3. The signup/login flow is what a genuinely unclaimed handle shows.
        if _SIGNUP_MARKER.search(body):
            return PublicPageResult(FREE, reason="signup_flow")

        # A 200 page with none of the markers means the layout changed. Never guess.
        return PublicPageResult(UNKNOWN, reason="unrecognised_page")

