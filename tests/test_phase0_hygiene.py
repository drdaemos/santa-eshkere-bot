"""Regression guards for the Phase 0 deployment hygiene fixes."""

import logging
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

from telegram import Update

from src.main import configure_logging, error_handler, webhook_secret

ROOT = Path(__file__).resolve().parent.parent


def test_httpx_does_not_log_request_urls():
    # Bot API URLs contain the token; httpx logs them at INFO
    configure_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_webhook_secret_is_valid_and_stable():
    secret = webhook_secret("123:abc")
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret)
    assert secret == webhook_secret("123:abc")
    assert secret != webhook_secret("123:rotated")
    assert "abc" not in secret
    assert webhook_secret("123:abc", override="explicit") == "explicit"


async def test_error_log_does_not_contain_message_text(harness, caplog):
    update = Update.de_json(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 42, "type": "private", "first_name": "A"},
                "from": {"id": 42, "is_bot": False, "first_name": "A"},
                "text": "мой секретный вишлист",
            },
        },
        harness.app.bot,
    )
    with caplog.at_level(logging.ERROR, logger="src.main"):
        await error_handler(update, SimpleNamespace(error=RuntimeError("boom"), bot=harness.app.bot))
    assert "секретный" not in caplog.text
    assert "update_id=1" in caplog.text and "user_id=42" in caplog.text


def test_railway_start_does_not_resync_dependencies():
    deploy = tomllib.loads((ROOT / "railway.toml").read_text(encoding="utf-8"))["deploy"]
    assert "--no-sync" in deploy["startCommand"]
    assert all("--no-sync" in cmd for cmd in deploy["preDeployCommand"])
