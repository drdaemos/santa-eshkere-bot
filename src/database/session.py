"""Database session management"""

import os
from typing import AsyncGenerator

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

# Global engine and session maker
_engine = None
_async_session_maker = None


def get_database_url() -> str:
    """Get database URL from environment, handling SQLite vs PostgreSQL"""
    database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./santa_eshkere.db")

    # Convert PostgreSQL URL to async version if needed
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)

    return database_url


def run_migrations() -> None:
    """Run Alembic migrations to upgrade the database"""
    # Get the path to alembic.ini (in the project root)
    alembic_cfg = Config("alembic.ini")

    # Run migrations to the latest version
    command.upgrade(alembic_cfg, "head")


async def init_db() -> None:
    """Initialize database engine and run migrations"""
    global _engine, _async_session_maker

    database_url = get_database_url()

    # Create async engine
    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

    # Create session maker
    _async_session_maker = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Run Alembic migrations to ensure database is up to date
    run_migrations()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session"""
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    """Close database connections"""
    global _engine
    if _engine:
        await _engine.dispose()
