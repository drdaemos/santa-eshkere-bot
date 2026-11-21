"""Scenario DSL: people talking to the bot in groups and DMs.

    world = World(harness)
    admin = world.user("Eugene", username="eugene")
    office = world.group("Office", owner=admin)
    alice = world.user("Alice")
    office.add(alice)

    await alice.dm("/start")
    await alice.send(office, "/join")
    assert "имя" in alice.last_dm.text

Every action feeds one Update through the real Application and returns an
Outcome with the Bot API calls the bot made while handling it.
"""

import itertools
import time
from dataclasses import dataclass
from typing import Any

from telegram import Update
from telegram.ext import Application, ContextTypes

from src.main import build_application

from .fake_bot_api import ApiCall, FakeBotAPI, FakeGroup, FakeUser, SentMessage

TEST_TOKEN = "123456789:TEST-fake-token-for-the-in-process-bot-api"


@dataclass
class Outcome:
    calls: list[ApiCall]
    errors: list[BaseException]

    @property
    def sent(self) -> list[SentMessage]:
        """Messages successfully sent or edited while handling the update."""
        return [c.message for c in self.calls if c.ok and c.message is not None]

    @property
    def failed(self) -> list[ApiCall]:
        return [c for c in self.calls if not c.ok]

    @property
    def texts(self) -> list[str]:
        return [m.text for m in self.sent]

    def sent_to(self, chat_id: int) -> list[SentMessage]:
        return [m for m in self.sent if m.chat_id == chat_id]


class Harness:
    """Owns the fake API and the Application; can simulate a process restart."""

    def __init__(self, api: FakeBotAPI | None = None) -> None:
        self.api = api or FakeBotAPI()
        self.app: Application | None = None
        self.errors: list[BaseException] = []
        self._update_ids = itertools.count(1)
        self._inbound_message_ids = itertools.count(100000)

    async def start(self) -> None:
        app = build_application(TEST_TOKEN, request=self.api, with_lifecycle_hooks=False)
        app.add_error_handler(self._capture_error)
        await app.initialize()
        self.app = app

    async def stop(self) -> None:
        if self.app is not None:
            await self.app.shutdown()
            self.app = None

    async def restart(self) -> None:
        """New process, same database. No persistence volume on Railway, so
        context.user_data starts empty, exactly like a redeploy."""
        await self.stop()
        await self.start()

    async def _capture_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        if context.error is not None:
            self.errors.append(context.error)

    async def feed(self, payload: dict[str, Any]) -> Outcome:
        assert self.app is not None, "harness not started"
        payload = {"update_id": next(self._update_ids), **payload}
        calls_before, errors_before = len(self.api.calls), len(self.errors)
        await self.app.process_update(Update.de_json(payload, self.app.bot))
        return Outcome(self.api.calls[calls_before:], self.errors[errors_before:])

    def next_message_id(self) -> int:
        return next(self._inbound_message_ids)


class Actor:
    """A human Telegram user."""

    def __init__(self, world: "World", user: FakeUser) -> None:
        self.world = world
        self.user = user

    @property
    def id(self) -> int:
        return self.user.id

    def __repr__(self) -> str:
        return f"Actor({self.user.first_name})"

    # --- what the user does ---------------------------------------------------

    async def send(self, chat: "Group", text: str) -> Outcome:
        """Post a text message in a group chat."""
        return await self._message(chat.chat.to_dict(), text)

    async def dm(self, text: str) -> Outcome:
        """Write to the bot in private. Opening a DM is what allows the bot to
        message this user afterwards."""
        self.user.started_bot = True
        return await self._message(self.user.private_chat(), text)

    async def dm_non_text(self, kind: str = "sticker") -> Outcome:
        """Send a photo/sticker/voice instead of text."""
        self.user.started_bot = True
        payloads = {
            "sticker": {"sticker": {"file_id": "s1", "file_unique_id": "s1u", "width": 512, "height": 512, "is_animated": False, "is_video": False, "type": "regular"}},
            "photo": {"photo": [{"file_id": "p1", "file_unique_id": "p1u", "width": 90, "height": 90}]},
            "voice": {"voice": {"file_id": "v1", "file_unique_id": "v1u", "duration": 3}},
        }
        message = {
            "message_id": self.world.harness.next_message_id(),
            "date": int(time.time()),
            "chat": self.user.private_chat(),
            "from": self.user.to_dict(),
            **payloads[kind],
        }
        return await self.world.harness.feed({"message": message})

    async def click(self, message: SentMessage, button: str) -> Outcome:
        """Press the inline button whose text contains `button`."""
        matches = [data for text, data in message.buttons if button in text]
        assert matches, f"no button containing {button!r}; buttons: {[t for t, _ in message.buttons]}"
        return await self.click_data(message, matches[0])

    async def click_data(self, message: SentMessage, data: str) -> Outcome:
        """Send a callback query with arbitrary data (stale or forged buttons)."""
        query = {
            "id": str(self.world.harness.next_message_id()),
            "from": self.user.to_dict(),
            "chat_instance": f"ci{message.chat_id}",
            "data": data,
            "message": message.to_dict(),
        }
        return await self.world.harness.feed({"callback_query": query})

    async def tap_join(self, group: "Group") -> Outcome:
        """Tap the join post's button: Telegram opens the DM and sends
        /start join_<event_id> (which also lets the bot message this user)."""
        url = join_url(join_post(group))
        return await self.dm(f"/start {url.split('start=', 1)[1]}")

    def block_bot(self) -> None:
        self.user.blocked_bot = True

    # --- what the user sees ---------------------------------------------------

    @property
    def inbox(self) -> list[SentMessage]:
        """Bot messages in this user's DM, oldest first."""
        return [m for (chat_id, _), m in sorted(self.world.api.messages.items()) if chat_id == self.id]

    @property
    def last_dm(self) -> SentMessage:
        assert self.inbox, f"{self} has no DMs from the bot"
        return self.inbox[-1]

    async def _message(self, chat: dict[str, Any], text: str) -> Outcome:
        message: dict[str, Any] = {
            "message_id": self.world.harness.next_message_id(),
            "date": int(time.time()),
            "chat": chat,
            "from": self.user.to_dict(),
            "text": text,
        }
        if text.startswith("/"):
            command = text.split()[0]
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
        return await self.world.harness.feed({"message": message})


class Group:
    def __init__(self, world: "World", chat: FakeGroup) -> None:
        self.world = world
        self.chat = chat

    @property
    def id(self) -> int:
        return self.chat.id

    def add(self, *actors: Actor, status: str = "member") -> "Group":
        for actor in actors:
            self.chat.members[actor.id] = status
        return self

    def promote(self, actor: Actor) -> None:
        self.chat.members[actor.id] = "administrator"

    def demote(self, actor: Actor) -> None:
        self.chat.members[actor.id] = "member"

    @property
    def feed(self) -> list[SentMessage]:
        """Bot messages posted in this group, oldest first."""
        return [m for (chat_id, _), m in sorted(self.world.api.messages.items()) if chat_id == self.id]


class World:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self._user_ids = itertools.count(1001)
        self._group_ids = itertools.count(1)

    @property
    def api(self) -> FakeBotAPI:
        return self.harness.api

    def user(self, first_name: str, username: str | None = None) -> Actor:
        user = FakeUser(id=next(self._user_ids), first_name=first_name, username=username)
        self.api.users[user.id] = user
        return Actor(self, user)

    def group(self, title: str, owner: Actor, admins: tuple[Actor, ...] = (), members: tuple[Actor, ...] = ()) -> Group:
        chat = FakeGroup(id=-1001000000000 - next(self._group_ids), title=title)
        self.api.groups[chat.id] = chat
        group = Group(self, chat)
        group.add(owner, status="creator")
        group.add(*admins, status="administrator")
        group.add(*members)
        return group


async def register(actor: Actor, group: Group, name: str, wishlist: str) -> None:
    """The documented participant flow: open DM, /join in group, name, wishlist."""
    await actor.dm("/start")
    await actor.send(group, "/join")
    await actor.dm(name)
    await actor.dm(wishlist)


async def select_group(admin: Actor, group: Group) -> None:
    """Admin picks `group` via /listgroups and its inline button."""
    await admin.dm("/listgroups")
    await admin.click(admin.last_dm, group.chat.title)


def url_buttons(message: SentMessage) -> list[str]:
    markup = message.reply_markup or {}
    return [b["url"] for row in markup.get("inline_keyboard", []) for b in row if "url" in b]


JOIN_BUTTON = "🎁 Участвовать"


def join_post(group: Group) -> SentMessage:
    """The group's current join post (the newest bot message with the join button)."""
    posts = [m for m in group.feed if any(text == JOIN_BUTTON for text, _ in m.buttons)]
    assert posts, f"no join post in {group.chat.title}: {[m.text[:40] for m in group.feed]}"
    return posts[-1]


def join_url(message: SentMessage) -> str:
    return next(u for u in url_buttons(message) if "start=join_" in u)


def listed(post: SentMessage) -> list[str]:
    """Names in a join post's participant line."""
    line = post.text.rsplit("\n", 1)[-1]
    names = line.split(":", 1)[1].strip()
    return [] if "пока никого" in names else [n.strip() for n in names.split(",")]


ASSIGNMENT_MARKER = "Получает: "


def assignment_of(actor: Actor) -> str | None:
    """Receiver name from the latest assignment DM this actor got, if any."""
    for message in reversed(actor.inbox):
        if ASSIGNMENT_MARKER in message.text:
            return message.text.split(ASSIGNMENT_MARKER, 1)[1].split("\n", 1)[0].strip()
    return None


def assignment_dms(actor: Actor) -> list[SentMessage]:
    return [m for m in actor.inbox if ASSIGNMENT_MARKER in m.text]


def assert_no_errors(world: World) -> None:
    errors = world.harness.errors
    assert not errors, f"handler raised: {[repr(e) for e in errors]}"
    failed = [c for c in world.api.calls if not c.ok]
    assert not failed, f"Bot API rejected calls: {[(c.method, c.error) for c in failed]}"
