"""Collectible username engine.

Kept fully separate from the basic checker. Collectible usernames are Telegram
usernames that were auctioned/sold on Fragment; the only public source of
ownership and listing state is Fragment itself.

Rules:
* never invent an owner, price or listing state,
* when a source is unavailable the answer is UNKNOWN,
* a username that is provably unoccupied cannot be collectible.
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

        # A name nobody owns cannot be a collectible.
        if mtproto_client.ready:
            mt = await mtproto_client.resolve_username(name)
            if mt.kind == "not_occupied":
                return CollectibleResult(
                    username=name,
                    status=CollectibleStatus.NOT_DETECTED,
                    is_collectible=False,
                    source="mtproto",
                    reason="username_unoccupied",
                )
            if mt.kind in ("flood", "error", "unknown"):
                logger.debug("collectible pre-check inconclusive for %s: %s", name, mt.kind)

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
