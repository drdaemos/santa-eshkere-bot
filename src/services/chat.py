"""Anonymous messages between a Santa and the person they give to.

Every message goes through the bot, one message per tap: "✉️ Написать…"
starts a draft, the next text is relayed, and the relayed message carries a
"↩️ Ответить" button. The receiver never learns who their Santa is: the bot
copies only the text and signs it "Тайный Санта".

Both directions hang off one assignment (giver -> receiver); who is writing
follows from which side of it the tapping user is on. Repairs and resets
replace assignment rows, so buttons of a pairing that no longer exists stop
working by themselves.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telegram import InlineKeyboardButton

from ..database.models import Assignment, Event, EventStatus, Participant
from ..formatting import truncate
from ..messages import Messages
from ..validation import callback

TO_RECEIVER = "to_receiver"
TO_SANTA = "to_santa"


@dataclass
class Pairing:
    """One side of an assignment, from the point of view of the user writing."""

    assignment_id: int
    direction: str  # TO_RECEIVER (the Santa writes) or TO_SANTA (the receiver writes)
    sender: Participant
    recipient: Participant
    group_title: str


async def pairing(s: AsyncSession, assignment_id: int, telegram_id: int) -> Pairing | None:
    """The pairing behind a button, if it still exists, its season is running
    and `telegram_id` is one of the two people in it."""
    assignment = await s.get(
        Assignment,
        assignment_id,
        options=[
            selectinload(Assignment.giver),
            selectinload(Assignment.receiver),
            selectinload(Assignment.event).selectinload(Event.group),
        ],
    )
    if assignment is None:
        return None
    event = assignment.event
    if event.status != EventStatus.DRAWN or not event.group.is_active:
        return None
    if assignment.giver.telegram_id == telegram_id:
        return Pairing(assignment.id, TO_RECEIVER, assignment.giver, assignment.receiver, event.group.title)
    if assignment.receiver.telegram_id == telegram_id:
        return Pairing(assignment.id, TO_SANTA, assignment.receiver, assignment.giver, event.group.title)
    return None


def chat_rows(
    to_receiver: int | None, to_santa: int | None, group_title: str | None = None
) -> list[list[InlineKeyboardButton]]:
    """Buttons to write to one's receiver (own assignment id) and to one's
    Santa (the assignment where one is the receiver). With a group title the
    labels say which group (for people in several)."""
    rows = []
    if to_receiver is not None:
        label = (
            Messages.CHAT_TO_RECEIVER_IN_GROUP_BUTTON.format(group_name=group_title)
            if group_title
            else Messages.CHAT_TO_RECEIVER_BUTTON
        )
        rows.append([InlineKeyboardButton(truncate(label, 60), callback_data=callback("ms", to_receiver))])
    if to_santa is not None:
        label = (
            Messages.CHAT_TO_SANTA_IN_GROUP_BUTTON.format(group_name=group_title) if group_title else Messages.CHAT_TO_SANTA_BUTTON
        )
        rows.append([InlineKeyboardButton(truncate(label, 60), callback_data=callback("ms", to_santa))])
    return rows
