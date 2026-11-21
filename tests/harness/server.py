"""The fake Bot API as a real HTTP server, for driving the bot as a separate process.

    https://api.telegram.org/bot<token>/<method>   ->   http://127.0.0.1:<port>/bot<token>/<method>

The bot is pointed here via TELEGRAM_API_BASE_URL. Bot API semantics come
from FakeBotAPI.dispatch (shared with the in-process transport); this layer
adds what only makes sense over a network:

- token check (401 like Telegram)
- update delivery, both ways Telegram does it:
  * long-polling getUpdates with offsets (at-least-once: unconfirmed updates
    are redelivered, e.g. to a restarted process)
  * webhook: POST to the URL from setWebhook with the X-Telegram-Bot-Api-Secret-Token header
- settle(): wait until the bot has finished reacting to what was delivered
"""

import asyncio
import json
import time
from typing import Any

import httpx
import tornado.httpserver
import tornado.netutil
import tornado.web

from .fake_bot_api import FakeBotAPI

# PTB sends form-encoded bodies: strings as-is, everything else JSON-encoded
_JSON_KEYS = {"reply_markup", "reply_parameters", "link_preview_options", "entities", "allowed_updates", "caption_entities"}
_INT_KEYS = {"chat_id", "message_id", "user_id", "offset", "limit", "timeout", "from_chat_id", "max_connections"}
_BOOL_KEYS = {"drop_pending_updates", "show_alert", "disable_notification", "protect_content", "allow_sending_without_reply"}


def _coerce(params: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in params.items():
        if key in _JSON_KEYS:
            out[key] = json.loads(value)
        elif key in _INT_KEYS:
            try:
                out[key] = int(value)
            except ValueError:
                out[key] = value  # e.g. chat_id="@channel"
        elif key in _BOOL_KEYS:
            out[key] = value.lower() == "true"
        else:
            out[key] = value
    return out


class _BotApiHandler(tornado.web.RequestHandler):
    def initialize(self, server: "FakeTelegramServer") -> None:
        self.server = server

    async def post(self, token: str, method: str) -> None:
        if self.request.headers.get("Content-Type", "").startswith("application/json") and self.request.body:
            params = json.loads(self.request.body)
        else:
            params = _coerce({k: self.get_argument(k) for k in self.request.arguments})
        status, payload = await self.server.handle(token, method, params)
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.finish(json.dumps(payload))

    get = post


class FakeTelegramServer:
    def __init__(self, api: FakeBotAPI, token: str) -> None:
        self.api = api
        self.token = token
        self.webhook_url: str | None = None
        self.webhook_secret: str | None = None
        self._updates: list[dict[str, Any]] = []  # delivered via polling, not yet confirmed
        self._fetched_upto = 0  # highest update_id handed out via getUpdates
        self._delivered_upto = 0
        self._new_updates = asyncio.Event()
        self._last_activity = time.monotonic()
        self._activity_count = 0
        self.get_updates_seen = asyncio.Event()
        self._http: tornado.httpserver.HTTPServer | None = None
        self.port = 0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/bot"

    async def start(self) -> None:
        app = tornado.web.Application([(r"/bot([^/]+)/(\w+)", _BotApiHandler, {"server": self})])
        sockets = tornado.netutil.bind_sockets(0, "127.0.0.1")
        self.port = sockets[0].getsockname()[1]
        self._http = tornado.httpserver.HTTPServer(app)
        self._http.add_sockets(sockets)

    async def stop(self) -> None:
        if self._http is not None:
            self._http.stop()
            await self._http.close_all_connections()

    # --- Bot API side ---------------------------------------------------------

    async def handle(self, token: str, method: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if token != self.token:
            return 401, {"ok": False, "error_code": 401, "description": "Unauthorized"}
        if method == "getUpdates":
            return 200, {"ok": True, "result": await self._get_updates(params)}
        self._touch()
        if method == "setWebhook":
            self.webhook_url = params.get("url") or None
            self.webhook_secret = params.get("secret_token")
        elif method == "deleteWebhook":
            self.webhook_url = self.webhook_secret = None
        return self.api.dispatch(method, params)

    async def _get_updates(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.get_updates_seen.set()
        if self.webhook_url:
            return []  # Telegram refuses getUpdates while a webhook is set
        offset = int(params.get("offset", 0) or 0)
        if offset:
            self._updates = [u for u in self._updates if u["update_id"] >= offset]  # confirmed
        timeout = float(params.get("timeout", 0) or 0)
        deadline = time.monotonic() + timeout
        while not self._updates and time.monotonic() < deadline:
            self._new_updates.clear()
            try:
                await asyncio.wait_for(self._new_updates.wait(), timeout=max(0.0, deadline - time.monotonic()))
            except TimeoutError:
                break
        batch = self._updates[: int(params.get("limit", 100) or 100)]
        if batch:
            self._fetched_upto = max(self._fetched_upto, batch[-1]["update_id"])
            self._touch()
        return batch

    def _touch(self) -> None:
        self._last_activity = time.monotonic()
        self._activity_count += 1

    # --- test side ------------------------------------------------------------

    async def deliver(self, update: dict[str, Any]) -> int:
        """Hand one update to the bot, the way Telegram would. Returns the HTTP
        status of the webhook POST (200 in polling mode)."""
        self._delivered_upto = max(self._delivered_upto, update["update_id"])
        if self.webhook_url:
            return await self.post_to_webhook(update, secret=self.webhook_secret)
        self._updates.append(update)
        self._new_updates.set()
        return 200

    async def post_to_webhook(self, update: dict[str, Any], secret: str | None) -> int:
        assert self.webhook_url, "bot has not set a webhook"
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret} if secret else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self.webhook_url, json=update, headers=headers)
        return response.status_code

    async def settle(self, quiet: float = 0.4, first_activity_timeout: float = 3.0, timeout: float = 15.0) -> None:
        """Wait until the bot has reacted to everything delivered so far.

        The bot runs in another process, so "done" is inferred: every polled
        update was fetched, some API activity happened after delivery (or none
        came within first_activity_timeout), then no API call for `quiet` seconds.
        """
        start = time.monotonic()
        activity_at_start = self._activity_count
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.05)
            if not self.webhook_url and self._fetched_upto < self._delivered_upto:
                continue
            if self._activity_count == activity_at_start and time.monotonic() - start < first_activity_timeout:
                continue
            if time.monotonic() - self._last_activity >= quiet:
                return
        raise TimeoutError("bot did not settle")
