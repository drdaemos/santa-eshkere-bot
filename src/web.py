"""Webhook mode: our own small HTTP server instead of Application.run_webhook.

PTB's built-in webhook server only serves the webhook path. Railway's
healthcheck needs a GET endpoint on the same port, so this module runs one
tornado server with both:

  POST /webhook  Telegram updates (secret header required, else 403)
  GET  /health   200 once the bot is started and the database answers, else 503

Railway calls /health during a deploy and only switches traffic to the new
container once it answers 200, so a bot that can't reach its database never
replaces a working one.
"""

import asyncio
import json
import logging
import signal
from types import TracebackType

import tornado.httpserver
import tornado.web
from sqlalchemy import text
from telegram import Update
from telegram.ext import Application

from .database.session import session_scope

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook"
HEALTH_PATH = "/health"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
DB_CHECK_TIMEOUT = 5.0


async def database_ok() -> bool:
    try:
        async with asyncio.timeout(DB_CHECK_TIMEOUT):
            async with session_scope() as s:
                await s.execute(text("SELECT 1"))
        return True
    except Exception as e:  # any failure means "not healthy"; never leak details
        logger.warning("Health check: database unavailable (%s)", e.__class__.__name__)
        return False


class _WebhookHandler(tornado.web.RequestHandler):
    def initialize(self, bot_app: Application, secret: str) -> None:
        self.bot_app = bot_app
        self.secret = secret

    async def post(self) -> None:
        if self.request.headers.get(SECRET_HEADER) != self.secret:
            raise tornado.web.HTTPError(403)
        try:
            update = Update.de_json(json.loads(self.request.body), self.bot_app.bot)
        except Exception:  # anything that is not a valid Update
            raise tornado.web.HTTPError(400) from None
        if update is None:
            raise tornado.web.HTTPError(400)
        await self.bot_app.update_queue.put(update)
        self.set_status(200)

    def log_exception(self, typ: type[BaseException] | None, value: BaseException | None, tb: TracebackType | None) -> None:
        # 403/400 are expected noise from scanners; don't dump request details
        if isinstance(value, tornado.web.HTTPError):
            return
        super().log_exception(typ, value, tb)


class _HealthHandler(tornado.web.RequestHandler):
    def initialize(self, bot_app: Application) -> None:
        self.bot_app = bot_app

    async def get(self) -> None:
        ok = self.bot_app.running and await database_ok()
        self.set_status(200 if ok else 503)
        self.write({"status": "ok" if ok else "unavailable"})


def make_web_app(application: Application, secret: str) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (WEBHOOK_PATH, _WebhookHandler, {"bot_app": application, "secret": secret}),
            (HEALTH_PATH, _HealthHandler, {"bot_app": application}),
        ],
        # access logs would list every request; health checks every few seconds add nothing
        log_function=lambda handler: None,
    )


def _stop_event() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # Windows
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    return stop


async def serve_webhook(
    application: Application,
    *,
    port: int,
    webhook_url: str,
    secret: str,
    allowed_updates: list[str],
) -> None:
    """Run the bot in webhook mode until SIGTERM/SIGINT."""
    stop = _stop_event()
    async with application:  # initialize() ... shutdown()
        if application.post_init:
            await application.post_init(application)
        await application.bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            allowed_updates=allowed_updates,
            # keep updates sent while a deploy was in progress
            drop_pending_updates=False,
        )
        await application.start()
        server = tornado.httpserver.HTTPServer(make_web_app(application, secret), xheaders=True)
        server.listen(port, address="0.0.0.0")
        logger.info("Webhook server listening on 0.0.0.0:%s (%s, %s)", port, WEBHOOK_PATH, HEALTH_PATH)
        try:
            await stop.wait()
        finally:
            logger.info("Stopping webhook server...")
            server.stop()
            await application.stop()
    if application.post_shutdown:
        await application.post_shutdown(application)
