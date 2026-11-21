"""Run the real bot as a separate OS process against FakeTelegramServer.

Deployment-shaped: migrations run via the pre-deploy command from
railway.toml, then `python bot.py` starts with environment variables only,
like on Railway. ProcessHarness has the same interface as the in-process
Harness (api / feed / restart / errors / next_message_id), so the World/Actor
scenario DSL works unchanged.

The start command in railway.toml is `uv run --no-sync python bot.py`; here
the venv's interpreter runs bot.py directly, because on Windows killing `uv`
does not kill its child, and restart tests must really kill the bot.
"""

import asyncio
import itertools
import os
import shlex
import socket
import sys
import tomllib
from pathlib import Path
from typing import Any

import httpx

from .fake_bot_api import FakeBotAPI
from .scenario import TEST_TOKEN, Outcome
from .server import FakeTelegramServer

ROOT = Path(__file__).resolve().parents[2]
_RAILWAY = tomllib.loads((ROOT / "railway.toml").read_text(encoding="utf-8"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RAILWAY_", "TEST_"))}
    for key in ("TELEGRAM_BOT_TOKEN", "DATABASE_URL", "USE_WEBHOOK", "WEBHOOK_URL", "WEBHOOK_SECRET", "PORT", "TELEGRAM_API_BASE_URL"):
        env.pop(key, None)
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    return env


async def run_pre_deploy(database_url: str) -> str:
    """Run railway.toml's preDeployCommand exactly as written."""
    env = _clean_env() | {"DATABASE_URL": database_url, "TELEGRAM_BOT_TOKEN": TEST_TOKEN}
    output = []
    for command in _RAILWAY["deploy"]["preDeployCommand"]:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(command), cwd=ROOT, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await proc.communicate()
        output.append(out.decode("utf-8", "replace"))
        if proc.returncode != 0:
            raise RuntimeError(f"pre-deploy command failed ({command}):\n{output[-1]}")
    return "".join(output)


class BotProcess:
    def __init__(self, server: FakeTelegramServer, database_url: str, mode: str) -> None:
        assert mode in ("polling", "webhook")
        self.server, self.database_url, self.mode = server, database_url, mode
        self.port = free_port()
        self.proc: asyncio.subprocess.Process | None = None
        self.lines: list[str] = []
        self._reader: asyncio.Task | None = None

    @property
    def env(self) -> dict[str, str]:
        env = _clean_env() | {
            "TELEGRAM_BOT_TOKEN": TEST_TOKEN,
            "TELEGRAM_API_BASE_URL": self.server.base_url,
            "DATABASE_URL": self.database_url,
        }
        if self.mode == "webhook":
            env |= {"USE_WEBHOOK": "true", "WEBHOOK_URL": f"http://127.0.0.1:{self.port}", "PORT": str(self.port)}
        else:
            env |= {"USE_WEBHOOK": "false"}
        return env

    async def start(self, timeout: float = 30) -> None:
        self.server.get_updates_seen.clear()
        self.server.webhook_url = None
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, "bot.py", cwd=ROOT, env=self.env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        self._reader = asyncio.create_task(self._read())
        await self._wait_ready(timeout)

    async def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        async for raw in self.proc.stdout:
            self.lines.append(raw.decode("utf-8", "replace").rstrip())

    async def _wait_ready(self, timeout: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.proc is not None and self.proc.returncode is not None:
                raise RuntimeError("bot exited during startup:\n" + "\n".join(self.lines[-40:]))
            if self.mode == "polling" and self.server.get_updates_seen.is_set():
                return
            # the same readiness signal Railway's healthcheck uses
            if self.mode == "webhook" and self.server.webhook_url and await self.health() == 200:
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("bot did not become ready:\n" + "\n".join(self.lines[-40:]))

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def health(self) -> int | None:
        """Status code of GET /health, or None if nothing is listening yet."""
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                return (await client.get(f"{self.url}/health")).status_code
        except httpx.HTTPError:
            return None

    async def kill(self) -> None:
        """Hard kill, like a container being replaced mid-flight."""
        if self.proc is not None and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)

    def log_errors(self, since: int = 0) -> list[str]:
        return [line for line in self.lines[since:] if "Exception while handling" in line or "Traceback" in line]


class ProcessHarness:
    """Scenario-compatible harness backed by a real bot process."""

    def __init__(self, database_url: str, mode: str = "polling") -> None:
        self.api = FakeBotAPI()
        self.server = FakeTelegramServer(self.api, TEST_TOKEN)
        self.database_url = database_url
        self.mode = mode
        self.bot: BotProcess | None = None
        self.errors: list[Any] = []
        self.pre_deploy_output = ""
        self._update_ids = itertools.count(1)
        self._inbound_message_ids = itertools.count(100000)

    async def start(self) -> None:
        await self.server.start()
        self.pre_deploy_output = await run_pre_deploy(self.database_url)
        await self._start_bot()

    async def _start_bot(self) -> None:
        self.bot = BotProcess(self.server, self.database_url, self.mode)
        await self.bot.start()

    async def restart(self) -> None:
        assert self.bot is not None
        await self.bot.kill()
        await self._start_bot()

    async def stop(self) -> None:
        if self.bot is not None:
            await self.bot.kill()
        await self.server.stop()

    def next_message_id(self) -> int:
        return next(self._inbound_message_ids)

    async def feed(self, payload: dict[str, Any]) -> Outcome:
        assert self.bot is not None
        payload = {"update_id": next(self._update_ids), **payload}
        calls_before, lines_before = len(self.api.calls), len(self.bot.lines)
        status = await self.server.deliver(payload)
        assert status == 200, f"webhook answered {status}"
        await self.server.settle()
        errors = self.bot.log_errors(lines_before)
        self.errors.extend(errors)
        return Outcome(self.api.calls[calls_before:], errors)  # type: ignore[arg-type]
