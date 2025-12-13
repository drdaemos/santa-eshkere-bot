"""User DM command handlers for registration, wishlist, status"""

import logging

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from ..config import config
from ..database.models import Assignment, Group, User
from ..database.session import get_session
from ..messages import Messages
from ..utils.auth import require_private_chat

logger = logging.getLogger(__name__)


async def handle_registration_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle multi-step registration flow in DM"""
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text

    registration_step = context.user_data.get("registration_step")

    if registration_step == "awaiting_name":
        # User sent their name
        context.user_data["real_name"] = text
        context.user_data["registration_step"] = "awaiting_wishlist"

        await update.message.reply_text(Messages.ASK_WISHLIST, parse_mode="Markdown")

    elif registration_step == "awaiting_wishlist":
        # User sent their wishlist
        real_name = context.user_data.get("real_name")
        group_id = context.user_data.get("joining_group_id")
        group_name = context.user_data.get("joining_group_name")
        username = context.user_data.get("telegram_username")

        if not real_name or not group_id:
            await update.message.reply_text(Messages.ERROR_SYSTEM)
            return

        # Save to database
        async for session in get_session():
            user = User(
                telegram_id=user_id,
                telegram_username=username,
                real_name=real_name,
                wishlist=text,
                group_id=group_id
            )
            session.add(user)
            await session.commit()

            logger.info(f"User {user_id} registered in group {group_id}")

        # Confirm registration
        await update.message.reply_text(
            Messages.REGISTRATION_COMPLETE.format(
                name=real_name,
                wishlist=text
            ),
            parse_mode="Markdown"
        )

        # Clear registration state
        context.user_data.pop("registration_step", None)
        context.user_data.pop("joining_group_id", None)
        context.user_data.pop("joining_group_name", None)
        context.user_data.pop("real_name", None)


@require_private_chat
async def wishlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update wishlist"""
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    async for session in get_session():
        # Get user's registrations
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        users = list(result.scalars().all())

        if not users:
            await update.message.reply_text(Messages.ERROR_NOT_REGISTERED)
            return

        # For simplicity, if user is in multiple groups, update all
        # In a more complex implementation, we'd ask which group
        if len(users) == 1:
            user = users[0]
            context.user_data["updating_wishlist_user_id"] = user.id
            context.user_data["wishlist_update_step"] = "awaiting_new_wishlist"

            await update.message.reply_text(
                Messages.SHOW_CURRENT_WISHLIST.format(
                    wishlist=user.wishlist or "Не указан"
                ),
                parse_mode="Markdown"
            )
        else:
            # Multiple groups - for now, update all
            context.user_data["updating_wishlist_all"] = True
            context.user_data["wishlist_update_step"] = "awaiting_new_wishlist"

            current_wishlist = users[0].wishlist or "Не указан"
            await update.message.reply_text(
                Messages.SHOW_CURRENT_WISHLIST.format(
                    wishlist=current_wishlist
                ),
                parse_mode="Markdown"
            )


async def handle_wishlist_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle wishlist update flow"""
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    new_wishlist = update.message.text

    wishlist_step = context.user_data.get("wishlist_update_step")

    if wishlist_step == "awaiting_new_wishlist":
        async for session in get_session():
            if context.user_data.get("updating_wishlist_all"):
                # Update all user registrations
                result = await session.execute(
                    select(User).where(User.telegram_id == user_id)
                )
                users = list(result.scalars().all())

                for user in users:
                    user.wishlist = new_wishlist

                await session.commit()
            else:
                # Update specific user
                user_id_to_update = context.user_data.get("updating_wishlist_user_id")
                result = await session.execute(
                    select(User).where(User.id == user_id_to_update)
                )
                user = result.scalar_one_or_none()

                if user:
                    user.wishlist = new_wishlist
                    await session.commit()

        await update.message.reply_text(Messages.WISHLIST_UPDATED)

        # Clear state
        context.user_data.pop("wishlist_update_step", None)
        context.user_data.pop("updating_wishlist_user_id", None)
        context.user_data.pop("updating_wishlist_all", None)


@require_private_chat
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show registration and assignment status"""
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    event_year = config.EVENT_YEAR

    async for session in get_session():
        # Get all user registrations
        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        users = list(result.scalars().all())

        if not users:
            await update.message.reply_text(Messages.ERROR_NOT_REGISTERED)
            return

        if len(users) == 1:
            # Single group registration
            user = users[0]

            # Get group
            result = await session.execute(
                select(Group).where(Group.id == user.group_id)
            )
            group = result.scalar_one()

            # Check for assignment
            result = await session.execute(
                select(Assignment).where(
                    Assignment.giver_id == user.id,
                    Assignment.event_year == event_year
                )
            )
            assignment = result.scalar_one_or_none()

            if assignment:
                # Get receiver
                result = await session.execute(
                    select(User).where(User.id == assignment.receiver_id)
                )
                receiver = result.scalar_one()

                await update.message.reply_text(
                    Messages.STATUS_AFTER_ASSIGNMENT.format(
                        group_name=group.group_name,
                        name=user.real_name,
                        wishlist=user.wishlist or "Не указан",
                        receiver_name=receiver.real_name,
                        receiver_wishlist=receiver.wishlist or "Не указан"
                    ),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    Messages.STATUS_BEFORE_ASSIGNMENT.format(
                        group_name=group.group_name,
                        name=user.real_name,
                        wishlist=user.wishlist or "Не указан"
                    ),
                    parse_mode="Markdown"
                )

        else:
            # Multiple groups
            status_lines = []

            for idx, user in enumerate(users, 1):
                # Get group
                result = await session.execute(
                    select(Group).where(Group.id == user.group_id)
                )
                group = result.scalar_one()

                # Check for assignment
                result = await session.execute(
                    select(Assignment).where(
                        Assignment.giver_id == user.id,
                        Assignment.event_year == event_year
                    )
                )
                assignment = result.scalar_one_or_none()

                if assignment:
                    result = await session.execute(
                        select(User).where(User.id == assignment.receiver_id)
                    )
                    receiver = result.scalar_one()
                    status = Messages.STATUS_ASSIGNED.format(
                        receiver_name=receiver.real_name
                    )
                else:
                    status = Messages.STATUS_PENDING

                status_lines.append(
                    Messages.STATUS_GROUP_ENTRY.format(
                        index=idx,
                        group_name=group.group_name,
                        status=status
                    )
                )

            await update.message.reply_text(
                Messages.STATUS_MULTIPLE_GROUPS.format(
                    groups_status="\n\n".join(status_lines)
                ),
                parse_mode="Markdown"
            )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route text messages to appropriate handler based on context"""
    if not update.effective_chat or update.effective_chat.type != "private":
        return

    # Check if in registration flow
    if context.user_data.get("registration_step"):
        await handle_registration_flow(update, context)
        return

    # Check if in wishlist update flow
    if context.user_data.get("wishlist_update_step"):
        await handle_wishlist_update(update, context)
        return
