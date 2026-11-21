"""Shared fixtures.

Database: a fresh SQLite file per test by default, schema built by running the
real Alembic migrations. Set TEST_DATABASE_URL to a disposable Postgres
database (it is wiped per test) to run against the production engine.
"""

import asyncio
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Must be set before src.config is imported (it reads env at import time).
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:TEST-fake-token-for-the-in-process-bot-api"
os.environ["USE_WEBHOOK"] = "false"
os.environ.pop("EVENT_YEAR", None)

from src.database.session import close_db, get_database_url, init_db  # noqa: E402
from tests.harness.scenario import Group, Harness, World  # noqa: E402


def _run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")


async def _wipe_postgres() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(get_database_url())
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture
async def db(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
        await _wipe_postgres()
    else:
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'santa.db').as_posix()}")
    # alembic/env.py calls asyncio.run(); keep it off the test's running loop
    await asyncio.to_thread(_run_migrations)
    await init_db()
    yield
    await close_db()


@pytest.fixture
async def harness(db):
    h = Harness()
    await h.start()
    yield h
    await h.stop()


@pytest.fixture
def world(harness) -> World:
    return World(harness)


@pytest.fixture
def office(world) -> tuple[Group, "object"]:
    """A group whose owner is `admin`. Returns (group, admin)."""
    admin = world.user("Eugene", username="eugene")
    return world.group("Office", owner=admin), admin
