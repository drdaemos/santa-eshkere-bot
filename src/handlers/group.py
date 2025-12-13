"""Group command handlers for /start, /join, /kickitoff"""

import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from ..database.models import Assignment, Exclusion, Group, User
from ..database.session import get_session
from ..messages import Messages
from ..services.assignment import AssignmentGenerator
from ..services.notifications import NotificationService
from ..utils.auth import is_admin, require_group_chat

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate bot in a group (admin only) or greet user in DM"""
    if not update.effective_chat or not update.effective_user:
        return

    # Handle DM /start
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "Супер, бот на связи. Напиши теперь сообщение /join в группе"
        )
        return

    # Group chat /start - check admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(Messages.ERROR_ADMIN_ONLY)
        return

    chat_id = update.effective_chat.id
    group_name = update.effective_chat.title or "Unnamed Group"

    async for session in get_session():
        # Check if group already exists
        result = await session.execute(
            select(Group).where(Group.telegram_chat_id == chat_id)
        )
        group = result.scalar_one_or_none()

        if group:
            # Reactivate if disbanded
            if not group.is_active:
                group.is_active = True
                group.activated_at = datetime.now()
                group.disbanded_at = None
                await session.commit()
                logger.info(f"Reactivated group {chat_id}")
            else:
                logger.info(f"Group {chat_id} already active")
        else:
            # Create new group
            group = Group(
                telegram_chat_id=chat_id,
                group_name=group_name,
                is_active=True
            )
            session.add(group)
            await session.commit()
            logger.info(f"Created new group {chat_id}")

    await update.message.reply_text(Messages.WELCOME, parse_mode="Markdown")


@require_group_chat
async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User joins Secret Santa (triggers DM flow)"""
    if not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    username = update.effective_user.username

    async for session in get_session():
        # Get group
        result = await session.execute(
            select(Group).where(Group.telegram_chat_id == chat_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            await update.message.reply_text(Messages.ERROR_GROUP_NOT_FOUND)
            return

        if not group.is_active:
            await update.message.reply_text(Messages.ERROR_GROUP_INACTIVE)
            return

        # Check if user already registered
        result = await session.execute(
            select(User).where(
                User.telegram_id == user_id,
                User.group_id == group.id
            )
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            await update.message.reply_text(Messages.ERROR_ALREADY_REGISTERED)
            return

        # Store group context for DM flow
        context.user_data["joining_group_id"] = group.id
        context.user_data["joining_group_name"] = group.group_name
        context.user_data["telegram_username"] = username
        context.user_data["registration_step"] = "awaiting_name"

    # Send DM to user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=Messages.ASK_NAME.format(
                group_name=context.user_data["joining_group_name"]
            ),
            parse_mode="Markdown"
        )
        # Optional: confirm in group
        # await update.message.reply_text(Messages.JOIN_CHECK_DM)
    except Exception as e:
        logger.error(f"Failed to send DM to user {user_id}: {e}")
        await update.message.reply_text(
            "Не могу отправить вам личное сообщение. Пожалуйста, начните диалог с ботом (@santa_eshkere_bot) и попробуйте снова."
        )


@require_group_chat
async def kickitoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send assignments (admin only)"""
    if not update.effective_chat or not update.effective_user:
        return

    # Check admin
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(Messages.ERROR_ADMIN_ONLY)
        return

    chat_id = update.effective_chat.id

    async for session in get_session():
        # Get group
        result = await session.execute(
            select(Group).where(Group.telegram_chat_id == chat_id)
        )
        group = result.scalar_one_or_none()

        if not group or not group.is_active:
            await update.message.reply_text(Messages.ERROR_GROUP_NOT_FOUND)
            return

        # Get participants
        result = await session.execute(
            select(User).where(User.group_id == group.id)
        )
        participants = list(result.scalars().all())

        if len(participants) < 3:
            await update.message.reply_text(Messages.ERROR_NOT_ENOUGH_PARTICIPANTS)
            return

        # Get exclusions
        result = await session.execute(
            select(Exclusion).where(Exclusion.group_id == group.id)
        )
        exclusions = list(result.scalars().all())

        # Generate assignments
        try:
            assignment_pairs = AssignmentGenerator.generate_assignments(
                participants, exclusions
            )
        except ValueError as e:
            logger.error(f"Assignment generation failed: {e}")
            await update.message.reply_text(Messages.ERROR_ASSIGNMENT_IMPOSSIBLE)
            return

        # Save assignments to database
        event_year = config.EVENT_YEAR

        # Clear existing assignments for this year
        await session.execute(
            delete(Assignment).where(
                Assignment.group_id == group.id,
                Assignment.event_year == event_year
            )
        )

        # Create user lookup
        user_lookup = {user.id: user for user in participants}

        # Save new assignments
        for giver_id, receiver_id in assignment_pairs:
            assignment = Assignment(
                group_id=group.id,
                event_year=event_year,
                giver_id=giver_id,
                receiver_id=receiver_id
            )
            session.add(assignment)

        await session.commit()

        # Send notifications
        notification_service = NotificationService(context.bot)
        assignments_dict = {
            user_lookup[giver_id]: user_lookup[receiver_id]
            for giver_id, receiver_id in assignment_pairs
        }

        results = await notification_service.send_bulk_assignments(
            assignments_dict,
            group_name=group.group_name or "Неизвестная группа"
        )

        # Report success
        success_count = sum(1 for success in results.values() if success)
        logger.info(
            f"Sent {success_count}/{len(results)} assignments for group {group.id}"
        )

    await update.message.reply_text(Messages.ASSIGNMENTS_SENT, parse_mode="Markdown")
