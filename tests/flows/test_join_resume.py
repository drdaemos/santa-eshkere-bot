"""Joining again while halfway through registering continues where the person
stopped, instead of starting over or answering with an error."""

from datetime import datetime

from src import clock
from tests.harness import db
from tests.harness.scenario import assert_no_errors, join_post, register


async def started_group(office):
    group, admin = office
    await admin.send(group, "/start")
    return group, admin


async def halfway(world, group, name="Алиса"):
    """Opened the bot, /join in the group, gave a name, no wishlist yet."""
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    await alice.dm(name)
    assert "вишлист" in alice.last_dm.text
    return alice


async def test_wishlist_prompt_does_not_mention_the_command(world, office):
    group, _ = await started_group(office)
    alice = await halfway(world, group)
    assert "/wishlist" not in alice.last_dm.text


async def test_join_again_in_the_group_asks_for_the_wishlist(world, office):
    group, _ = await started_group(office)
    alice = await halfway(world, group)
    out = await alice.send(group, "/join")
    assert "осталось прислать вишлист" in alice.last_dm.text
    assert not out.sent_to(group.id), "nothing in the group"
    await alice.dm("книги и чай")
    assert "ты в деле" in alice.last_dm.text
    assert [p.real_name for p in await db.participants_named("Алиса")] == ["Алиса"], "the name was kept"
    assert_no_errors(world)


async def test_join_button_again_asks_for_the_wishlist(world, office):
    group, _ = await started_group(office)
    alice = await halfway(world, group)
    await alice.tap_join(group)
    assert "осталось прислать вишлист" in alice.last_dm.text
    await alice.dm("книги")
    assert await db.participants_named("Алиса")


async def test_join_in_dm_asks_for_the_wishlist(world, office):
    group, _ = await started_group(office)
    alice = await halfway(world, group)
    out = await alice.dm("/join")
    assert "осталось прислать вишлист" in out.texts[-1]
    assert "только в группе" not in out.texts[-1]


async def test_join_again_before_the_name(world, office):
    group, _ = await started_group(office)
    alice = world.user("Alice")
    group.add(alice)
    await alice.tap_join(group)
    await alice.send(group, "/join")
    assert "осталось написать имя" in alice.last_dm.text
    assert alice.last_dm.buttons, "the one-tap name buttons are still there"


async def test_join_in_dm_when_already_in(world, office):
    group, _ = await started_group(office)
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    out = await alice.dm("/join")
    assert "Ты уже участвуешь" in out.texts[-1] and "книги" in out.texts[-1]


async def test_join_in_dm_for_a_stranger(world):
    alice = world.user("Alice")
    out = await alice.dm("/join")
    assert "Участвовать" in out.texts[-1]


async def test_halfway_people_continue_after_the_deadline(world, office, monkeypatch):
    group, admin = await started_group(office)
    now = datetime(2026, 11, 22, 9, 0)
    monkeypatch.setattr(clock, "utcnow", lambda: now)
    await admin.send(group, "/deadline 22.11 15:00")
    alice = await halfway(world, group)
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 11, 23, 9, 0))
    await alice.send(group, "/join")
    assert "осталось прислать вишлист" in alice.last_dm.text, "started before the deadline: may finish"
    await alice.dm("книги")
    assert await db.participants_named("Алиса")


async def test_halfway_in_one_group_joining_another_starts_fresh(world, office):
    group, _ = await started_group(office)
    alice = await halfway(world, group)
    owner = world.user("Owner")
    family = world.group("Family", owner=owner)
    await owner.send(family, "/start")
    family.add(alice)
    await alice.send(family, "/join")
    assert "Family" in alice.last_dm.text and "осталось" not in alice.last_dm.text
    assert join_post(family)
