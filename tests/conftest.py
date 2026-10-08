"""Shared pytest fixtures.

The dispatcher holds module-level routers, so it is created once per session.
Per-test isolation is provided by truncating the database and clearing the
in-memory caches before every test.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import delete

from app.bot.routers import all_routers
from app.bot.middlewares.access_guard import AccessGuardMiddleware
from app.bot.middlewares.database import DatabaseMiddleware, UserContextMiddleware
from app.bot.middlewares.errors import ErrorMiddleware
from app.cache.redis_cache import CacheService
from app.collectible.checker import CollectibleChecker
from app.config import settings
from app.database import database as db_module
from app.database.database import dispose_db, get_session_factory, init_db
from app.database.models import Base
from app.services.access import access_guard
from app.services.captcha import CaptchaService
from app.services.runtime_config import runtime
from app.telegram.mtproto import mtproto_client
from app.telegram.username_checker import UsernameChecker
from tests.mock_telegram import FakePageProbe, MockTelegramSession

CHANNEL_USERNAME = "test_channel"
CHAT_USERNAME = "test_chat"


@pytest.fixture(scope="session")
def db_url(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("db") / "test.db"
    return f"sqlite+aiosqlite:///{path.as_posix()}"


@pytest.fixture(scope="session", autouse=True)
def patched_settings(db_url):
    """Session-wide configuration. Individual tests override what they need."""
    original = {}
    overrides = {
        "database_url": db_url,
        "redis_enabled": False,
        "redis_url": "redis://127.0.0.1:6399/0",
        "bot_token": "123456:TEST-TOKEN",
        "admin_ids": "",
        "required_channel_id": 0,
        "required_channel_username": CHANNEL_USERNAME,
        "required_channel_invite_url": "",
        "required_chat_id": 0,
        "required_chat_username": CHAT_USERNAME,
        "required_chat_invite_url": "",
        # Force the legacy channel/chat fallback: the real .env may carry a
        # REQUIRED_SUBSCRIPTIONS JSON list that the tests do not know about.
        "required_subscriptions": "",
        "captcha_verification_ttl": 86400,
        "max_captcha_attempts": 3,
        "captcha_ttl": 300,
        "max_search_results": 50,
        "allow_bot_api_availability": False,
        "fragment_enabled": False,
        "membership_recheck_ttl": 300,
        # Keep the original, conservative scan caps in tests: the live default
        # is unlimited (free bot), but tests must stay fast and deterministic.
        "unlimited_search": False,
        # checkUsername is now the main availability call, so its pace is the
        # bot's real throughput. Tests never touch Telegram, so they run it at
        # the safety floor instead of the live 3s - otherwise a handful of
        # confirmations would add half a minute to every search test.
        "user_session_delay": 0.2,
    }
    for key, value in overrides.items():
        original[key] = getattr(settings, key)
        setattr(settings, key, value)
    db_module._engine = None
    db_module._session_factory = None
    yield
    for key, value in original.items():
        setattr(settings, key, value)
    db_module._engine = None
    db_module._session_factory = None


@pytest_asyncio.fixture(scope="session")
async def database(patched_settings):
    ok = await init_db()
    assert ok, "test database failed to initialise"
    yield
    await dispose_db()


@pytest.fixture(scope="session")
def mock_session() -> MockTelegramSession:
    return MockTelegramSession()


@pytest_asyncio.fixture(scope="session")
async def bot(mock_session: MockTelegramSession):
    instance = Bot(
        token="123456:TEST-TOKEN",
        session=mock_session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    yield instance
    await instance.session.close()


@pytest_asyncio.fixture(scope="session")
async def cache():
    service = CacheService(enabled=False)
    await service.connect()
    yield service


@pytest.fixture(scope="session")
def captcha_service(cache) -> CaptchaService:
    return CaptchaService(cache)


@pytest.fixture(scope="session")
def page_probe() -> FakePageProbe:
    """The public-page probe is always faked - tests never hit the network."""
    return FakePageProbe(state="free")


@pytest.fixture(autouse=True)
def no_public_network(request, monkeypatch):
    """The session-free public classifier must never reach the network in tests.

    It is a live HTTP call (``t.me`` + ``fragment.com``), which would make every
    search test slow, flaky and dependent on the outside world - exactly what
    ``FakePageProbe`` exists to prevent for the older screen. The whole class is
    stubbed so any code path that reaches it gets the honest "could not settle
    it" verdict. The classifier's own test module is skipped: it builds its own
    offline client against canned pages and must judge for real.
    """
    from app.telegram.public_verdict import PublicVerdict

    if request.node.fspath.basename == "test_public_verdict.py":
        yield
        return

    async def offline_judge(self, username):
        return PublicVerdict("unknown", "fragment_inconclusive", confidence="none")

    monkeypatch.setattr(
        "app.telegram.public_verdict.PublicVerdictClient.judge", offline_judge
    )
    yield


@pytest_asyncio.fixture(scope="session")
async def checker(bot, cache, page_probe):
    return UsernameChecker(cache=cache, bot=bot, page_probe=page_probe)


@pytest_asyncio.fixture(scope="session")
async def collectible_checker():
    return CollectibleChecker()


@pytest_asyncio.fixture(scope="function")
async def search_queue(bot, checker, collectible_checker):
    """The search runner, not started by default.

    Tests that only exercise the wizard assert on the "running" reply; tests
    that exercise the live search call ``search_queue.start()`` themselves.

    Scoped per test on purpose: the runner owns asyncio tasks bound to the
    running event loop, and pytest-asyncio gives each test its own loop.
    Sharing it across tests would make behaviour order-dependent and blow
    up with "bound to a different event loop".
    """
    from app.services.search_queue import SearchQueue

    queue = SearchQueue(bot, checker, collectible_checker)
    yield queue
    await queue.stop()


@pytest_asyncio.fixture(scope="session")
async def dispatcher(bot, cache, checker, collectible_checker, captcha_service,
                     database):
    dp = Dispatcher()
    dp["cache_service"] = cache
    dp["checker"] = checker
    dp["collectible_checker"] = collectible_checker
    dp["captcha_service"] = captcha_service

    dp.update.outer_middleware(ErrorMiddleware())
    dp.update.outer_middleware(DatabaseMiddleware())
    dp.update.outer_middleware(UserContextMiddleware())

    guard = AccessGuardMiddleware(captcha_service)
    dp.message.middleware(guard)
    dp.callback_query.middleware(guard)

    for router in all_routers():
        dp.include_router(router)
    return dp


@pytest_asyncio.fixture(autouse=True)
async def clean_state(database, mock_session, captcha_service, dispatcher, page_probe,
                      checker, search_queue):
    from app.telegram.public_page import FREE

    # The dispatcher is session-scoped (its routers are module-level singletons
    # that can only attach to one dispatcher), but the queue is per-test - so we
    # rebind the live queue into the session dispatcher every test. This keeps
    # the asyncio-bound queue on the current event loop while routers stay put.
    dispatcher["search_queue"] = search_queue

    page_probe.state = FREE
    page_probe.title = None
    page_probe.calls.clear()
    # The checker is session-scoped, so its verdict cache would otherwise leak a
    # verdict from one test into the next.
    checker.verdicts.clear()
    # Same reasoning for the queue: never deliver one test's job in another.
    search_queue.drain()
    """Wipe every mutable store before each test."""
    factory = get_session_factory()
    async with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        await session.commit()

    mock_session.reset()
    mock_session.memberships.clear()
    mock_session.chats.clear()
    captcha_service._memory.clear()
    access_guard._membership_cache.clear()
    runtime._overrides = {}
    mtproto_client._ready = False
    mtproto_client._client = None
    mtproto_client._bot_clients = []
    mtproto_client._bot_turn = 0
    mtproto_client._main_cooldown = 0.0
    # Tests deploy WITH a claimability gate: a properly configured bot has a
    # user session, and the search refuses to run without one.
    mtproto_client._user_clients = [
        {"name": "t", "client": None, "ready": True, "cooldown_until": 0.0}
    ]
    mtproto_client._user_turn = 0
    yield


@pytest_asyncio.fixture
async def session(database):
    factory = get_session_factory()
    async with factory() as s:
        yield s
        await s.commit()
