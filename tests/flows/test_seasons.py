"""Seasons, returning players, deep-link joining, rule carry-over, live wishlist."""

from tests.harness import db
from tests.harness.fake_bot_api import BOT_USERNAME
from tests.harness.scenario import assert_no_errors, assignment_of, kick_off, register, select_group


async def open_new_season(admin, group):
    await admin.send(group, "/newseason")
    confirm = group.feed[-1]
    await admin.click(confirm, "Да")
    return confirm


async def seeded(world, office, names=("Алиса", "Борис", "Вера")):
    group, admin = office
    await admin.send(group, "/start")
    people = {}
    for i, name in enumerate(names):
        actor = world.user(f"U{i}", username=f"user{i}")
        group.add(actor)
        await register(actor, group, name, f"вишлист {name}")
        people[name] = actor
    return group, admin, people


async def test_deep_link_continues_registration_for_user_who_never_opened_dm(world, office):
    group, admin = office
    await admin.send(group, "/start")
    alice = world.user("Alice")
    group.add(alice)

    out = await alice.send(group, "/join")
    reply = out.sent_to(group.id)[-1]
    (button_text, _), = reply.buttons
    url = reply.reply_markup["inline_keyboard"][0][0]["url"]
    assert url.startswith(f"https://t.me/{BOT_USERNAME}?start=join_")

    payload = url.split("start=", 1)[1]
    await alice.dm(f"/start {payload}")
    assert "имя" in alice.last_dm.text
    await alice.dm("Алиса")
    await alice.dm("книги")
    assert "ты в деле" in alice.last_dm.text
    assert world.harness.errors == []
    assert [c.error for c in world.api.calls if not c.ok] == ["Forbidden: bot can't initiate conversation with a user"]


async def test_forged_deep_link_to_another_event_is_harmless(world, office):
    group, admin = office
    await admin.send(group, "/start")
    alice = world.user("Alice")
    out = await alice.dm("/start join_999999")
    assert "нет активного сезона" in out.texts[-1]


async def test_new_season_requires_admin_and_confirmation(world, office):
    group, admin, people = await seeded(world, office)
    out = await people["Алиса"].send(group, "/newseason")
    assert "Только администратор" in out.texts[-1]

    await admin.send(group, "/newseason")
    confirm = group.feed[-1]
    await people["Алиса"].click(confirm, "Да")  # a non-admin presses the admin's button
    assert len(await db.events()) == 1
    await admin.click(confirm, "Да")
    assert "Новый сезон" in confirm.text
    assert [e.status for e in await db.events()] == ["closed", "open"]


async def test_returning_player_reuses_name_and_wishlist_in_two_taps(world, office):
    group, admin, people = await seeded(world, office)
    await kick_off(admin, group)
    await open_new_season(admin, group)

    alice = people["Алиса"]
    await alice.send(group, "/join")
    await alice.click(alice.last_dm, "🔁")
    assert "вишлист Алиса" in alice.last_dm.text, "last year's wishlist is shown"
    await alice.click(alice.last_dm, "Как в прошлый раз")
    assert "ты в деле" in alice.last_dm.text
    current = (await db.events())[-1]
    mine = [p for p in await db.participants_named("Алиса") if p.event_id == current.id]
    assert len(mine) == 1 and mine[0].wishlist == "вишлист Алиса"
    assert_no_errors(world)


async def test_reuse_button_from_an_old_prompt_is_stale(world, office):
    group, admin, people = await seeded(world, office)
    await open_new_season(admin, group)
    alice = people["Алиса"]
    await alice.send(group, "/join")
    prompt = alice.last_dm
    await alice.dm("Алиса Новая")
    await alice.click(prompt, "🔁")  # flow already moved on
    assert "вишлист" in alice.last_dm.text and "ты в деле" not in alice.last_dm.text


async def test_rules_carry_over_between_seasons(world, office):
    group, admin, people = await seeded(world, office, ("Алиса", "Борис", "Вера", "Глеб"))
    await select_group(admin, group)
    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Алиса")
    await admin.click(admin.last_dm, "Борис")
    await open_new_season(admin, group)

    await admin.dm("/listrules")
    assert "не участвует" in admin.last_dm.text

    for name in ("Алиса", "Борис", "Вера", "Глеб"):
        await register(people[name], group, name, f"вишлист {name}")
    for _ in range(4):
        await select_group(admin, group)
        await admin.dm("/dryrunassignments")
        assert "возможно" in admin.last_dm.text
    await admin.dm("/listrules")
    assert "Алиса ↔ Борис" in admin.last_dm.text and "не участвует" not in admin.last_dm.text


async def test_santa_is_told_when_their_receiver_changes_wishlist(world, office):
    group, admin, people = await seeded(world, office)
    await kick_off(admin, group)
    alice = people["Алиса"]
    santa = next(actor for actor in people.values() if assignment_of(actor) == "Алиса")

    await alice.dm("/wishlist")
    await alice.dm("теперь хочу варежки")
    assert "обновлён" in alice.last_dm.text
    assert "теперь хочу варежки" in santa.last_dm.text
    others = [a for a in people.values() if a not in (alice, santa)]
    assert all("варежки" not in m.text for a in others for m in a.inbox)
    assert_no_errors(world)


async def test_kickoff_twice_explains_instead_of_reshuffling(world, office):
    group, admin, _ = await seeded(world, office)
    await kick_off(admin, group)
    out = await kick_off(admin, group)
    assert "уже сделано" in out.texts[-1]


async def test_redeploy_mid_registration_resumes_on_start(world, office):
    group, admin = office
    await admin.send(group, "/start")
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    await alice.dm("Алиса")
    await world.harness.restart()

    out = await alice.dm("/start")
    assert any("Продолжим" in t for t in out.texts)
    assert "вишлист" in alice.last_dm.text
    await alice.dm("книги")
    assert "ты в деле" in alice.last_dm.text


async def test_malformed_callback_is_answered_and_ignored(world, office):
    group, admin, _ = await seeded(world, office)
    await admin.dm("/start")
    for data in ["rs:1:2", "cf:9:1", "rr:abc", "select_group_1", "x" * 64]:
        out = await admin.click_data(admin.last_dm, data)
        assert out.errors == []
        assert [c.method for c in out.calls] == ["answerCallbackQuery"]
