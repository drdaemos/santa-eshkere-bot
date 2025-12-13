"""Configuration management from environment variables"""

import os
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration"""

    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    ADMIN_TELEGRAM_ID: int = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

    # Database Settings
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./santa_eshkere.db")

    # Event Settings
    EVENT_YEAR: int = int(os.getenv("EVENT_YEAR", str(datetime.now().year)))

    # Webhook Settings (for Railway deployment)
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Runtime mode
    USE_WEBHOOK: bool = os.getenv("USE_WEBHOOK", "false").lower() == "true"

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration"""
        if not cls.TELEGRAM_BOT_TOKEN:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")

        if cls.ADMIN_TELEGRAM_ID == 0:
            raise ValueError("ADMIN_TELEGRAM_ID is required")

        if cls.USE_WEBHOOK and not cls.WEBHOOK_URL:
            raise ValueError("WEBHOOK_URL is required when USE_WEBHOOK=true")


# Singleton instance
config = Config()
