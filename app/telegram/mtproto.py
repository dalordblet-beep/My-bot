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
from app.utils.ratelimit import RateLimiter

logger = get_logger(__name__)

# The repository root - the folder that holds .env and, most likely, any
# session file the operator uploads next to the code.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _session_file(name: str, root: Path | None = None) -> Path:
    """Locate a session file: working directory first, then the project root.

    Deployments often run the bot from a different working directory than the
    folder where the operator drops ``username_scanner_user.session``; both
    places are checked before giving up.
    """
    local = Path(f"{name}.session")
    if local.exists():
        return local.resolve()
    candidate = (root or PROJECT_ROOT) / f"{name}.session"
    if candidate.exists():
        return candidate
    return local.resolve()

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
        UsernamePurchaseAvailableError,
    )
    from telethon.errors.rpcerrorlist import BotMethodInvalidError, UsernameOccupiedError
    from telethon.tl.functions.account import CheckUsernameRequest
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
        # Optional pool of extra *bot* sessions (tokens from BotFather, no
        # phone). Each entry: {"name", "client", "ready", "cooldown_until"}.
        # Every session carries its own Telegram quota, so authoritative
        # availability checks scale with the pool and a rate-limited session
        # never stalls the others.
        self._bot_clients: list[dict[str, Any]] = []
        self._bot_turn = 0
        self._main_cooldown = 0.0
        # Optional pool of user sessions, used only for account.checkUsername.
        # Each entry: {"name", "client", "ready", "cooldown_until"}.
        self._user_clients: list[dict[str, Any]] = []
        self._user_turn = 0
        # checkUsername is a real account-level call with the same escalation
        # threshold as resolveUsername - unpaced, one session would be flood
        # limited within minutes of a busy short-name search. The pace is
        # shared across the user-session pool.
        self._user_limiter = RateLimiter(min_interval=settings.request_delay)

    @property
    def configured(self) -> bool:
        return TELETHON_AVAILABLE and settings.mtproto_configured

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def resolve_ready(self) -> bool:
        """True when any session able to run resolveUsername is loaded."""
        return self._ready or any(entry["ready"] for entry in self._bot_clients)

    @property
    def bot_session_count(self) -> int:
        """How many MTProto sessions can serve a resolve *right now*.

        Parked (FloodWait-limited) sessions are excluded on purpose: the shared
        request pace is divided by this number, so counting a session that
        cannot answer would over-pace the ones that can - pushing each of them
        past the safe per-account rate and straight into the next FloodWait.
        """
        now = asyncio.get_event_loop().time()
        count = 1 if (self._ready and self._main_cooldown <= now) else 0
        count += sum(
            1 for entry in self._bot_clients
            if entry["ready"] and entry["cooldown_until"] <= now
        )
        return max(count, 1)

    @property
    def user_ready(self) -> bool:
        """True when at least one real user session is loaded."""
        return any(entry["ready"] for entry in self._user_clients)

    @property
    def user_session_count(self) -> int:
        return sum(1 for entry in self._user_clients if entry["ready"])

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
                await self._start_bot_pool()
        except Exception as exc:
            logger.error("mtproto start failed: %s", exc)
            self._client = None
            self._ready = False
        return self._ready

    async def _start_bot_pool(self) -> None:
        """Authorise extra bot sessions by token (BotFather tokens, no phone).

        Every session carries its own Telegram quota, so the pool is how the
        availability checks scale to many users: the engine rotates across the
        sessions and a rate-limited one is parked while the next answers.
        """
        if self._bot_clients:
            return
        tokens = [
            token for token in settings.bot_session_tokens
            if token and token != settings.bot_token
        ]
        for index, token in enumerate(tokens, start=2):
            name = f"{settings.mtproto_session}-p{index}"
            try:
                client = TelegramClient(name, settings.api_id, settings.api_hash)
                await client.start(bot_token=token)
                if not await client.is_user_authorized():
                    # Same self-healing as the main session: a stale shell is
                    # wiped and the bot logs in fresh by token.
                    await self._drop(client)
                    for suffix in (".session", ".session-journal"):
                        path = Path(f"{name}{suffix}")
                        try:
                            if path.exists():
                                path.unlink()
                        except OSError as exc:  # pragma: no cover
                            logger.debug("could not remove %s: %s", path, exc)
                    client = TelegramClient(name, settings.api_id, settings.api_hash)
                    await client.start(bot_token=token)
                    if not await client.is_user_authorized():
                        await self._drop(client)
                        logger.warning("bot session %s is not authorised - skipped", name)
                        continue
                self._bot_clients.append(
                    {"name": name, "client": client, "ready": True, "cooldown_until": 0.0}
                )
            except Exception as exc:
                logger.warning("bot session %s failed to start: %s", name, exc)

        ready = sum(1 for entry in self._bot_clients if entry["ready"])
        if ready:
            logger.info(
                "bot session pool ready: %d extra session(s), %d total for resolves",
                ready, self.bot_session_count,
            )

    @staticmethod
    async def _drop(client: Any) -> None:
        """Disconnect an arbitrary client, ignoring teardown errors."""
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

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
        await self._drop(self._client)
        for entry in self._bot_clients:
            await self._drop(entry["client"])
        for entry in self._user_clients:
            await self._drop(entry["client"])
        self._client = None
        self._ready = False
        self._bot_clients = []
        self._bot_turn = 0
        self._main_cooldown = 0.0
        self._user_clients = []
        self._user_turn = 0

    async def start_user(self) -> bool:
        """Load the optional *user* session pool for account.checkUsername.

        ``contacts.resolveUsername`` answers "not occupied" for a name that
        Telegram will nevertheless refuse to assign (reserved, cooldown,
        anti-abuse). A bot is forbidden from calling ``account.checkUsername``,
        the one method that separates the two - so, when real user sessions are
        available, they are used as the final assignability gate.

        Several sessions may be configured (``MTPROTO_USER_SESSIONS``); they are
        pooled and rotated so a single account's FloodWait cannot stall every
        check. No session file means the feature is simply off.
        """
        if not self.configured or self._user_clients:
            return self.user_ready

        names = settings.user_session_names
        found = 0
        for name in names:
            if not name:
                continue
            path = _session_file(name)
            if not path.exists():
                continue
            try:
                client = TelegramClient(str(path), settings.api_id, settings.api_hash)
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    continue
                me = await client.get_me()
                if getattr(me, "bot", False):
                    logger.warning("user session %s is a bot - skipped", name)
                    await client.disconnect()
                    continue
                self._user_clients.append(
                    {"name": name, "client": client, "ready": True, "cooldown_until": 0.0}
                )
                found += 1
            except Exception as exc:
                logger.warning("could not start user session %s: %s", name, exc)

        if found:
            logger.info("user session pool ready (%d account(s)) - claimability on", found)
        else:
            # This is the exact failure behind "the bot reports taken/cooldown
            # names as free": without this session account.checkUsername cannot
            # run. Say precisely where the file was expected.
            logger.warning(
                "no user session found - claimability check stays OFF. Searched "
                "the working directory (%s) and the project root (%s) for %s. "
                "Copy username_scanner_user.session into one of those folders "
                "(exact name, no double .session extension) and restart.",
                Path.cwd(), PROJECT_ROOT, " or ".join(f"{n}.session" for n in names) or "-",
            )
        return self.user_ready

    async def check_username(self, username: str) -> bool | None:
        """Authoritative assignability test via the user-only checkUsername.

        This is the exact call the Telegram app makes when you type a username,
        so it is the only signal that separates "nobody owns it" from "nobody
        owns it *and* Telegram will not give it to you". The verdicts:

        * ``True``  - claimable right now;
        * ``False`` - occupied, or unassignable (``UsernameInvalidError``:
          reserved / cooldown / anti-abuse / Fragment stock, which the app shows
          as "incorrect username"), or listed for sale (``UsernamePurchaseAvailableError``);
        * ``None`` - no verdict available (no session, or every session was
          rate-limited / errored), so the caller stays best-effort.

        Sessions are tried in rotation; a rate-limited one is parked for a while
        and the next is used, so one busy account does not stall the pool.
        """
        ready = [e for e in self._user_clients if e["ready"]]
        if not ready:
            return None

        # The safe per-account rate divided by the number of live sessions:
        # one session carries the whole pace, N sessions share it.
        self._user_limiter.min_interval = max(
            1.0, settings.request_delay / len(ready)
        )

        now = asyncio.get_event_loop().time()
        order = ready[self._user_turn % len(ready):] + ready[: self._user_turn % len(ready)]
        self._user_turn += 1

        for entry in order:
            if entry["cooldown_until"] > now:
                continue
            async with self._lock:
                await self._user_limiter.acquire()
                try:
                    return bool(await entry["client"](CheckUsernameRequest(username)))
                except (UsernameInvalidError, UsernamePurchaseAvailableError):
                    return False
                except BotMethodInvalidError:
                    logger.warning("session %s is a bot - dropping it", entry["name"])
                    entry["ready"] = False
                    continue
                except FloodWaitError as exc:  # pragma: no cover - network dependent
                    wait = float(getattr(exc, "seconds", 60) or 60)
                    entry["cooldown_until"] = now + wait
                    logger.warning("session %s flood wait %ss - parked", entry["name"], int(wait))
                    continue
                except Exception as exc:
                    logger.debug("checkUsername(%s) via %s failed: %s", username, entry["name"], exc)
                    continue
        return None

    def _park(self, name: str, wait: float) -> None:
        """Stop using one session until its FloodWait window has passed."""
        until = asyncio.get_event_loop().time() + max(wait, 0.0)
        if name == "main":
            self._main_cooldown = until
            return
        for entry in self._bot_clients:
            if entry["name"] == name:
                entry["cooldown_until"] = until
                return

    def _soonest_recovery(self) -> float | None:
        """Seconds until some parked session becomes usable again."""
        now = asyncio.get_event_loop().time()
        waits: list[float] = []
        if self._ready and self._main_cooldown > now:
            waits.append(self._main_cooldown - now)
        waits.extend(
            entry["cooldown_until"] - now
            for entry in self._bot_clients
            if entry["ready"] and entry["cooldown_until"] > now
        )
        return min(waits) if waits else None

    async def resolve_username(self, username: str) -> MtprotoResult:
        """Resolve a username across the whole session pool.

        The main session is tried first, then the extra bot sessions in
        rotation. A session that answers ``FloodWait`` is parked for the
        requested window and the next one takes the call, so a rate-limited
        account never stalls the pool. Only when **every** session is parked
        does the caller see a ``flood`` result (with the soonest recovery
        time), and a generic failure on all sessions reports ``error``.
        """
        candidates: list[tuple[str, Any]] = []
        now = asyncio.get_event_loop().time()
        if self._ready and self._client is not None and self._main_cooldown <= now:
            candidates.append(("main", self._client))

        ready = [
            entry for entry in self._bot_clients
            if entry["ready"] and entry["cooldown_until"] <= now
        ]
        if ready:
            turn = self._bot_turn % len(ready)
            self._bot_turn += 1
            ordered = ready[turn:] + ready[:turn]
            candidates.extend((entry["name"], entry["client"]) for entry in ordered)

        if not candidates:
            wait = self._soonest_recovery()
            if wait is None:
                return MtprotoResult("unknown", "mtproto_unavailable")
            return MtprotoResult("flood", str(int(wait)))

        last_error: str | None = None
        for name, client in candidates:
            try:
                response = await client(ResolveUsernameRequest(username))
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
            except UsernameOccupiedError:
                return MtprotoResult("occupied", "occupied_error")
            except FloodWaitError as exc:  # pragma: no cover - network dependent
                wait = float(getattr(exc, "seconds", 60) or 60)
                self._park(name, wait)
                logger.warning("mtproto session %s flood wait %ss - parked", name, int(wait))
                continue
            except Exception as exc:
                cls = type(exc).__name__
                if "FloodWait" in cls:
                    wait = float(getattr(exc, "seconds", 60) or 60)
                    self._park(name, wait)
                    logger.warning("mtproto session %s flood wait %ss - parked", name, int(wait))
                    continue
                last_error = cls
                logger.debug("resolve_username(%s) via %s failed: %s", username, name, exc)
                continue

            return self._classify(response)

        if last_error:
            return MtprotoResult("error", last_error)
        wait = self._soonest_recovery() or 60.0
        return MtprotoResult("flood", str(int(wait)))

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
