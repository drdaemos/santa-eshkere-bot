"""The group's join post: one message with a join button and the live list of
who is in. It is edited as people join and leave, so the group chat gets one
message per season instead of a notice per person.

The button is a deep link (t.me/<bot>?start=join_<event_id>): one tap opens
the DM with the bot and starts registration, even for people who never talked
to the bot before.
"""

import hashlib
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError

from .. import clock
from ..database.models import Event, EventStatus
from ..database.session import session_scope
from ..formatting import Safe, join, render, truncate
from ..messages import Messages
from ..validation import callback
from . import seasons

logger = logging.getLogger(__name__)

MAX_NAMES = 60  # keeps the post far below the 4096-char limit


def join_link(bot_username: str, event_id: int) -> str:
    return f"https://t.me/{bot_username}?start=join_{event_id}"


def participant_buttons() -> InlineKeyboardMarkup:
    """Shown under a participant's own registration/status messages."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(Messages.EDIT_WISHLIST_BUTTON, callback_data=callback("ew"))],
            [InlineKeyboardButton(Messages.LEAVE_BUTTON, callback_data=callback("lw"))],
        ]
    )


async def _content(event: Event, bot_username: str) -> tuple[Safe, InlineKeyboardMarkup | None]:
    async with session_scope() as s:
        people = sorted(await seasons.participants(s, event.id), key=lambda p: (p.joined_at, p.id))
    shown = [truncate(p.real_name, 40) for p in people[:MAX_NAMES]]
    names = join(shown, sep=", ") if people else Safe(Messages.JOIN_POST_NOBODY)
    if len(people) > MAX_NAMES:
        names = Safe(names + render(Messages.JOIN_POST_MORE, count=len(people) - MAX_NAMES))
    values = {"group_name": event.group.title, "count": len(people), "names": names}
    if event.status == EventStatus.CLOSED or not event.group.is_active:
        return render(Messages.JOIN_POST_CLOSED, **values), None
    if seasons.joining_closed(event):
        return render(Messages.JOIN_POST_REGISTRATION_OVER, **values), None
    deadline = render(Messages.JOIN_POST_DEADLINE, deadline=clock.show(event.join_deadline)) if event.join_deadline else ""
    template = Messages.JOIN_POST_DRAWN if event.status == EventStatus.DRAWN else Messages.JOIN_POST
    button = InlineKeyboardButton(Messages.JOIN_BUTTON, url=join_link(bot_username, event.id))
    return render(template, deadline=deadline, **values), InlineKeyboardMarkup([[button]])


def _digest(text: str, markup: InlineKeyboardMarkup | None) -> str:
    return hashlib.sha256(f"{text}\x00{markup is not None}".encode()).hexdigest()


async def post_join_message(bot: Bot, event_id: int) -> None:
    """Post a fresh join post for the season; the previous one (if any) is
    turned into a pointer to the new one."""
    async with session_scope() as s:
        event = await seasons.get_event(s, event_id)
        if event is None:
            return
        chat_id, old_message_id = event.group.telegram_chat_id, event.join_message_id
    text, markup = await _content(event, bot.username)
    try:
        message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
    except TelegramError as e:
        logger.warning("Join post in chat_id=%s failed: %s", chat_id, e.__class__.__name__)
        return
    async with session_scope() as s:
        event = await seasons.get_event(s, event_id)
        if event is not None:
            event.join_message_id = message.message_id
            event.join_message_digest = _digest(text, markup)
    if old_message_id is not None:
        await _edit(bot, chat_id, old_message_id, Safe(Messages.JOIN_POST_MOVED), None)


async def refresh_join_message(bot: Bot, event_id: int) -> None:
    """Bring the join post up to date (participants, season status). Cheap to
    call after any change: nothing is sent when the post would not change."""
    async with session_scope() as s:
        event = await seasons.get_event(s, event_id)
        if event is None or event.join_message_id is None:
            return
    text, markup = await _content(event, bot.username)
    digest = _digest(text, markup)
    if digest == event.join_message_digest:
        return
    result = await _edit(bot, event.group.telegram_chat_id, event.join_message_id, text, markup)
    if result == _GONE and markup is not None:
        # Deleted, or the group became a supergroup (messages get new ids
        # there). The post is how people join: put a new one up.
        async with session_scope() as s:
            stored = await seasons.get_event(s, event_id)
            if stored is not None:
                stored.join_message_id = None
                stored.join_message_digest = None
        logger.info("Join post of event_id=%s is gone; posting a new one", event_id)
        await post_join_message(bot, event_id)
    elif result == _EDITED:
        async with session_scope() as s:
            stored = await seasons.get_event(s, event_id)
            if stored is not None:
                stored.join_message_digest = digest


_EDITED, _GONE, _FAILED = "edited", "gone", "failed"


async def _edit(bot: Bot, chat_id: int, message_id: int, text: Safe, markup: InlineKeyboardMarkup | None) -> str:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        return _EDITED
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return _EDITED
        logger.info("Join post %s in chat_id=%s can't be edited: %s", message_id, chat_id, e.message)
        return _GONE if "not found" in str(e).lower() else _FAILED
    except TelegramError as e:
        logger.warning("Join post edit in chat_id=%s failed: %s", chat_id, e.__class__.__name__)
        return _FAILED


async def check_groups(bot: Bot) -> None:
    """At startup: log how each active group looks to Telegram (a stale chat id
    shows up as "chat not found"), and bring every season's join post up to
    date. Posts that changed while the bot was down, or whose edit failed, get
    edited; posts that are gone (deleted, or lost in a supergroup migration)
    are posted afresh. Unchanged posts cost no API call."""
    async with session_scope() as s:
        rows = []
        for group in await seasons.active_groups(s):
            event = await seasons.current_event(s, group.id)
            rows.append((group.id, group.telegram_chat_id, event.id if event else None))
    for group_id, chat_id, event_id in rows:
        try:
            chat = await bot.get_chat(chat_id)
            me = await bot.get_chat_member(chat_id, bot.id)
            logger.info("Group group_id=%s chat_id=%s: %s, bot is %s", group_id, chat_id, chat.type, me.status)
        except TelegramError as e:
            logger.warning("Group group_id=%s chat_id=%s unreachable: %s", group_id, chat_id, e.message)
            continue
        if event_id is not None:
            await refresh_join_message(bot, event_id)
