"""Database session management"""

import logging
import os
from typing import AsyncGenerator

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

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
    try:
        logger.info("Checking database migrations...")

        # Get the path to alembic.ini (in the project root)
        alembic_cfg = Config("alembic.ini")
        # Suppress alembic's own logging to avoid duplicate messages
        alembic_cfg.set_main_option("script_location", "alembic")

        # Check if this is an existing database without alembic tracking
        from sqlalchemy import create_engine, inspect
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext

        # Create a sync engine just for checking (alembic uses sync)
        database_url = get_database_url()
        # Convert async URL back to sync for inspection
        sync_url = database_url.replace("+aiosqlite", "").replace("+asyncpg", "")
        engine = create_engine(sync_url)

        # Check if alembic_version table exists
        inspector = inspect(engine)
        has_alembic_version = "alembic_version" in inspector.get_table_names()
        has_groups_table = "groups" in inspector.get_table_names()

        if not has_alembic_version and has_groups_table:
            # Database exists but not tracked by Alembic - stamp it with current version
            logger.info("Existing database detected. Initializing migration tracking...")
            command.stamp(alembic_cfg, "head")
            logger.info("Database migration tracking initialized")
        else:
            # Run migrations normally
            # This is idempotent - only applies migrations that haven't been run yet
            command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations completed successfully")

        engine.dispose()

    except Exception as e:
        logger.error(f"Failed to run database migrations: {e}")
        raise


async def init_db() -> None:
    """Initialize database engine"""
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
