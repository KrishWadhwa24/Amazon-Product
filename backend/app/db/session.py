"""Async PostgreSQL engine, session factory, and request-scoped dependency.

Wires a SQLAlchemy async engine (``create_async_engine`` over the asyncpg
driver) and an ``async_sessionmaker`` so the service/persistence layers can run
non-blocking queries against the Relational_Store.

Connections are created lazily: the engine and sessionmaker are built on first
use (memoized), so importing this module never opens a socket or requires a
running database. This keeps imports cheap for tests and tooling.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use.

    The engine is memoized so a single connection pool is shared across the
    application. ``pool_pre_ping`` recycles stale connections transparently.
    """
    settings = get_settings()
    return create_async_engine(
        settings.db_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the memoized async session factory bound to the engine."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped ``AsyncSession``.

    The session is opened per request and closed when the request finishes.
    Any unhandled exception rolls back the transaction before propagating so a
    failed request never leaves a half-applied write committed.
    """
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine's connection pool (used on app shutdown)."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
