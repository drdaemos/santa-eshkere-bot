"""Configuration from environment variables"""

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./db/santa_eshkere.db")

    # Webhook mode (Railway)
    USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").lower() == "true"
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "").rstrip("/")
    # Optional; when empty a secret is derived from the bot token (see main.webhook_secret)
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
    PORT: int = int(os.getenv("PORT", "8000"))

    @classmethod
    def validate(cls) -> None:
        if not cls.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if cls.USE_WEBHOOK:
            if not cls.WEBHOOK_URL.startswith("https://"):
                raise ValueError("WEBHOOK_URL must be an https:// URL when USE_WEBHOOK=true")
            if cls.DATABASE_URL.startswith("sqlite"):
                # a container filesystem is wiped on deploy: refuse to lose data silently
                raise ValueError("DATABASE_URL must point at Postgres in webhook (production) mode")


config = Config()
