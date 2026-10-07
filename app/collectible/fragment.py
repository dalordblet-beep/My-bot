"""Collectible username lookup.

Two sources, in strict order of trust:

1. **MTProto** - ``fragment.getCollectibleInfo``. This is Telegram's own API for
   collectible usernames: it returns the real purchase date, currency, amount
   and Fragment URL. Requires an authorised session (``scripts/login_mtproto.py``).
   When it answers, the answer is final.

2. **Fragment web page** - a read-only best-effort parse, disabled by default.
   Fragment has no public documented API, so this is fail-closed: any layout
   ambiguity becomes UNKNOWN, and prices are only reported when literally read
   from the page.

Neither source ever invents data. "Not collectible" and "unknown" are different
answers and are reported as such.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.telegram.mtproto import mtproto_client
from app.utils.enums import CollectibleStatus
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

FRAGMENT_USERNAME_URL = "https://fragment.com/username/{username}"
FRAGMENT_HOME_URL = "https://fragment.com/"

# The Fragment homepage renders the live auction table server-side: one
# <tr class="tm-row-selectable"> per collectible, with the username, its
# minimum bid (TON) and the listing status. Scraping this is how a user would
# "browse what is for sale right now" - it is a real, finite, current list,
# not a random guess.
_ROW_RE = re.compile(r'<tr class="tm-row-selectable">(.*?)</tr>', re.S)
_ROW_NAME_RE = re.compile(r'/username/([a-z0-9_]+)\"')
_ROW_BID_RE = re.compile(r'icon-ton">\s*([^\<]+?)\s*</div>')
_ROW_STATUS_RE = re.compile(r'table-cell-status-thin">\s*([^\<]+?)\s*</div>')

# A real collectible listing on Fragment always carries a live bid in TON inside
# a ``js-bid_value`` span, plus a USD value in ``js-bid_usd_value``. That single
# marker is far more trustworthy than the marketing boilerplate ("collectible
# username" appears on every page) or the "for sale" wording, which Fragment now
# shows for *any* name it offers. So presence of a bid = a real, buyable
# collectible; absence = not a collectible we can report.
_BID_TON_RE = re.compile(r'js-bid_value"[^>]*>([\d][\d\s.,]*)')
_BID_USD_RE = re.compile(r'js-bid_usd_value"[^>]*>([\d][\d\s.,]*)')
_SOLD_RE = re.compile(r"\bsold\b", re.IGNORECASE)
_PLACE_BID_RE = re.compile(r"js-place-bid-form")


@dataclass
class FragmentLookup:
    status: CollectibleStatus
    is_collectible: bool
    price: str | None = None
    owner: str | None = None
    reason: str | None = None
    marketplace: str | None = "Fragment"
    source: str | None = None
    purchase_date: str | None = None


@dataclass
class FragmentListing:
    """One collectible currently listed for sale / auction on Fragment."""

    name: str
    min_bid: str | None
    status: str | None
    url: str


class FragmentClient:
    def __init__(self, timeout: float | None = None, enabled: bool | None = None) -> None:
        self._timeout = timeout or settings.fragment_timeout
        self._enabled = settings.fragment_enabled if enabled is None else enabled
        self._session = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------ entry
    async def lookup(self, username: str) -> FragmentLookup:
        """MTProto only when it can positively confirm a collectible; the
        Fragment web source is the reliable fallback (it needs no session).

        A bot account is forbidden from calling ``fragment.getCollectibleInfo``,
        so ``_lookup_mtproto`` returns ``None`` for bot sessions and we always
        fall through to the web page, which is the source that actually works.
        """
        via_mtproto = await self._lookup_mtproto(username)
        if via_mtproto is not None and via_mtproto.is_collectible:
            return via_mtproto

        if not self._enabled:
            return FragmentLookup(
                status=CollectibleStatus.UNKNOWN,
                is_collectible=False,
                reason="needs_mtproto_login" if mtproto_client.configured else "fragment_disabled",
            )

        return await self._lookup_web(username)

    # ------------------------------------------------------------------ mtproto
    async def _lookup_mtproto(self, username: str) -> FragmentLookup | None:
        if not mtproto_client.ready:
            return None

        info = await mtproto_client.collectible_info(username)
        if info is None:
            # ``None`` means "could not confirm" (forbidden for bots, or an
            # error). We do NOT treat it as "not collectible" - the web source
            # decides. Only a real object is trusted as a positive hit.
            return None

        purchase = None
        if info.purchase_date is not None:
            try:
                purchase = info.purchase_date.strftime("%d.%m.%Y")
            except Exception:
                purchase = str(info.purchase_date)

        return FragmentLookup(
            status=CollectibleStatus.OWNED,
            is_collectible=True,
            price=info.price_label(),
            owner=None,
            source="mtproto",
            purchase_date=purchase,
        )

    # ------------------------------------------------------------------ web
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

    async def _lookup_web(self, username: str) -> FragmentLookup:
        url = FRAGMENT_USERNAME_URL.format(username=username)
        try:
            session = await self._get_session()
            # Do NOT follow redirects: a non-listed name is redirected to the
            # Fragment search page, which would otherwise render as a 200.
            async with session.get(url, allow_redirects=False) as response:
                if response.status in (301, 302, 303, 307, 308):
                    return FragmentLookup(
                        status=CollectibleStatus.NOT_DETECTED,
                        is_collectible=False,
                        reason="not_listed",
                        source="fragment_web",
                    )
                if response.status == 404:
                    return FragmentLookup(
                        status=CollectibleStatus.NOT_DETECTED,
                        is_collectible=False,
                        reason="not_listed",
                        source="fragment_web",
                    )
                if response.status == 429:
                    return FragmentLookup(
                        status=CollectibleStatus.UNKNOWN,
                        is_collectible=False,
                        reason="rate_limited",
                        source="fragment_web",
                    )
                if response.status != 200:
                    return FragmentLookup(
                        status=CollectibleStatus.UNKNOWN,
                        is_collectible=False,
                        reason=f"http_{response.status}",
                        source="fragment_web",
                    )
                html = await response.text()
        except Exception as exc:
            logger.debug("fragment lookup failed for %s: %s", username, exc)
            return FragmentLookup(
                status=CollectibleStatus.UNKNOWN,
                is_collectible=False,
                reason="request_failed",
                source="fragment_web",
            )

        return self._parse(html)

    @staticmethod
    def _parse(html: str) -> FragmentLookup:
        """Decide collectible status from a real Fragment username page.

        The only trustworthy signal is an active bid (``js-bid_value``). The
        marketing sentence "collectible username" is on every page and must be
        ignored. A page with a bid is a buyable collectible; anything else is
        not a collectible we can report.
        """
        bid_match = _BID_TON_RE.search(html)
        usd_match = _BID_USD_RE.search(html)

        if bid_match is None and not _PLACE_BID_RE.search(html):
            return FragmentLookup(
                status=CollectibleStatus.NOT_DETECTED,
                is_collectible=False,
                reason="not_listed",
                source="fragment_web",
            )

        ton = bid_match.group(1).strip().replace(" ", "") if bid_match else None
        usd = usd_match.group(1).strip().replace(" ", "") if usd_match else None

        if _SOLD_RE.search(html):
            status = CollectibleStatus.OWNED
        else:
            status = CollectibleStatus.AVAILABLE_FOR_PURCHASE

        price = None
        # A current bid of 0 means the auction just opened - show the status,
        # not a misleading "0 TON" that reads like the name is free.
        if ton:
            try:
                if float(ton.replace(",", "")) > 0:
                    price = f"{ton} TON"
            except ValueError:
                price = f"{ton} TON"
        if price is None and usd:
            try:
                if float(usd.replace(",", "")) > 0:
                    price = f"${usd}"
            except ValueError:
                price = f"${usd}"

        return FragmentLookup(
            status=status,
            is_collectible=True,
            price=price,
            owner=None,
            source="fragment_web",
        )

    # ------------------------------------------------------------------ browse
    async def browse(self, query: str, limit: int = 20) -> list[FragmentListing]:
        """Currently-listed collectibles on Fragment, filtered by a substring.

        This is the honest way to *discover* collectibles: Fragment is a finite,
        known marketplace, so you browse what is listed rather than guessing
        random names (a random string almost never collides with a real
        collectible). An empty query returns the first ``limit`` listed names.
        """
        q = (query or "").strip().lower()
        try:
            session = await self._get_session()
            async with session.get(FRAGMENT_HOME_URL, allow_redirects=False) as response:
                if response.status != 200:
                    return []
                html = await response.text()
        except Exception as exc:
            logger.debug("fragment browse failed: %s", exc)
            return []

        out: list[FragmentListing] = []
        for row in _ROW_RE.findall(html):
            name_match = _ROW_NAME_RE.search(row)
            if not name_match:
                continue
            name = name_match.group(1)
            if q and q not in name.lower():
                continue
            bid = _ROW_BID_RE.search(row)
            status = _ROW_STATUS_RE.search(row)
            out.append(
                FragmentListing(
                    name=name,
                    min_bid=bid.group(1).strip() if bid else None,
                    status=status.group(1).strip() if status else None,
                    url=FRAGMENT_USERNAME_URL.format(username=name),
                )
            )
            if limit and len(out) >= limit:
                break
        return out
