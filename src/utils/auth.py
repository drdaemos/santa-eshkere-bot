"""Authentication and authorization utilities"""

from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from ..messages import Messages


def require_admin(func: Callable) -> Callable:
    """Decorator to require admin authentication"""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user:
            return

        if update.effective_user.id != config.ADMIN_TELEGRAM_ID:
            if update.message:
                await update.message.reply_text(Messages.ERROR_ADMIN_ONLY)
            return

        return await func(update, context)

    return wrapper


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
    """Decorator to require admin has selected a group"""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if "selected_group_id" not in context.user_data:
            if update.message:
                await update.message.reply_text(Messages.ERROR_NO_GROUP_SELECTED)
            return

        return await func(update, context)

    return wrapper


def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id == config.ADMIN_TELEGRAM_ID
