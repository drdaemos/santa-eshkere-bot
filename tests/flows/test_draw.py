"""/kickitoff: generating and delivering assignments, and what happens next."""

import pytest
from sqlalchemy import select

from src.config import config
from src.database.models import Assignment
from tests.harness import db
from tests.harness.scenario import assert_no_errors, assignment_dms, assignment_of, register, select_group
from tests.known_bugs import known_bug

NAMES = ["Алиса", "Борис", "Вера", "Глеб", "Даша"]


async def setup_group(world, office, names=NAMES[:4], wishlists=None):
    group, admin = office
    await admin.send(group, "/start")
    people = {}
    for i, name in enumerate(names):
        actor = world.user(f"U{i}", username=f"user{i}")
        group.add(actor)
        await register(actor, group, name, (wishlists or {}).get(name, f"хочу подарок для {name}"))
        people[name] = actor
    return group, admin, people


async def test_everyone_gets_exactly_one_valid_assignment(world, office):
    group, admin, people = await setup_group(world, office)
    out = await admin.send(group, "/kickitoff")
    assert any("Сани поехали" in m.text for m in out.sent_to(group.id))

    received = {name: assignment_of(actor) for name, actor in people.items()}
    assert all(received.values()), received
    assert sorted(received.values()) == sorted(people), "each person receives exactly once"
    assert all(giver != receiver for giver, receiver in received.items())
    # the Santa sees the receiver's wishlist
    for giver, receiver in received.items():
        assert f"хочу подарок для {receiver}" in assignment_dms(people[giver])[-1].text
    assert_no_errors(world)


async def test_status_after_draw_shows_receiver(world, office):
    group, admin, people = await setup_group(world, office, NAMES[:3])
    await admin.send(group, "/kickitoff")
    alice = people["Алиса"]
    await alice.dm("/status")
    assert f"Кому дарить: {assignment_of(alice)}" in alice.last_dm.text


async def test_exclusions_are_respected(world, office):
    group, admin, people = await setup_group(world, office)
    await select_group(admin, group)
    for a, b in [("Алиса", "Борис"), ("Вера", "Глеб")]:
        await admin.dm("/addrule")
        await admin.click(admin.last_dm, a)
        await admin.click(admin.last_dm, b)

    for _ in range(5):
        await admin.send(group, "/kickitoff")
        received = {name: assignment_of(actor) for name, actor in people.items()}
        assert received["Алиса"] != "Борис" and received["Борис"] != "Алиса"
        assert received["Вера"] != "Глеб" and received["Глеб"] != "Вера"


async def test_needs_three_participants(world, office):
    group, admin, _ = await setup_group(world, office, NAMES[:2])
    out = await admin.send(group, "/kickitoff")
    assert "минимум 3" in out.texts[-1]
    assert await db.assignments() == []


async def test_impossible_rules_are_reported(world, office):
    group, admin, _ = await setup_group(world, office, NAMES[:3])
    await select_group(admin, group)
    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Алиса")
    await admin.click(admin.last_dm, "Борис")
    out = await admin.send(group, "/kickitoff")
    assert "Невозможно" in out.texts[-1]
    assert await db.assignments() == []


async def test_only_admin_can_kick_off(world, office):
    group, admin, people = await setup_group(world, office, NAMES[:3])
    out = await people["Алиса"].send(group, "/kickitoff")
    assert "Только администратор" in out.texts[-1]
    assert await db.assignments() == []


# --- where real usage falls through -------------------------------------------------


@known_bug("Receiver's wishlist goes into a Markdown message unescaped: their Santa never gets the assignment, /status fails too")
async def test_assignment_delivered_whatever_the_wishlist(world, office):
    group, admin, people = await setup_group(
        world, office, NAMES[:3], wishlists={"Вера": "вот это: https://www.wildberries.ru/catalog/123/detail_aspx"}
    )
    await admin.send(group, "/kickitoff")
    missing = [name for name, actor in people.items() if assignment_of(actor) is None]
    assert missing == []


@known_bug("Assignment message = template + wishlist; a long wishlist overflows 4096 and the Santa gets nothing")
async def test_assignment_delivered_with_long_wishlist(world, office):
    # 3900 chars fits in a user's message; registration echo is a separate bug, so seed directly
    group, admin, people = await setup_group(world, office, NAMES[:3])
    await db.set_wishlist("Вера", "мечтаю о " * 450)  # 4050 chars, under the 4096 a user can send
    await admin.send(group, "/kickitoff")
    assert all(assignment_of(actor) for actor in people.values())


@known_bug("A second /kickitoff (mis-tap, or 'did it work?') reshuffles everyone after gifts may be bought")
async def test_second_kickoff_does_not_reshuffle(world, office):
    group, admin, people = await setup_group(world, office)
    await admin.send(group, "/kickitoff")
    first = {name: assignment_of(actor) for name, actor in people.items()}
    await admin.send(group, "/kickitoff")
    assert all(len(assignment_dms(actor)) == 1 for actor in people.values()), "nobody should get a second assignment"
    assert {name: assignment_of(actor) for name, actor in people.items()} == first


@known_bug("Failed deliveries (user blocked the bot) are only logged; the admin is never told who missed out")
async def test_admin_is_told_about_failed_deliveries(world, office):
    group, admin, people = await setup_group(world, office)
    people["Глеб"].block_bot()
    out = await admin.send(group, "/kickitoff")
    to_admin_or_group = [m.text for m in out.sent if m.chat_id in (admin.id, group.id)]
    assert any("Глеб" in text for text in to_admin_or_group), to_admin_or_group


@known_bug("Joining after the draw registers the user with nobody giving to them and no notice to anyone")
async def test_late_joiner_is_not_silently_left_out(world, office):
    group, admin, people = await setup_group(world, office, NAMES[:3])
    await admin.send(group, "/kickitoff")
    late = world.user("Late")
    group.add(late)
    await register(late, group, "Опоздун", "что угодно")

    registered = await db.users_named("Опоздун")
    if registered:  # if the bot let them in, someone must now be gifting them
        receivers = {a.receiver_id for a in await db.assignments()}
        assert registered[0].id in receivers


# --- next season -------------------------------------------------------------------


@pytest.fixture
def year(monkeypatch):
    def set_year(value: int) -> None:
        monkeypatch.setattr(config, "EVENT_YEAR", value)

    return set_year


@known_bug("Participants are per group, not per season: returning players are told they're 'already registered'")
async def test_returning_player_can_join_next_season(world, office, year):
    year(2025)
    group, admin, people = await setup_group(world, office, NAMES[:3])
    await admin.send(group, "/kickitoff")

    year(2026)
    alice = people["Алиса"]
    out = await alice.send(group, "/join")
    assert not any("уже зарегистрированы" in t for t in out.texts)


@known_bug("Last year's participants are drawn again this year even if they never re-joined")
async def test_last_years_players_are_not_drawn_automatically(world, office, year):
    year(2025)
    group, admin, veterans = await setup_group(world, office, NAMES[:3])
    await admin.send(group, "/kickitoff")

    year(2026)
    newcomers = {}
    for i, name in enumerate(["Жора", "Зоя", "Игорь"]):
        actor = world.user(f"N{i}")
        group.add(actor)
        await register(actor, group, name, "книги")
        newcomers[name] = actor
    await admin.send(group, "/kickitoff")

    assert all(len(assignment_dms(a)) == 1 for a in veterans.values()), "veterans got a 2026 assignment"
    assert len(await db.fetch_all(select(Assignment).where(Assignment.event_year == 2026))) == 3
