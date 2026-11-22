"""Chat-type guards, admin and membership checks"""

import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from telegram import Bot, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..formatting import Safe
from ..messages import Messages

logger = logging.getLogger(__name__)

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

_ADMIN_STATUSES = {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}


def require_private_chat(func: Handler) -> Handler:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat:
            return
        if update.effective_chat.type != "private":
            if update.effective_message:
                await update.effective_message.reply_text(Safe(Messages.ERROR_DM_ONLY))
            return
        await func(update, context)

    return wrapper


def require_group_chat(func: Handler) -> Handler:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat:
            return
        if update.effective_chat.type == "private":
            if update.effective_message:
                await update.effective_message.reply_text(Safe(Messages.ERROR_GROUP_ONLY))
            return
        await func(update, context)

    return wrapper


async def is_chat_admin(chat_id: int, user_id: int, bot: Bot) -> bool:
    """Is user_id currently an admin/owner of chat_id (asks Telegram, never cached).

    Telegram only guarantees getChatMember for other users when the bot is an
    admin itself: in a supergroup (especially with hidden members) it can
    fail. The admin list stays visible to every member, so it is the fallback;
    if both fail, the answer is no."""
    status = "unknown"
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in _ADMIN_STATUSES:
            return True
        status = member.status
    except TelegramError as e:
        logger.warning("Admin check in chat_id=%s failed: %s; trying the admin list", chat_id, e.message)
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except TelegramError as e:
        logger.warning("Admin list of chat_id=%s unavailable: %s", chat_id, e.message)
        return False
    if any(admin.user.id == user_id for admin in admins):
        return True
    # a "no" is what people ask about ("I'm an admin but the bot doesn't see it")
    logger.info("Not an admin: user_id=%s in chat_id=%s (status %s, %s admins listed)", user_id, chat_id, status, len(admins))
    return False


async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Is the sender of this group message an admin (incl. anonymous admins)."""
    chat, message = update.effective_chat, update.effective_message
    if not chat or chat.type == "private":
        return False
    if message and message.sender_chat and message.sender_chat.id == chat.id:
        return True  # admin posting anonymously as the group
    if not update.effective_user:
        return False
    return await is_chat_admin(chat.id, update.effective_user.id, context.bot)


_MEMBER_STATUSES = {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}


async def is_group_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Is user_id in the group now. Fails open on API errors: a hiccup must
    never lock a real member out of the game."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramError as e:
        logger.warning("Membership check in chat_id=%s failed: %s", chat_id, e.__class__.__name__)
        return True
    if member.status in _MEMBER_STATUSES:
        return True
    if member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False)):
        return True
    logger.info("Join link refused in chat_id=%s: status %s", chat_id, member.status)
    return False
