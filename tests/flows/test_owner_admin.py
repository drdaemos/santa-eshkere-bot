"""ADMIN_TELEGRAM_ID: the bot's owner counts as an admin in every group, even
when Telegram hides them from the bot (anonymous admin: reported as "left")."""

import pytest

from src.config import Config
from tests.harness import db
from tests.harness.scenario import kick_off, register


@pytest.fixture
def owner(world, monkeypatch):
    actor = world.user("Owner")
    monkeypatch.setattr(Config, "ADMIN_TELEGRAM_ID", str(actor.id))
    return actor


async def group_with_people(world, office, hidden_from_bot):
    group, creator = office
    await creator.send(group, "/start")
    for i, name in enumerate(("Алиса", "Борис", "Вера")):
        actor = world.user(f"U{i}")
        group.add(actor)
        await register(actor, group, name, "книги")
    if hidden_from_bot is not None:
        group.add(hidden_from_bot, status="left")  # how Telegram shows a hidden admin
    return group, creator


async def test_owner_sees_and_manages_the_group(world, office, owner):
    group, _ = await group_with_people(world, office, owner)
    await owner.dm("/start")
    await owner.dm("/listgroups")
    assert "Office" in owner.last_dm.text
    await owner.dm("/listjoined")
    assert "(3)" in owner.last_dm.text
    await owner.dm("/dryrunassignments")
    assert "возможно" in owner.last_dm.text


async def test_owner_runs_group_commands_and_buttons(world, office, owner):
    group, _ = await group_with_people(world, office, owner)
    await owner.send(group, "/deadline off")
    assert "убран" in " ".join(m.text for m in group.feed[-3:])
    await kick_off(owner, group)
    assert len(await db.assignments()) == 3


async def test_other_people_are_not_affected(world, office, owner):
    group, _ = await group_with_people(world, office, owner)
    member = world.user("Member")
    group.add(member)
    out = await member.send(group, "/kickitoff")
    assert "Только администратор" in out.texts[-1]
    await member.dm("/listgroups")
    assert "Office" not in member.last_dm.text


async def test_without_the_setting_nothing_changes(world, office, monkeypatch):
    monkeypatch.setattr(Config, "ADMIN_TELEGRAM_ID", "")
    group, _ = await group_with_people(world, office, None)
    outsider = world.user("Outsider")
    await outsider.dm("/listgroups")
    assert "Office" not in outsider.last_dm.text


def test_owner_ids_parsing(monkeypatch):
    monkeypatch.setattr(Config, "ADMIN_TELEGRAM_ID", " 123, 456 ,")
    assert Config.owner_ids() == {123, 456}
    monkeypatch.setattr(Config, "ADMIN_TELEGRAM_ID", "")
    assert Config.owner_ids() == frozenset()
    monkeypatch.setattr(Config, "ADMIN_TELEGRAM_ID", "@eugene")
    with pytest.raises(ValueError, match="ADMIN_TELEGRAM_ID"):
        Config.validate()
