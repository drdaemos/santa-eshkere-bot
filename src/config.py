"""Configuration from environment variables"""

import os
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    # Only for tests: point the bot at a fake Bot API server (e.g. http://127.0.0.1:8081/bot)
    TELEGRAM_API_BASE_URL: str = os.getenv("TELEGRAM_API_BASE_URL", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./db/santa_eshkere.db")

    # Webhook mode (Railway)
    USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").lower() == "true"
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "").rstrip("/")
    # Optional; when empty a secret is derived from the bot token (see main.webhook_secret)
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Time zone people type and read deadlines in (IANA name)
    TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Moscow")
    # How often the bot checks for passed joining deadlines
    DEADLINE_CHECK_SECONDS: int = int(os.getenv("DEADLINE_CHECK_SECONDS", "60"))

    # The bot's owner(s): Telegram user ids, comma-separated. They count as an
    # admin in every group the bot runs, whatever Telegram reports.
    ADMIN_TELEGRAM_ID: str = os.getenv("ADMIN_TELEGRAM_ID", "")

    # Railway sets this in every deployment
    ON_RAILWAY: bool = bool(os.getenv("RAILWAY_ENVIRONMENT"))

    @classmethod
    def owner_ids(cls) -> frozenset[int]:
        return frozenset(int(part) for part in cls.ADMIN_TELEGRAM_ID.replace(" ", "").split(",") if part)

    @classmethod
    def validate(cls) -> None:
        try:
            cls.owner_ids()
        except ValueError as e:
            raise ValueError("ADMIN_TELEGRAM_ID must be Telegram user ids separated by commas") from e
        if not cls.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if cls.USE_WEBHOOK:
            url = urlparse(cls.WEBHOOK_URL)
            local = url.hostname in ("localhost", "127.0.0.1")
            if not (url.scheme == "https" or (url.scheme == "http" and local)):
                raise ValueError("WEBHOOK_URL must be an https:// URL when USE_WEBHOOK=true")
        if cls.ON_RAILWAY and cls.DATABASE_URL.startswith("sqlite"):
            # a container filesystem is wiped on deploy: refuse to lose data silently
            raise ValueError("DATABASE_URL must point at Postgres on Railway")
        try:
            ZoneInfo(cls.TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"TIMEZONE must be an IANA time zone name like Europe/Moscow, got {cls.TIMEZONE!r}") from e
        if cls.ON_RAILWAY and cls.TELEGRAM_API_BASE_URL:
            raise ValueError("TELEGRAM_API_BASE_URL is for tests only")


config = Config()
