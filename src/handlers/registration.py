"""Registration flow: name -> wishlist, with one-tap reuse of last season's answers"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..database.models import Event, EventStatus, Group
from ..database.session import session_scope
from ..formatting import Safe, render, truncate
from ..messages import Messages
from ..services import seasons, state
from ..services.assignment import ImpossibleDraw
from ..services.notifications import Notice, deliver, reassignment_notices
from ..validation import ValidationError, callback, clean_name, clean_wishlist

logger = logging.getLogger(__name__)


def _button(text: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(truncate(text, 60), callback_data=data)]])


async def name_prompt(s: AsyncSession, group: Group, event: Event, telegram_id: int) -> tuple[Safe, InlineKeyboardMarkup | None]:
    text = render(Messages.ASK_NAME, group_name=group.title)
    if event.status == EventStatus.DRAWN:
        text = Safe(text + Messages.LATE_JOIN_NOTE)
    previous = await seasons.previous_participation(s, group.id, telegram_id, event.id)
    if previous is None:
        return text, None
    return Safe(text + Messages.ASK_NAME_REUSE_HINT), _button(
        Messages.REUSE_NAME_BUTTON.format(name=previous.real_name), callback("rn", event.id)
    )


async def wishlist_prompt(s: AsyncSession, event: Event, telegram_id: int) -> tuple[Safe, InlineKeyboardMarkup | None]:
    text = Messages.ASK_WISHLIST
    previous = await seasons.previous_participation(s, event.group_id, telegram_id, event.id)
    if previous is None or not previous.wishlist:
        return Safe(text), None
    hint = render(Messages.ASK_WISHLIST_REUSE_HINT, wishlist=truncate(previous.wishlist, 600))
    return Safe(text + hint), _button(Messages.REUSE_WISHLIST_BUTTON, callback("rw", event.id))


async def _joinable_event(s: AsyncSession, event_id: int) -> tuple[Event | None, str | None]:
    """(event, None) if registration into event_id may proceed, else (None, error message).

    A drawn season is joinable too: the newcomer is spliced into the chain."""
    event = await seasons.get_event(s, event_id)
    if event is None or event.status == EventStatus.CLOSED or not event.group.is_active:
        return None, Messages.NO_SEASON
    return event, None


async def begin(s: AsyncSession, telegram_id: int, event_id: int) -> tuple[Safe, InlineKeyboardMarkup | None]:
    """Start (or restart) registration into an event; returns the first prompt."""
    event, error = await _joinable_event(s, event_id)
    if event is None:
        await state.clear_flow(s, telegram_id)
        return Safe(error or Messages.ERROR_SYSTEM), None
    if await seasons.find_participant(s, event.id, telegram_id) is not None:
        await state.clear_flow(s, telegram_id)
        return Safe(Messages.ERROR_ALREADY_REGISTERED), None
    await state.set_flow(s, telegram_id, state.REG_NAME, event_id=event.id)
    return await name_prompt(s, event.group, event, telegram_id)


async def resume_prompt(s: AsyncSession, telegram_id: int, flow: state.Flow) -> tuple[Safe, InlineKeyboardMarkup | None] | None:
    """Re-send the prompt for a pending registration step (after /start)."""
    event, _ = await _joinable_event(s, int(flow.data.get("event_id", 0)))
    if event is None:
        return None
    if flow.name == state.REG_NAME:
        return await name_prompt(s, event.group, event, telegram_id)
    if flow.name == state.REG_WISHLIST:
        return await wishlist_prompt(s, event, telegram_id)
    return None


async def on_name(s: AsyncSession, update: Update, flow: state.Flow, raw: str) -> tuple[Safe, InlineKeyboardMarkup | None]:
    assert update.effective_user is not None
    telegram_id = update.effective_user.id
    try:
        name = clean_name(raw)
    except ValidationError as e:
        return render(Messages.INVALID_INPUT, reason=str(e)), None
    event, error = await _joinable_event(s, int(flow.data["event_id"]))
    if event is None:
        await state.clear_flow(s, telegram_id)
        return Safe(error or Messages.ERROR_SYSTEM), None
    await state.set_flow(s, telegram_id, state.REG_WISHLIST, event_id=event.id, name=name)
    return await wishlist_prompt(s, event, telegram_id)


async def on_wishlist(s: AsyncSession, update: Update, flow: state.Flow, raw: str) -> tuple[Safe, list[Notice]]:
    """Returns the reply and DMs to send once the session is committed."""
    try:
        wishlist = clean_wishlist(raw)
    except ValidationError as e:
        return render(Messages.INVALID_INPUT, reason=str(e)), []
    return await _complete(s, update, flow, wishlist)


async def _complete(s: AsyncSession, update: Update, flow: state.Flow, wishlist: str) -> tuple[Safe, list[Notice]]:
    user = update.effective_user
    assert user is not None
    event, error = await _joinable_event(s, int(flow.data["event_id"]))
    await state.clear_flow(s, user.id)
    if event is None:
        return Safe(error or Messages.ERROR_SYSTEM), []
    await seasons.lock_event(s, event)
    if await seasons.find_participant(s, event.id, user.id) is not None:
        return Safe(Messages.ERROR_ALREADY_REGISTERED), []
    name = str(flow.data["name"])
    participant = await seasons.add_participant(s, event, user.id, user.username, name, wishlist)
    if event.status != EventStatus.DRAWN:
        logger.info("Registered user_id=%s in event_id=%s", user.id, event.id)
        return render(Messages.REGISTRATION_COMPLETE, name=name, wishlist=wishlist), []

    try:
        reassigned = await seasons.splice_late_participant(s, event, participant)
    except ImpossibleDraw:
        await s.delete(participant)
        await s.flush()
        return Safe(Messages.LATE_JOIN_IMPOSSIBLE), []
    logger.info("Late registration user_id=%s spliced into event_id=%s", user.id, event.id)
    notices = reassignment_notices(reassigned, event.group, newcomer_id=participant.id)
    # the newcomer's own assignment arrives right after the confirmation
    notices.sort(key=lambda n: n.telegram_id != user.id)
    return render(Messages.REGISTRATION_COMPLETE_LATE, name=name, wishlist=wishlist), notices


async def reuse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, event_id: int) -> None:
    """'Как в прошлый раз' buttons (rn = name, rw = wishlist)."""
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    expected_flow = state.REG_NAME if kind == "rn" else state.REG_WISHLIST
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
        if flow.name != expected_flow or int(flow.data.get("event_id", 0)) != event_id:
            await query.answer(Messages.STALE_BUTTON)
            return
        event = await seasons.get_event(s, event_id)
        previous = await seasons.previous_participation(s, event.group_id, user.id, event_id) if event else None
        if previous is None:
            await query.answer(Messages.STALE_BUTTON)
            return
        await query.answer()
        notices: list[Notice] = []
        if kind == "rn":
            text, markup = await on_name(s, update, flow, previous.real_name)
        else:
            (text, notices), markup = await on_wishlist(s, update, flow, previous.wishlist), None
    await context.bot.send_message(chat_id=user.id, text=text, reply_markup=markup)
    await deliver(context.bot, notices)
