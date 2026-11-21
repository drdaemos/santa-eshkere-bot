"""The seasons migration runs once, on production data from the 2025 party."""

import os
import sqlite3

import pytest

from tests.conftest import ROOT

pytestmark = pytest.mark.skipif(bool(os.environ.get("TEST_DATABASE_URL")), reason="seeds legacy rows via sqlite3")


def _alembic(revision: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, revision)


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path.as_posix()}")
    _alembic("65a064dc1941")
    con = sqlite3.connect(path)
    con.executescript(
        """
        INSERT INTO groups (id, telegram_chat_id, group_name, activated_at, is_active) VALUES
            (1, -1001, 'Office', '2025-12-01 10:00:00', 1),
            (2, -1002, 'Friends', '2025-12-05 10:00:00', 1),
            (3, -1003, 'Empty', '2025-12-06 10:00:00', 1);
        INSERT INTO users (id, telegram_id, telegram_username, real_name, wishlist, group_id, joined_at) VALUES
            (1, 101, 'alice', 'Алиса', 'книги', 1, '2025-12-02 10:00:00'),
            (2, 102, NULL, 'Борис', NULL, 1, '2025-12-02 11:00:00'),
            (3, 103, 'vera', 'Вера', 'чай', 1, '2025-12-03 10:00:00'),
            (4, 104, NULL, 'Глеб', 'кофе', 1, '2025-12-03 11:00:00'),
            (5, 101, 'alice', 'Алиса', 'книги', 2, '2025-12-06 10:00:00'),
            (6, 105, NULL, 'Даша', 'носки', 2, '2025-12-06 11:00:00');
        INSERT INTO assignments (group_id, event_year, giver_id, receiver_id, assigned_at) VALUES
            (1, 2025, 1, 2, '2025-12-14 20:00:00'),
            (1, 2025, 2, 3, '2025-12-14 20:00:00'),
            (1, 2025, 3, 4, '2025-12-14 20:00:00'),
            (1, 2025, 4, 1, '2025-12-14 20:00:00');
        INSERT INTO exclusions (user1_id, user2_id, group_id, created_at) VALUES
            (1, 2, 1, '2025-12-10 10:00:00'),
            (3, 4, 1, '2025-12-10 10:00:00');
        """
    )
    con.commit()
    con.close()
    _alembic("head")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    yield con
    con.close()


def test_drawn_group_becomes_closed_season_with_history(legacy_db):
    events = {r["group_id"]: dict(r) for r in legacy_db.execute("SELECT * FROM events")}
    assert set(events) == {1, 2}, "a group with no users needs no event"
    assert events[1]["status"] == "closed" and events[1]["drawn_at"] is not None
    assert events[2]["status"] == "open"

    office = legacy_db.execute(
        "SELECT id, telegram_id, real_name, wishlist FROM participants WHERE event_id = ? ORDER BY id", (events[1]["id"],)
    ).fetchall()
    assert [(r["id"], r["telegram_id"]) for r in office] == [(1, 101), (2, 102), (3, 103), (4, 104)]
    assert office[1]["wishlist"] == "", "NULL wishlist becomes empty, column is NOT NULL now"

    pairs = legacy_db.execute("SELECT giver_id, receiver_id FROM assignments ORDER BY giver_id").fetchall()
    assert [tuple(p) for p in pairs] == [(1, 2), (2, 3), (3, 4), (4, 1)]


def test_rules_are_rekeyed_by_telegram_id(legacy_db):
    rules = legacy_db.execute("SELECT group_id, telegram_id_a, telegram_id_b FROM exclusions ORDER BY telegram_id_a").fetchall()
    assert [tuple(r) for r in rules] == [(1, 101, 102), (1, 103, 104)]


def test_same_person_in_two_groups_keeps_both_entries(legacy_db):
    rows = legacy_db.execute("SELECT event_id FROM participants WHERE telegram_id = 101").fetchall()
    assert len(rows) == 2


def test_new_season_can_be_opened_next_to_the_closed_one(legacy_db):
    legacy_db.execute("INSERT INTO events (group_id, status, created_at) VALUES (1, 'open', '2026-11-22 10:00:00')")
    with pytest.raises(sqlite3.IntegrityError):
        legacy_db.execute("INSERT INTO events (group_id, status, created_at) VALUES (1, 'open', '2026-11-22 11:00:00')")


async def test_models_match_migrated_schema(db):
    """Autogenerate against the migrated DB must find nothing to do."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from src.database import session as session_module
    from src.database.models import Base

    async with session_module._engine.connect() as conn:
        diff = await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    assert diff == []
