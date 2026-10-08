"""Collectible username engine.

Kept fully separate from the basic checker. Collectible usernames are Telegram
usernames that were auctioned/sold on Fragment; the only public source of
ownership and listing state is Fragment itself.

Rules:
* never invent an owner, price or listing state,
* when a source is unavailable the answer is UNKNOWN,
* **"unowned" does not mean "not a collectible".** A collectible can be owned
  on-chain (its wallet holds the NFT) without being linked to any Telegram
  account, so ``contacts.resolveUsername`` answers ``not_occupied`` for it. The
  only source that knows is Fragment, so ownership is decided there - an
  earlier shortcut that trusted ``not_occupied`` mislabelled real, listed names
  (e.g. ``roundup`` at 556 TON) as "not listed".
"""

from __future__ import annotations

from app.collectible.fragment import FragmentClient
from app.config import settings
from app.telegram.mtproto import mtproto_client
from app.utils.enums import CollectibleStatus
from app.utils.logging_setup import get_logger
from app.utils.results import CollectibleResult
from app.utils.username import parse_username

logger = get_logger(__name__)


class CollectibleChecker:
    def __init__(self, fragment: FragmentClient | None = None) -> None:
        self._fragment = fragment or FragmentClient()

    @property
    def fragment(self) -> FragmentClient:
        return self._fragment

    async def close(self) -> None:
        await self._fragment.close()

    async def check_collectible_username(self, username: str) -> CollectibleResult:
        parsed = parse_username(username)
        if not parsed.is_valid:
            return CollectibleResult(
                username=parsed.value or parsed.raw,
                status=CollectibleStatus.UNKNOWN,
                is_collectible=False,
                reason=parsed.reason or "invalid_username",
            )

        name = parsed.value

        # Fragment is the only source that knows ownership. Do NOT short-circuit
        # on "not_occupied": an unassigned collectible (owned on-chain, not
        # linked to any account) resolves exactly that way, yet is a real,
        # listed name.
        lookup = await self._fragment.lookup(name)

        source = lookup.source or "fragment"

        if lookup.status is CollectibleStatus.UNKNOWN:
            return CollectibleResult(
                username=name,
                status=CollectibleStatus.UNKNOWN,
                is_collectible=False,
                source=source,
                reason=lookup.reason,
            )

        return CollectibleResult(
            username=name,
            status=lookup.status,
            is_collectible=lookup.is_collectible,
            marketplace=lookup.marketplace if lookup.is_collectible else None,
            owner=lookup.owner,
            price=lookup.price,
            purchase_date=lookup.purchase_date,
            source=source,
            reason=lookup.reason,
        )

    @staticmethod
    def engine_status() -> str:
        """'ok' when a real source is wired up, otherwise 'disabled'."""
        if mtproto_client.ready or settings.fragment_enabled:
            return "ok"
        return "disabled"


def collectible_engine_available() -> bool:
    """True when collectible lookups can actually return data."""
    return mtproto_client.ready or settings.fragment_enabled
