"""The participant experience: joining in a tap or two, buttons instead of
commands, forgiving free text, and a group chat that stays quiet.
"""

from src.main import COMMAND_MENUS, set_command_menus
from src.services.join_post import refresh_join_message
from tests.harness import db
from tests.harness.scenario import assert_no_errors, assignment_of, join_post, kick_off, listed, register, select_group


async def started(office):
    group, admin = office
    await admin.send(group, "/start")
    return group, admin


async def test_join_post_tap_is_the_whole_onboarding(world, office):
    group, admin = await started(office)
    alice = world.user("Alice", username="alice")
    alice.user.last_name = "Smith"
    group.add(alice)
    group_messages = len(group.feed)

    # never talked to the bot before: one tap on the post opens the DM
    await alice.tap_join(group)
    prompt = alice.last_dm
    assert "имя" in prompt.text
    await alice.click(prompt, "👤 Alice Smith")
    assert prompt.buttons == [], "answered prompts lose their buttons, so they can't be tapped twice"
    await alice.dm("книги и настолки")

    done = alice.last_dm
    assert "ты в деле" in done.text and "Alice Smith" in done.text
    assert [t for t, _ in done.buttons] == ["✏️ Вишлист", "🚪 Выйти"]
    assert listed(join_post(group)) == ["Alice Smith"]
    assert len(group.feed) == group_messages, "joining posts nothing new in the group"
    assert_no_errors(world)


async def test_outsider_with_a_forwarded_link_cannot_join(world, office):
    group, admin = await started(office)
    stranger = world.user("Stranger")  # not in the group
    await stranger.tap_join(group)
    assert "для участников группы" in stranger.last_dm.text
    await stranger.dm("Чужой")
    assert await db.participants_named("Чужой") == [], "no registration was started"

    group.add(stranger)  # after being added, the same tap works
    await stranger.tap_join(group)
    assert "имя" in stranger.last_dm.text


async def test_tapping_join_again_shows_your_entry_with_buttons(world, office):
    group, admin = await started(office)
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    await alice.tap_join(group)
    assert "Ты уже участвуешь" in alice.last_dm.text and "книги" in alice.last_dm.text

    await alice.click(alice.last_dm, "✏️ Вишлист")
    await alice.dm("и пазлы")
    assert "обновлён" in alice.last_dm.text
    assert [p.wishlist for p in await db.participants_named("Алиса")] == ["книги\nи пазлы"], "added, not replaced"
    assert_no_errors(world)


async def test_free_text_after_registration_is_offered_as_wishlist(world, office):
    group, admin = await started(office)
    people = {}
    for name in ("Алиса", "Борис", "Вера"):
        actor = world.user(name)
        group.add(actor)
        await register(actor, group, name, f"вишлист {name}")
        people[name] = actor
    await kick_off(admin, group)
    alice = people["Алиса"]
    santa = next(a for a in people.values() if assignment_of(a) == "Алиса")

    await alice.dm("лучше подарите тёплые носки")
    offer = alice.last_dm
    assert "Что сделать с этим текстом?" in offer.text and "тёплые носки" in offer.text
    await alice.click(offer, "🔁 Заменить")
    assert "обновлён" in offer.text
    assert "тёплые носки" in santa.last_dm.text, "the Santa hears about it"

    await alice.dm("а может и не носки")
    await alice.click(alice.last_dm, "Отмена")
    assert [p.wishlist for p in await db.participants_named("Алиса")] == ["лучше подарите тёплые носки"]
    assert_no_errors(world)


async def test_small_talk_gets_a_short_answer_not_a_wishlist_offer(world, office):
    group, admin = await started(office)
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    await alice.dm("Спасибо!")
    assert "Что сделать с этим текстом" not in alice.last_dm.text
    assert "/status" in alice.last_dm.text


async def test_free_text_from_a_stranger_explains_how_to_join(world, office):
    await started(office)
    bob = world.user("Bob")
    await bob.dm("привет, что это?")
    assert "Участвовать" in bob.last_dm.text


async def test_leave_button_under_registration_message(world, office):
    group, admin = await started(office)
    people = []
    for name in ("Алиса", "Борис"):
        actor = world.user(name)
        group.add(actor)
        await register(actor, group, name, "книги")
        people.append(actor)
    alice = people[0]
    registration_done = next(m for m in alice.inbox if "ты в деле" in m.text)
    await alice.click(registration_done, "Выйти")
    await alice.click(alice.last_dm, "Да")
    assert listed(join_post(group)) == ["Борис"]
    assert_no_errors(world)


async def test_double_tap_on_name_button_is_harmless(world, office):
    group, admin = await started(office)
    alice = world.user("Alice")
    group.add(alice)
    await alice.tap_join(group)
    prompt = alice.last_dm
    data = next(d for t, d in prompt.buttons if "👤" in t)
    await alice.click_data(prompt, data)
    out = await alice.click_data(prompt, data)
    assert [c.method for c in out.calls] == ["answerCallbackQuery"]
    assert "вишлист" in alice.last_dm.text.lower()


async def test_join_post_follows_the_season(world, office):
    group, admin = await started(office)
    names = ("Алиса", "Борис", "Вера")
    for name in names:
        actor = world.user(name)
        group.add(actor)
        await register(actor, group, name, "книги")
    first_post = join_post(group)

    await kick_off(admin, group)
    assert "распределение уже прошло" in first_post.text and listed(first_post) == list(names)
    assert join_post(group) is first_post, "still joinable, same post"

    await admin.send(group, "/newseason")
    await admin.click(group.feed[-1], "Да")
    assert "закрыт" in first_post.text and first_post.reply_markup is None
    new_post = join_post(group)
    assert new_post is not first_post and listed(new_post) == []
    assert_no_errors(world)


async def test_start_again_reposts_the_join_post_at_the_bottom(world, office):
    group, admin = await started(office)
    old = join_post(group)
    await admin.send(group, "/start")
    new = join_post(group)
    assert new is not old
    assert "в сообщении ниже" in old.text and old.reply_markup is None
    assert_no_errors(world)


async def test_unchanged_join_post_is_not_re_sent(world, office):
    group, admin = await started(office)
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    event_id = (await db.events())[-1].id
    calls = len(world.api.calls)
    await refresh_join_message(world.harness.app.bot, event_id)
    assert [c.method for c in world.api.calls[calls:]] == [], "nothing changed, nothing sent"
    assert_no_errors(world)


async def test_deleted_join_post_does_not_break_joining(world, office):
    group, admin = await started(office)
    post = join_post(group)
    world.api.messages.pop((group.id, post.message_id))  # an admin deleted it
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    assert "ты в деле" in alice.last_dm.text
    assert world.harness.errors == []
    fresh = join_post(group)
    assert fresh.message_id != post.message_id, "a new post went up by itself"
    assert listed(fresh) == ["Алиса"]
    bob = world.user("Bob")
    group.add(bob)
    await register(bob, group, "Борис", "чай")
    assert sorted(listed(join_post(group))) == ["Алиса", "Борис"]
    assert join_post(group).message_id == fresh.message_id, "and it is edited from then on, not re-posted"


async def test_big_group_join_post_stays_short(world, office):
    group, admin = await started(office)
    for i in range(65):
        actor = world.user(f"P{i}")
        group.add(actor)
        await register(actor, group, f"Гость{i:02d}", "книги")
    post = join_post(group)
    assert "Участвуют (65)" in post.text and "и ещё 5" in post.text
    assert_no_errors(world)


async def test_admin_sees_join_post_update_after_removal(world, office):
    group, admin = await started(office)
    for name in ("Алиса", "Борис"):
        actor = world.user(name)
        group.add(actor)
        await register(actor, group, name, "книги")
    await select_group(admin, group)
    await admin.dm("/removeparticipant")
    await admin.click(admin.last_dm, "Алиса")
    await admin.click(admin.last_dm, "Да")
    assert listed(join_post(group)) == ["Борис"]


async def test_command_menus_are_valid_for_telegram(world):
    await set_command_menus(world.harness.app.bot)
    assert world.api.command_menus == {
        "all_private_chats": [c for c, _ in COMMAND_MENUS["private"]],
        "all_group_chats": [c for c, _ in COMMAND_MENUS["groups"]],
        "all_chat_administrators": [c for c, _ in COMMAND_MENUS["group_admins"]],
    }
    assert_no_errors(world)
