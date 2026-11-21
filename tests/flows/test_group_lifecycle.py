"""Activating the bot in a group, disbanding, reactivating, chat migration."""

import time

from tests.harness.scenario import assert_no_errors, join_post, join_url, listed, register, select_group


async def test_admin_activates_bot_in_group(world, office):
    group, admin = office
    out = await admin.send(group, "/start")
    [post] = out.sent_to(group.id)
    assert post is join_post(group)
    assert join_url(post).startswith("https://t.me/santa_eshkere_bot?start=join_")
    assert listed(post) == []
    assert_no_errors(world)


async def test_non_admin_cannot_activate(world, office):
    group, _ = office
    bob = world.user("Bob")
    group.add(bob)
    out = await bob.send(group, "/start")
    assert "Только администратор" in out.texts[-1]


async def test_dm_start_points_user_to_group(world):
    alice = world.user("Alice")
    out = await alice.dm("/start")
    assert "/join" in out.texts[-1]


async def test_join_before_activation_is_refused(world, office):
    group, _ = office
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    out = await alice.send(group, "/join")
    assert "Группа не найдена" in out.texts[-1]


async def test_join_in_dm_is_refused(world):
    alice = world.user("Alice")
    out = await alice.dm("/join")
    assert "только в группе" in out.texts[-1]


async def test_disband_blocks_joining_and_start_reactivates(world, office):
    group, admin = office
    await admin.send(group, "/start")
    await select_group(admin, group)

    await admin.dm("/disband")
    assert "Продолжить?" in admin.last_dm.text
    await admin.click(admin.last_dm, "Да")
    assert "расформирована" in admin.last_dm.text

    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    out = await alice.send(group, "/join")
    assert "выключен" in out.texts[-1]

    await admin.send(group, "/start")
    out = await alice.send(group, "/join")
    assert "имя" in alice.last_dm.text
    assert_no_errors(world)


async def test_disband_answer_other_than_yes_cancels(world, office):
    group, admin = office
    await admin.send(group, "/start")
    await select_group(admin, group)
    await admin.dm("/disband")
    confirm = admin.last_dm
    await admin.click(confirm, "Нет")
    assert "Отменено" in confirm.text
    await admin.dm("/listgroups")
    assert "Office" in admin.last_dm.text


async def test_group_with_underscore_in_title_is_listed(world):
    admin = world.user("Eugene")
    group = world.group("Santa_2026", owner=admin)
    await admin.send(group, "/start")
    await admin.dm("/listgroups")
    assert "Santa_2026" in admin.last_dm.text


async def test_join_works_in_group_with_underscore_in_title(world):
    admin = world.user("Eugene")
    group = world.group("Santa_2026", owner=admin)
    await admin.send(group, "/start")
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    assert "имя" in alice.last_dm.text


async def test_group_survives_supergroup_migration(world, office):
    group, admin = office
    group.chat.type = "group"
    await admin.send(group, "/start")
    alice = world.user("Alice", username="alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")

    old_id, new_id = group.chat.id, group.chat.id - 500
    old_chat = group.chat.to_dict()
    await world.harness.feed(
        {"message": {"message_id": 1, "date": int(time.time()), "chat": old_chat, "from": admin.user.to_dict(), "migrate_to_chat_id": new_id}}
    )
    world.api.groups.pop(old_id)
    group.chat.id, group.chat.type = new_id, "supergroup"
    world.api.groups[new_id] = group.chat
    await world.harness.feed(
        {"message": {"message_id": 2, "date": int(time.time()), "chat": group.chat.to_dict(), "from": admin.user.to_dict(), "migrate_from_chat_id": old_id}}
    )

    bob = world.user("Bob")
    group.add(bob)
    await bob.dm("/start")
    await bob.send(group, "/join")
    assert "имя" in bob.last_dm.text
