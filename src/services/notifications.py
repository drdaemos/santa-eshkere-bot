"""Sending DMs that may fail for reasons outside our control."""

import logging

from telegram import Bot
from telegram.error import TelegramError

from ..database.models import Participant
from ..formatting import Safe, render, truncate
from ..messages import Messages

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


async def send_dm(bot: Bot, telegram_id: int, text: Safe) -> bool:
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
        return True
    except TelegramError as e:
        # no names or texts in logs
        logger.warning("DM to user_id=%s failed: %s", telegram_id, e.__class__.__name__)
        return False
