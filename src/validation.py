"""Validation of everything that comes from users: names, wishlists,
command arguments and callback data."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

NAME_MAX_LENGTH = 40
WISHLIST_MIN_LENGTH = 3
# The assignment DM is template + name + wishlist; this keeps it far below 4096
WISHLIST_MAX_LENGTH = 1500

_LAZY_WISHLISTS = {"не знаю", "я не знаю", "хз", "ничего", "нет", "что угодно", "-", "...", "?"}


class ValidationError(ValueError):
    """Carries a user-facing message (Russian, plain text)."""


def _strip_controls(text: str) -> str:
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def clean_name(raw: str) -> str:
    text = _strip_controls(raw).strip()
    if "\n" in text:
        raise ValidationError("Имя должно быть одной строкой. Как тебя подписать?")
    text = re.sub(r"\s+", " ", text)
    if not text:
        raise ValidationError("Имя не может быть пустым. Как тебя подписать?")
    if len(text) > NAME_MAX_LENGTH:
        raise ValidationError(f"Слишком длинно — до {NAME_MAX_LENGTH} символов, пожалуйста. Как тебя подписать?")
    if not any(ch.isalpha() for ch in text):
        raise ValidationError("В имени должна быть хотя бы одна буква. Как тебя подписать?")
    return text


def clean_wishlist(raw: str) -> str:
    text = _strip_controls(raw).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) < WISHLIST_MIN_LENGTH:
        raise ValidationError("Коротковато 🙂 Напиши хотя бы пару идей.")
    if text.lower().strip(" .!") in _LAZY_WISHLISTS:
        raise ValidationError("«Не знаю» не принимается 😄 Напиши хоть пару идей или чего точно НЕ дарить.")
    if len(text) > WISHLIST_MAX_LENGTH:
        raise ValidationError(
            f"Вишлист длиннее {WISHLIST_MAX_LENGTH} символов (у тебя {len(text)}). Сократи, пожалуйста, — Санта всё равно не дочитает 🙂"
        )
    return text


CHAT_MESSAGE_MAX_LENGTH = 1000


def clean_chat_message(raw: str) -> str:
    text = _strip_controls(raw).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise ValidationError("Пустое сообщение. Напиши текст.")
    if len(text) > CHAT_MESSAGE_MAX_LENGTH:
        raise ValidationError(f"Длинновато: до {CHAT_MESSAGE_MAX_LENGTH} символов (у тебя {len(text)}). Сократи, пожалуйста.")
    return text


def parse_index(args: list[str], count: int) -> int:
    """1-based list index from command args -> 0-based, or ValidationError."""
    if len(args) != 1 or not args[0].isdigit():
        raise ValidationError("Использование: /selectgroup <номер>")
    index = int(args[0]) - 1
    if not 0 <= index < count:
        raise ValidationError(f"Нет группы с номером {args[0]}.")
    return index


_DEADLINE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?(?:\s+(\d{1,2})[:.](\d{2}))?$")
DEADLINE_USAGE = "Напиши дату: /deadline 30.11 или /deadline 30.11 18:00. Убрать дедлайн: /deadline off"


def parse_deadline(raw: str, now: datetime) -> datetime:
    """'30.11', '30.11 18:00', '30.11.2026 18:00' -> naive local datetime.

    A date alone means the end of that day; without a year it is this year's
    date, or next year's when this year's is long gone (January typed in
    December). Must be in the future and within a year of `now` (local)."""
    match = _DEADLINE.match(" ".join(raw.split()))
    if match is None:
        raise ValidationError(f"Не понял дату. {DEADLINE_USAGE}")
    day, month, year, hour, minute = match.groups()
    explicit_year = year is not None
    year_value = (2000 + int(year) if len(year) == 2 else int(year)) if year else now.year
    hour_value, minute_value = (int(hour), int(minute)) if hour is not None else (23, 59)
    try:
        moment = datetime(year_value, int(month), int(day), hour_value, minute_value)
        if not explicit_year and moment < now - timedelta(days=31):  # "10.01" typed in December
            moment = moment.replace(year=year_value + 1)
    except ValueError as e:
        raise ValidationError(f"Такой даты нет. {DEADLINE_USAGE}") from e
    if moment <= now:
        raise ValidationError("Эта дата уже прошла — дедлайн должен быть в будущем.")
    if moment > now + timedelta(days=366):
        raise ValidationError("Слишком далеко — дедлайн можно поставить максимум на год вперёд.")
    return moment


# --- callback data ------------------------------------------------------------
#
# Every inline button carries the ids it acts on, so a handler never depends on
# per-user state (which may be stale). Handlers must still re-check that the
# clicking user is allowed to act on those ids: callback data is client input.

_CALLBACK_SHAPES: dict[str, int] = {
    "sg": 1,  # select group: group_id
    "ra": 2,  # addrule, first pick, page: event_id, page
    "rf": 2,  # addrule first person picked: event_id, participant_id
    "rb": 3,  # addrule, second pick, page: event_id, first_participant_id, page
    "rs": 3,  # addrule second person picked: event_id, first_participant_id, participant_id
    "rr": 1,  # remove rule: exclusion_id
    "cf": 2,  # confirm: action code, group_id  (action is an int code, see CONFIRM_ACTIONS)
    "cx": 0,  # cancel a confirmation
    "rn": 1,  # registration: reuse previous name: event_id
    "rw": 1,  # registration: reuse previous wishlist: event_id
    "tn": 1,  # registration: use Telegram name: event_id
    "ew": 0,  # edit wishlist (same as /wishlist)
    "wy": 0,  # replace the wishlist with the text just sent
    "wa": 0,  # add the text just sent to the wishlist
    "wm": 0,  # wishlist edit: switch from adding to replacing
    "wu": 1,  # undo the last wishlist change: token (services.wishlists.undo_token)
    "lw": 0,  # leave (same as /leave)
    "lq": 1,  # /leave, group picked: participant_id
    "lv": 1,  # /leave confirmed: participant_id
    "pp": 2,  # removeparticipant page: event_id, page
    "pr": 2,  # removeparticipant picked: event_id, participant_id
    "px": 2,  # removeparticipant confirmed: event_id, participant_id
    "ms": 1,  # write an anonymous message within a pairing: assignment_id
    "mx": 0,  # cancel the message draft
    "noop": 0,
}

CONFIRM_ACTIONS = {1: "reset", 2: "disband", 3: "new_season", 4: "draw"}
CONFIRM_CODES = {name: code for code, name in CONFIRM_ACTIONS.items()}

_INT = re.compile(r"^(0|[1-9][0-9]{0,18})$")


@dataclass(frozen=True)
class Callback:
    kind: str
    args: tuple[int, ...]


def callback(kind: str, *args: int) -> str:
    assert _CALLBACK_SHAPES[kind] == len(args), kind
    data = ":".join([kind, *(str(a) for a in args)])
    assert len(data.encode()) <= 64, data
    return data


def parse_callback(data: str | None) -> Callback | None:
    """Strictly parse callback data; None for anything malformed or unknown."""
    if not data or len(data) > 64:
        return None
    kind, *raw_args = data.split(":")
    if _CALLBACK_SHAPES.get(kind) != len(raw_args):
        return None
    if not all(_INT.match(a) for a in raw_args):
        return None
    return Callback(kind, tuple(int(a) for a in raw_args))
