"""The organizer's side: hard to start the draw by accident, a season that
starts by adding the bot, and seeing who is stuck."""

from tests.harness import db
from tests.harness.scenario import DRAW_START_BUTTON, assert_no_errors, assignment_dms, join_post, kick_off, register


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


# --- the draw asks first ------------------------------------------------------------


async def test_kickitoff_asks_before_drawing(world, office):
    group, admin, people = await season_with(world, office)
    await admin.send(group, "/kickitoff")
    prompt = group.feed[-1]
    assert "3" in prompt.text and "Запустить" in prompt.text
    assert await db.assignments() == [], "nothing is drawn before the confirmation"
    assert not any(assignment_dms(a) for a in people.values())

    await admin.click(prompt, DRAW_START_BUTTON)
    assert "Сани поехали" in prompt.text, "the prompt turns into the result: one group message"
    assert prompt.buttons == []
    assert all(len(assignment_dms(a)) == 1 for a in people.values())
    assert_no_errors(world)


async def test_cancelled_draw_changes_nothing(world, office):
    group, admin, people = await season_with(world, office)
    await admin.send(group, "/kickitoff")
    prompt = group.feed[-1]
    await admin.click(prompt, "Отмена")
    assert await db.assignments() == []
    assert "Запустить" not in [text for text, _ in prompt.buttons]


async def test_draw_prompt_names_people_who_have_not_finished(world, office):
    group, admin, _ = await season_with(world, office)
    halfway = world.user("Gleb", username="gleb")
    group.add(halfway)
    await halfway.tap_join(group)  # opened the DM, never typed a name
    named = world.user("Dasha")
    group.add(named)
    await named.tap_join(group)
    await named.dm("Даша")  # gave a name, no wishlist yet

    await admin.send(group, "/kickitoff")
    prompt = group.feed[-1].text
    assert "не закончили" in prompt
    assert "Gleb" in prompt and "Даша" in prompt
    assert "Алиса" not in prompt


async def test_only_admins_can_confirm_the_draw(world, office):
    group, admin, people = await season_with(world, office)
    await admin.send(group, "/kickitoff")
    prompt = group.feed[-1]
    out = await people["Алиса"].click(prompt, DRAW_START_BUTTON)
    assert await db.assignments() == []
    assert any(c.method == "answerCallbackQuery" and "администратор" in str(c.params) for c in out.calls)


async def test_confirming_twice_draws_once(world, office):
    group, admin, people = await season_with(world, office)
    await admin.send(group, "/kickitoff")
    prompt = group.feed[-1]
    data = next(d for text, d in prompt.buttons if DRAW_START_BUTTON in text)
    await admin.click_data(prompt, data)
    await admin.click_data(prompt, data)
    assert all(len(assignment_dms(a)) == 1 for a in people.values())
    assert len(await db.assignments()) == 3


async def test_impossible_draw_is_refused_before_asking(world, office):
    group, admin, _ = await season_with(world, office, names=("Алиса", "Борис"))
    out = await admin.send(group, "/kickitoff")
    assert "минимум 3" in out.texts[-1]
    assert not any("Запустить" in text for m in group.feed for text, _ in m.buttons)


# --- adding the bot -----------------------------------------------------------------


async def test_admin_adding_the_bot_starts_the_season(world, office):
    group, admin = office
    await group.add_bot(by=admin)
    assert "Тайного Санту" in group.feed[0].text
    post = join_post(group)
    alice = world.user("Alice")
    group.add(alice)
    await alice.tap_join(group)
    assert "имя" in alice.last_dm.text.lower()
    assert post.message_id == join_post(group).message_id
    assert_no_errors(world)


async def test_member_adding_the_bot_gets_a_hint_only(world, office):
    group, admin = office
    member = world.user("Boris")
    group.add(member)
    await group.add_bot(by=member)
    assert len(group.feed) == 1
    assert "/start" in group.feed[0].text
    assert group.feed[0].buttons == []
    assert await db.events() == []


async def test_other_people_joining_the_group_are_ignored(world, office):
    group, admin = office
    newcomer = world.user("Vera")
    group.add(newcomer)
    message = {
        "message_id": world.harness.next_message_id(),
        "date": 0,
        "chat": group.chat.to_dict(),
        "from": newcomer.user.to_dict(),
        "new_chat_members": [newcomer.user.to_dict()],
    }
    await world.harness.feed({"message": message})
    assert group.feed == []


# --- who is stuck ---------------------------------------------------------------------


async def test_listjoined_shows_unfinished_and_undelivered(world, office):
    group, admin, people = await season_with(world, office)
    halfway = world.user("Gleb")
    group.add(halfway)
    await halfway.tap_join(group)
    await admin.dm("/listjoined")
    assert "не закончили: Gleb" in admin.last_dm.text

    people["Вера"].block_bot()
    await kick_off(admin, group)
    await admin.dm("/listjoined")
    text = admin.last_dm.text
    assert "Не получили задание" in text and "Вера" in text.split("Не получили задание", 1)[1]


async def test_finished_registration_is_not_listed_as_unfinished(world, office):
    group, admin, _ = await season_with(world, office)
    await admin.dm("/listjoined")
    assert "не закончили" not in admin.last_dm.text


# --- one group, no selection needed -------------------------------------------------


async def test_single_group_needs_no_selection(world, office):
    group, admin, _ = await season_with(world, office)
    await admin.dm("/listjoined")
    assert "(3)" in admin.last_dm.text


async def test_two_groups_still_ask_which(world, office):
    group, admin, _ = await season_with(world, office)
    other = world.group("Family", owner=admin)
    await admin.send(other, "/start")
    out = await admin.dm("/listjoined")
    assert "выбери группу" in out.texts[-1]
