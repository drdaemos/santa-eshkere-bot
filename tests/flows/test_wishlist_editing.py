"""Changing a wishlist after registration: text adds by default, replacing is
explicit, and the last change can be undone. Nobody should lose what they
typed before."""

from src.database.session import session_scope
from src.services import state
from tests.harness import db
from tests.harness.scenario import assert_no_errors, assignment_of, kick_off, register

ADD = "➕ Добавить"
REPLACE = "🔁 Заменить"
UNDO = "↩️ Вернуть"


async def one_person(world, office, wishlist="книги"):
    group, admin = office
    await admin.send(group, "/start")
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", wishlist)
    return group, admin, alice


async def wishlist_of(name="Алиса") -> list[str]:
    return [p.wishlist for p in await db.participants_named(name)]


async def drawn(world, office):
    group, admin, alice = await one_person(world, office)
    people = {"Алиса": alice}
    for i, name in enumerate(("Борис", "Вера")):
        actor = world.user(f"U{i}")
        group.add(actor)
        await register(actor, group, name, "чай")
        people[name] = actor
    await kick_off(admin, group)
    santa = next(a for a in people.values() if assignment_of(a) == "Алиса")
    return group, admin, alice, santa


# --- sending text: add by default ------------------------------------------------------


async def test_text_is_offered_to_add_first(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("и настолки")
    offer = alice.last_dm
    labels = [text for text, _ in offer.buttons]
    assert ADD in labels[0], "adding is the first, main button"
    assert any(REPLACE in label for label in labels) and "Отмена" in labels

    await alice.click(offer, ADD)
    assert await wishlist_of() == ["книги\nи настолки"]
    assert "книги\nи настолки" in offer.text, "the confirmation shows the whole list"
    assert_no_errors(world)


async def test_adding_twice_keeps_everything(world, office):
    _, _, alice = await one_person(world, office)
    for extra in ("и настолки", "и тёплые носки"):
        await alice.dm(extra)
        await alice.click(alice.last_dm, ADD)
    assert await wishlist_of() == ["книги\nи настолки\nи тёплые носки"]


async def test_replace_is_explicit(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("только пазлы")
    await alice.click(alice.last_dm, REPLACE)
    assert await wishlist_of() == ["только пазлы"]


async def test_nothing_changes_nothing(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("просто мысли вслух")
    await alice.click(alice.last_dm, "Отмена")
    assert await wishlist_of() == ["книги"]


async def test_lazy_addition_is_not_offered(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("не знаю")
    assert not alice.last_dm.buttons
    assert await wishlist_of() == ["книги"]


async def test_too_long_to_add_keeps_the_offer(world, office):
    _, _, alice = await one_person(world, office, wishlist="а" * 1400)
    await alice.dm("б" * 200)
    offer = alice.last_dm
    out = await alice.click(offer, ADD)
    assert any(c.method == "answerCallbackQuery" and "1500" in str(c.params) for c in out.calls)
    assert await wishlist_of() == ["а" * 1400], "nothing changed"
    assert any(REPLACE in t for t, _ in offer.buttons), "the offer is still there"
    await alice.click(offer, REPLACE)
    assert await wishlist_of() == ["б" * 200]


# --- the edit button / command ---------------------------------------------------------


async def test_edit_prompt_adds_by_default(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("/wishlist")
    prompt = alice.last_dm
    assert "книги" in prompt.text and "допишу" in prompt.text
    assert any("🔁 Заменить всё" in t for t, _ in prompt.buttons)
    await alice.dm("и пазлы")
    assert await wishlist_of() == ["книги\nи пазлы"]
    assert any(UNDO in t for t, _ in alice.last_dm.buttons)


async def test_edit_prompt_can_switch_to_replace(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("/wishlist")
    prompt = alice.last_dm
    await alice.click(prompt, "🔁 Заменить всё")
    assert "целиком" in prompt.text and prompt.buttons == []
    await alice.dm("всё новое")
    assert await wishlist_of() == ["всё новое"]


async def test_edit_too_long_keeps_the_step(world, office):
    _, _, alice = await one_person(world, office, wishlist="а" * 1400)
    await alice.dm("/wishlist")
    await alice.dm("б" * 200)
    assert "1500" in alice.last_dm.text
    await alice.dm("и чай")  # still adding: the step was not lost
    assert await wishlist_of() == ["а" * 1400 + "\nи чай"]


async def test_edit_started_before_this_change_still_replaces(world, office):
    """An edit step from before adding existed promised "send the new one"."""
    _, _, alice = await one_person(world, office)
    participant = (await db.participants_named("Алиса"))[0]
    async with session_scope() as s:
        await state.set_flow(s, alice.id, state.EDIT_WISHLIST, participant_ids=[participant.id])
    await alice.dm("новый вишлист")
    assert await wishlist_of() == ["новый вишлист"]


async def test_cancel_leaves_the_wishlist(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("/wishlist")
    await alice.dm("/cancel")
    await alice.dm("это не в вишлист")
    assert await wishlist_of() == ["книги"]
    assert "Что сделать с этим текстом" in alice.last_dm.text, "a new text gets the usual offer"


# --- undo -------------------------------------------------------------------------------


async def test_undo_after_adding(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("и пазлы")
    offer = alice.last_dm
    await alice.click(offer, ADD)
    await alice.click(offer, UNDO)
    assert await wishlist_of() == ["книги"]
    assert "Вернул как было" in offer.text and "книги" in offer.text
    assert offer.buttons == []
    assert_no_errors(world)


async def test_undo_after_replacing(world, office):
    _, _, alice = await one_person(world, office, wishlist="длинный продуманный вишлист")
    await alice.dm("ой")
    await alice.dm("случайно отправленное")
    await alice.click(alice.last_dm, REPLACE)
    await alice.click(alice.last_dm, UNDO)
    assert await wishlist_of() == ["длинный продуманный вишлист"]


async def test_undo_works_once(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("/wishlist")
    await alice.dm("и пазлы")
    confirmation = alice.last_dm
    data = next(d for t, d in confirmation.buttons if UNDO in t)
    await alice.click_data(confirmation, data)
    out = await alice.click_data(confirmation, data)
    assert any(c.method == "answerCallbackQuery" and "нечего" in str(c.params) for c in out.calls)
    assert await wishlist_of() == ["книги"]


async def test_only_the_latest_change_can_be_undone(world, office):
    _, _, alice = await one_person(world, office)
    await alice.dm("/wishlist")
    await alice.dm("первое")
    first = alice.last_dm
    await alice.dm("/wishlist")
    await alice.dm("второе")
    second = alice.last_dm

    out = await alice.click(first, UNDO)
    assert any("нечего" in str(c.params) for c in out.calls if c.method == "answerCallbackQuery")
    assert await wishlist_of() == ["книги\nпервое\nвторое"]
    await alice.click(second, UNDO)
    assert await wishlist_of() == ["книги\nпервое"]


async def test_undo_button_of_someone_else_does_nothing(world, office):
    group, _, alice = await one_person(world, office)
    await alice.dm("/wishlist")
    await alice.dm("и пазлы")
    data = next(d for t, d in alice.last_dm.buttons if UNDO in t)
    bob = world.user("Bob")
    group.add(bob)
    await register(bob, group, "Борис", "чай")
    await bob.click_data(bob.last_dm, data)
    assert await wishlist_of() == ["книги\nи пазлы"]
    assert await wishlist_of("Борис") == ["чай"]


# --- the Santa --------------------------------------------------------------------------


async def test_santa_sees_what_was_added(world, office):
    _, _, alice, santa = await drawn(world, office)
    await alice.dm("и тёплые носки")
    await alice.click(alice.last_dm, ADD)
    text = santa.last_dm.text
    assert "дополнил(а)" in text
    assert "➕" in text and "и тёплые носки" in text
    assert "книги" in text, "and the whole list"


async def test_santa_sees_replacement_and_undo(world, office):
    _, _, alice, santa = await drawn(world, office)
    await alice.dm("совсем другое")
    offer = alice.last_dm
    await alice.click(offer, REPLACE)
    assert "обновил(а)" in santa.last_dm.text and "совсем другое" in santa.last_dm.text
    await alice.click(offer, UNDO)
    assert "обновил(а)" in santa.last_dm.text and "книги" in santa.last_dm.text
    assert "совсем другое" not in santa.last_dm.text


async def test_no_santa_message_before_the_draw(world, office):
    group, _, alice = await one_person(world, office)
    bob = world.user("Bob")
    group.add(bob)
    await register(bob, group, "Борис", "чай")
    before = len(bob.inbox)
    await alice.dm("и пазлы")
    await alice.click(alice.last_dm, ADD)
    assert len(bob.inbox) == before


# --- several groups ---------------------------------------------------------------------


async def test_adding_and_undo_in_two_groups(world):
    alice = world.user("Alice")
    for title, wishlist in (("Office", "книги"), ("Family", "пледы")):
        owner = world.user(f"Owner{title}")
        group = world.group(title, owner=owner)
        await owner.send(group, "/start")
        group.add(alice)
        await register(alice, group, "Алиса", wishlist)

    await alice.dm("и чай")
    offer = alice.last_dm
    await alice.click(offer, ADD)
    assert sorted(await wishlist_of()) == ["книги\nи чай", "пледы\nи чай"], "each group keeps its own list"
    await alice.click(offer, UNDO)
    assert sorted(await wishlist_of()) == ["книги", "пледы"]
