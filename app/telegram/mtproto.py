"""Telethon (MTProto) client manager.

MTProto is the only channel that can authoritatively answer "is this username
free?" — Telegram raises ``UsernameNotOccupiedError`` for a name that nobody
owns. The Bot API cannot distinguish "free" from "reserved/deleted", so we
never derive AVAILABLE from it.

The client is optional. If it is not configured or not authorised, every call
degrades to ``UNKNOWN`` instead of inventing an answer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

# Telegram's own shape for a username (documented alongside USERNAME_INVALID):
# r'[a-zA-Z][\w\d]{3,30}[a-zA-Z\d]'. Kept here for reference and diagnostics;
# the resolver no longer branches on it, because a shape-valid handle can still
# be unassignable (see resolve_username).

try:  # Telethon is a hard requirement, but import errors must not crash boot.
    from telethon import TelegramClient
    from telethon.errors import (
        FloodWaitError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    )
    from telethon.errors.rpcerrorlist import UsernameOccupiedError
    from telethon.tl.functions.contacts import ResolveUsernameRequest
    from telethon.tl.functions.fragment import GetCollectibleInfoRequest
    from telethon.tl.types import Channel, Chat, InputCollectibleUsername
    from telethon.tl.types import User as TgUser

    TELETHON_AVAILABLE = True
except Exception:  # pragma: no cover
    TELETHON_AVAILABLE = False
    TelegramClient = None  # type: ignore[assignment]


class MtprotoCollectible:
    """Authoritative collectible data straight from Telegram (fragment.*)."""

    __slots__ = ("url", "purchase_date", "fiat_currency", "fiat_amount",
                 "crypto_currency", "crypto_amount")

    def __init__(
        self,
        url: str,
        purchase_date: Any = None,
        fiat_currency: str | None = None,
        fiat_amount: float | None = None,
        crypto_currency: str | None = None,
        crypto_amount: float | None = None,
    ) -> None:
        self.url = url
        self.purchase_date = purchase_date
        self.fiat_currency = fiat_currency
        self.fiat_amount = fiat_amount
        self.crypto_currency = crypto_currency
        self.crypto_amount = crypto_amount

    def price_label(self) -> str | None:
        """Human-readable original purchase price, e.g. ``12.5 TON``."""
        if self.crypto_amount is not None and self.crypto_currency:
            return f"{self.crypto_amount:g} {self.crypto_currency}"
        if self.fiat_amount is not None and self.fiat_currency:
            return f"{self.fiat_amount:g} {self.fiat_currency}"
        return None


class MtprotoResult:
    __slots__ = ("kind", "detail", "entity_type", "entity_id", "title")

    def __init__(
        self,
        kind: str,
        detail: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        title: str | None = None,
    ) -> None:
        self.kind = kind  # occupied | not_occupied | invalid | flood | unknown | error
        self.detail = detail
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.title = title


class MtprotoClient:
    def __init__(self) -> None:
        self._client: Any | None = None
        self._lock = asyncio.Lock()
        self._ready = False

    @property
    def configured(self) -> bool:
        return TELETHON_AVAILABLE and settings.mtproto_configured

    @property
    def ready(self) -> bool:
        return self._ready

    async def start(self) -> bool:
        if not self.configured:
            logger.warning("mtproto not configured (API_ID/API_HASH missing)")
            return False
        if self._client is not None:
            return self._ready
        try:
            # When a bot token is available the session is self-healing: a
            # missing or wiped session (for example, one deleted by an aborted
            # interactive login) is re-authorised as the bot automatically, with
            # no phone number and no code. That is exactly what the availability
            # checks require, and it stops the silent failure where the session
            # was deleted and every name then came back UNKNOWN.
            if settings.bot_token:
                self._client = TelegramClient(
                    settings.mtproto_session, settings.api_id, settings.api_hash
                )
                await self._client.start(bot_token=settings.bot_token)
                self._ready = await self._client.is_user_authorized()
                if not self._ready:
                    # A stale or half-finished session left an unauthorised
                    # shell. Drop it and log the bot in fresh by token.
                    logger.warning(
                        "mtproto session unauthorised - re-authorising as bot by token"
                    )
                    await self._safe_disconnect()
                    self._remove_session_files()
                    self._client = TelegramClient(
                        settings.mtproto_session, settings.api_id, settings.api_hash
                    )
                    await self._client.start(bot_token=settings.bot_token)
                    self._ready = await self._client.is_user_authorized()
            else:
                self._client = TelegramClient(
                    settings.mtproto_session, settings.api_id, settings.api_hash
                )
                await self._client.start()
                self._ready = await self._client.is_user_authorized()
                if not self._ready:
                    logger.warning(
                        "mtproto session is not authorised - run scripts/login_mtproto.py"
                    )

            if self._ready:
                logger.info("mtproto connected and authorised")
        except Exception as exc:
            logger.error("mtproto start failed: %s", exc)
            self._client = None
            self._ready = False
        return self._ready

    def _remove_session_files(self) -> None:
        """Delete the on-disk session so a fresh login can start clean."""
        base = settings.mtproto_session
        for path in (Path(f"{base}.session"), Path(f"{base}.session-journal")):
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:  # pragma: no cover - filesystem dependent
                logger.debug("could not remove %s: %s", path, exc)

    async def _safe_disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._ready = False

    async def resolve_username(self, username: str) -> MtprotoResult:
        if not self._ready or self._client is None:
            return MtprotoResult("unknown", "mtproto_unavailable")

        async with self._lock:
            try:
                response = await self._client(ResolveUsernameRequest(username))
            except UsernameNotOccupiedError:
                return MtprotoResult("not_occupied")
            except UsernameInvalidError:
                # Telegram answers USERNAME_INVALID both for a malformed handle
                # and for a valid-shaped handle it will not hand out: reserved
                # names, recently released ones still in cooldown, Fragment
                # stock, patterns its anti-abuse dislikes. The one call that
                # separates "unowned" from "unassignable" is
                # account.checkUsername, and it is user-only
                # (BotMethodInvalidError for bots - verified live), so the two
                # cases cannot be told apart here. Mapping the valid-shaped ones
                # to "free" anyway made the search hand out handles Telegram then
                # rejects with "username is invalid" at claim time - a false
                # available verdict, the worst thing this bot can emit. So
                # INVALID is never a free verdict: the search skips it and keeps
                # hunting for a name Telegram answers USERNAME_NOT_OCCUPIED for,
                # which is the only signal it honours at claim time.
                return MtprotoResult("invalid")
            except FloodWaitError as exc:  # pragma: no cover - network dependent
                return MtprotoResult("flood", str(exc.seconds))
            except UsernameOccupiedError:
                return MtprotoResult("occupied", "occupied_error")
            except Exception as exc:
                name = type(exc).__name__
                if "FloodWait" in name:
                    seconds = getattr(exc, "seconds", None)
                    return MtprotoResult("flood", str(seconds) if seconds else None)
                logger.debug("resolve_username(%s) failed: %s", username, exc)
                return MtprotoResult("error", name)

            return self._classify(response)

    async def collectible_info(self, username: str) -> MtprotoCollectible | None:
        """Authoritative collectible lookup via ``fragment.getCollectibleInfo``.

        This is Telegram's own API for collectible usernames - no scraping, no
        guessing. Returns ``None`` when the session is unavailable or when
        Telegram reports that the username is not collectible.
        """
        if not self._ready or self._client is None:
            return None

        async with self._lock:
            try:
                info = await self._client(
                    GetCollectibleInfoRequest(
                        collectible=InputCollectibleUsername(username=username)
                    )
                )
            except FloodWaitError as exc:  # pragma: no cover - network dependent
                logger.warning("fragment flood wait %ss", exc.seconds)
                return None
            except Exception as exc:
                logger.debug("collectible_info(%s) unavailable: %s", username, exc)
                return None

        # amount is in the smallest unit of the currency (100 = 1.00 USD),
        # crypto_amount is in nanoTON (1e9 = 1 TON).
        fiat = getattr(info, "amount", None)
        crypto = getattr(info, "crypto_amount", None)
        return MtprotoCollectible(
            url=getattr(info, "url", "") or "",
            purchase_date=getattr(info, "purchase_date", None),
            fiat_currency=getattr(info, "currency", None) or None,
            fiat_amount=(fiat / 100) if isinstance(fiat, int) else None,
            crypto_currency=getattr(info, "crypto_currency", None) or None,
            crypto_amount=(crypto / 1_000_000_000) if isinstance(crypto, int) else None,
        )

    @staticmethod
    def _classify(response: Any) -> MtprotoResult:
        peer = getattr(response, "peer", None)
        chats = getattr(response, "chats", None) or []
        users = getattr(response, "users", None) or []

        entity = None
        if chats:
            entity = chats[0]
        elif users:
            entity = users[0]
        elif peer is not None:
            entity = peer

        if entity is None:
            # ResolveUsername returned nothing usable - not a trustworthy "free".
            return MtprotoResult("unknown", "empty_resolve_response")

        entity_type = "unknown"
        title = None
        entity_id = getattr(entity, "id", None)
        if TELETHON_AVAILABLE:
            if isinstance(entity, Channel):
                entity_type = "channel" if getattr(entity, "broadcast", False) else "supergroup"
                title = getattr(entity, "title", None)
            elif isinstance(entity, Chat):
                entity_type = "group"
                title = getattr(entity, "title", None)
            elif isinstance(entity, TgUser):
                entity_type = "user"
                parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
                title = " ".join(part for part in parts if part) or None

        return MtprotoResult(
            "occupied",
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
        )


mtproto_client = MtprotoClient()
