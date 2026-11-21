"""The seasons migration runs once, on production data from the 2025 party.

Dialect-agnostic: runs on SQLite by default and on Postgres with TEST_DATABASE_URL
(which is what production runs, including the sequence fix-up branch).
"""

import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.database.session import get_database_url
from tests.conftest import ROOT, _wipe_postgres

SEED = [
    """INSERT INTO groups (id, telegram_chat_id, group_name, activated_at, is_active) VALUES
        (1, -1001, 'Office', '2025-12-01 10:00:00', TRUE),
        (2, -1002, 'Friends', '2025-12-05 10:00:00', TRUE),
        (3, -1003, 'Empty', '2025-12-06 10:00:00', TRUE)""",
    """INSERT INTO users (id, telegram_id, telegram_username, real_name, wishlist, group_id, joined_at) VALUES
        (1, 101, 'alice', 'Алиса', 'книги', 1, '2025-12-02 10:00:00'),
        (2, 102, NULL, 'Борис', NULL, 1, '2025-12-02 11:00:00'),
        (3, 103, 'vera', 'Вера', 'чай', 1, '2025-12-03 10:00:00'),
        (4, 104, NULL, 'Глеб', 'кофе', 1, '2025-12-03 11:00:00'),
        (5, 101, 'alice', 'Алиса', 'книги', 2, '2025-12-06 10:00:00'),
        (6, 105, NULL, 'Даша', 'носки', 2, '2025-12-06 11:00:00')""",
    """INSERT INTO assignments (group_id, event_year, giver_id, receiver_id, assigned_at) VALUES
        (1, 2025, 1, 2, '2025-12-14 20:00:00'),
        (1, 2025, 2, 3, '2025-12-14 20:00:00'),
        (1, 2025, 3, 4, '2025-12-14 20:00:00'),
        (1, 2025, 4, 1, '2025-12-14 20:00:00')""",
    """INSERT INTO exclusions (user1_id, user2_id, group_id, created_at) VALUES
        (1, 2, 1, '2025-12-10 10:00:00'),
        (3, 4, 1, '2025-12-10 10:00:00')""",
]


def _alembic(revision: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, revision)


@pytest.fixture
async def legacy_db(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        monkeypatch.setenv("DATABASE_URL", url)
        await _wipe_postgres()
    else:
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    await asyncio.to_thread(_alembic, "65a064dc1941")
    engine = create_async_engine(get_database_url())
    async with engine.begin() as conn:
        for statement in SEED:
            await conn.execute(text(statement))
    await asyncio.to_thread(_alembic, "head")
    yield engine
    await engine.dispose()


async def rows(engine: AsyncEngine, sql: str, **params) -> list:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).mappings().all())


async def test_drawn_group_becomes_closed_season_with_history(legacy_db):
    events = {r["group_id"]: r for r in await rows(legacy_db, "SELECT * FROM events")}
    assert set(events) == {1, 2}, "a group with no users needs no event"
    assert events[1]["status"] == "closed" and events[1]["drawn_at"] is not None
    assert events[2]["status"] == "open"

    office = await rows(
        legacy_db, "SELECT id, telegram_id, wishlist FROM participants WHERE event_id = :e ORDER BY id", e=events[1]["id"]
    )
    assert [(r["id"], r["telegram_id"]) for r in office] == [(1, 101), (2, 102), (3, 103), (4, 104)]
    assert office[1]["wishlist"] == "", "NULL wishlist becomes empty, column is NOT NULL now"

    pairs = await rows(legacy_db, "SELECT giver_id, receiver_id FROM assignments ORDER BY giver_id")
    assert [(p["giver_id"], p["receiver_id"]) for p in pairs] == [(1, 2), (2, 3), (3, 4), (4, 1)]


async def test_rules_are_rekeyed_by_telegram_id(legacy_db):
    rules = await rows(legacy_db, "SELECT group_id, telegram_id_a, telegram_id_b FROM exclusions ORDER BY telegram_id_a")
    assert [(r["group_id"], r["telegram_id_a"], r["telegram_id_b"]) for r in rules] == [(1, 101, 102), (1, 103, 104)]


async def test_same_person_in_two_groups_keeps_both_entries(legacy_db):
    assert len(await rows(legacy_db, "SELECT event_id FROM participants WHERE telegram_id = 101")) == 2


async def test_new_rows_get_fresh_ids_after_explicit_id_copy(legacy_db):
    # On Postgres this needs the migration's sequence fix-up (setval)
    async with legacy_db.begin() as conn:
        await conn.execute(text("INSERT INTO events (group_id, status, created_at) VALUES (1, 'open', '2026-11-22 10:00:00')"))
        event_id = (await conn.execute(text("SELECT MAX(id) FROM events"))).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO participants (event_id, telegram_id, real_name, wishlist, joined_at) "
                "VALUES (:e, 101, 'Алиса', 'книги', '2026-11-22 10:00:00')"
            ),
            {"e": event_id},
        )
    newest = await rows(legacy_db, "SELECT MAX(id) AS id FROM participants")
    assert newest[0]["id"] > 6


async def test_only_one_current_season_per_group(legacy_db):
    async with legacy_db.begin() as conn:
        await conn.execute(text("INSERT INTO events (group_id, status, created_at) VALUES (1, 'open', '2026-11-22 10:00:00')"))
    with pytest.raises(IntegrityError):
        async with legacy_db.begin() as conn:
            await conn.execute(text("INSERT INTO events (group_id, status, created_at) VALUES (1, 'open', '2026-11-22 11:00:00')"))


async def test_models_match_migrated_schema(db):
    """Autogenerate against the migrated DB must find nothing to do."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from src.database import session as session_module
    from src.database.models import Base

    async with session_module._engine.connect() as conn:
        diff = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    assert diff == []
