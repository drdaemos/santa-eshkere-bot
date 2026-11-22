"""End-to-end: the real bot process, a fake Telegram server, real HTTP.

What this layer adds over the in-process flow tests:
- startup exactly as deployed: pre-deploy migrations, env-only config, main()
- the HTTP transport (form encoding, JSON markup, long-polling offsets)
- webhook mode with the secret token, as Telegram calls it
- real restarts: the process is killed and a new one takes over

Kept to a few long journeys because each test starts a process (~1-2 s).
"""

import os
import tomllib

import httpx
import pytest

from src.main import webhook_secret
from tests.harness.process import ROOT, ProcessHarness
from tests.harness.scenario import TEST_TOKEN, World, assignment_of, join_post, kick_off, listed, register

pytestmark = pytest.mark.e2e


async def _database_url(tmp_path, monkeypatch) -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return f"sqlite+aiosqlite:///{(tmp_path / 'e2e.db').as_posix()}"
    from tests.conftest import _wipe_postgres

    monkeypatch.setenv("DATABASE_URL", url)
    await _wipe_postgres()
    return url


@pytest.fixture
async def make_world(tmp_path, monkeypatch):
    harnesses = []

    async def make(mode: str = "polling") -> World:
        harness = ProcessHarness(await _database_url(tmp_path, monkeypatch), mode)
        harnesses.append(harness)
        await harness.start()
        return World(harness)

    yield make
    for harness in harnesses:
        await harness.stop()


def assert_clean(world: World, allowed_failures: tuple[str, ...] = ()) -> None:
    assert world.harness.errors == [], "\n".join(world.harness.errors)
    unexpected = [(c.method, c.error) for c in world.api.calls if not c.ok and c.error not in allowed_failures]
    assert unexpected == []


async def test_deploy_runs_migrations_and_bot_starts(make_world):
    world = await make_world()
    assert "Running upgrade" in world.harness.pre_deploy_output
    assert any("Application started" in line for line in world.harness.bot.lines)
    assert not any("api.telegram.org" in line or TEST_TOKEN in line for line in world.harness.bot.lines), "token leaked to logs"
    assert set(world.api.command_menus) == {"all_private_chats", "all_group_chats", "all_chat_administrators"}


async def test_full_season_over_http(make_world):
    world = await make_world("polling")
    admin = world.user("Eugene", username="eugene")
    office = world.group("Office", owner=admin)
    await admin.send(office, "/start")
    assert "Участвуют (0)" in join_post(office).text

    # two people open the DM first, one joins cold and uses the deep link
    names = {"Алиса": "Alice", "Борис": "Boris", "Вера": "Vera", "Глеб": "Gleb"}
    people = {}
    for name, first in names.items():
        actor = world.user(first, username=first.lower())
        office.add(actor)
        people[name] = actor
    for name in ("Алиса", "Борис", "Вера"):
        await register(people[name], office, name, f"хочу: {name} & <книги> https://ozon.ru/a_b_c")
    gleb = people["Глеб"]
    await gleb.send(office, "/join")
    url = office.feed[-1].reply_markup["inline_keyboard"][0][0]["url"]
    await gleb.dm(f"/start {url.split('start=', 1)[1]}")
    await gleb.dm("Глеб")
    await gleb.dm("кофе и носки")
    assert "ты в деле" in gleb.last_dm.text

    # admin: select group, add a rule, preview
    await admin.dm("/listgroups")
    await admin.click(admin.last_dm, "Office")
    await admin.dm("/addrule")
    await admin.click(admin.last_dm, "Алиса")
    await admin.click(admin.last_dm, "Борис")
    assert "Алиса ↔ Борис" in admin.last_dm.text
    await admin.dm("/listjoined")
    assert "(4)" in admin.last_dm.text

    # draw
    await kick_off(admin, office)
    received = {name: assignment_of(actor) for name, actor in people.items()}
    assert sorted(received.values()) == sorted(people)
    assert all(giver != receiver for giver, receiver in received.items())
    assert received["Алиса"] != "Борис" and received["Борис"] != "Алиса"
    santa_of_vera = next(people[g] for g, r in received.items() if r == "Вера")
    assert "хочу: Вера & <книги> https://ozon.ru/a_b_c" in santa_of_vera.last_dm.text, "wishlist arrives verbatim"

    # live wishlist update reaches the Santa; a second draw is refused
    await people["Вера"].dm("/wishlist")
    await people["Вера"].dm("передумала: варежки")
    assert "варежки" in santa_of_vera.last_dm.text
    await kick_off(admin, office)
    assert "уже сделано" in office.feed[-1].text

    # a latecomer is spliced into the chain; then someone drops out
    dasha = world.user("Dasha", username="dasha")
    office.add(dasha)
    await register(dasha, office, "Даша", "чай и пазлы")
    assert assignment_of(dasha) in people
    people["Даша"] = dasha
    await people["Глеб"].dm("/leave")
    await people["Глеб"].click(people["Глеб"].last_dm, "Да")
    assert "больше не участвуешь" in people["Глеб"].last_dm.text
    del people["Глеб"]
    received = {name: assignment_of(actor) for name, actor in people.items()}
    assert sorted(received.values()) == sorted(people), "still a complete draw without Глеб"
    assert all(giver != receiver for giver, receiver in received.items())
    assert received["Алиса"] != "Борис" and received["Борис"] != "Алиса"
    assert sorted(listed(join_post(office))) == sorted(people), "the join post tracks who is in"

    # next season: a returning player rejoins in two taps
    await admin.send(office, "/newseason")
    await admin.click(office.feed[-1], "Да")
    alice = people["Алиса"]
    await alice.send(office, "/join")
    await alice.click(alice.last_dm, "Как в прошлый раз")
    await alice.click(alice.last_dm, "Оставить")
    assert "ты в деле" in alice.last_dm.text

    assert_clean(world, allowed_failures=("Forbidden: bot can't initiate conversation with a user",))


async def test_killed_process_resumes_registration(make_world):
    world = await make_world("polling")
    admin = world.user("Eugene")
    office = world.group("Office", owner=admin)
    await admin.send(office, "/start")
    alice = world.user("Alice")
    office.add(alice)
    await alice.dm("/start")
    await alice.send(office, "/join")
    await alice.dm("Алиса")

    await world.harness.restart()  # SIGKILL, new process, same database

    await alice.dm("настолки и чай")
    assert "ты в деле" in alice.last_dm.text
    assert_clean(world)


async def test_webhook_mode_enforces_secret(make_world):
    world = await make_world("webhook")
    server = world.harness.server
    assert server.webhook_url.endswith("/webhook")
    assert server.webhook_secret == webhook_secret(TEST_TOKEN)

    alice = world.user("Alice")
    out = await alice.dm("/start")
    assert "/join" in out.texts[-1], "update delivered with the right secret is handled"

    update = {
        "update_id": 999,
        "message": {
            "message_id": 1, "date": 0, "text": "/start",
            "chat": alice.user.private_chat(), "from": alice.user.to_dict(),
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }
    replies_before = len(alice.inbox)
    for secret in (None, "wrong"):
        assert await server.post_to_webhook(update, secret=secret) == 403
    async with httpx.AsyncClient() as client:
        assert (await client.post(server.webhook_url, content=b"not json", headers={"X-Telegram-Bot-Api-Secret-Token": server.webhook_secret})).status_code >= 400
    await server.settle(first_activity_timeout=0.5)
    assert len(alice.inbox) == replies_before, "forged updates must not be processed"
    assert_clean(world)


async def test_webhook_mode_serves_railway_healthcheck(make_world):
    world = await make_world("webhook")
    bot = world.harness.bot
    healthcheck_path = tomllib.loads((ROOT / "railway.toml").read_text())["deploy"]["healthcheckPath"]
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{bot.url}{healthcheck_path}")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert (await client.get(f"{bot.url}/webhook")).status_code == 405, "the webhook only takes POST"
        assert (await client.get(f"{bot.url}/anything-else")).status_code == 404
    # Railway polls this every few seconds during a deploy: keep it out of the logs
    assert not any("/health" in line and "GET" in line for line in bot.lines)
    assert_clean(world)
