"""HTML message rendering. The bot sends every message with parse_mode=HTML.

Rule: never call str.format on a template with user data. Use render(),
which escapes every value unless it is already Safe (pre-rendered HTML).
"""

from html import escape

MAX_MESSAGE_LENGTH = 4096


class Safe(str):
    """A string that is already valid Telegram HTML."""


def h(value: object) -> str:
    if isinstance(value, Safe):
        return value
    return escape(str(value), quote=False)


def render(template: str, **values: object) -> Safe:
    return Safe(template.format(**{key: h(value) for key, value in values.items()}))


def join(parts: list[Safe] | list[str], sep: str = "\n") -> Safe:
    return Safe(sep.join(h(p) for p in parts))


def truncate(text: str, limit: int) -> str:
    """Cut plain text to `limit` chars (before escaping), marking the cut."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
