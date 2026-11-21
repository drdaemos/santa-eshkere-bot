"""Database engine and session management"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None


def get_database_url() -> str:
    """DATABASE_URL with the async driver filled in (Railway gives postgresql://)."""
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./db/santa_eshkere.db")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return database_url


def _enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def init_db() -> None:
    global _engine, _async_session_maker
    url = get_database_url()
    _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    if url.startswith("sqlite"):
        # Postgres enforces FKs/cascades; make local SQLite behave the same
        event.listen(_engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    _async_session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Unit of work: commits on success, rolls back on error."""
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
