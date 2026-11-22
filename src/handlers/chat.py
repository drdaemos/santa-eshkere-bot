"""Anonymous Santa <-> receiver messages: the buttons and the relay.

See services/chat.py for the model. Everything is re-checked when the text
arrives, not only when the button was tapped: the pairing may have changed
in between (someone left, the draw was reset).
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..database.session import session_scope
from ..formatting import Safe, render, truncate
from ..messages import Messages
from ..services import chat, state
from ..services.notifications import send_dm
from ..validation import ValidationError, callback, clean_chat_message

logger = logging.getLogger(__name__)


def _reply_markup(assignment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(Messages.CHAT_REPLY_BUTTON, callback_data=callback("ms", assignment_id))]])


async def on_compose(update: Update, context: ContextTypes.DEFAULT_TYPE, assignment_id: int) -> None:
    """"✉️ Написать…" / "↩️ Ответить": the next text goes to the other side."""
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        pair = await chat.pairing(s, assignment_id, user.id)
        if pair is None:
            await query.answer(Messages.CHAT_STALE, show_alert=True)
            return
        await state.set_flow(s, user.id, state.CHAT_COMPOSE, assignment_id=pair.assignment_id)
        if pair.direction == chat.TO_RECEIVER:
            text = render(Messages.CHAT_COMPOSE_TO_RECEIVER, name=truncate(pair.recipient.real_name, 64), group_name=pair.group_title)
        else:
            text = render(Messages.CHAT_COMPOSE_TO_SANTA, group_name=pair.group_title)
    await query.answer()
    cancel = InlineKeyboardMarkup([[InlineKeyboardButton(Messages.CANCEL_BUTTON, callback_data=callback("mx"))]])
    await context.bot.send_message(chat_id=user.id, text=text, reply_markup=cancel)


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        if (await state.get_flow(s, user.id)).name == state.CHAT_COMPOSE:
            await state.clear_flow(s, user.id)
    await query.answer()
    await query.edit_message_text(Safe(Messages.CANCELLED))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE, flow: state.Flow, raw: str) -> None:
    """The draft's text: relay it, signed only "Тайный Санта" or with the receiver's name."""
    user, message = update.effective_user, update.effective_message
    assert user is not None and message is not None
    try:
        text = clean_chat_message(raw)
    except ValidationError as e:
        await message.reply_text(render(Messages.INVALID_INPUT, reason=str(e)))  # the draft stays open
        return
    async with session_scope() as s:
        await state.clear_flow(s, user.id)  # one message per tap: nothing else gets relayed by accident
        pair = await chat.pairing(s, int(flow.data.get("assignment_id", 0)), user.id)
        if pair is None:
            relay = None
        elif pair.direction == chat.TO_RECEIVER:
            relay = render(Messages.CHAT_FROM_SANTA, group_name=pair.group_title, text=text)
        else:
            relay = render(Messages.CHAT_FROM_RECEIVER, name=truncate(pair.sender.real_name, 64), group_name=pair.group_title, text=text)
    if pair is None or relay is None:
        await message.reply_text(Safe(Messages.CHAT_STALE))
        return
    delivered = await send_dm(context.bot, pair.recipient.telegram_id, relay, _reply_markup(pair.assignment_id))
    # only the assignment id: names, user ids and the text stay out of the logs
    logger.info("Relayed an anonymous message within assignment_id=%s (%s)", pair.assignment_id, "ok" if delivered else "failed")
    await message.reply_text(Safe(Messages.CHAT_SENT if delivered else Messages.CHAT_NOT_DELIVERED))
