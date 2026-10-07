"""Database engine, session factory and schema bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database.models import Base
from app.utils.logging_setup import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        sqlite = make_url(settings.database_url).get_backend_name() == "sqlite"
        connect_args = {"timeout": 30} if sqlite else {}
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            connect_args=connect_args,
        )
        if sqlite:
            event.listen(_engine.sync_engine, "connect", _configure_sqlite_connection)
    return _engine


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Use WAL and a bounded lock wait for concurrent bot/background writes."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        try:
            mode = cursor.execute("PRAGMA journal_mode=WAL").fetchone()
            if mode and str(mode[0]).lower() == "wal":
                cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception as exc:
            # A database opened by another process can refuse a journal-mode
            # switch. Keep the connection usable with busy_timeout enabled.
            logger.warning("could not enable SQLite WAL mode: %s", exc)
    finally:
        cursor.close()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for background tasks that own their session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> bool:
    """Create tables if missing and run lightweight data migrations."""
    try:
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with get_session_factory()() as session:
            await _run_migrations(session)
            await session.commit()
        logger.info("database ready")
        return True
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.error("database unavailable: %s", exc)
        return False


async def _run_migrations(session: AsyncSession) -> None:
    """Idempotent, marker-guarded data fixes.

    The schema itself is created by ``create_all``; these handle value-level
    changes that ``create_all`` cannot express.
    """
    from sqlalchemy import update

    from app.database import repository as repo
    from app.database.models import UserSetting

    marker = "migration_language_picker_v1"
    if await repo.get_bot_setting(session, marker) == "done":
        pass
    else:
        # Before the language picker existed, every row carried the old default
        # ('en') whether the user had chosen anything or not. Clear it once so the
        # picker is shown to everyone on their next /start.
        result = await session.execute(update(UserSetting).values(language=""))
        await repo.set_bot_setting(session, marker, "done")
        logger.info(
            "migration %s applied: reset language on %s row(s)",
            marker, result.rowcount,
        )

    # Columns added after the first release. create_all() never alters an
    # existing table, so they are added explicitly and idempotently.
    await _ensure_columns(
        session,
        "user_settings",
        {
            "search_length": "INTEGER NOT NULL DEFAULT 8",
            "search_digits": "BOOLEAN NOT NULL DEFAULT 0",
            "search_min_score": "INTEGER NOT NULL DEFAULT 40",
            "search_mask": "VARCHAR(64) NOT NULL DEFAULT ''",
            "daily_drop": "BOOLEAN NOT NULL DEFAULT 0",
            "daily_drop_last": "TIMESTAMP",
        },
    )
    await _ensure_columns(
        session,
        "users",
        {"subscriptions_verified": "JSON NOT NULL DEFAULT '{}'"},
    )
    await _ensure_columns(
        session, "traps", {"kind": "VARCHAR(8) NOT NULL DEFAULT 'name'"}
    )
    await _ensure_columns(session, "battles", {"winner_id": "BIGINT"})


async def _ensure_columns(
    session: AsyncSession, table: str, columns: dict[str, str]
) -> None:
    """Add missing columns to an existing table (SQLite / PostgreSQL safe)."""
    from sqlalchemy import text

    existing = await session.execute(text(f"PRAGMA table_info({table})"))
    rows = existing.fetchall()
    if not rows:
        # Not SQLite - fall back to information_schema.
        existing = await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        )
        present = {str(row[0]) for row in existing.fetchall()}
    else:
        present = {str(row[1]) for row in rows}

    for column, definition in columns.items():
        if column in present:
            continue
        await session.execute(
            text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        )
        logger.info("migration: added %s.%s", table, column)


async def ping_db() -> bool:
    try:
        from sqlalchemy import text

        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
