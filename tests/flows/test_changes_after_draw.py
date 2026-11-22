"""Leaving, admin removal and late joining, before and after the draw.

After the draw people have started shopping, so the bot repairs the chain
instead of reshuffling: the result is always a complete valid draw, and only
the Santas whose assignment really changed hear about it.
"""

from sqlalchemy import select

from src.database.models import Participant
from tests.harness import db
from tests.harness.scenario import (
    ASSIGNMENT_MARKER,
    assert_no_errors,
    assignment_dms,
    assignment_of,
    join_post,
    kick_off,
    listed,
    register,
    select_group,
)

NAMES = ["Алиса", "Борис", "Вера", "Глеб", "Даша"]
REASSIGNED = "Небольшая перестановка"


async def setup(world, office, names=NAMES[:4], draw=True):
    group, admin = office
    await admin.send(group, "/start")
    people = {}
    for i, name in enumerate(names):
        actor = world.user(f"U{i}", username=f"user{i}")
        group.add(actor)
        await register(actor, group, name, f"хочу подарок для {name}")
        people[name] = actor
    if draw:
        await kick_off(admin, group)
    return group, admin, people


async def chain() -> dict[str, str]:
    """giver name -> receiver name, straight from the database."""
    names = {p.id: p.real_name for p in await db.fetch_all(select(Participant))}
    return {names[a.giver_id]: names[a.receiver_id] for a in await db.assignments()}


def assert_complete_draw(pairs: dict[str, str], people: set[str]) -> None:
    assert set(pairs) == people, "everyone gives"
    assert sorted(pairs.values()) == sorted(people), "everyone receives exactly once"
    assert all(g != r for g, r in pairs.items())


def dm_counts(people) -> dict[str, int]:
    return {name: len(actor.inbox) for name, actor in people.items()}


async def leave(actor):
    await actor.dm("/leave")
    return await actor.click(actor.last_dm, "Да")


# --- /leave -------------------------------------------------------------------


async def test_leave_before_draw_just_removes_the_person(world, office):
    group, admin, people = await setup(world, office, draw=False)
    await leave(people["Вера"])
    assert "больше не участвуешь" in people["Вера"].last_dm.text
    assert listed(join_post(group)) == ["Алиса", "Борис", "Глеб"], "the join post is updated, no extra message"
    assert await db.participants_named("Вера") == []

    await people["Вера"].dm("/status")
    assert "Сначала нужно зарегистрироваться" in people["Вера"].last_dm.text
    await kick_off(admin, group)
    assert_complete_draw(await chain(), {"Алиса", "Борис", "Глеб"})
    assert_no_errors(world)


async def test_leave_after_draw_rewires_only_the_affected_santa(world, office):
    group, admin, people = await setup(world, office, NAMES[:5])
    before = await chain()
    leaver = "Вера"
    santa = next(g for g, r in before.items() if r == leaver)
    counts = dm_counts(people)
    group_messages = len(group.feed)

    await leave(people[leaver])

    after = await chain()
    remaining = set(NAMES[:5]) - {leaver}
    assert_complete_draw(after, remaining)
    changed = {g for g in after if after[g] != before[g]}
    assert santa in changed and len(changed) <= 2
    # exactly the changed Santas got a message, and it names their new receiver
    for name, actor in people.items():
        if name in changed:
            assert REASSIGNED in actor.last_dm.text
            assert assignment_of(actor) == after[name]
            assert f"хочу подарок для {after[name]}" in actor.last_dm.text
        elif name != leaver:
            assert len(actor.inbox) == counts[name], f"{name} must not be bothered"
    assert len(group.feed) == group_messages, "nothing new in the group"
    assert leaver not in listed(join_post(group))
    assert leaver not in after.values()
    assert_no_errors(world)


async def test_status_after_reassignment_shows_the_new_receiver(world, office):
    group, admin, people = await setup(world, office, NAMES[:5])
    santa = next(g for g, r in (await chain()).items() if r == "Глеб")
    await leave(people["Глеб"])
    new_receiver = (await chain())[santa]
    await people[santa].dm("/status")
    assert f"Кому дарить: {new_receiver}" in people[santa].last_dm.text


async def test_leave_is_refused_when_too_few_would_remain(world, office):
    group, admin, people = await setup(world, office, NAMES[:3])
    before = await chain()
    out = await leave(people["Алиса"])
    assert "меньше 3 участников" in out.texts[-1]
    assert await chain() == before, "nothing changed"
    assert len(await db.participants_named("Алиса")) == 1


async def test_leave_is_refused_when_rules_allow_no_small_repair(world, office):
    # 4 people, rule Алиса <-> Вера; if Борис leaves, {Алиса, Вера, Глеб} has no valid draw at all
    group, admin, people = await setup(world, office, draw=False)
    await select_group(admin, group)
    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Алиса")
    await admin.click(admin.last_dm, "Вера")
    await kick_off(admin, group)
    before = await chain()

    out = await leave(people["Борис"])
    assert "правил исключения" in out.texts[-1]
    assert await chain() == before


async def test_leave_with_several_groups_asks_which_one(world, office):
    group, admin, people = await setup(world, office, draw=False)
    alice = people["Алиса"]
    other = world.group("Family", owner=admin, members=(alice,))
    await admin.send(other, "/start")
    await alice.send(other, "/join")
    await alice.dm("Алиса")
    await alice.dm("носки и книги")

    await alice.dm("/leave")
    assert "Из какой группы" in alice.last_dm.text
    await alice.click(alice.last_dm, "Family")
    assert "Family" in alice.last_dm.text
    await alice.click(alice.last_dm, "Да")
    assert len(await db.participants_named("Алиса")) == 1, "still in the office season"
    assert_no_errors(world)


async def test_leave_button_of_someone_else_does_nothing(world, office):
    group, admin, people = await setup(world, office, draw=False)
    alice, boris = people["Алиса"], people["Борис"]
    await alice.dm("/leave")
    forged = next(data for text, data in alice.last_dm.buttons if text == "Да")
    out = await boris.click_data(alice.last_dm, forged)
    assert [c.method for c in out.calls] == ["answerCallbackQuery"]
    assert len(await db.participants_named("Алиса")) == 1


async def test_leave_twice_with_old_button_is_stale(world, office):
    group, admin, people = await setup(world, office, draw=False)
    alice = people["Алиса"]
    await alice.dm("/leave")
    prompt = alice.last_dm
    yes = next(data for text, data in prompt.buttons if text == "Да")
    await alice.click_data(prompt, yes)
    out = await alice.click_data(prompt, yes)  # double tap / replayed button
    assert [c.method for c in out.calls] == ["answerCallbackQuery"]
    assert_no_errors(world)


async def test_reassigned_santa_who_blocked_the_bot_is_named_in_the_group(world, office):
    group, admin, people = await setup(world, office, NAMES[:5])
    santa = next(g for g, r in (await chain()).items() if r == "Даша")
    people[santa].block_bot()
    await leave(people["Даша"])
    assert any("Не смог написать" in m.text and santa in m.text for m in group.feed)


async def test_rejoining_after_leaving_a_drawn_season_splices_back_in(world, office):
    group, admin, people = await setup(world, office, NAMES[:4])
    await leave(people["Глеб"])
    await register(people["Глеб"], group, "Глеб", "снова хочу подарок")
    assert_complete_draw(await chain(), set(NAMES[:4]))
    assert assignment_of(people["Глеб"]) is not None


# --- admin removal ------------------------------------------------------------


async def remove(admin, group, name):
    await select_group(admin, group)
    await admin.dm("/removeparticipant")
    await admin.click(admin.last_dm, name)
    return await admin.click(admin.last_dm, "Да")


async def test_admin_removes_participant_after_draw(world, office):
    group, admin, people = await setup(world, office, NAMES[:5])
    before = await chain()
    out = await remove(admin, group, "Борис")

    assert_complete_draw(await chain(), set(NAMES[:5]) - {"Борис"})
    done = admin.last_dm.text
    assert "Борис больше не участвует" in done
    # the admin sees how many Santas changed, never who gives to whom
    assert "Новое задание получили участников" in done
    assert not any(f"{g} →" in done or ASSIGNMENT_MARKER in done for g in before)
    assert "Админ убрал тебя" in people["Борис"].last_dm.text
    assert "Борис" not in listed(join_post(group))
    assert all(m is join_post(group) for m in out.sent_to(group.id)), "only the join post changes"
    assert_no_errors(world)


async def test_removal_rechecks_admin_rights_at_confirmation(world, office):
    group, admin, people = await setup(world, office, draw=False)
    await select_group(admin, group)
    await admin.dm("/removeparticipant")
    await admin.click(admin.last_dm, "Вера")
    group.chat.members[admin.id] = "member"  # demoted while the prompt was open
    out = await admin.click(admin.last_dm, "Да")
    assert [c.method for c in out.calls if c.method != "getChatMember"] == ["answerCallbackQuery"]
    assert len(await db.participants_named("Вера")) == 1


async def test_non_admin_cannot_use_removal_buttons(world, office):
    group, admin, people = await setup(world, office, draw=False)
    await select_group(admin, group)
    await admin.dm("/removeparticipant")
    await admin.click(admin.last_dm, "Вера")
    confirm = admin.last_dm
    yes = next(data for text, data in confirm.buttons if text == "Да")
    await people["Алиса"].click_data(confirm, yes)
    assert len(await db.participants_named("Вера")) == 1


async def test_removal_picker_pages_through_a_big_group(world, office):
    names = [f"Гость{i:02d}" for i in range(11)]
    group, admin, people = await setup(world, office, names, draw=False)
    await select_group(admin, group)
    await admin.dm("/removeparticipant")
    await admin.click(admin.last_dm, "Вперёд")
    await admin.click(admin.last_dm, "Гость10")
    await admin.click(admin.last_dm, "Да")
    assert await db.participants_named("Гость10") == []
    assert_no_errors(world)


# --- late joining -------------------------------------------------------------


async def test_late_joiner_gets_an_assignment_and_one_santa_is_rewired(world, office):
    group, admin, people = await setup(world, office, NAMES[:4])
    before = await chain()
    counts = dm_counts(people)

    late = world.user("Late")
    group.add(late)
    await late.dm("/start")
    await late.send(group, "/join")
    assert "Распределение уже прошло" in late.last_dm.text
    await late.dm("Даша")
    await late.dm("варежки и какао")

    after = await chain()
    assert_complete_draw(after, set(NAMES[:5]))
    assert "задание — следующим сообщением" in late.inbox[-2].text
    assert assignment_of(late) == after["Даша"]
    changed = [g for g in before if after[g] != before[g]]
    assert len(changed) == 1 and after[changed[0]] == "Даша"
    santa = people[changed[0]]
    assert REASSIGNED in santa.last_dm.text and "варежки и какао" in santa.last_dm.text
    for name, actor in people.items():
        if name != changed[0]:
            assert len(actor.inbox) == counts[name]
    assert_no_errors(world)


async def test_late_joiner_with_rules_against_everyone_is_turned_away(world, office):
    group, admin, people = await setup(world, office, NAMES[:3], draw=False)
    late = world.user("Late")
    group.add(late)
    # last season's rules carry over by Telegram id: block Late from everyone
    await register(late, group, "Даша", "варежки")
    await select_group(admin, group)
    for name in NAMES[:3]:
        await admin.dm("/addrule")
        await admin.click(admin.last_dm, "Даша")
        await admin.click(admin.last_dm, name)
    await leave(late)
    await kick_off(admin, group)
    before = await chain()

    await register(late, group, "Даша", "варежки")
    assert "не получается вписать тебя" in late.last_dm.text
    assert await db.participants_named("Даша") == []
    assert await chain() == before
    assert assignment_dms(late) == []


async def test_late_join_reuse_button_also_splices(world, office):
    group, admin, people = await setup(world, office, NAMES[:3])
    late = world.user("Late")
    group.add(late)
    await register(late, group, "Глеб", "варежки")
    await admin.send(group, "/newseason")
    await admin.click(group.feed[-1], "Да")
    for actor in people.values():
        await actor.send(group, "/join")
        await actor.click(actor.last_dm, "Как в прошлый раз")
        await actor.click(actor.last_dm, "Оставить прошлый")
    await kick_off(admin, group)

    await late.send(group, "/join")
    await late.click(late.last_dm, "Как в прошлый раз")
    await late.click(late.last_dm, "Оставить прошлый")
    assert_complete_draw(await chain_for_current(), set(NAMES[:3]) | {"Глеб"})
    assert assignment_of(late) is not None
    assert_no_errors(world)


async def chain_for_current() -> dict[str, str]:
    current = (await db.events())[-1]
    names = {p.id: p.real_name for p in await db.fetch_all(select(Participant).where(Participant.event_id == current.id))}
    return {names[a.giver_id]: names[a.receiver_id] for a in await db.assignments(current.id)}
