"""Admin DM flows: /listgroups, selection, participants, exclusion rules, reset."""

import pytest

from tests.harness import db
from tests.harness.scenario import assert_no_errors, register, select_group
from tests.known_bugs import known_bug


@pytest.fixture
async def office_with_people(world, office):
    """Activated group with Алиса, Борис, Вера registered; admin not a participant."""
    group, admin = office
    await admin.send(group, "/start")
    people = {}
    for first, name, username in [("Alice", "Алиса", "alice"), ("Boris", "Борис", "boris"), ("Vera", "Вера", None)]:
        actor = world.user(first, username=username)
        group.add(actor)
        await register(actor, group, name, f"вишлист {name}")
        people[name] = actor
    return group, admin, people


async def test_listgroups_shows_only_groups_where_user_is_admin(world, office):
    group, admin = office
    other_admin = world.user("Other")
    other = world.group("Other group", owner=other_admin)
    await admin.send(group, "/start")
    await other_admin.send(other, "/start")

    await admin.dm("/listgroups")
    assert "Office" in admin.last_dm.text
    assert "Other group" not in admin.last_dm.text

    stranger = world.user("Stranger")
    out = await stranger.dm("/listgroups")
    assert "Нет активных групп" in out.texts[-1]


async def test_select_group_by_button(world, office_with_people):
    group, admin, _ = office_with_people
    await admin.dm("/listgroups")
    assert "Участников: 3" in admin.last_dm.text
    await admin.click(admin.last_dm, "Office")
    assert "Выбрана группа" in admin.last_dm.text
    assert_no_errors(world)


async def test_select_group_by_number(world, office_with_people):
    group, admin, _ = office_with_people
    await admin.dm("/listgroups")
    out = await admin.dm("/selectgroup 1")
    assert "Выбрана группа" in out.texts[-1]
    out = await admin.dm("/selectgroup 7")
    assert "Неправильный формат" in out.texts[-1]


async def test_non_admin_cannot_select_group_with_crafted_button(world, office_with_people):
    group, admin, people = office_with_people
    await admin.dm("/listgroups")
    data = admin.last_dm.buttons[0][1]
    mallory = people["Борис"]
    await mallory.dm("/start")
    await mallory.click_data(mallory.last_dm, data)
    assert "Только администратор" in mallory.last_dm.text
    out = await mallory.dm("/listjoined")
    assert "выберите группу" in out.texts[-1]


async def test_group_commands_require_selection(world):
    admin = world.user("Eugene")
    for command in ["/addrule", "/listrules", "/removerule", "/listjoined", "/reset", "/disband", "/dryrunassignments"]:
        out = await admin.dm(command)
        assert "выберите группу" in out.texts[-1], command


async def test_admin_commands_are_dm_only(world, office):
    group, admin = office
    await admin.send(group, "/start")
    out = await admin.send(group, "/listjoined")
    assert "только в личных" in out.texts[-1]


async def test_listjoined(world, office_with_people):
    group, admin, _ = office_with_people
    await select_group(admin, group)
    await admin.dm("/listjoined")
    text = admin.last_dm.text
    assert "(3)" in text
    assert "Алиса (@alice)" in text and "Вера" in text
    assert_no_errors(world)


@known_bug("escape_markdown escapes for MarkdownV2 but messages are sent as legacy Markdown -> literal backslashes")
async def test_listjoined_shows_names_verbatim(world, office):
    group, admin = office
    await admin.send(group, "/start")
    anna = world.user("Anna")
    group.add(anna)
    await register(anna, group, "Анна-Мария С.", "книги")
    await select_group(admin, group)
    await admin.dm("/listjoined")
    assert "Анна-Мария С." in admin.last_dm.text


async def test_add_list_and_remove_rule(world, office_with_people):
    group, admin, _ = office_with_people
    await select_group(admin, group)

    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Алиса")
    assert "Алиса" in admin.last_dm.text and "второго" in admin.last_dm.text
    assert all("Алиса" not in text for text, _ in admin.last_dm.buttons), "can't pick the same person twice"
    await admin.click(admin.last_dm, "Борис")
    assert "Алиса ↔ Борис" in admin.last_dm.text

    await admin.dm("/listrules")
    assert "Алиса ↔ Борис" in admin.last_dm.text

    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Борис")
    await admin.click(admin.last_dm, "Алиса")
    assert "уже существует" in admin.last_dm.text

    await admin.dm("/removerule")
    await admin.click(admin.last_dm, "Алиса ↔ Борис")
    assert "удалено" in admin.last_dm.text
    out = await admin.dm("/listrules")
    assert "Нет правил" in out.texts[-1]
    assert_no_errors(world)


async def test_addrule_paginates_large_groups(world, office):
    group, admin = office
    await admin.send(group, "/start")
    for i in range(11):
        actor = world.user(f"P{i}")
        group.add(actor)
        await register(actor, group, f"Участник {i:02d}", "что угодно")
    await select_group(admin, group)

    await admin.dm("/addrule")
    first_page = [t for t, _ in admin.last_dm.buttons]
    assert "Участник 10" not in " ".join(first_page)
    await admin.click(admin.last_dm, "Вперёд")
    assert any("Участник 10" in t for t, _ in admin.last_dm.buttons)
    await admin.click(admin.last_dm, "Участник 10")
    await admin.click(admin.last_dm, "Участник 00")
    assert "Участник 10 ↔ Участник 00" in admin.last_dm.text or "Участник 00 ↔ Участник 10" in admin.last_dm.text
    assert_no_errors(world)


async def test_addrule_needs_two_participants(world, office):
    group, admin = office
    await admin.send(group, "/start")
    await select_group(admin, group)
    out = await admin.dm("/addrule")
    assert "недостаточно участников" in out.texts[-1]


async def test_dry_run_shows_pairs_without_saving(world, office_with_people):
    group, admin, _ = office_with_people
    await select_group(admin, group)
    await admin.dm("/dryrunassignments")
    assert "Симуляция" in admin.last_dm.text
    assert admin.last_dm.text.count("→") >= 3
    assert await db.assignments() == []
    assert_no_errors(world)


@known_bug("Stale /addrule keyboard after switching groups creates a rule between people from different groups")
async def test_stale_addrule_keyboard_cannot_mix_groups(world):
    admin = world.user("Eugene")
    work, friends = world.group("Work", owner=admin), world.group("Friends", owner=admin)
    for g in (work, friends):
        await admin.send(g, "/start")
    for g, names in ((work, ["Алиса", "Борис", "Вера"]), (friends, ["Дима", "Ева", "Фёдор"])):
        for name in names:
            actor = world.user(name)
            g.add(actor)
            await register(actor, g, name, "книги")

    await select_group(admin, work)
    await admin.dm("/addrule")
    stale = admin.last_dm
    await select_group(admin, friends)

    await admin.click(stale, "Алиса")  # the old keyboard is edited in place
    if any("Дима" in t for t, _ in stale.buttons):
        await admin.click(stale, "Дима")
    await admin.dm("/listrules")
    assert "Алиса" not in admin.last_dm.text


@known_bug("remove_rule_<id> callback has no ownership/admin check: anyone can delete any group's rules")
async def test_rule_cannot_be_removed_by_outsider(world, office_with_people):
    group, admin, people = office_with_people
    await select_group(admin, group)
    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Алиса")
    await admin.click(admin.last_dm, "Борис")
    rule = (await db.exclusions())[0]

    outsider = world.user("Mallory")
    await outsider.dm("/start")
    await outsider.click_data(outsider.last_dm, f"remove_rule_{rule.id}")
    assert len(await db.exclusions()) == 1


@known_bug("Pending /reset confirmation does not re-check admin rights")
async def test_demoted_admin_cannot_confirm_reset(world, office_with_people):
    group, admin, _ = office_with_people
    await admin.send(group, "/kickitoff")
    await select_group(admin, group)
    await admin.dm("/reset")
    group.demote(admin)
    await admin.dm("да")
    assert len(await db.assignments()) == 3


async def test_reset_clears_assignments(world, office_with_people):
    group, admin, people = office_with_people
    await admin.send(group, "/kickitoff")
    assert len(await db.assignments()) == 3
    await select_group(admin, group)
    await admin.dm("/reset")
    await admin.dm("да")
    assert "сброшены" in admin.last_dm.text
    assert await db.assignments() == []
    await people["Алиса"].dm("/status")
    assert "Ожидаем распределения" in people["Алиса"].last_dm.text
