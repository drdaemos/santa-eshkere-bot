"""Joining deadline: /deadline in the group, enforcement, and what happens when it passes.

Time is frozen (src.clock.utcnow) so tests can move past the deadline.
Default time zone is Europe/Moscow (UTC+3).
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from src import clock
from src.config import config
from src.services import deadlines
from src.validation import ValidationError, parse_deadline
from tests.harness import db
from tests.harness.scenario import JOIN_BUTTON, assert_no_errors, join_post, kick_off, register

START = datetime(2026, 11, 22, 9, 0)  # UTC = 12:00 in Moscow


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def frozen(monkeypatch):
    c = Clock(START)
    monkeypatch.setattr(clock, "utcnow", lambda: c.now)
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Moscow")
    return c


async def season_with(world, office, names=("Алиса", "Борис", "Вера")):
    group, admin = office
    await admin.send(group, "/start")
    people = {}
    for i, name in enumerate(names):
        actor = world.user(f"U{i}")
        group.add(actor)
        await register(actor, group, name, f"вишлист {name}")
        people[name] = actor
    return group, admin, people


def has_join_button(message) -> bool:
    return any(text == JOIN_BUTTON for text, _ in message.buttons)


# --- parsing --------------------------------------------------------------------------


NOW_LOCAL = datetime(2026, 11, 22, 12, 0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30.11", datetime(2026, 11, 30, 23, 59)),
        ("30.11 18:00", datetime(2026, 11, 30, 18, 0)),
        ("30.11 18.30", datetime(2026, 11, 30, 18, 30)),
        ("  30.11   9:05 ", datetime(2026, 11, 30, 9, 5)),
        ("30.11.2026 18:00", datetime(2026, 11, 30, 18, 0)),
        ("30.11.26", datetime(2026, 11, 30, 23, 59)),
        ("22.11", datetime(2026, 11, 22, 23, 59)),  # today, end of day
        ("22.11 12:01", datetime(2026, 11, 22, 12, 1)),
        ("10.01", datetime(2027, 1, 10, 23, 59)),  # January typed in November
        ("01.12", datetime(2026, 12, 1, 23, 59)),
    ],
)
def test_deadline_formats(raw, expected):
    assert parse_deadline(raw, NOW_LOCAL) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("завтра", "Не понял"),
        ("30/11", "Не понял"),
        ("18:00", "Не понял"),
        ("31.02", "Такой даты нет"),
        ("30.11 25:00", "Такой даты нет"),
        ("30.13", "Такой даты нет"),
        ("22.11 11:59", "уже прошла"),  # earlier today
        ("21.11", "уже прошла"),  # yesterday: not silently next year
        ("30.11.2025", "уже прошла"),
        ("30.11.2028", "Слишком далеко"),
    ],
)
def test_bad_deadlines_are_explained(raw, reason):
    with pytest.raises(ValidationError, match=reason):
        parse_deadline(raw, NOW_LOCAL)


def test_time_zone_conversion(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Moscow")
    assert clock.to_utc(datetime(2026, 11, 30, 18, 0)) == datetime(2026, 11, 30, 15, 0)
    assert clock.show(datetime(2026, 11, 30, 15, 0)) == "30.11 в 18:00"
    monkeypatch.setattr(config, "TIMEZONE", "Europe/Riga")  # UTC+2 in winter
    assert clock.to_utc(datetime(2026, 11, 30, 18, 0)) == datetime(2026, 11, 30, 16, 0)


# --- setting it ------------------------------------------------------------------------


async def test_admin_sets_deadline_and_the_join_post_shows_it(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    out = await admin.send(group, "/deadline 30.11 18:00")
    assert "30.11 в 18:00" in out.texts[-1]
    event = (await db.events())[-1]
    assert event.join_deadline == datetime(2026, 11, 30, 15, 0), "stored as UTC"
    assert event.deadline_set_by == admin.id
    post = join_post(group)
    assert "Регистрация открыта до 30.11 в 18:00" in post.text
    assert has_join_button(post)
    assert_no_errors(world)


async def test_date_alone_means_end_of_day(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 30.11")
    assert "30.11 в 23:59" in join_post(group).text


async def test_only_admins_set_deadlines(world, office, frozen):
    group, admin, people = await season_with(world, office)
    out = await people["Алиса"].send(group, "/deadline 30.11")
    assert "Только администратор" in out.texts[-1]
    assert (await db.events())[-1].join_deadline is None


async def test_bad_input_changes_nothing(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 30.11 18:00")
    for raw in ("/deadline вчера", "/deadline 21.11", "/deadline 31.02"):
        out = await admin.send(group, raw)
        assert out.texts[-1].startswith("❌")
    assert (await db.events())[-1].join_deadline == datetime(2026, 11, 30, 15, 0)


async def test_deadline_without_arguments_shows_it(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    out = await admin.send(group, "/deadline")
    assert "Дедлайна нет" in out.texts[-1] and "/deadline 30.11" in out.texts[-1]
    await admin.send(group, "/deadline 30.11 18:00")
    out = await admin.send(group, "/deadline")
    assert "30.11 в 18:00" in out.texts[-1]


async def test_deadline_off(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 30.11 18:00")
    out = await admin.send(group, "/deadline off")
    assert any("убран" in text for text in out.texts)
    assert (await db.events())[-1].join_deadline is None
    assert "Регистрация открыта до" not in join_post(group).text


async def test_deadline_is_a_group_command(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    out = await admin.dm("/deadline 30.11")
    assert "только в группе" in out.texts[-1]


# --- after it passes -------------------------------------------------------------------


async def test_newcomers_are_turned_away_after_the_deadline(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)  # 15:00 Moscow

    late = world.user("Late")
    group.add(late)
    await late.dm("/start")  # has opened the bot before
    out = await late.send(group, "/join")
    assert "закрыта" in late.last_dm.text and "22.11 в 15:00" in late.last_dm.text
    assert not any(m.chat_id == group.id for m in out.sent), "the refusal goes to DM, not the group"

    # the join link (kept from before) refuses too
    event = (await db.events())[-1]
    await late.dm(f"/start join_{event.id}")
    assert "закрыта" in late.last_dm.text
    await late.dm("Опоздун")  # no registration step is pending
    assert await db.participants_named("Опоздун") == []
    assert_no_errors(world)


async def test_refusal_in_group_when_dm_is_impossible(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=4)
    stranger = world.user("Stranger")  # never opened the bot
    group.add(stranger)
    out = await stranger.send(group, "/join")
    reply = out.sent_to(group.id)[-1]
    assert "закрыта" in reply.text
    assert reply.buttons == [], "no join link once registration is over"


async def test_people_midway_may_finish(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    halfway = world.user("Gleb")
    group.add(halfway)
    await halfway.tap_join(group)
    await halfway.dm("Глеб")
    frozen.advance(hours=5)
    await halfway.dm("носки и чай")
    assert "ты в деле" in halfway.last_dm.text
    assert await db.participants_named("Глеб")


async def test_registered_people_still_see_their_entry(world, office, frozen):
    group, admin, people = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(days=1)
    alice = people["Алиса"]
    await alice.send(group, "/join")
    assert "Ты уже участвуешь" in alice.last_dm.text


async def test_passing_deadline_closes_the_post_and_tells_the_admin(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.dm("/start")
    await admin.send(group, "/deadline 22.11 15:00")
    halfway = world.user("Gleb")
    group.add(halfway)
    await halfway.tap_join(group)

    assert await deadlines.handle_due(world.harness.app.bot) == 0, "not yet"
    frozen.advance(hours=3)
    assert await deadlines.handle_due(world.harness.app.bot) == 1

    post = join_post_or_last(group)
    assert "регистрация закрыта" in post.text
    assert not has_join_button(post)
    assert "Алиса" in post.text, "the list stays"
    notice = admin.last_dm.text
    assert "Регистрация в Office закрыта" in notice and "Участников: 3" in notice
    assert "Gleb" in notice and "/kickitoff" in notice

    dms_before, feed_before = len(admin.inbox), len(group.feed)
    assert await deadlines.handle_due(world.harness.app.bot) == 0, "handled once"
    assert len(admin.inbox) == dms_before
    assert len(group.feed) == feed_before, "the group heard nothing: the admin was DMed"
    assert_no_errors(world)


async def test_admin_without_dm_is_told_in_the_group(world, office, frozen):
    group, admin, _ = await season_with(world, office)  # the admin never opened the bot
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)
    await deadlines.handle_due(world.harness.app.bot)
    last = group.feed[-1].text
    assert "Регистрация закрыта, участников: 3" in last and "/kickitoff" in last


async def test_two_checks_at_once_handle_it_once(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.dm("/start")
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)
    bot = world.harness.app.bot
    results = await asyncio.gather(deadlines.handle_due(bot), deadlines.handle_due(bot))
    assert sorted(results) == [0, 1]
    assert sum("закрыта" in m.text for m in admin.inbox) == 1


async def test_deadline_enforced_even_if_the_check_never_ran(world, office, frozen):
    """The bot may be down when the deadline passes: joining checks the time itself."""
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)
    late = world.user("Late")
    group.add(late)
    await late.dm("/start")
    await late.send(group, "/join")
    assert "закрыта" in late.last_dm.text


async def test_extending_reopens_joining(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)
    await deadlines.handle_due(world.harness.app.bot)
    assert not has_join_button(join_post_or_last(group))

    await admin.send(group, "/deadline 25.11 20:00")
    post = join_post(group)
    assert "25.11 в 20:00" in post.text and has_join_button(post)
    late = world.user("Late")
    group.add(late)
    await register(late, group, "Даша", "пазлы")
    assert await db.participants_named("Даша")

    frozen.advance(days=4)
    assert await deadlines.handle_due(world.harness.app.bot) == 1, "the new deadline is handled afresh"


async def test_removing_a_passed_deadline_reopens_joining(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)
    await deadlines.handle_due(world.harness.app.bot)
    await admin.send(group, "/deadline off")
    assert has_join_button(join_post(group))


async def test_draw_prompt_mentions_an_open_deadline(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 30.11 18:00")
    await admin.send(group, "/kickitoff")
    assert "Регистрация открыта до 30.11 в 18:00" in group.feed[-1].text


async def test_after_the_draw_the_deadline_closes_late_joining_quietly(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    await kick_off(admin, group)
    dms_before = len(admin.inbox)
    frozen.advance(hours=3)
    assert await deadlines.handle_due(world.harness.app.bot) == 1
    assert len(admin.inbox) == dms_before, "nothing to tell the admin after the draw"
    assert not has_join_button(join_post_or_last(group))

    late = world.user("Late")
    group.add(late)
    await late.dm("/start")
    await late.send(group, "/join")
    assert "закрыта" in late.last_dm.text
    assert len(await db.assignments()) == 3


async def test_new_season_starts_without_deadline(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    frozen.advance(hours=3)
    await admin.send(group, "/newseason")
    await admin.click(group.feed[-1], "Да")
    assert (await db.events())[-1].join_deadline is None
    assert has_join_button(join_post(group))


async def test_closed_season_is_not_handled(world, office, frozen):
    group, admin, _ = await season_with(world, office)
    await admin.send(group, "/deadline 22.11 15:00")
    await admin.send(group, "/newseason")
    await admin.click(group.feed[-1], "Да")
    frozen.advance(hours=3)
    assert await deadlines.handle_due(world.harness.app.bot) == 0


async def test_check_loop_survives_errors(monkeypatch):
    calls = []

    async def flaky(bot):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database hiccup")
        return 0

    monkeypatch.setattr(deadlines, "handle_due", flaky)
    task = asyncio.create_task(deadlines.run_checks(object(), 0.01))
    while len(calls) < 3:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 3


def join_post_or_last(group):
    """The join post, also once it lost its button (closed)."""
    posts = [m for m in group.feed if "Участвуют" in m.text or "Участвовали" in m.text]
    return posts[-1]
