"""Chat-type guards and admin checks"""

from collections.abc import Awaitable, Callable
from functools import wraps

from telegram import Bot, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..formatting import Safe
from ..messages import Messages

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
    """Is user_id currently an admin/owner of chat_id (asks Telegram, never cached)."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramError:
        return False
    return member.status in _ADMIN_STATUSES


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
