"""Basic Telegram username engine.

Pipeline: normalise -> validate -> cache -> MTProto -> (Bot API + public page)
-> classify. The classification is deliberately conservative:

* MTProto says the name is not occupied  -> AVAILABLE (authoritative)
* Anything resolves to an entity         -> OCCUPIED
* Telegram gives no trustworthy answer   -> UNKNOWN (never AVAILABLE)

Without MTProto, a "not found" from the Bot API is NOT enough to call a name
free: the Bot API cannot resolve personal accounts at all. The public preview
page is used to confirm, and only a confirmed-free name may be reported as
AVAILABLE (and only when ALLOW_BOT_API_AVAILABILITY is on).
"""

from __future__ import annotations

import time

from app.cache.redis_cache import CacheService, username_cache_key
from app.config import settings
from app.services.runtime_config import runtime
from app.telegram.bot_api import lookup_chat
from app.telegram.mtproto import mtproto_client
from app.telegram.public_page import OCCUPIED, PublicPageProbe, PublicPageResult
from app.utils.enums import CheckStatus
from app.utils.logging_setup import get_logger
from app.utils.ratelimit import FloodWaitBudget, RateLimiter
from app.utils.results import CheckResult
from app.utils.username import parse_username
from app.utils.verdict_cache import VerdictCache

logger = get_logger(__name__)

# Shared across the whole process so a mass scan cannot outrun the limiter.
shared_rate_limiter = RateLimiter(min_interval=settings.request_delay)
shared_flood_budget = FloodWaitBudget()


class UsernameChecker:
    def __init__(
        self,
        cache: CacheService | None = None,
        bot=None,
        rate_limiter: RateLimiter | None = None,
        page_probe: PublicPageProbe | None = None,
        verdict_cache: VerdictCache | None = None,
    ) -> None:
        self._cache = cache
        self._bot = bot
        self._limiter = rate_limiter or shared_rate_limiter
        self._page_probe = page_probe or PublicPageProbe()
        self._verdicts = verdict_cache if verdict_cache is not None else VerdictCache(
            occupied_ttl=settings.verdict_occupied_ttl,
            free_ttl=settings.verdict_free_ttl,
        )

    @property
    def limiter(self) -> RateLimiter:
        """The shared throttler, exposed so callers can see a FloodWait coming."""
        return self._limiter

    @property
    def verdicts(self) -> VerdictCache:
        """The in-memory verdict cache. Costs no Telegram quota to consult."""
        return self._verdicts

    async def close(self) -> None:
        await self._page_probe.close()

    async def check_basic_username(self, username: str, use_cache: bool = True) -> CheckResult:
        started = time.perf_counter()

        parsed = parse_username(username)
        if not parsed.is_valid:
            return CheckResult(
                username=parsed.value or parsed.raw,
                status=CheckStatus.INVALID,
                source="validation",
                reason=parsed.reason,
                duration_ms=self._elapsed(started),
            )

        name = parsed.value
        cache_key = username_cache_key(name, "basic")

        if use_cache and self._cache is not None and self._cache.available:
            cached = await self._cache.get_json(cache_key)
            if cached is not None:
                result = CheckResult.from_cache(cached)
                result.duration_ms = self._elapsed(started)
                logger.info(
                    "username check username=%s status=%s source=cache duration_ms=%s",
                    name, result.status.value, result.duration_ms,
                )
                return result

        result = await self._resolve(name)
        result.duration_ms = self._elapsed(started)

        if use_cache and self._cache is not None and result.is_definitive:
            await self._cache.set_json(cache_key, result.to_cache(), runtime.cache_ttl)

        logger.info(
            "username check username=%s status=%s source=%s duration_ms=%s",
            name, result.status.value, result.source, result.duration_ms,
        )
        return result

    async def check_for_release(self, username: str) -> CheckResult:
        """Used by traps: is this name free *right now*?

        The public page is consulted first because it is cheap and works with no
        MTProto session, but it is only allowed to say two things:

        * a rendered profile card -> OCCUPIED, definitively;
        * no usable signal -> fall through to the authoritative check.

        The generic "contact @name" placeholder is explicitly **not** treated as
        a release - real, owned accounts render it too (verified), so trusting it
        used to fire a false "the name is free" for names that were taken. Only
        MTProto can declare a name free.
        """
        page = await self._page_probe.check(username)

        if page.is_occupied:
            return CheckResult(
                username=username, status=CheckStatus.OCCUPIED, source="public_page",
                title=page.title, detail="confirmed_by_public_page",
            )
        if page.is_free:
            return CheckResult(
                username=username, status=CheckStatus.AVAILABLE, source="public_page",
                detail="confirmed_by_public_page",
            )

        # The page said nothing trustworthy - use the authoritative pipeline.
        return await self._resolve(username, allow_public_free=False)

    async def probe_public_page(self, username: str) -> PublicPageResult:
        """The free, unauthenticated screen.

        Fetches ``t.me/<name>`` like a browser would: no account, no MTProto
        quota, nothing Telegram can ban. A rendered profile card is proof of
        ownership; anything else is merely "not ruled out".

        A remembered OCCUPIED verdict is served from the cache, which makes a
        repeated search instant instead of re-fetching every page.
        """
        cached = self._verdicts.get(username)
        if cached is not None and cached.status is CheckStatus.OCCUPIED:
            return PublicPageResult(OCCUPIED, title=cached.title, reason="cached")

        page = await self._page_probe.check(username)
        if page.is_occupied:
            self._verdicts.put(
                CheckResult(
                    username=username, status=CheckStatus.OCCUPIED,
                    source="public_page", title=page.title,
                )
            )
        return page

    async def reconfirm_claimable(self, username: str) -> bool | None:
        """One ``account.checkUsername`` call - the cheapest definitive answer.

        For a name the stock already proved claimable, the only open question is
        whether it is *still* free, and that is exactly what this call answers.
        Going through the full pipeline instead spent a resolve on the bot pool
        (and waited out its pace) for a question the user session can answer on
        its own - which is how delivering one stored name took sixteen seconds.

        ``None`` means the user session could not answer, so the caller falls
        back to the full pipeline rather than guessing.
        """
        if not mtproto_client.user_ready:
            return None
        return await mtproto_client.check_username(username)

    async def confirm_availability(self, username: str) -> CheckResult:
        """Authoritative resolve - the only channel that can say AVAILABLE.

        Spends one MTProto call, so callers must treat it as the scarce
        resource it is (~20-30 resolves/account/minute before FloodWait). A
        cached verdict short-circuits the call entirely; OCCUPIED is kept long
        (it can only cause a miss, never a false "free") and AVAILABLE only
        briefly (somebody can claim the name within minutes).
        """
        cached = self._verdicts.get(username)
        if cached is not None:
            return cached

        result = await self._resolve(username, allow_public_free=False)
        self._verdicts.put(result)
        return result

    async def check_free_candidate(self, username: str) -> CheckResult:
        """Screen a search candidate cheaply, then confirm it authoritatively.

        Telegram rate-limits ``ResolveUsername`` at roughly 20-30 calls per
        account per minute; going over earns multi-hour FloodWaits. But the
        overwhelming majority of candidates in a search are *occupied*, and a
        rendered public profile card proves that for free - no account, no
        quota, nothing to ban.

        So the order is deliberate:

        * the page may only ever answer **OCCUPIED** (a profile card is proof);
        * every other name costs one authoritative MTProto resolve, because
          MTProto is the only channel that can truthfully say AVAILABLE.

        This keeps the result trustworthy - a "free" verdict always comes from
        MTProto - while spending the scarce quota only on real possibilities.
        """
        page = await self.probe_public_page(username)

        if page.is_occupied:
            return CheckResult(
                username=username, status=CheckStatus.OCCUPIED, source="public_page",
                title=page.title, detail="screened_by_public_page",
            )

        return await self.confirm_availability(username)

    # ------------------------------------------------------------------ internals
    async def _resolve(self, name: str, allow_public_free: bool = False) -> CheckResult:
        if mtproto_client.resolve_ready:
            # The safe per-account pace is shared across the whole session pool,
            # with a margin: these are fresh bot accounts, and running them at
            # the bare 20/min threshold got them FloodWaited under load.
            #
            # The pace is only paid when a session can actually take the call.
            # With every bot session parked the resolve goes nowhere anyway, and
            # waiting for the pool's (deliberately backed-off) interval first
            # froze the whole check behind a multi-hour ban - two lookups in five
            # minutes while the user session sat idle and able to answer.
            if mtproto_client.resolve_sessions_live:
                self._limiter.min_interval = mtproto_client.call_interval
                await self._limiter.acquire()
            mt = await mtproto_client.resolve_username(name)

            if mt.kind == "not_occupied":
                # "not occupied" is NOT the same as "claimable". Telegram also
                # answers not_occupied for names it then refuses to assign
                # (reserved, recently-released cooldown, anti-abuse), which the
                # app reports as "incorrect username". account.checkUsername is
                # the only method that separates the two, and only a *user*
                # session may call it - so when one is configured, it gets the
                # final word and an unassignable name is never reported free.
                if mtproto_client.user_ready:
                    claimable = await mtproto_client.check_username(name)
                    if claimable is False:
                        return CheckResult(
                            username=name, status=CheckStatus.INVALID,
                            source="mtproto_user", reason="not_assignable",
                        )
                    if claimable is True:
                        return CheckResult(
                            username=name, status=CheckStatus.AVAILABLE,
                            source="mtproto", detail="claimability_verified",
                        )
                    # The user session could not answer (rate-limited, etc.) -
                    # fall through: the verdict stays honestly unverified.
                # No user session - the verdict is honest about what it could
                # not check: "nobody owns it" is confirmed, "Telegram will give
                # it to you" is not. The result screen states this caveat.
                return CheckResult(
                    username=name, status=CheckStatus.AVAILABLE, source="mtproto",
                    detail="claimability_unverified",
                )
            if mt.kind == "occupied":
                return CheckResult(
                    username=name, status=CheckStatus.OCCUPIED, source="mtproto",
                    entity_type=mt.entity_type, title=mt.title, detail=mt.detail,
                )
            if mt.kind == "invalid":
                return CheckResult(
                    username=name, status=CheckStatus.INVALID, source="mtproto",
                    reason="telegram_rejected_username",
                )
            if mt.kind == "flood":
                seconds = float(mt.detail or 0) + settings.floodwait_safety_margin
                shared_flood_budget.record(seconds)
                # Every *bot* session is parked - but the user session is a
                # different account with a quota of its own, and
                # account.checkUsername is the one call that can still answer
                # "claimable, yes or no". Use it instead of declaring the check
                # dead: this is what keeps a real, verified name coming out while
                # the bot pool sits out its FloodWait.
                if mtproto_client.user_ready:
                    claimable = await mtproto_client.check_username(name)
                    if claimable is True:
                        return CheckResult(
                            username=name, status=CheckStatus.AVAILABLE,
                            source="mtproto_user", detail="claimability_verified",
                        )
                    if claimable is False:
                        return CheckResult(
                            username=name, status=CheckStatus.INVALID,
                            source="mtproto_user", reason="not_assignable",
                        )
                # Nothing with a quota could answer. The account-free signals
                # (Bot API + public page) cost no MTProto quota and can still
                # screen names out, so a temporary Telegram limit degrades the
                # bot instead of taking it down.
                probe = await self._bot_api_probe(name, "flood_wait", allow_public_free)
                if probe.status is not CheckStatus.UNKNOWN:
                    return probe
                # IMPORTANT: never pause the shared limiter here. With a pool,
                # each session parks itself for exactly its own flood window;
                # a global pause used to freeze EVERY call in the process for
                # hours - searches hanging on "SEARCHING...", appraise stuck.
                return CheckResult(
                    username=name, status=CheckStatus.RATE_LIMITED, source="mtproto",
                    reason="flood_wait", detail=str(int(seconds)),
                )
            if mt.kind == "error":
                logger.debug("mtproto error for %s: %s", name, mt.detail)
                # fall through to the Bot API signal before giving up
                return await self._bot_api_probe(name, mt.detail, allow_public_free)

            return CheckResult(
                username=name, status=CheckStatus.UNKNOWN, source="mtproto",
                reason=mt.detail or "no_trustworthy_answer",
            )

        return await self._bot_api_probe(name, "mtproto_unavailable", allow_public_free)

    async def _bot_api_probe(
        self, name: str, prior_reason: str | None, allow_public_free: bool = False
    ) -> CheckResult:
        if self._bot is None:
            return CheckResult(
                username=name, status=CheckStatus.UNKNOWN, source="none",
                reason="no_checker_available", detail=prior_reason,
            )

        await self._limiter.acquire()
        lookup = await lookup_chat(self._bot, f"@{name}")

        if lookup.found:
            return CheckResult(
                username=name, status=CheckStatus.OCCUPIED, source="bot_api",
                entity_type=lookup.chat_type, title=lookup.title,
                detail="resolved_via_bot_api",
            )

        if lookup.reason == "flood_wait":
            return CheckResult(
                username=name, status=CheckStatus.RATE_LIMITED, source="bot_api",
                reason="flood_wait",
            )

        # The Bot API only resolves channels, supergroups and bots. For a
        # username owned by a personal account it answers "chat not found",
        # which is indistinguishable from free. Confirm with the public page
        # before making any claim.
        page = await self._page_probe.check(name)

        if page.is_occupied:
            return CheckResult(
                username=name, status=CheckStatus.OCCUPIED, source="public_page",
                title=page.title, detail="confirmed_by_public_page",
            )

        if page.is_free:
            # A positively-shaped free page (redirect / signup flow). This is
            # still only trusted for a one-shot check when the operator has
            # explicitly opted in, because Telegram can render it for names that
            # are merely without a public card.
            if settings.allow_bot_api_availability or allow_public_free:
                return CheckResult(
                    username=name, status=CheckStatus.AVAILABLE, source="public_page",
                    detail="confirmed_by_public_page",
                )
            return CheckResult(
                username=name, status=CheckStatus.UNKNOWN, source="public_page",
                reason="mtproto_required_for_availability", detail=prior_reason,
            )

        if page.reason == "no_profile_card":
            # The generic "contact @name" placeholder. It means only that there
            # is no public card, and real owned accounts render it too, so it can
            # never justify AVAILABLE - that was the source of the bot reporting
            # taken names as free.
            return CheckResult(
                username=name, status=CheckStatus.UNKNOWN, source="public_page",
                reason="no_public_card_not_proof_of_freedom", detail=prior_reason,
            )

        return CheckResult(
            username=name, status=CheckStatus.UNKNOWN, source="bot_api",
            reason=page.reason or lookup.reason or "unavailable", detail=prior_reason,
        )

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
