"""Participant DM commands and text routing: /start, /status, /wishlist, /leave, /cancel"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..database.models import EventStatus, Participant
from ..database.session import session_scope
from ..formatting import Safe, join, render, truncate
from ..messages import Messages
from ..services import seasons, state
from ..services.assignment import ImpossibleDraw, NotEnoughParticipants
from ..services.notifications import Notice, deliver, post, reassignment_notices, send_dm, wishlist_text
from ..utils.auth import require_private_chat
from ..validation import ValidationError, callback, clean_wishlist
from . import registration

logger = logging.getLogger(__name__)

_DEEP_LINK_JOIN = re.compile(r"^join_(\d{1,18})$")


async def _reply(update: Update, text: str, markup: object = None) -> None:
    assert update.effective_message is not None
    await update.effective_message.reply_text(Safe(text), reply_markup=markup)  # type: ignore[arg-type]


async def start_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start in DM: plain greeting, deep link from /join, or resume a pending step."""
    user = update.effective_user
    assert user is not None
    args = context.args or []
    async with session_scope() as s:
        match = _DEEP_LINK_JOIN.match(args[0]) if args else None
        if match:
            text, markup = await registration.begin(s, user.id, int(match.group(1)))
            await _reply(update, text, markup)
            return
        flow = await state.get_flow(s, user.id)
        prompt = await registration.resume_prompt(s, user.id, flow) if flow.name else None
    if prompt is not None:
        await _reply(update, Messages.RESUME_FLOW)
        await _reply(update, *prompt)
    else:
        await _reply(update, Messages.DM_GREETING)


@require_private_chat
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        memberships = await seasons.current_memberships(s, user.id)
    if not memberships:
        await _reply(update, Messages.ERROR_NOT_REGISTERED)
        return

    if len(memberships) == 1:
        m = memberships[0]
        if m.receiver is not None:
            text = render(
                Messages.STATUS_AFTER_ASSIGNMENT,
                group_name=m.group.title,
                receiver_name=m.receiver.real_name,
                receiver_wishlist=wishlist_text(m.receiver),
            )
        else:
            text = render(
                Messages.STATUS_BEFORE_ASSIGNMENT,
                group_name=m.group.title,
                name=m.participant.real_name,
                wishlist=wishlist_text(m.participant),
            )
        await _reply(update, text)
        return

    entries = []
    for index, m in enumerate(memberships, 1):
        status = (
            render(Messages.STATUS_ASSIGNED, receiver_name=m.receiver.real_name) if m.receiver else Safe(Messages.STATUS_PENDING)
        )
        entries.append(render(Messages.STATUS_GROUP_ENTRY, index=index, group_name=m.group.title, status=status))
    await _reply(update, render(Messages.STATUS_MULTIPLE_GROUPS, groups_status=join(entries, sep="\n\n")))


@require_private_chat
async def wishlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        memberships = await seasons.current_memberships(s, user.id)
        if not memberships:
            await _reply(update, Messages.ERROR_NOT_REGISTERED)
            return
        await state.set_flow(s, user.id, state.EDIT_WISHLIST, participant_ids=[m.participant.id for m in memberships])
    current = truncate(memberships[0].participant.wishlist or Messages.EMPTY_WISHLIST, 2000)
    await _reply(update, render(Messages.SHOW_CURRENT_WISHLIST, wishlist=current))


@require_private_chat
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        cleared = await state.clear_flow(s, user.id)
    await _reply(update, Messages.CANCELLED if cleared else Messages.NOTHING_TO_CANCEL)


async def _update_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE, flow: state.Flow, raw: str) -> None:
    user = update.effective_user
    assert user is not None
    try:
        wishlist = clean_wishlist(raw)
    except ValidationError as e:
        await _reply(update, render(Messages.INVALID_INPUT, reason=str(e)))
        return

    async with session_scope() as s:
        await state.clear_flow(s, user.id)
        ids = [int(i) for i in flow.data.get("participant_ids", [])]
        memberships = {m.participant.id: m for m in await seasons.current_memberships(s, user.id)}
        updated = [pid for pid in ids if pid in memberships]  # never touch someone else's row
        for pid in updated:
            memberships[pid].participant.wishlist = wishlist
        santas = [
            (giver.telegram_id, memberships[receiver.id].group.title, receiver)
            for giver, receiver in await seasons.santas_of(s, updated)
            if memberships[receiver.id].event.status == EventStatus.DRAWN
        ]
    await _reply(update, Messages.WISHLIST_UPDATED if updated else Messages.ERROR_NOT_REGISTERED)

    # Their Santa may already be shopping: tell them.
    for giver_telegram_id, group_title, receiver in santas:
        await send_dm(
            context.bot,
            giver_telegram_id,
            render(
                Messages.RECEIVER_WISHLIST_CHANGED,
                receiver_name=receiver.real_name,
                group_name=group_title,
                receiver_wishlist=wishlist_text(receiver),
            ),
        )


async def dm_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free text in DM: feeds whichever flow is pending."""
    user, message = update.effective_user, update.effective_message
    assert user is not None and message is not None and message.text is not None
    notices: list[Notice] = []
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
        if flow.name == state.REG_NAME:
            reply = await registration.on_name(s, update, flow, message.text)
        elif flow.name == state.REG_WISHLIST:
            text, notices = await registration.on_wishlist(s, update, flow, message.text)
            reply = (text, None)
        else:
            reply = None
    if reply is not None:
        await _reply(update, *reply)
        await deliver(context.bot, notices)
    elif flow.name == state.EDIT_WISHLIST:
        await _update_wishlist(update, context, flow, message.text)
    else:
        await _reply(update, Messages.USER_HELP)


async def dm_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stickers, photos, voice... in DM."""
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
    await _reply(update, Messages.NEED_TEXT if flow.name else Messages.USER_HELP)


# --- /leave -------------------------------------------------------------------


def _leave_confirm(group_title: str, drawn: bool, participant_id: int) -> tuple[Safe, InlineKeyboardMarkup]:
    text = render(Messages.LEAVE_CONFIRM, group_name=group_title, drawn_note=Messages.DRAWN_REPAIR_NOTE if drawn else "")
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(Messages.CONFIRM_YES_BUTTON, callback_data=callback("lv", participant_id)),
            InlineKeyboardButton(Messages.CONFIRM_NO_BUTTON, callback_data=callback("cx")),
        ]]
    )
    return text, markup


@require_private_chat
async def leave_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        memberships = await seasons.current_memberships(s, user.id)
    if not memberships:
        await _reply(update, Messages.ERROR_NOT_REGISTERED)
        return
    if len(memberships) == 1:
        m = memberships[0]
        await _reply(update, *_leave_confirm(m.group.title, m.event.status == EventStatus.DRAWN, m.participant.id))
        return
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(truncate(m.group.title, 60), callback_data=callback("lq", m.participant.id))] for m in memberships]
    )
    await _reply(update, Messages.LEAVE_PICK_GROUP, markup)


async def _own_membership(s: AsyncSession, update: Update, participant_id: int) -> seasons.Membership | None:
    """The clicking user's membership behind a button, or None (answers the query)."""
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    membership = next((m for m in await seasons.current_memberships(s, user.id) if m.participant.id == participant_id), None)
    if membership is None:  # someone else's participant id, or the season is over
        await query.answer(Messages.STALE_BUTTON, show_alert=True)
    return membership


async def on_leave_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, participant_id: int) -> None:
    query = update.callback_query
    assert query is not None
    async with session_scope() as s:
        m = await _own_membership(s, update, participant_id)
        if m is None:
            return
        text, markup = _leave_confirm(m.group.title, m.event.status == EventStatus.DRAWN, m.participant.id)
    await query.answer()
    await query.edit_message_text(text, reply_markup=markup)


async def on_leave_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, participant_id: int) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        m = await _own_membership(s, update, participant_id)
        if m is None:
            return
        participant: Participant = m.participant
        name, group_title, chat_id = participant.real_name, m.group.title, m.group.telegram_chat_id
        try:
            reassigned = await seasons.remove_participant(s, m.event, participant)
        except NotEnoughParticipants:
            await query.answer()
            await query.edit_message_text(Safe(Messages.REPAIR_TOO_FEW))
            return
        except ImpossibleDraw:
            await query.answer()
            await query.edit_message_text(Safe(Messages.REPAIR_IMPOSSIBLE))
            return
        notices = reassignment_notices(reassigned, m.group)
    logger.info("user_id=%s left event_id=%s (%s reassigned)", user.id, m.event.id, len(reassigned))
    await query.answer()
    await query.edit_message_text(render(Messages.LEFT_SEASON, group_name=group_title))
    notice = Messages.PARTICIPANT_LEFT_REPAIRED if reassigned else Messages.PARTICIPANT_LEFT
    await post(context.bot, chat_id, render(notice, name=name))
    await deliver(context.bot, notices)
