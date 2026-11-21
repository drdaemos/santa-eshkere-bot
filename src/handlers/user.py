"""Participant DM: /start (and the join button), /status, /wishlist, /leave, /cancel, free text.

Participants should never need to remember a command: their messages carry
buttons for the next step, and text sent outside any step is offered as a
new wishlist.
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..database.models import EventStatus, Participant
from ..database.session import session_scope
from ..formatting import Safe, join, render, truncate
from ..messages import Messages
from ..services import seasons, state
from ..services.assignment import ImpossibleDraw, NotEnoughParticipants
from ..services.join_post import participant_buttons, refresh_join_message
from ..services.notifications import deliver, reassignment_notices, send_dm, wishlist_text
from ..utils.auth import require_private_chat
from ..validation import ValidationError, callback, clean_wishlist
from . import registration

logger = logging.getLogger(__name__)

_DEEP_LINK_JOIN = re.compile(r"^join_(\d{1,18})$")

# Small talk is answered, not offered as a wishlist
_CHATTER = {"спасибо", "спс", "ок", "окей", "ok", "привет", "пока", "hi", "hello", "thanks", "круто", "супер", "ага", "понял", "поняла"}

Markup = InlineKeyboardMarkup | None


async def _reply(update: Update, text: str, markup: Markup = None) -> None:
    assert update.effective_message is not None
    await update.effective_message.reply_text(Safe(text), reply_markup=markup)


async def _send(bot: Bot, chat_id: int, text: str, markup: Markup = None) -> None:
    await bot.send_message(chat_id=chat_id, text=Safe(text), reply_markup=markup)


async def start_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start in DM: the join button (deep link), a pending step, or a greeting."""
    user = update.effective_user
    assert user is not None
    args = context.args or []
    match = _DEEP_LINK_JOIN.match(args[0]) if args else None
    async with session_scope() as s:
        if match:
            prompt = await registration.begin(s, context.bot, user, int(match.group(1)))
            resumed = False
        else:
            flow = await state.get_flow(s, user.id)
            prompt = await registration.resume_prompt(s, user, flow) if flow.name else None
            resumed = prompt is not None
    if prompt is None:
        await _reply(update, Messages.DM_GREETING)
        return
    if resumed:
        await _reply(update, Messages.RESUME_FLOW)
    await _reply(update, *prompt)


# --- /status --------------------------------------------------------------------


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
        await _reply(update, text, participant_buttons())
        return

    entries = []
    for index, m in enumerate(memberships, 1):
        status = (
            render(Messages.STATUS_ASSIGNED, receiver_name=m.receiver.real_name) if m.receiver else Safe(Messages.STATUS_PENDING)
        )
        entries.append(render(Messages.STATUS_GROUP_ENTRY, index=index, group_name=m.group.title, status=status))
    await _reply(update, render(Messages.STATUS_MULTIPLE_GROUPS, groups_status=join(entries, sep="\n\n")), participant_buttons())


# --- wishlist -------------------------------------------------------------------


async def _wishlist_edit_prompt(s: AsyncSession, telegram_id: int) -> Safe:
    memberships = await seasons.current_memberships(s, telegram_id)
    if not memberships:
        return Safe(Messages.ERROR_NOT_REGISTERED)
    await state.set_flow(s, telegram_id, state.EDIT_WISHLIST, participant_ids=[m.participant.id for m in memberships])
    current = truncate(memberships[0].participant.wishlist or Messages.EMPTY_WISHLIST, 2000)
    return render(Messages.SHOW_CURRENT_WISHLIST, wishlist=current)


@require_private_chat
async def wishlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        text = await _wishlist_edit_prompt(s, user.id)
    await _reply(update, text)


async def on_edit_wishlist_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        text = await _wishlist_edit_prompt(s, user.id)
    await query.answer()
    await _send(context.bot, user.id, text)


async def _save_wishlist(bot: Bot, telegram_id: int, participant_ids: list[int], wishlist: str) -> bool:
    """Store the wishlist on the given participations (only the user's own) and
    tell Santas who already have this person. Returns False if nothing matched."""
    async with session_scope() as s:
        await state.clear_flow(s, telegram_id)
        memberships = {m.participant.id: m for m in await seasons.current_memberships(s, telegram_id)}
        updated = [pid for pid in participant_ids if pid in memberships]  # never touch someone else's row
        for pid in updated:
            memberships[pid].participant.wishlist = wishlist
        santas = [
            (giver.telegram_id, memberships[receiver.id].group.title, receiver)
            for giver, receiver in await seasons.santas_of(s, updated)
            if memberships[receiver.id].event.status == EventStatus.DRAWN
        ]
    # Their Santa may already be shopping: tell them.
    for giver_telegram_id, group_title, receiver in santas:
        await send_dm(
            bot,
            giver_telegram_id,
            render(
                Messages.RECEIVER_WISHLIST_CHANGED,
                receiver_name=receiver.real_name,
                group_name=group_title,
                receiver_wishlist=wishlist_text(receiver),
            ),
        )
    return bool(updated)


async def _on_edit_wishlist_text(update: Update, context: ContextTypes.DEFAULT_TYPE, flow: state.Flow, raw: str) -> None:
    user = update.effective_user
    assert user is not None
    try:
        wishlist = clean_wishlist(raw)
    except ValidationError as e:
        await _reply(update, render(Messages.INVALID_INPUT, reason=str(e)))
        return
    ids = [int(i) for i in flow.data.get("participant_ids", [])]
    saved = await _save_wishlist(context.bot, user.id, ids, wishlist)
    await _reply(update, Messages.WISHLIST_UPDATED if saved else Messages.ERROR_NOT_REGISTERED)


async def _on_free_text(update: Update, raw: str) -> None:
    """Text outside any step. A registered person is probably sending a new
    wishlist: offer it (one tap) instead of replying with a command list."""
    user = update.effective_user
    assert user is not None
    if raw.strip().lower().strip("!.)") in _CHATTER:
        async with session_scope() as s:
            registered = bool(await seasons.current_memberships(s, user.id))
        await _reply(update, Messages.REGISTERED_HELP if registered else Messages.USER_HELP)
        return
    async with session_scope() as s:
        if not await seasons.current_memberships(s, user.id):
            reply = (Safe(Messages.USER_HELP), None)
        else:
            try:
                wishlist = clean_wishlist(raw)
            except ValidationError:
                reply = (Safe(Messages.REGISTERED_HELP), None)
            else:
                await state.set_flow(s, user.id, state.CONFIRM_WISHLIST, text=wishlist)
                markup = InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(Messages.CONFIRM_FREE_WISHLIST_YES, callback_data=callback("wy")),
                        InlineKeyboardButton(Messages.CONFIRM_FREE_WISHLIST_NO, callback_data=callback("cx")),
                    ]]
                )
                reply = (render(Messages.CONFIRM_FREE_WISHLIST, wishlist=truncate(wishlist, 2000)), markup)
    await _reply(update, *reply)


async def on_confirm_free_wishlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
        memberships = await seasons.current_memberships(s, user.id)
    if flow.name != state.CONFIRM_WISHLIST:
        await query.answer(Messages.STALE_BUTTON)
        return
    await query.answer()
    saved = await _save_wishlist(context.bot, user.id, [m.participant.id for m in memberships], str(flow.data["text"]))
    await query.edit_message_text(Safe(Messages.WISHLIST_UPDATED if saved else Messages.ERROR_NOT_REGISTERED))


@require_private_chat
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        cleared = await state.clear_flow(s, user.id)
    await _reply(update, Messages.CANCELLED if cleared else Messages.NOTHING_TO_CANCEL)


# --- text routing ---------------------------------------------------------------


async def dm_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free text in DM: feeds whichever step is pending."""
    user, message = update.effective_user, update.effective_message
    assert user is not None and message is not None and message.text is not None
    step: registration.Step | None = None
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
        if flow.name == state.REG_NAME:
            step = registration.Step(*await registration.on_name(s, update, flow, message.text))
        elif flow.name == state.REG_WISHLIST:
            step = await registration.on_wishlist(s, update, flow, message.text)
    if step is not None:
        await registration.send_step(context.bot, user.id, step)
    elif flow.name == state.EDIT_WISHLIST:
        await _on_edit_wishlist_text(update, context, flow, message.text)
    else:  # no step, or an unanswered "use this as wishlist?" (a new text replaces it)
        await _on_free_text(update, message.text)


async def dm_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stickers, photos, voice... in DM."""
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        flow = await state.get_flow(s, user.id)
    await _reply(update, Messages.NEED_TEXT if flow.name else Messages.USER_HELP)


# --- leaving --------------------------------------------------------------------


def _leave_confirm(group_title: str, drawn: bool, participant_id: int) -> tuple[Safe, InlineKeyboardMarkup]:
    text = render(Messages.LEAVE_CONFIRM, group_name=group_title, drawn_note=Messages.DRAWN_REPAIR_NOTE if drawn else "")
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(Messages.CONFIRM_YES_BUTTON, callback_data=callback("lv", participant_id)),
            InlineKeyboardButton(Messages.CONFIRM_NO_BUTTON, callback_data=callback("cx")),
        ]]
    )
    return text, markup


async def _leave_prompt(telegram_id: int) -> tuple[Safe, Markup]:
    async with session_scope() as s:
        memberships = await seasons.current_memberships(s, telegram_id)
    if not memberships:
        return Safe(Messages.ERROR_NOT_REGISTERED), None
    if len(memberships) == 1:
        m = memberships[0]
        return _leave_confirm(m.group.title, m.event.status == EventStatus.DRAWN, m.participant.id)
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(truncate(m.group.title, 60), callback_data=callback("lq", m.participant.id))] for m in memberships]
    )
    return Safe(Messages.LEAVE_PICK_GROUP), markup


@require_private_chat
async def leave_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    await _reply(update, *await _leave_prompt(user.id))


async def on_leave_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    await query.answer()
    await _send(context.bot, user.id, *await _leave_prompt(user.id))


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
        group_title, event_id = m.group.title, m.event.id
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
    logger.info("user_id=%s left event_id=%s (%s reassigned)", user.id, event_id, len(reassigned))
    await query.answer()
    await query.edit_message_text(render(Messages.LEFT_SEASON, group_name=group_title))
    await refresh_join_message(context.bot, event_id)
    await deliver(context.bot, notices)
