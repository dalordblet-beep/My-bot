"""AccessGuard - the single place that decides whether a user may use the bot.

Order of the onboarding gate (fixed by product spec):

    captcha -> required channel -> required chat -> access granted

Nothing else in the codebase is allowed to bypass this. Callbacks are never
trusted: every entry point re-runs the guard.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import repository as repo
from app.database.models import User
from app.services.subscriptions import RequiredSub, required_subs
from app.telegram.bot_api import build_chat_ref, get_membership, lookup_chat
from app.telegram.mtproto import mtproto_client
from app.utils.enums import (
    Privilege,
    Permission,
    permissions_for,
)
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

STEP_BANNED = "banned"
STEP_RESTRICTED = "restricted"
STEP_CAPTCHA = "captcha"
STEP_SUBS = "subscriptions"
STEP_OK = "ok"


@dataclass
class AccessState:
    user: User
    captcha_ok: bool = False
    subs_ok: bool = True
    # The required subscriptions the user has not joined yet (empty when done).
    pending_subs: list["RequiredSub"] = field(default_factory=list)
    banned: bool = False
    restricted: bool = False
    restricted_until: datetime | None = None
    restriction_reason: str | None = None
    is_admin: bool = False
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    checked_at: float = field(default_factory=time.monotonic)

    @property
    def granted(self) -> bool:
        return (
            not self.banned
            and not self.restricted
            and self.captcha_ok
            and self.subs_ok
        )

    @property
    def missing_step(self) -> str:
        if self.banned:
            return STEP_BANNED
        if self.restricted:
            return STEP_RESTRICTED
        if not self.captcha_ok:
            return STEP_CAPTCHA
        if not self.subs_ok:
            return STEP_SUBS
        return STEP_OK

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


class AccessGuard:
    """Evaluates access and caches membership lookups briefly."""

    def __init__(self) -> None:
        # user_id -> (monotonic_ts, {subscription_key: joined})
        self._membership_cache: dict[int, tuple[float, dict[str, bool]]] = {}

    async def evaluate(
        self,
        session: AsyncSession,
        bot: Bot | None,
        user: User,
        *,
        live_membership: bool = True,
    ) -> AccessState:
        state = AccessState(user=user)
        state.is_admin = user.privilege == Privilege.ADMIN.value
        state.permissions = permissions_for(
            Privilege(user.privilege) if user.privilege in Privilege._value2member_map_ else Privilege.FREE
        )

        # 1. permanent ban
        if user.is_banned:
            state.banned = True
            state.restriction_reason = user.ban_reason
            return state

        # 2. temporary restriction
        if repo.restriction_active(user):
            state.restricted = True
            state.restricted_until = user.ban_until
            state.restriction_reason = user.ban_reason
            return state

        # 3. captcha (skipped entirely when the user holds NO_CAPTCHA)
        if Permission.NO_CAPTCHA in state.permissions:
            state.captcha_ok = True
        else:
            state.captcha_ok = self._captcha_valid(user)

        # 4. required subscriptions (channel(s) + chat, as configured)
        subs = required_subs()
        if not subs:
            state.subs_ok = True
            state.pending_subs = []
        elif live_membership and bot is not None:
            results = await self._check_subs(session, bot, user, subs)
            state.pending_subs = [sub for sub in subs if not results.get(sub.key, False)]
            state.subs_ok = not state.pending_subs
        else:
            state.pending_subs = [
                sub for sub in subs
                if not self._stored_valid(repo.sub_verified_at(user, sub.key))
            ]
            state.subs_ok = not state.pending_subs

        return state

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _captcha_valid(user: User) -> bool:
        verified = user.captcha_verified_at
        if verified is None:
            return False
        if verified.tzinfo is None:
            verified = verified.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - verified < timedelta(
            seconds=settings.captcha_verification_ttl
        )

    @staticmethod
    def _stored_valid(moment: datetime | None) -> bool:
        if moment is None:
            return False
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - moment < timedelta(
            seconds=settings.membership_recheck_ttl
        )

    async def _check_subs(
        self, session: AsyncSession, bot: Bot, user: User, subs: list[RequiredSub]
    ) -> dict[str, bool]:
        """Live membership for every required subscription, briefly cached.

        Returns ``{subscription_key: joined}``. A subscription that is not
        configured (no id and no username) counts as joined so a half-configured
        deployment cannot lock everyone out.

        The cache is rejected whenever the set of required subscription keys
        changes - that is how a channel the admin adds later starts blocking
        existing users on their very next interaction instead of being ignored
        until the old cache entry silently expired.
        """
        required_keys = {sub.key for sub in subs}
        cached = self._membership_cache.get(user.telegram_id)
        now = time.monotonic()
        if (
            cached is not None
            and now - cached[0] < settings.membership_recheck_ttl
            and set(cached[1].keys()) == required_keys
        ):
            return cached[1]

        results: dict[str, bool] = {}
        changed = False

        for sub in subs:
            if not sub.configured:
                results[sub.key] = True
                continue

            ref = build_chat_ref(sub.chat_id, sub.username)
            status = await get_membership(bot, ref, user.telegram_id)
            joined = status.grants_access

            # Not a member - but a private channel approves requests by hand, and
            # the approval queue is not the user's fault. Somebody who has already
            # asked to join has done their part, so a *pending* request counts as
            # a subscription instead of leaving them stuck on the gate.
            if not joined:
                joined = await self.join_request_pending(session, bot, sub, user)

            results[sub.key] = joined

            stored = repo.sub_verified_at(user, sub.key)
            if joined and stored is None:
                await repo.set_sub_verified(session, user, sub.key)
                changed = True
            elif not joined and stored is not None:
                await repo.clear_sub_verified(session, user, sub.key)
                changed = True

        if changed:
            await session.flush()

        self._membership_cache[user.telegram_id] = (now, results)
        return results

    async def join_request_pending(
        self, session: AsyncSession, bot: Bot, sub: RequiredSub, user: User
    ) -> bool:
        """Does this user have an unapproved request to join ``sub``?

        Two sources, cheapest and most certain first:

        * the request Telegram pushed to the bot (``chat_join_request``), which is
          instant and needs nothing but the bot being an administrator;
        * the request queue itself, read with the user session - this is what
          covers a request sent while the bot was offline, or before this feature
          existed.

        Both are "not proven" when they cannot answer: a failure here must never
        be read as "the request exists", or a stranger would be let in.
        """
        chat_id = sub.chat_id
        if not chat_id:
            # Only a @username is configured. Resolve it once so the record can
            # be keyed the same way the update keys it.
            lookup = await lookup_chat(bot, build_chat_ref(0, sub.username))
            chat_id = int(lookup.chat_id or 0) if lookup.found else 0
        if not chat_id:
            return False

        if await repo.has_join_request(
            session, chat_id, user.telegram_id, settings.join_request_ttl
        ):
            return True

        pending = await mtproto_client.join_request_pending(chat_id, user.telegram_id)
        if pending:
            # Remember it so the next check does not need the queue again.
            await repo.record_join_request(session, chat_id, user.telegram_id)
            logger.info(
                "join request found for user %s in chat %s - access granted",
                user.telegram_id, chat_id,
            )
            return True
        return False

    def invalidate(self, telegram_id: int) -> None:
        self._membership_cache.pop(telegram_id, None)

    def invalidate_all(self) -> None:
        """Drop every cached membership verdict.

        Call this after the admin adds or removes a required subscription so the
        new requirement is enforced (or dropped) for all users immediately,
        without waiting for each per-user cache to age out.
        """
        self._membership_cache.clear()


access_guard = AccessGuard()
