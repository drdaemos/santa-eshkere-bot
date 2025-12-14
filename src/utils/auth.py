"""Authentication and authorization utilities"""

from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from ..messages import Messages


def require_private_chat(func: Callable) -> Callable:
    """Decorator to require private chat (DM)"""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat:
            return

        if update.effective_chat.type != "private":
            if update.message:
                await update.message.reply_text(Messages.ERROR_DM_ONLY)
            return

        return await func(update, context)

    return wrapper


def require_group_chat(func: Callable) -> Callable:
    """Decorator to require group chat"""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat:
            return

        if update.effective_chat.type == "private":
            if update.message:
                await update.message.reply_text(Messages.ERROR_GROUP_ONLY)
            return

        return await func(update, context)

    return wrapper


def require_selected_group(func: Callable) -> Callable:
    """Decorator to require admin has selected a group and is admin of it"""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        from ..database.models import Group
        from ..database.session import get_session
        from sqlalchemy import select

        if "selected_group_id" not in context.user_data:
            if update.message:
                await update.message.reply_text(Messages.ERROR_NO_GROUP_SELECTED)
            return

        if not update.effective_user:
            return

        # Verify user is still admin of the selected group
        group_id = context.user_data["selected_group_id"]
        async for session in get_session():
            result = await session.execute(
                select(Group).where(Group.id == group_id)
            )
            group = result.scalar_one_or_none()

            if not group:
                if update.message:
                    await update.message.reply_text(Messages.ERROR_GROUP_NOT_FOUND)
                return

            # Check admin status
            if not await is_chat_admin(group.telegram_chat_id, update.effective_user.id, context.bot):
                if update.message:
                    await update.message.reply_text(Messages.ERROR_ADMIN_ONLY)
                return

        return await func(update, context)

    return wrapper


async def is_chat_admin(chat_id: int, user_id: int, bot) -> bool:
    """Check if user is admin in a specific chat"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False


async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is admin in the current group chat"""
    if not update.effective_chat:
        return False

    # This function only works in group chats
    if update.effective_chat.type == "private":
        return False

    # Check if message sent anonymously as group (sender_chat = group)
    if update.message and update.message.sender_chat:
        # If sender_chat matches the group, it's an admin posting anonymously
        if update.message.sender_chat.id == update.effective_chat.id:
            return True

    # Check Telegram group admin status
    if not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id
        )
        return member.status in ["creator", "administrator"]
    except Exception:
        return False
