"""The webhook HTTP server in isolation: secret check, bad bodies, /health."""

import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import pytest
import tornado.httpserver

from src import web

SECRET = "s3cret"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def served(monkeypatch):
    """A fake Application behind the real tornado app; yields (base_url, app, queue)."""
    queue: asyncio.Queue = asyncio.Queue()
    app = SimpleNamespace(running=True, bot=None, update_queue=queue)
    db = {"ok": True}

    async def fake_database_ok() -> bool:
        return db["ok"]

    monkeypatch.setattr(web, "database_ok", fake_database_ok)
    port = _free_port()
    server = tornado.httpserver.HTTPServer(web.make_web_app(app, SECRET))  # type: ignore[arg-type]
    server.listen(port, address="127.0.0.1")
    try:
        yield f"http://127.0.0.1:{port}", app, queue, db
    finally:
        server.stop()


UPDATE = {"update_id": 7, "message": {"message_id": 1, "date": 0, "chat": {"id": 5, "type": "private"}, "text": "hi"}}


async def test_update_with_secret_is_queued(served):
    url, _, queue, _ = served
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{url}/webhook", content=json.dumps(UPDATE), headers={web.SECRET_HEADER: SECRET})
    assert r.status_code == 200
    update = queue.get_nowait()
    assert update.update_id == 7 and update.message.text == "hi"


@pytest.mark.parametrize("headers", [{}, {web.SECRET_HEADER: "wrong"}, {web.SECRET_HEADER: ""}])
async def test_missing_or_wrong_secret_is_rejected(served, headers):
    url, _, queue, _ = served
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{url}/webhook", content=json.dumps(UPDATE), headers=headers)
    assert r.status_code == 403
    assert queue.empty()


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null", b'{"no_update_id": 1}'])
async def test_malformed_body_is_rejected(served, body):
    url, _, queue, _ = served
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{url}/webhook", content=body, headers={web.SECRET_HEADER: SECRET})
    assert r.status_code == 400
    assert queue.empty()


async def test_health_reflects_bot_and_database(served):
    url, app, _, db = served
    async with httpx.AsyncClient() as client:
        assert (await client.get(f"{url}/health")).status_code == 200
        db["ok"] = False
        r = await client.get(f"{url}/health")
        assert r.status_code == 503 and r.json() == {"status": "unavailable"}
        db["ok"] = True
        app.running = False
        assert (await client.get(f"{url}/health")).status_code == 503


async def test_database_ok_against_real_database(db):
    assert await web.database_ok() is True
