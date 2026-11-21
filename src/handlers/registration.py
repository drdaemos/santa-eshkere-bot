"""Registration flow: name -> wishlist.

Every step offers a one-tap answer where one exists (the Telegram name, last
season's name and wishlist), and the final message carries buttons for what
people do next, so nobody needs to remember a command.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update, User
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..database.models import Event, EventStatus, Group, Participant
from ..database.session import session_scope
from ..formatting import Safe, render, truncate
from ..messages import Messages
from ..services import seasons, state
from ..services.assignment import ImpossibleDraw
from ..services.join_post import participant_buttons, refresh_join_message
from ..services.notifications import Notice, deliver, reassignment_notices, wishlist_text
from ..utils.auth import is_group_member
from ..validation import ValidationError, callback, clean_name, clean_wishlist

logger = logging.getLogger(__name__)

Markup = InlineKeyboardMarkup | None


@dataclass
class Step:
    """What to send for a registration step, once the session is committed."""

    text: Safe
    markup: Markup = None
    notices: list[Notice] = field(default_factory=list)
    joined_event_id: int | None = None  # someone joined: refresh that season's join post


async def send_step(bot: Bot, chat_id: int, step: Step) -> None:
    await bot.send_message(chat_id=chat_id, text=step.text, reply_markup=step.markup)
    await deliver(bot, step.notices)
    if step.joined_event_id is not None:
        await refresh_join_message(bot, step.joined_event_id)


def telegram_name(user: User) -> str | None:
    """The user's Telegram name if it is acceptable as a Santa-facing name."""
    try:
        return clean_name(user.full_name)
    except ValidationError:
        return None


async def name_prompt(s: AsyncSession, group: Group, event: Event, user: User) -> tuple[Safe, Markup]:
    text = render(Messages.ASK_NAME, group_name=group.title)
    if event.status == EventStatus.DRAWN:
        text = Safe(text + Messages.LATE_JOIN_NOTE)
    rows = []
    previous = await seasons.previous_participation(s, group.id, user.id, event.id)
    if previous is not None:
        label = Messages.REUSE_NAME_BUTTON.format(name=previous.real_name)
        rows.append([InlineKeyboardButton(truncate(label, 60), callback_data=callback("rn", event.id))])
    from_telegram = telegram_name(user)
    if from_telegram and (previous is None or from_telegram != previous.real_name):
        label = Messages.TELEGRAM_NAME_BUTTON.format(name=from_telegram)
        rows.append([InlineKeyboardButton(truncate(label, 60), callback_data=callback("tn", event.id))])
    if not rows:
        return text, None
    return Safe(text + Messages.ASK_NAME_BUTTONS_HINT), InlineKeyboardMarkup(rows)


async def wishlist_prompt(s: AsyncSession, event: Event, telegram_id: int) -> tuple[Safe, Markup]:
    text = Messages.ASK_WISHLIST
    previous = await seasons.previous_participation(s, event.group_id, telegram_id, event.id)
    if previous is None or not previous.wishlist:
        return Safe(text), None
    hint = render(Messages.ASK_WISHLIST_REUSE_HINT, wishlist=truncate(previous.wishlist, 600))
    button = InlineKeyboardButton(Messages.REUSE_WISHLIST_BUTTON, callback_data=callback("rw", event.id))
    return Safe(text + hint), InlineKeyboardMarkup([[button]])


def already_in(group: Group, participant: Participant) -> tuple[Safe, Markup]:
    text = render(
        Messages.ALREADY_IN, group_name=group.title, name=participant.real_name, wishlist=wishlist_text(participant)
    )
    return text, participant_buttons()


async def _joinable_event(s: AsyncSession, event_id: int) -> tuple[Event | None, str | None]:
    """(event, None) if registration into event_id may proceed, else (None, error message).

    A drawn season is joinable too: the newcomer is spliced into the chain."""
    event = await seasons.get_event(s, event_id)
    if event is None or event.status == EventStatus.CLOSED or not event.group.is_active:
        return None, Messages.NO_SEASON
    return event, None


async def begin(s: AsyncSession, bot: Bot, user: User, event_id: int) -> tuple[Safe, Markup]:
    """Start registration from the join button (deep link); returns the first prompt.

    The link can be forwarded anywhere, so membership of the group is checked
    here; /join in the group needs no check."""
    event, error = await _joinable_event(s, event_id)
    if event is None:
        await state.clear_flow(s, user.id)
        return Safe(error or Messages.ERROR_SYSTEM), None
    existing = await seasons.find_participant(s, event.id, user.id)
    if existing is not None:
        await state.clear_flow(s, user.id)
        return already_in(event.group, existing)
    if not await is_group_member(bot, event.group.telegram_chat_id, user.id):
        return render(Messages.JOIN_NOT_A_MEMBER, group_name=event.group.title), None
    await state.set_flow(s, user.id, state.REG_NAME, event_id=event.id)
    return await name_prompt(s, event.group, event, user)


async def resume_prompt(s: AsyncSession, user: User, flow: state.Flow) -> tuple[Safe, Markup] | None:
    """Re-send the prompt for a pending registration step (after /start)."""
    event, _ = await _joinable_event(s, int(flow.data.get("event_id", 0)))
    if event is None:
        return None
    if flow.name == state.REG_NAME:
        return await name_prompt(s, event.group, event, user)
    if flow.name == state.REG_WISHLIST:
        return await wishlist_prompt(s, event, user.id)
    return None


async def on_name(s: AsyncSession, update: Update, flow: state.Flow, raw: str) -> tuple[Safe, Markup]:
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


async def on_wishlist(s: AsyncSession, update: Update, flow: state.Flow, raw: str) -> Step:
    try:
        wishlist = clean_wishlist(raw)
    except ValidationError as e:
        return Step(render(Messages.INVALID_INPUT, reason=str(e)))
    return await _complete(s, update, flow, wishlist)


async def _complete(s: AsyncSession, update: Update, flow: state.Flow, wishlist: str) -> Step:
    user = update.effective_user
    assert user is not None
    event, error = await _joinable_event(s, int(flow.data["event_id"]))
    await state.clear_flow(s, user.id)
    if event is None:
        return Step(Safe(error or Messages.ERROR_SYSTEM))
    await seasons.lock_event(s, event)
    existing = await seasons.find_participant(s, event.id, user.id)
    if existing is not None:
        return Step(*already_in(event.group, existing))
    name = str(flow.data["name"])
    participant = await seasons.add_participant(s, event, user.id, user.username, name, wishlist)
    if event.status != EventStatus.DRAWN:
        logger.info("Registered user_id=%s in event_id=%s", user.id, event.id)
        text = render(Messages.REGISTRATION_COMPLETE, name=name, wishlist=wishlist)
        return Step(text, participant_buttons(), joined_event_id=event.id)

    try:
        reassigned = await seasons.splice_late_participant(s, event, participant)
    except ImpossibleDraw:
        await s.delete(participant)
        await s.flush()
        return Step(Safe(Messages.LATE_JOIN_IMPOSSIBLE))
    logger.info("Late registration user_id=%s spliced into event_id=%s", user.id, event.id)
    notices = reassignment_notices(reassigned, event.group, newcomer_id=participant.id)
    # the newcomer's own assignment arrives right after the confirmation
    notices.sort(key=lambda n: n.telegram_id != user.id)
    text = render(Messages.REGISTRATION_COMPLETE_LATE, name=name, wishlist=wishlist)
    return Step(text, participant_buttons(), notices, joined_event_id=event.id)


async def reuse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str, event_id: int) -> None:
    """One-tap answers: rn = last season's name, tn = Telegram name, rw = last season's wishlist."""
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    expected_flow = state.REG_WISHLIST if kind == "rw" else state.REG_NAME
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
        if flow.name != expected_flow or int(flow.data.get("event_id", 0)) != event_id:
            await query.answer(Messages.STALE_BUTTON)
            return
        if kind == "tn":
            name = telegram_name(user)
            if name is None:
                await query.answer(Messages.STALE_BUTTON)
                return
            step = Step(*await on_name(s, update, flow, name))
        else:
            event = await seasons.get_event(s, event_id)
            previous = await seasons.previous_participation(s, event.group_id, user.id, event_id) if event else None
            if previous is None:
                await query.answer(Messages.STALE_BUTTON)
                return
            if kind == "rn":
                step = Step(*await on_name(s, update, flow, previous.real_name))
            else:
                step = await on_wishlist(s, update, flow, previous.wishlist)
    await query.answer()
    await _drop_buttons(update)
    await send_step(context.bot, user.id, step)


async def _drop_buttons(update: Update) -> None:
    """Remove the buttons from the prompt just answered, so it can't be tapped twice."""
    query = update.callback_query
    assert query is not None
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass
