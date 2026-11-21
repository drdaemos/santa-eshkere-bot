"""Participant flow: /join in group -> name -> wishlist in DM; /wishlist, /status."""

import pytest

from tests.harness import db
from tests.harness.scenario import assert_no_errors, register


@pytest.fixture
async def started(world, office):
    group, admin = office
    await admin.send(group, "/start")
    return group, admin


async def test_full_registration(world, started):
    group, _ = started
    alice = world.user("Alice", username="alice")
    group.add(alice)

    await alice.dm("/start")
    out = await alice.send(group, "/join")
    assert out.sent_to(group.id) == [], "join should be silent in the group"
    assert "Office" in alice.last_dm.text

    await alice.dm("Алиса")
    assert "вишлист" in alice.last_dm.text

    await alice.dm("Настолки, кофе, размер M")
    assert "ты в деле" in alice.last_dm.text
    assert "Алиса" in alice.last_dm.text
    assert [u.wishlist for u in await db.participants_named("Алиса")] == ["Настолки, кофе, размер M"]
    assert_no_errors(world)


async def test_join_without_opening_dm_tells_user_what_to_do(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    out = await alice.send(group, "/join")
    assert "Не могу написать" in out.texts[-1]

    # Following the instruction then works
    await alice.dm("/start")
    await alice.send(group, "/join")
    assert "имя" in alice.last_dm.text


async def test_join_twice_is_refused(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    out = await alice.send(group, "/join")
    assert "уже зарегистрированы" in out.texts[-1]


async def test_wishlist_update(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")

    await alice.dm("/wishlist")
    assert "книги" in alice.last_dm.text
    await alice.dm("чай и растения")
    assert "обновлён" in alice.last_dm.text

    await alice.dm("/status")
    assert "чай и растения" in alice.last_dm.text
    assert_no_errors(world)


async def test_status_before_registration(world):
    alice = world.user("Alice")
    out = await alice.dm("/status")
    assert "Сначала нужно зарегистрироваться" in out.texts[-1]


async def test_status_lists_every_group(world):
    admin = world.user("Eugene")
    work, friends = world.group("Work", owner=admin), world.group("Friends", owner=admin)
    await admin.send(work, "/start")
    await admin.send(friends, "/start")
    alice = world.user("Alice")
    work.add(alice)
    friends.add(alice)
    await register(alice, work, "Алиса", "книги")
    await register(alice, friends, "Алиса", "книги")

    await alice.dm("/status")
    assert "Work" in alice.last_dm.text and "Friends" in alice.last_dm.text
    assert_no_errors(world)


# --- where real usage falls through -------------------------------------------------


REAL_WISHLISTS = [
    pytest.param("https://www.ozon.ru/product/nastolnaya_igra_kodovye_imena_123/", id="link-even-underscores"),
    pytest.param("https://www.wildberries.ru/catalog/123/detail_aspx", id="link-odd-underscores"),
    pytest.param("Размер одежды M * но не oversize", id="lone-asterisk"),
    pytest.param("Что-нибудь для `vim`-а и консоли`", id="backticks"),
]


@pytest.mark.parametrize("wishlist", REAL_WISHLISTS)
async def test_registration_confirms_any_wishlist_text(world, started, wishlist):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", wishlist)
    assert "ты в деле" in alice.last_dm.text
    assert wishlist in alice.last_dm.text, "wishlist must be shown verbatim"


async def test_user_can_recover_after_confirmation_failure(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "ссылка https://ozon.ru/product/igra_123")
    out = await alice.dm("книги")  # the user retries with something else
    assert out.errors == []
    assert out.sent, "the user should get some answer"


async def test_name_with_underscore(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Саша_К", "книги")
    assert "ты в деле" in alice.last_dm.text


@pytest.mark.parametrize("name", ["Алиса\nкупите\nслона", "А" * 300], ids=["multiline", "very-long"])
async def test_unreasonable_name_is_rejected(world, started, name):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    await alice.dm(name)
    assert "вишлист" not in alice.last_dm.text, "should ask for the name again"


async def test_oversized_wishlist_is_rejected_up_front(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    await alice.dm("Алиса")
    out = await alice.dm("очень хочу " * 360)  # ~3960 chars: a legal message, but echoing it overflows 4096
    assert out.sent and not out.failed, "bot should answer (e.g. 'too long, shorten it')"


async def test_non_text_wishlist_gets_a_hint(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    await alice.dm("Алиса")
    out = await alice.dm_non_text("photo")
    assert out.sent, "bot should ask for a text wishlist"


async def test_registration_survives_redeploy(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await alice.dm("/start")
    await alice.send(group, "/join")
    await alice.dm("Алиса")

    await world.harness.restart()

    out = await alice.dm("книги и чай")
    assert out.sent, "user got no answer at all after the redeploy"


async def test_stray_dm_gets_a_hint(world):
    alice = world.user("Alice")
    out = await alice.dm("привет, а как участвовать?")
    assert out.sent


async def test_wishlist_edit_can_be_cancelled(world, started):
    group, _ = started
    alice = world.user("Alice")
    group.add(alice)
    await register(alice, group, "Алиса", "книги")
    await alice.dm("/wishlist")
    out = await alice.dm("/cancel")
    assert out.sent
    await alice.dm("ой, это не вишлист")
    assert [u.wishlist for u in await db.participants_named("Алиса")] == ["книги"]
