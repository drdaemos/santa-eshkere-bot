"""A supergroup where the bot is not an admin and members are hidden: Telegram
refuses getChatMember for other people. Admins must still be recognised
(through the admin list), and members must still be able to join."""

import logging

from tests.harness import db
from tests.harness.fake_bot_api import BOT_ID
from tests.harness.scenario import kick_off, register


async def hidden_group(world, office):
    group, owner = office
    await owner.send(group, "/start")
    group.chat.hidden_members = True
    return group, owner


async def test_admin_promoted_after_start_sees_the_group(world, office, caplog):
    group, owner = await hidden_group(world, office)
    helper = world.user("Helper")
    group.add(helper)
    group.promote(helper)  # became an admin after /start
    await helper.dm("/start")
    caplog.set_level(logging.WARNING)
    await helper.dm("/listgroups")
    assert "Office" in helper.last_dm.text
    assert any(group.chat.title in t for t, _ in helper.last_dm.buttons)
    assert "Admin check in chat_id" in caplog.text, "the failed lookup is logged"
    assert world.harness.errors == [], "Telegram refused the lookup (expected); the bot didn't crash"


async def test_admin_commands_work_in_a_hidden_supergroup(world, office):
    group, owner = await hidden_group(world, office)
    people = []
    for i, name in enumerate(("Алиса", "Борис", "Вера")):
        actor = world.user(f"U{i}")
        group.add(actor)
        await register(actor, group, name, "книги")
        people.append(actor)
    assert len(await db.participants_named("Алиса")) == 1, "members can join although lookups fail"

    await owner.dm("/listjoined")
    assert "(3)" in owner.last_dm.text
    await kick_off(owner, group)
    assert len(await db.assignments()) == 3


async def test_non_admins_are_still_refused(world, office):
    group, owner = await hidden_group(world, office)
    member = world.user("Member")
    group.add(member)
    await member.dm("/start")
    out = await member.send(group, "/kickitoff")
    assert "Только администратор" in out.texts[-1]
    await member.dm("/listgroups")
    assert "Office" not in member.last_dm.text


async def test_demoted_admin_loses_access(world, office):
    group, owner = await hidden_group(world, office)
    helper = world.user("Helper")
    group.add(helper)
    group.promote(helper)
    await helper.dm("/listgroups")
    assert "Office" in helper.last_dm.text
    group.demote(helper)
    await helper.dm("/listgroups")
    assert "Office" not in helper.last_dm.text


async def test_when_telegram_answers_neither_way_nobody_is_admin(world, office):
    group, owner = await hidden_group(world, office)
    group.chat.admin_list_fails = True
    out = await owner.send(group, "/kickitoff")
    assert "Только администратор" in out.texts[-1], "safe default: no admin rights without an answer"


async def test_bot_as_admin_needs_no_fallback(world, office):
    group, owner = await hidden_group(world, office)
    group.chat.members[BOT_ID] = "administrator"
    helper = world.user("Helper")
    group.add(helper)
    group.promote(helper)
    await helper.dm("/listgroups")
    assert "Office" in helper.last_dm.text
    assert not any(c.method == "getChatAdministrators" for c in world.api.calls)


async def test_a_no_is_logged_with_what_telegram_said(world, office, caplog):
    group, owner = office
    await owner.send(group, "/start")
    member = world.user("Member")
    group.add(member)
    caplog.set_level(logging.INFO)
    await member.dm("/listgroups")
    assert f"Not an admin: user_id={member.id} in chat_id={group.id} (status member, 1 admins listed)" in caplog.text
