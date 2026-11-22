"""Joining deadlines.

An admin sets one per season (/deadline in the group). From that moment new
people can't start registering; whoever is midway through may finish. The
deadline is enforced whenever someone tries to join, so it holds even if the
bot was down when it passed. A background check also closes the join post
and tells the admin who set it, once per deadline (in the group if the
admin never opened a DM with the bot).
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from .. import clock
from ..database.models import Event, EventStatus, Group
from ..database.session import session_scope
from ..formatting import Safe, join, render
from ..messages import Messages
from . import seasons
from .join_post import refresh_join_message
from .notifications import post, send_dm

logger = logging.getLogger(__name__)


async def set_deadline(s: AsyncSession, event: Event, deadline: datetime | None, admin_telegram_id: int | None) -> None:
    """Set (naive UTC) or remove the deadline; a new one is handled afresh."""
    event.join_deadline = deadline
    event.deadline_set_by = admin_telegram_id if deadline is not None else None
    event.deadline_handled = False


async def handle_due(bot: Bot) -> int:
    """Close the join posts of seasons whose deadline just passed and tell the
    admin who set it. Each deadline is claimed atomically, so two bot
    processes (e.g. during a deploy) never handle it twice. Returns how many."""
    now = clock.utcnow()
    async with session_scope() as s:
        due = (
            await s.execute(
                select(Event.id).where(
                    Event.join_deadline.is_not(None),
                    Event.join_deadline <= now,
                    Event.deadline_handled.is_(False),
                    Event.status != EventStatus.CLOSED,
                )
            )
        ).scalars().all()
    handled = 0
    for event_id in due:
        async with session_scope() as s:
            claimed = await s.execute(
                update(Event).where(Event.id == event_id, Event.deadline_handled.is_(False)).values(deadline_handled=True)
            )
            if claimed.rowcount != 1:
                continue
            notice = await _admin_notice(s, event_id)
        handled += 1
        await refresh_join_message(bot, event_id)
        if notice is not None:
            admin_id, text, chat_id, fallback = notice
            if not await send_dm(bot, admin_id, text):
                await post(bot, chat_id, fallback)
        logger.info("Joining deadline passed for event_id=%s", event_id)
    return handled


async def _admin_notice(s: AsyncSession, event_id: int) -> tuple[int, Safe, int, Safe] | None:
    """(admin id, DM, group chat id, group fallback) for an open season, else None."""
    event = await seasons.get_event(s, event_id)
    if event is None or event.deadline_set_by is None or event.status != EventStatus.OPEN:
        return None  # nothing to do for the admin after the draw
    group: Group = event.group
    if not group.is_active:
        return None
    unfinished = await seasons.unfinished_names(s, event.id)
    note = render(Messages.DEADLINE_PASSED_UNFINISHED, names=join(unfinished, sep=", ")) if unfinished else ""
    count = await seasons.participant_count(s, event.id)
    dm = render(Messages.DEADLINE_PASSED_ADMIN, group_name=group.title, count=count, unfinished=note)
    return event.deadline_set_by, dm, group.telegram_chat_id, render(Messages.DEADLINE_PASSED_GROUP, count=count)


async def run_checks(bot: Bot, interval: float) -> None:
    """Background loop: check for passed deadlines every `interval` seconds."""
    while True:
        try:
            await handle_due(bot)
        except asyncio.CancelledError:
            raise
        except Exception:  # never let one bad check stop the loop
            logger.exception("Deadline check failed")
        await asyncio.sleep(interval)
