"""Admin command handlers"""

import logging
import re
from datetime import datetime

from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..config import config
from ..database.models import Assignment, Exclusion, Group, User
from ..database.session import get_session
from ..messages import Messages
from ..utils.auth import is_chat_admin, require_private_chat, require_selected_group

logger = logging.getLogger(__name__)


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown"""
    if not text:
        return text
    # Escape special Markdown characters
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + char if char in escape_chars else char for char in text)


@require_private_chat
async def listgroups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all active groups where user is admin"""
    if not update.effective_user:
        return

    async for session in get_session():
        result = await session.execute(
            select(Group).where(Group.is_active == True).order_by(Group.activated_at.desc())
        )
        all_groups = list(result.scalars().all())

        # Filter to only groups where user is admin
        groups = []
        for group in all_groups:
            if await is_chat_admin(group.telegram_chat_id, update.effective_user.id, context.bot):
                groups.append(group)

        if not groups:
            await update.message.reply_text(Messages.NO_GROUPS)
            return

        group_lines = []
        event_year = config.EVENT_YEAR

        for idx, group in enumerate(groups, 1):
            # Count participants
            result = await session.execute(
                select(func.count(User.id)).where(User.group_id == group.id)
            )
            participant_count = result.scalar() or 0

            # Check if assignments sent
            result = await session.execute(
                select(func.count(Assignment.id)).where(
                    Assignment.group_id == group.id,
                    Assignment.event_year == event_year
                )
            )
            assignment_count = result.scalar() or 0

            assignment_status = (
                Messages.ASSIGNMENT_STATUS_SENT
                if assignment_count > 0
                else Messages.ASSIGNMENT_STATUS_NOT_SENT
            )

            group_lines.append(
                Messages.GROUP_LIST_ENTRY.format(
                    index=idx,
                    group_name=group.group_name or "Unnamed",
                    chat_id=group.telegram_chat_id,
                    activated_at=group.activated_at.strftime("%Y-%m-%d"),
                    participants=participant_count,
                    assignment_status=assignment_status
                )
            )

        # Store groups in context for selectgroup
        context.user_data["available_groups"] = [
            {"id": g.id, "name": g.group_name} for g in groups
        ]

        # Create inline keyboard with group selection buttons
        keyboard = []
        for idx, group in enumerate(groups):
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ {group.group_name or 'Unnamed'}",
                    callback_data=f"select_group_{group.id}"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            Messages.LIST_GROUPS.format(groups_list="\n\n".join(group_lines)),
            parse_mode="Markdown",
            reply_markup=reply_markup
        )


@require_private_chat
async def selectgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Select a group for subsequent operations"""
    if not update.message or not context.args:
        await update.message.reply_text("Использование: /selectgroup <номер>")
        return

    try:
        group_index = int(context.args[0]) - 1
    except (ValueError, IndexError):
        await update.message.reply_text(Messages.ERROR_INVALID_INPUT)
        return

    available_groups = context.user_data.get("available_groups", [])

    if group_index < 0 or group_index >= len(available_groups):
        await update.message.reply_text(Messages.ERROR_INVALID_INPUT)
        return

    selected_group = available_groups[group_index]
    context.user_data["selected_group_id"] = selected_group["id"]

    await update.message.reply_text(
        Messages.GROUP_SELECTED.format(group_name=selected_group["name"]),
        parse_mode="Markdown"
    )


async def handle_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle group selection from inline keyboard"""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("select_group_") or not update.effective_user:
        return

    # Extract group ID from callback data
    group_id = int(query.data.replace("select_group_", ""))

    # Get group name from database
    async for session in get_session():
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            await query.edit_message_text(Messages.ERROR_GROUP_NOT_FOUND)
            return

        # Verify user is admin of this group
        if not await is_chat_admin(group.telegram_chat_id, update.effective_user.id, context.bot):
            await query.edit_message_text(Messages.ERROR_ADMIN_ONLY)
            return

        # Store selected group
        context.user_data["selected_group_id"] = group_id

        # Update message to show selection
        await query.edit_message_text(
            f"✓ Выбрана группа: **{group.group_name}**\n\n"
            f"Используйте команды для управления этой группой:\n"
            f"/addrule - Добавить правило исключения\n"
            f"/listrules - Показать правила\n"
            f"/listjoined - Список участников\n"
            f"/disband - Расформировать группу\n"
            f"/reset - Сбросить распределения",
            parse_mode="Markdown"
        )

        logger.info(f"Admin selected group {group_id}")


@require_private_chat
@require_selected_group
async def disband_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disband the selected group"""
    group_id = context.user_data["selected_group_id"]

    async for session in get_session():
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()

        if not group:
            await update.message.reply_text(Messages.ERROR_GROUP_NOT_FOUND)
            return

        # Ask for confirmation
        context.user_data["pending_disband_group_id"] = group_id
        context.user_data["awaiting_disband_confirmation"] = True

        await update.message.reply_text(
            Messages.DISBAND_CONFIRM.format(group_name=group.group_name),
            parse_mode="Markdown"
        )


async def handle_disband_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle disband confirmation"""
    if not update.message:
        return

    response = update.message.text.lower().strip()
    group_id = context.user_data.get("pending_disband_group_id")

    if response == Messages.CONFIRM_YES:
        async for session in get_session():
            result = await session.execute(
                select(Group).where(Group.id == group_id)
            )
            group = result.scalar_one_or_none()

            if group:
                group.is_active = False
                group.disbanded_at = datetime.now()
                await session.commit()

                await update.message.reply_text(Messages.GROUP_DISBANDED)
                logger.info(f"Group {group_id} disbanded")
    else:
        await update.message.reply_text("Отменено.")

    context.user_data.pop("pending_disband_group_id", None)
    context.user_data.pop("awaiting_disband_confirmation", None)


def build_user_selection_keyboard(users: list, page: int, callback_prefix: str, users_per_page: int = 8):
    """Build paginated keyboard for user selection"""
    total_pages = (len(users) + users_per_page - 1) // users_per_page
    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, len(users))

    keyboard = []

    # Add user buttons for current page
    for user in users[start_idx:end_idx]:
        username_text = f" (@{user.telegram_username})" if user.telegram_username else ""
        keyboard.append([
            InlineKeyboardButton(
                f"{user.real_name}{username_text}",
                callback_data=f"{callback_prefix}{user.id}"
            )
        ])

    # Add navigation buttons if needed
    if total_pages > 1:
        nav_buttons = []

        # Previous button
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("← Назад", callback_data=f"addrule_page_{callback_prefix}{page - 1}")
            )

        # Page indicator
        nav_buttons.append(
            InlineKeyboardButton(f"· {page + 1}/{total_pages} ·", callback_data="addrule_noop")
        )

        # Next button
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("Вперёд →", callback_data=f"addrule_page_{callback_prefix}{page + 1}")
            )

        keyboard.append(nav_buttons)

    return InlineKeyboardMarkup(keyboard)


@require_private_chat
@require_selected_group
async def addrule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add exclusion rule using inline keyboard with pagination"""
    group_id = context.user_data["selected_group_id"]

    # Get all registered users in this group
    async for session in get_session():
        result = await session.execute(
            select(User).where(User.group_id == group_id).order_by(User.real_name)
        )
        users = list(result.scalars().all())

        if len(users) < 2:
            await update.message.reply_text(
                "❌ В группе недостаточно участников для создания правил исключения (минимум 2)."
            )
            return

        # Store users list for pagination
        context.user_data["addrule_all_users"] = [
            {"id": u.id, "name": u.real_name, "username": u.telegram_username}
            for u in users
        ]

        # Build paginated keyboard
        reply_markup = build_user_selection_keyboard(users, 0, "addrule_first_")

        await update.message.reply_text(
            "Выберите первого человека:",
            reply_markup=reply_markup
        )


async def handle_addrule_page_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination for user selection"""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("addrule_page_"):
        return

    # Parse callback data: addrule_page_addrule_first_2 or addrule_page_addrule_second_1
    parts = query.data.replace("addrule_page_", "").split("_")
    callback_prefix = f"{parts[0]}_{parts[1]}_"  # e.g., "addrule_first_"
    page = int(parts[2])

    group_id = context.user_data.get("selected_group_id")
    all_users = context.user_data.get("addrule_all_users", [])

    if not all_users:
        await query.edit_message_text("❌ Ошибка: список пользователей потерян.")
        return

    # Rebuild User objects from stored data
    async for session in get_session():
        user_ids = [u["id"] for u in all_users]
        result = await session.execute(
            select(User).where(User.id.in_(user_ids))
        )
        users_dict = {u.id: u for u in result.scalars().all()}

        # Filter if selecting second user
        if callback_prefix == "addrule_second_":
            first_user_id = context.user_data.get("addrule_first_user_id")
            users = [users_dict[u["id"]] for u in all_users if u["id"] != first_user_id and u["id"] in users_dict]
        else:
            users = [users_dict[u["id"]] for u in all_users if u["id"] in users_dict]

        # Build paginated keyboard
        reply_markup = build_user_selection_keyboard(users, page, callback_prefix)

        # Update message based on selection stage
        if callback_prefix == "addrule_first_":
            text = "Выберите первого человека:"
        else:
            first_name = context.user_data.get("addrule_first_user_name", "")
            text = f"Выбран: **{first_name}**\n\nТеперь выберите второго человека:"

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )


async def handle_addrule_first_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle first user selection for exclusion rule"""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("addrule_first_"):
        return

    # Extract user ID from callback data
    first_user_id = int(query.data.replace("addrule_first_", ""))
    group_id = context.user_data.get("selected_group_id")

    async for session in get_session():
        # Get first user details
        result = await session.execute(
            select(User).where(User.id == first_user_id)
        )
        first_user = result.scalar_one_or_none()

        if not first_user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        # Store first user
        context.user_data["addrule_first_user_id"] = first_user_id
        context.user_data["addrule_first_user_name"] = first_user.real_name

        # Get all users except the first one
        result = await session.execute(
            select(User).where(
                User.group_id == group_id,
                User.id != first_user_id
            ).order_by(User.real_name)
        )
        users = list(result.scalars().all())

        # Build paginated keyboard for second user
        reply_markup = build_user_selection_keyboard(users, 0, "addrule_second_")

        await query.edit_message_text(
            f"Выбран: **{first_user.real_name}**\n\nТеперь выберите второго человека:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )


async def handle_addrule_second_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle second user selection for exclusion rule"""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("addrule_second_"):
        return

    # Extract user ID from callback data
    second_user_id = int(query.data.replace("addrule_second_", ""))
    first_user_id = context.user_data.get("addrule_first_user_id")
    first_user_name = context.user_data.get("addrule_first_user_name")
    group_id = context.user_data.get("selected_group_id")

    if not first_user_id or not group_id:
        await query.edit_message_text("❌ Ошибка: потеряны данные первого пользователя.")
        return

    async for session in get_session():
        # Get second user details
        result = await session.execute(
            select(User).where(User.id == second_user_id)
        )
        second_user = result.scalar_one_or_none()

        if not second_user:
            await query.edit_message_text("❌ Пользователь не найден.")
            return

        # Canonical ordering
        user1_id = min(first_user_id, second_user_id)
        user2_id = max(first_user_id, second_user_id)

        # Check if rule already exists
        result = await session.execute(
            select(Exclusion).where(
                Exclusion.user1_id == user1_id,
                Exclusion.user2_id == user2_id,
                Exclusion.group_id == group_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            await query.edit_message_text(Messages.ERROR_DUPLICATE_RULE)
            context.user_data.pop("addrule_first_user_id", None)
            context.user_data.pop("addrule_first_user_name", None)
            return

        # Create exclusion
        exclusion = Exclusion(
            user1_id=user1_id,
            user2_id=user2_id,
            group_id=group_id
        )
        session.add(exclusion)
        await session.commit()

        # Get group name
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one()

        await query.edit_message_text(
            Messages.ADDRULE_COMPLETE.format(
                group_name=group.group_name,
                name1=first_user_name,
                name2=second_user.real_name
            ),
            parse_mode="Markdown"
        )

        logger.info(f"Added exclusion rule: {user1_id} <-> {user2_id} in group {group_id}")

        context.user_data.pop("addrule_first_user_id", None)
        context.user_data.pop("addrule_first_user_name", None)


@require_private_chat
@require_selected_group
async def listrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all exclusion rules for selected group"""
    group_id = context.user_data["selected_group_id"]

    async for session in get_session():
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one()

        result = await session.execute(
            select(Exclusion).where(Exclusion.group_id == group_id)
        )
        exclusions = list(result.scalars().all())

        if not exclusions:
            await update.message.reply_text(Messages.NO_RULES)
            return

        rule_lines = []
        for exclusion in exclusions:
            # Get user names
            result = await session.execute(
                select(User).where(User.id == exclusion.user1_id)
            )
            user1 = result.scalar_one()

            result = await session.execute(
                select(User).where(User.id == exclusion.user2_id)
            )
            user2 = result.scalar_one()

            rule_lines.append(
                Messages.RULE_ENTRY.format(
                    name1=user1.real_name,
                    name2=user2.real_name
                )
            )

        await update.message.reply_text(
            Messages.LIST_RULES.format(
                group_name=group.group_name,
                rules_list="\n".join(rule_lines),
                count=len(exclusions)
            ),
            parse_mode="Markdown"
        )


@require_private_chat
@require_selected_group
async def removerule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove an exclusion rule"""
    group_id = context.user_data["selected_group_id"]

    async for session in get_session():
        result = await session.execute(
            select(Exclusion).where(Exclusion.group_id == group_id)
        )
        exclusions = list(result.scalars().all())

        if not exclusions:
            await update.message.reply_text(Messages.NO_RULES)
            return

        # Build inline keyboard with rules
        keyboard = []
        for exclusion in exclusions:
            result = await session.execute(
                select(User).where(User.id == exclusion.user1_id)
            )
            user1 = result.scalar_one()

            result = await session.execute(
                select(User).where(User.id == exclusion.user2_id)
            )
            user2 = result.scalar_one()

            keyboard.append([
                InlineKeyboardButton(
                    f"{user1.real_name} ↔ {user2.real_name}",
                    callback_data=f"remove_rule_{exclusion.id}"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            Messages.REMOVE_RULE_SELECT,
            reply_markup=reply_markup
        )


async def handle_remove_rule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle rule removal callback"""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("remove_rule_"):
        return

    exclusion_id = int(query.data.replace("remove_rule_", ""))

    async for session in get_session():
        await session.execute(
            delete(Exclusion).where(Exclusion.id == exclusion_id)
        )
        await session.commit()

        logger.info(f"Removed exclusion rule {exclusion_id}")

    await query.edit_message_text(Messages.RULE_REMOVED)


@require_private_chat
@require_selected_group
async def listjoined_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all joined participants in selected group"""
    group_id = context.user_data["selected_group_id"]

    async for session in get_session():
        result = await session.execute(
            select(Group).where(Group.id == group_id)
        )
        group = result.scalar_one()

        result = await session.execute(
            select(User).where(User.group_id == group_id).order_by(User.joined_at)
        )
        users = list(result.scalars().all())

        if not users:
            await update.message.reply_text(Messages.NO_PARTICIPANTS)
            return

        user_lines = []
        for user in users:
            if user.telegram_username:
                user_lines.append(
                    Messages.USER_ENTRY.format(
                        name=escape_markdown(user.real_name),
                        username=escape_markdown(user.telegram_username)
                    )
                )
            else:
                user_lines.append(
                    Messages.USER_ENTRY_NO_USERNAME.format(
                        name=escape_markdown(user.real_name)
                    )
                )

        await update.message.reply_text(
            Messages.LIST_JOINED.format(
                group_name=escape_markdown(group.group_name or ""),
                count=len(users),
                users_list="\n".join(user_lines)
            ),
            parse_mode="Markdown"
        )


@require_private_chat
async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin help"""
    await update.message.reply_text(Messages.ADMIN_HELP, parse_mode="Markdown")


@require_private_chat
@require_selected_group
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset assignments for selected group"""
    group_id = context.user_data["selected_group_id"]

    context.user_data["pending_reset_group_id"] = group_id
    context.user_data["awaiting_reset_confirmation"] = True

    await update.message.reply_text(Messages.RESET_CONFIRM, parse_mode="Markdown")


async def handle_reset_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle reset confirmation"""
    if not update.message:
        return

    response = update.message.text.lower().strip()
    group_id = context.user_data.get("pending_reset_group_id")

    if response == Messages.CONFIRM_YES:
        event_year = config.EVENT_YEAR

        async for session in get_session():
            await session.execute(
                delete(Assignment).where(
                    Assignment.group_id == group_id,
                    Assignment.event_year == event_year
                )
            )
            await session.commit()

            await update.message.reply_text(Messages.RESET_COMPLETE)
            logger.info(f"Reset assignments for group {group_id}, year {event_year}")
    else:
        await update.message.reply_text("Отменено.")

    context.user_data.pop("pending_reset_group_id", None)
    context.user_data.pop("awaiting_reset_confirmation", None)


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route admin text messages to appropriate handler"""
    if not update.effective_chat or update.effective_chat.type != "private":
        return

    # Import here to avoid circular import
    from . import user

    # Check for user flows first (admin can also be a participant)
    if context.user_data.get("registration_step"):
        await user.handle_registration_flow(update, context)
        return

    if context.user_data.get("wishlist_update_step"):
        await user.handle_wishlist_update(update, context)
        return

    # Check for admin-specific confirmation flows
    if context.user_data.get("awaiting_disband_confirmation"):
        await handle_disband_confirmation(update, context)
        return

    if context.user_data.get("awaiting_reset_confirmation"):
        await handle_reset_confirmation(update, context)
        return
