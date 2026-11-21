"""In-process fake of the Telegram Bot API.

Plugged into python-telegram-bot as its HTTP transport (``BaseRequest``), so
the real Application, handlers, filters and Bot serialization all run; only
the network hop is replaced. It keeps a small model of Telegram's world
(users, chats, memberships, sent messages) and enforces the server-side
rules that make real bots fail:

- entity parsing for parse_mode (see formatting.py) and the 4096 char limit
- a bot cannot DM a user who never started it, or who blocked it
- editing a message to identical content is rejected ("message is not modified")
- callback_data is limited to 64 bytes, button text must be non-empty
"""

import itertools
import json
import time
from dataclasses import dataclass, field
from typing import Any

from telegram.request import BaseRequest, RequestData

from .formatting import MAX_MESSAGE_LENGTH, EntityParseError, render, utf16_len

BOT_ID = 7000000001
BOT_USERNAME = "santa_eshkere_bot"


class ApiError(Exception):
    def __init__(self, status: int, description: str) -> None:
        super().__init__(description)
        self.status = status
        self.description = description


@dataclass
class FakeUser:
    id: int
    first_name: str
    username: str | None = None
    started_bot: bool = False  # user has opened a DM with the bot
    blocked_bot: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "is_bot": False, "first_name": self.first_name}
        if self.username:
            d["username"] = self.username
        return d

    def private_chat(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "type": "private", "first_name": self.first_name}
        if self.username:
            d["username"] = self.username
        return d


@dataclass
class FakeGroup:
    id: int
    title: str
    # user_id -> "creator" | "administrator" | "member" | "left" | "kicked"
    members: dict[int, str] = field(default_factory=dict)
    type: str = "supergroup"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "title": self.title}


@dataclass
class SentMessage:
    """A message the bot sent, as the recipient sees it (edits applied)."""

    message_id: int
    chat_id: int
    text: str  # rendered plain text
    raw_text: str
    parse_mode: str | None
    reply_markup: dict[str, Any] | None
    chat: dict[str, Any]
    history: list[str] = field(default_factory=list)  # previous rendered texts

    @property
    def buttons(self) -> list[tuple[str, str | None]]:
        """Inline buttons as (text, callback_data), row-major."""
        if not self.reply_markup or "inline_keyboard" not in self.reply_markup:
            return []
        return [(b.get("text", ""), b.get("callback_data")) for row in self.reply_markup["inline_keyboard"] for b in row]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "message_id": self.message_id,
            "date": int(time.time()),
            "chat": self.chat,
            "from": {"id": BOT_ID, "is_bot": True, "first_name": "Santa", "username": BOT_USERNAME},
            "text": self.text,
        }
        if self.reply_markup:
            d["reply_markup"] = self.reply_markup
        return d


@dataclass
class ApiCall:
    method: str
    params: dict[str, Any]
    error: str | None = None
    message: SentMessage | None = None  # for sendMessage / editMessageText

    @property
    def ok(self) -> bool:
        return self.error is None


def _admin_member(user: dict[str, Any]) -> dict[str, Any]:
    perms = [
        "can_be_edited", "is_anonymous", "can_manage_chat", "can_delete_messages", "can_manage_video_chats",
        "can_restrict_members", "can_promote_members", "can_change_info", "can_invite_users",
        "can_post_stories", "can_edit_stories", "can_delete_stories",
    ]
    d = {"status": "administrator", "user": user}
    d.update({p: p != "is_anonymous" and p != "can_be_edited" for p in perms})
    return d


class FakeBotAPI(BaseRequest):
    def __init__(self) -> None:
        self.users: dict[int, FakeUser] = {}
        self.groups: dict[int, FakeGroup] = {}
        self.messages: dict[tuple[int, int], SentMessage] = {}
        self.calls: list[ApiCall] = []
        self._message_ids = itertools.count(1)

    # --- BaseRequest plumbing -------------------------------------------------

    @property
    def read_timeout(self) -> float | None:
        return None

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def do_request(
        self,
        url: str,
        method: str,
        request_data: RequestData | None = None,
        read_timeout: Any = None,
        write_timeout: Any = None,
        connect_timeout: Any = None,
        pool_timeout: Any = None,
    ) -> tuple[int, bytes]:
        api_method = url.rsplit("/", 1)[-1]
        params = dict(request_data.parameters) if request_data else {}
        call = ApiCall(method=api_method, params=params)
        self.calls.append(call)
        handler = getattr(self, f"_api_{api_method}", None)
        try:
            if handler is None:
                raise ApiError(400, f"Bad Request: fake Bot API does not implement {api_method}")
            result = handler(params, call)
        except ApiError as e:
            call.error = e.description
            return e.status, json.dumps({"ok": False, "error_code": e.status, "description": e.description}).encode()
        return 200, json.dumps({"ok": True, "result": result}).encode()

    # --- helpers --------------------------------------------------------------

    def _chat_dict(self, chat_id: int) -> dict[str, Any]:
        if chat_id in self.groups:
            return self.groups[chat_id].to_dict()
        if chat_id in self.users:
            return self.users[chat_id].private_chat()
        raise ApiError(400, "Bad Request: chat not found")

    def _check_can_send(self, chat_id: int) -> None:
        if chat_id in self.groups:
            return
        user = self.users.get(chat_id)
        if user is None:
            raise ApiError(400, "Bad Request: chat not found")
        if user.blocked_bot:
            raise ApiError(403, "Forbidden: bot was blocked by the user")
        if not user.started_bot:
            raise ApiError(403, "Forbidden: bot can't initiate conversation with a user")

    @staticmethod
    def _render(params: dict[str, Any]) -> str:
        text = params.get("text")
        if not text or not str(text).strip():
            raise ApiError(400, "Bad Request: message text is empty")
        try:
            plain = render(str(text), params.get("parse_mode"))
        except EntityParseError as e:
            raise ApiError(400, f"Bad Request: {e}") from e
        if not plain.strip():
            raise ApiError(400, "Bad Request: message text is empty")
        if utf16_len(plain) > MAX_MESSAGE_LENGTH:
            raise ApiError(400, "Bad Request: message is too long")
        return plain

    @staticmethod
    def _check_markup(markup: dict[str, Any] | None) -> None:
        if not markup or "inline_keyboard" not in markup:
            return
        for row in markup["inline_keyboard"]:
            for button in row:
                if not button.get("text"):
                    raise ApiError(400, "Bad Request: text buttons are unallowed in the inline keyboard")
                data = button.get("callback_data")
                if data is not None and not (1 <= len(data.encode()) <= 64):
                    raise ApiError(400, "Bad Request: BUTTON_DATA_INVALID")

    # --- Bot API methods ------------------------------------------------------

    def _api_getMe(self, params: dict[str, Any], call: ApiCall) -> dict[str, Any]:
        return {
            "id": BOT_ID,
            "is_bot": True,
            "first_name": "Santa",
            "username": BOT_USERNAME,
            "can_join_groups": True,
            "can_read_all_group_messages": False,
            "supports_inline_queries": False,
        }

    def _api_sendMessage(self, params: dict[str, Any], call: ApiCall) -> dict[str, Any]:
        chat_id = int(params["chat_id"])
        self._check_can_send(chat_id)
        plain = self._render(params)
        markup = params.get("reply_markup")
        self._check_markup(markup)
        msg = SentMessage(
            message_id=next(self._message_ids),
            chat_id=chat_id,
            text=plain,
            raw_text=str(params["text"]),
            parse_mode=params.get("parse_mode"),
            reply_markup=markup,
            chat=self._chat_dict(chat_id),
        )
        self.messages[(chat_id, msg.message_id)] = msg
        call.message = msg
        return msg.to_dict()

    def _api_editMessageText(self, params: dict[str, Any], call: ApiCall) -> dict[str, Any]:
        chat_id = int(params["chat_id"])
        msg = self.messages.get((chat_id, int(params["message_id"])))
        if msg is None:
            raise ApiError(400, "Bad Request: message to edit not found")
        plain = self._render(params)
        markup = params.get("reply_markup")
        self._check_markup(markup)
        if plain == msg.text and markup == msg.reply_markup:
            raise ApiError(
                400,
                "Bad Request: message is not modified: specified new message content and reply markup "
                "are exactly the same as a current content and reply markup of the message",
            )
        msg.history.append(msg.text)
        msg.text, msg.raw_text, msg.parse_mode, msg.reply_markup = plain, str(params["text"]), params.get("parse_mode"), markup
        call.message = msg
        return msg.to_dict()

    def _api_answerCallbackQuery(self, params: dict[str, Any], call: ApiCall) -> bool:
        return True

    def _api_getChatMember(self, params: dict[str, Any], call: ApiCall) -> dict[str, Any]:
        chat_id, user_id = int(params["chat_id"]), int(params["user_id"])
        group = self.groups.get(chat_id)
        if group is None:
            raise ApiError(400, "Bad Request: chat not found")
        user = self.users.get(user_id)
        if user is None:
            raise ApiError(400, "Bad Request: user not found")
        status = group.members.get(user_id, "left")
        user_dict = user.to_dict()
        if status == "administrator":
            return _admin_member(user_dict)
        if status == "creator":
            return {"status": "creator", "user": user_dict, "is_anonymous": False}
        if status == "kicked":
            return {"status": "kicked", "user": user_dict, "until_date": 0}
        return {"status": status, "user": user_dict}

    def _api_setWebhook(self, params: dict[str, Any], call: ApiCall) -> bool:
        return True

    def _api_deleteWebhook(self, params: dict[str, Any], call: ApiCall) -> bool:
        return True

    def _api_deleteMessage(self, params: dict[str, Any], call: ApiCall) -> bool:
        self.messages.pop((int(params["chat_id"]), int(params["message_id"])), None)
        return True
