"""Sending DMs that may fail for reasons outside our control."""

import logging
from collections import defaultdict
from dataclasses import dataclass

from telegram import Bot
from telegram.error import TelegramError

from ..database.models import Group, Participant
from ..database.session import session_scope
from ..formatting import Safe, join, render, truncate
from ..messages import Messages
from .seasons import Reassignment, mark_delivered

logger = logging.getLogger(__name__)

# Older rows (and other future paths) may hold longer text than input
# validation allows; cap what goes into one message so it always fits 4096.
_NAME_CAP = 64
_GROUP_CAP = 100
_WISHLIST_CAP = 3000


def wishlist_text(participant: Participant) -> str:
    return truncate(participant.wishlist or Messages.EMPTY_WISHLIST, _WISHLIST_CAP)


def assignment_text(receiver: Participant, group_name: str) -> Safe:
    return render(
        Messages.ASSIGNMENT_NOTIFICATION,
        group_name=truncate(group_name, _GROUP_CAP),
        receiver_name=truncate(receiver.real_name, _NAME_CAP),
        receiver_wishlist=wishlist_text(receiver),
    )


def reassignment_text(receiver: Participant, group_name: str) -> Safe:
    return render(
        Messages.REASSIGNMENT_NOTIFICATION,
        group_name=truncate(group_name, _GROUP_CAP),
        receiver_name=truncate(receiver.real_name, _NAME_CAP),
        receiver_wishlist=wishlist_text(receiver),
    )


@dataclass
class Notice:
    """A DM to send after the database change it describes was committed."""

    telegram_id: int
    name: str
    text: Safe
    assignment_id: int | None = None  # marked delivered once sent
    report_chat_id: int | None = None  # group to tell if the DM can't be sent


def reassignment_notices(reassigned: list[Reassignment], group: Group, newcomer_id: int | None = None) -> list[Notice]:
    """DMs for givers whose assignment is new; a late joiner gets the regular
    assignment message, everyone else is told their old one is void."""
    return [
        Notice(
            telegram_id=r.giver.telegram_id,
            name=r.giver.real_name,
            text=(assignment_text if r.giver.id == newcomer_id else reassignment_text)(r.receiver, group.title),
            assignment_id=r.assignment_id,
            report_chat_id=group.telegram_chat_id,
        )
        for r in reassigned
    ]


async def deliver(bot: Bot, notices: list[Notice]) -> list[Notice]:
    """Send notices; record delivered assignments; report failures in their
    group (only names, never who gives to whom). Returns the failed ones."""
    delivered, failed = [], []
    for notice in notices:
        if await send_dm(bot, notice.telegram_id, notice.text):
            if notice.assignment_id is not None:
                delivered.append(notice.assignment_id)
        else:
            failed.append(notice)
    if delivered:
        async with session_scope() as s:
            await mark_delivered(s, delivered)
    by_chat: dict[int, list[str]] = defaultdict(list)
    for notice in failed:
        if notice.report_chat_id is not None:
            by_chat[notice.report_chat_id].append(notice.name)
    for chat_id, names in by_chat.items():
        await post(bot, chat_id, render(Messages.DELIVERY_FAILED, names=join(sorted(names), sep=", ")))
    return failed


async def post(bot: Bot, chat_id: int, text: Safe) -> bool:
    """Best-effort message to a group (the bot may have been removed from it)."""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except TelegramError as e:
        logger.warning("Message to chat_id=%s failed: %s", chat_id, e.__class__.__name__)
        return False


async def send_dm(bot: Bot, telegram_id: int, text: Safe) -> bool:
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
        return True
    except TelegramError as e:
        # no names or texts in logs
        logger.warning("DM to user_id=%s failed: %s", telegram_id, e.__class__.__name__)
        return False
