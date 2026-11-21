"""Re-implementation of Telegram's text-entity parsing rules, strict enough to
reproduce the "Bad Request: can't parse entities" failures real users trigger.

Only the parts the bot uses are modelled:
- legacy ``Markdown`` (parse_mode="Markdown")
- ``HTML``
MarkdownV2 is deliberately unsupported so that switching to it forces a
validator to be written first.
"""

import re
from html import unescape

MAX_MESSAGE_LENGTH = 4096  # UTF-16 code units, after entity parsing


class EntityParseError(Exception):
    """Mirrors Telegram's 400 'can't parse entities' response."""


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _byte_offset(text: str, index: int) -> int:
    return len(text[:index].encode("utf-8"))


def _missing_end(text: str, index: int) -> EntityParseError:
    return EntityParseError(
        f"Can't parse entities: can't find end of the entity starting at byte offset {_byte_offset(text, index)}"
    )


def parse_markdown_legacy(text: str) -> str:
    """Return the plain text Telegram would display, or raise EntityParseError.

    Legacy Markdown rules (Bot API docs, "Markdown style"):
    - entities: *bold*, _italic_, `code`, ```pre```, [text](url)
    - entities cannot be nested; the closing char is the next occurrence
    - a backslash escapes only _ * ` [ outside entities; any other backslash is literal
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in "_*`[":
            out.append(text[i + 1])
            i += 2
            continue
        if c in "_*":
            end = text.find(c, i + 1)
            if end == -1:
                raise _missing_end(text, i)
            out.append(text[i + 1 : end])
            i = end + 1
            continue
        if c == "`":
            if text.startswith("```", i):
                end = text.find("```", i + 3)
                if end == -1:
                    raise _missing_end(text, i)
                out.append(text[i + 3 : end])
                i = end + 3
                continue
            end = text.find("`", i + 1)
            if end == -1:
                raise _missing_end(text, i)
            out.append(text[i + 1 : end])
            i = end + 1
            continue
        if c == "[":
            end = text.find("]", i + 1)
            if end == -1:
                raise _missing_end(text, i)
            label = text[i + 1 : end]
            if end + 1 < n and text[end + 1] == "(":
                close = text.find(")", end + 2)
                if close == -1:
                    raise _missing_end(text, end + 1)
                out.append(label)
                i = close + 1
            else:
                out.append(label)
                i = end + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


_HTML_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "span", "tg-spoiler", "a", "code", "pre", "blockquote", "tg-emoji",
}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^<>]*)?)\s*>")


def parse_html(text: str) -> str:
    """Return the plain text Telegram would display, or raise EntityParseError."""
    out: list[str] = []
    stack: list[str] = []
    i = 0
    while i < len(text):
        c = text[i]
        if c == "<":
            m = _TAG_RE.match(text, i)
            if not m:
                raise EntityParseError(
                    f"Can't parse entities: unexpected '<' at byte offset {_byte_offset(text, i)}; use &lt;"
                )
            closing, tag = m.group(1) == "/", m.group(2).lower()
            if tag not in _HTML_ALLOWED_TAGS:
                raise EntityParseError(f"Can't parse entities: unsupported start tag \"{tag}\" at byte offset {_byte_offset(text, i)}")
            if closing:
                if not stack or stack[-1] != tag:
                    raise EntityParseError(f"Can't parse entities: unmatched end tag \"{tag}\" at byte offset {_byte_offset(text, i)}")
                stack.pop()
            else:
                stack.append(tag)
            i = m.end()
            continue
        out.append(c)
        i += 1
    if stack:
        raise EntityParseError(f"Can't parse entities: can't find end tag corresponding to start tag \"{stack[-1]}\"")
    return unescape("".join(out))


def render(text: str, parse_mode: str | None) -> str:
    """Validate `text` for `parse_mode` and return what the user would see."""
    if parse_mode is None:
        plain = text
    elif parse_mode == "Markdown":
        plain = parse_markdown_legacy(text)
    elif parse_mode == "HTML":
        plain = parse_html(text)
    else:
        raise NotImplementedError(f"Fake Bot API has no validator for parse_mode={parse_mode!r}")
    return plain
