"""The current time, in one place so tests can move it.

Deadlines are stored as naive UTC. People type and read them in the bot's
local time zone (config.TIMEZONE).
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .config import config


def utcnow() -> datetime:
    """Naive UTC now (the database stores naive datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)


def local_zone() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def to_utc(local: datetime) -> datetime:
    """Naive local time (config.TIMEZONE) -> naive UTC."""
    return local.replace(tzinfo=local_zone()).astimezone(UTC).replace(tzinfo=None)


def to_local(utc: datetime) -> datetime:
    """Naive UTC -> naive local time (config.TIMEZONE)."""
    return utc.replace(tzinfo=UTC).astimezone(local_zone()).replace(tzinfo=None)


def local_now() -> datetime:
    return to_local(utcnow())


def show(utc: datetime) -> str:
    """How a deadline reads in messages: 30.11 в 18:00."""
    local = to_local(utc)
    return f"{local:%d.%m} в {local:%H:%M}"
