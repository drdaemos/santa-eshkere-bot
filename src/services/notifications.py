"""Notification services for sending DMs"""

import logging
from typing import Dict

from telegram import Bot
from telegram.error import TelegramError

from ..database.models import User
from ..messages import Messages

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending notifications to users"""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_assignment_notification(
        self,
        giver: User,
        receiver: User,
        group_name: str = "Неизвестная группа"
    ) -> bool:
        """
        Send assignment notification to a giver.

        Args:
            giver: User who will give the gift
            receiver: User who will receive the gift
            group_name: Name of the group for this assignment

        Returns:
            True if message was sent successfully, False otherwise
        """
        try:
            message = Messages.ASSIGNMENT_NOTIFICATION.format(
                group_name=group_name,
                receiver_name=receiver.real_name,
                receiver_wishlist=receiver.wishlist or "Не указан"
            )

            await self.bot.send_message(
                chat_id=giver.telegram_id,
                text=message,
                parse_mode="Markdown"
            )

            return True

        except TelegramError as e:
            logger.error(
                f"Failed to send assignment to user {giver.telegram_id}: {e}",
                exc_info=True
            )
            return False

    async def send_bulk_assignments(
        self,
        assignments: Dict[User, User],
        group_name: str = "Неизвестная группа"
    ) -> Dict[int, bool]:
        """
        Send assignments to multiple users.

        Args:
            assignments: Dict mapping giver User to receiver User
            group_name: Name of the group for these assignments

        Returns:
            Dict mapping giver telegram_id to success status
        """
        results = {}

        for giver, receiver in assignments.items():
            success = await self.send_assignment_notification(giver, receiver, group_name)
            results[giver.telegram_id] = success

        return results
