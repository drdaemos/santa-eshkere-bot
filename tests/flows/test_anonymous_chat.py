"""Anonymous messages between a Santa and the person they give to.

The invariant above all: a receiver must never learn who their Santa is.
"""

import logging

from tests.harness import db
from tests.harness.scenario import assert_no_errors, assignment_dms, assignment_of, kick_off, register

TO_RECEIVER = "Написать получателю"
TO_SANTA = "Написать своему Санте"
REPLY = "Ответить"
FROM_SANTA = "Тебе пишет твой Тайный Санта"


async def drawn_season(world, office, names=("Алиса", "Борис", "Вера", "Глеб")):
    group, admin = office
    await admin.send(group, "/start")
    people = {}
    for i, name in enumerate(names):
        actor = world.user(f"Tg{name}", username=f"user{i}")
        group.add(actor)
        await register(actor, group, name, f"вишлист {name}")
        people[name] = actor
    await kick_off(admin, group)
    return group, admin, people


def pairs(people):
    """giver name -> receiver name, from the assignment DMs."""
    return {name: assignment_of(actor) for name, actor in people.items()}


def santa_of(people, receiver):
    return next(people[g] for g, r in pairs(people).items() if r == receiver)


def from_santa(actor):
    return [m for m in actor.inbox if FROM_SANTA in m.text]


# --- the basic exchange -------------------------------------------------------------


async def test_assignment_dm_offers_both_directions(world, office):
    _, _, people = await drawn_season(world, office)
    for actor in people.values():
        labels = [text for text, _ in assignment_dms(actor)[-1].buttons]
        assert any(TO_RECEIVER in label for label in labels) and any(TO_SANTA in label for label in labels), labels
        assert "анонимно" in assignment_dms(actor)[-1].text


async def test_santa_asks_receiver_anonymously(world, office):
    _, _, people = await drawn_season(world, office)
    receiver_name = pairs(people)["Алиса"]
    alice, receiver = people["Алиса"], people[receiver_name]

    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    assert receiver_name in alice.last_dm.text, "the Santa sees whom they are writing to"
    await alice.dm("Какой у тебя размер свитера?")
    assert "Отправлено" in alice.last_dm.text

    got = from_santa(receiver)
    assert len(got) == 1
    message = got[0]
    assert "Какой у тебя размер свитера?" in message.text
    # nothing that identifies the Santa
    for clue in ("Алиса", "TgАлиса", "user0", str(alice.id)):
        assert clue not in message.text, clue
    assert all(str(alice.id) not in data for _, data in message.buttons)
    assert [text for text, _ in message.buttons] == ["↩️ Ответить"]
    assert_no_errors(world)


async def test_receiver_replies_to_their_santa(world, office):
    _, _, people = await drawn_season(world, office)
    receiver_name = pairs(people)["Алиса"]
    alice, receiver = people["Алиса"], people[receiver_name]
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("Размер?")

    await receiver.click(from_santa(receiver)[-1], REPLY)
    assert "Тайному Санте" in receiver.last_dm.text
    await receiver.dm("M, и люблю зелёный")
    reply = alice.last_dm
    assert "M, и люблю зелёный" in reply.text
    assert f"Пишет {receiver_name}" in reply.text, "the Santa knows who answers"

    # and the Santa can answer back
    await alice.click(reply, REPLY)
    await alice.dm("Принято!")
    assert "Принято!" in from_santa(receiver)[-1].text


async def test_receiver_can_write_first(world, office):
    _, _, people = await drawn_season(world, office)
    vera = people["Вера"]
    santa = santa_of(people, "Вера")
    await vera.click(assignment_dms(vera)[-1], TO_SANTA)
    await vera.dm("Санта, у меня аллергия на шоколад")
    assert "аллергия на шоколад" in santa.last_dm.text
    assert "Пишет Вера" in santa.last_dm.text
    others = [a for n, a in people.items() if a is not santa and n != "Вера"]
    assert not any("аллергия" in m.text for a in others for m in a.inbox), "only Вера's Santa gets it"


async def test_status_has_chat_buttons_after_the_draw(world, office):
    group, admin = office
    await admin.send(group, "/start")
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    await alice.dm("/status")
    assert not any(TO_RECEIVER in t or TO_SANTA in t for t, _ in alice.last_dm.buttons), "nothing to chat about before the draw"

    people = {"Алиса": alice}
    for i, name in enumerate(("Борис", "Вера")):
        actor = world.user(f"U{i}")
        group.add(actor)
        await register(actor, group, name, "чай")
        people[name] = actor
    await kick_off(admin, group)
    await alice.dm("/status")
    labels = [t for t, _ in alice.last_dm.buttons]
    assert any(TO_RECEIVER in t for t in labels) and any(TO_SANTA in t for t in labels)
    assert any("Изменить вишлист" in t for t in labels), "the usual buttons stay"

    await alice.click(alice.last_dm, TO_RECEIVER)
    await alice.dm("Привет из статуса")
    assert "Привет из статуса" in from_santa(people[assignment_of(alice)])[-1].text


# --- hard to get wrong -----------------------------------------------------------------


async def test_one_message_per_tap(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("первое")
    await alice.dm("второе, не для получателя")
    assert [m.text for m in from_santa(receiver)][-1].count("первое") == 1
    assert not any("второе" in m.text for m in from_santa(receiver))
    assert "вишлист" in alice.last_dm.text.lower(), "a stray text is offered as a wishlist, as usual"


async def test_cancel_button_and_command(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    prompt = alice.last_dm
    await alice.click(prompt, "Отмена")
    assert prompt.text == "Отменено."
    await alice.dm("не отправляй это")
    assert from_santa(receiver) == []

    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("/cancel")
    await alice.dm("и это тоже")
    assert from_santa(receiver) == []


async def test_bad_text_keeps_the_draft(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("а" * 1001)
    assert "Длинновато" in alice.last_dm.text
    await alice.dm_non_text("sticker")
    assert "только текст" in alice.last_dm.text
    await alice.dm("короче")
    assert "короче" in from_santa(receiver)[-1].text


async def test_html_is_shown_as_typed(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("<b>жирный</b> & <a href='x'>ссылка</a>")
    assert "<b>жирный</b> & <a href='x'>ссылка</a>" in from_santa(receiver)[-1].text
    assert_no_errors(world)


async def test_recipient_unreachable(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    receiver.block_bot()
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("ты тут?")
    assert "Не получилось доставить" in alice.last_dm.text


# --- nobody else can use the channel ---------------------------------------------------


async def test_forged_button_from_an_outsider(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    data = next(d for t, d in assignment_dms(alice)[-1].buttons if TO_RECEIVER in t)
    receiver_name = pairs(people)["Алиса"]
    outsider = next(a for n, a in people.items() if n not in ("Алиса", receiver_name))
    out = await outsider.click_data(outsider.last_dm, data)
    assert any(c.method == "answerCallbackQuery" and "не действует" in str(c.params) for c in out.calls)
    await outsider.dm("подслушиваю")
    assert not any("подслушиваю" in m.text for a in people.values() for m in a.inbox if a is not outsider)


async def test_someone_from_another_group_cannot_use_it(world, office):
    _, _, people = await drawn_season(world, office)
    data = next(d for t, d in assignment_dms(people["Алиса"])[-1].buttons if TO_RECEIVER in t)
    stranger = world.user("Mallory")
    await stranger.dm("/start")
    await stranger.click_data(stranger.last_dm, data)
    await stranger.dm("привет")
    assert all(from_santa(a) == [] for a in people.values())


# --- the pairing changes ---------------------------------------------------------------


async def test_old_buttons_stop_working_after_a_repair(world, office):
    _, _, people = await drawn_season(world, office, names=("Алиса", "Борис", "Вера", "Глеб", "Даша"))
    receiver_name = pairs(people)["Алиса"]
    alice = people["Алиса"]
    old_dm = assignment_dms(alice)[-1]

    leaver = people[receiver_name]
    await leaver.dm("/leave")
    await leaver.click(leaver.last_dm, "Да")
    out = await alice.click(old_dm, TO_RECEIVER)
    assert any("не действует" in str(c.params) for c in out.calls if c.method == "answerCallbackQuery")

    # the new assignment DM has working buttons to the new receiver
    new_dm = assignment_dms(alice)[-1]
    assert new_dm is not old_dm
    del people[receiver_name]
    new_receiver = people[assignment_of(alice)]
    await alice.click(new_dm, TO_RECEIVER)
    await alice.dm("ты теперь мой получатель")
    assert "ты теперь мой получатель" in from_santa(new_receiver)[-1].text
    assert not any("ты теперь мой" in m.text for m in leaver.inbox)


async def test_open_draft_is_not_sent_after_the_pairing_changed(world, office):
    _, _, people = await drawn_season(world, office, names=("Алиса", "Борис", "Вера", "Глеб", "Даша"))
    alice = people["Алиса"]
    receiver_name = pairs(people)["Алиса"]
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    leaver = people[receiver_name]
    await leaver.dm("/leave")
    await leaver.click(leaver.last_dm, "Да")
    await alice.dm("это уже не тебе")
    assert "не действует" in alice.last_dm.text
    assert not any("это уже не тебе" in m.text for a in people.values() for m in a.inbox if a is not alice)


async def test_reset_and_new_season_end_the_channel(world, office):
    group, admin, people = await drawn_season(world, office)
    alice = people["Алиса"]
    old = assignment_dms(alice)[-1]
    await admin.dm("/reset")
    await admin.click(admin.last_dm, "Да")
    out = await alice.click(old, TO_RECEIVER)
    assert any("не действует" in str(c.params) for c in out.calls if c.method == "answerCallbackQuery")

    await kick_off(admin, group)
    fresh = assignment_dms(alice)[-1]
    await admin.send(group, "/newseason")
    await admin.click(group.feed[-1], "Да")
    out = await alice.click(fresh, TO_RECEIVER)
    assert any("не действует" in str(c.params) for c in out.calls if c.method == "answerCallbackQuery")


async def test_late_joiner_and_rewired_santa_get_chat_buttons(world, office):
    group, admin, people = await drawn_season(world, office)
    late = world.user("Late")
    group.add(late)
    await register(late, group, "Даша", "пазлы")
    dm = assignment_dms(late)[-1]
    assert any(TO_RECEIVER in t for t, _ in dm.buttons) and any(TO_SANTA in t for t, _ in dm.buttons)

    santa = santa_of({**people, "Даша": late}, "Даша")
    rewired = assignment_dms(santa)[-1]
    assert "новое задание" in rewired.text
    await santa.click(rewired, TO_RECEIVER)
    await santa.dm("добро пожаловать")
    assert "добро пожаловать" in from_santa(late)[-1].text
    await late.click(dm, TO_SANTA)
    await late.dm("спасибо, Санта")
    assert "спасибо, Санта" in santa.last_dm.text


async def test_two_groups_keep_conversations_apart(world):
    admin = world.user("Admin")
    alice = world.user("Alice")
    office = world.group("Office", owner=admin)
    family = world.group("Family", owner=admin)
    people_by_group = {}
    for group, names in ((office, ("Борис", "Вера")), (family, ("Мама", "Папа"))):
        await admin.send(group, "/start")
        group.add(alice)
        await register(alice, group, "Алиса", "книги")
        people = {"Алиса": alice}
        for name in names:
            actor = world.user(f"Tg{name}")
            group.add(actor)
            await register(actor, group, name, "чай")
            people[name] = actor
        await kick_off(admin, group)
        people_by_group[group.chat.title] = people

    await alice.dm("/status")
    labels = [t for t, _ in alice.last_dm.buttons]
    assert any("Office" in t and "Получателю" in t for t in labels) and any("Family" in t and "Санте" in t for t in labels), labels

    await alice.click(alice.last_dm, "Получателю · Family")
    await alice.dm("семейный вопрос")
    family_people = people_by_group["Family"]
    receivers = [a for a in family_people.values() if any("семейный вопрос" in m.text for m in from_santa(a))]
    assert len(receivers) == 1 and receivers[0] is not alice
    assert "Family" in from_santa(receivers[0])[-1].text
    assert not any("семейный вопрос" in m.text for a in people_by_group["Office"].values() for m in a.inbox if a is not alice)


async def test_logs_never_hold_the_text_or_names(world, office, caplog):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    caplog.set_level(logging.INFO)  # the production level (main.configure_logging)
    caplog.clear()
    await alice.click(assignment_dms(alice)[-1], TO_RECEIVER)
    await alice.dm("секретный вопрос про размер")
    await receiver.click(from_santa(receiver)[-1], REPLY)
    await receiver.dm("секретный ответ")
    logged = caplog.text
    assert logged.count("Relayed an anonymous message") == 2
    assert "секретный" not in logged
    for name, actor in people.items():
        assert name not in logged
        assert f"user_id={actor.id}" not in logged, "who wrote to whom must not be derivable from the log"
    assert len(await db.assignments()) == 4


async def test_text_typed_without_a_draft_points_to_the_buttons(world, office):
    _, _, people = await drawn_season(world, office)
    alice = people["Алиса"]
    receiver = people[pairs(people)["Алиса"]]
    await alice.dm("Санта, какой подарок ты мне готовишь?")
    assert "Обновить вишлист" in alice.last_dm.text and "/status" in alice.last_dm.text
    assert all(from_santa(a) == [] for a in people.values())
    assert not any("какой подарок" in m.text for m in receiver.inbox), "nothing is relayed without a tap"
