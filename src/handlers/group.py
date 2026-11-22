"""Group chat: /start, /join, /kickitoff (and the confirmed draw), /newseason,
the greeting when the bot is added, chat migration"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from ..database.models import EventStatus
from ..database.session import session_scope
from ..formatting import Safe, join, render, truncate
from ..messages import Messages
from ..services import seasons, state
from ..services.assignment import ImpossibleDraw, NotEnoughParticipants
from ..services.join_post import join_link, post_join_message, refresh_join_message
from ..services.notifications import assignment_text, post, send_dm
from ..utils.auth import is_group_admin, require_group_chat
from ..validation import CONFIRM_CODES, callback
from .registration import already_in, name_prompt

logger = logging.getLogger(__name__)


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    assert update.effective_message is not None
    await update.effective_message.reply_text(Safe(text), reply_markup=markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate the bot in this group (opening a season if there is none) and
    post the join post. Sent again, it re-posts the join post at the bottom."""
    chat = update.effective_chat
    if chat is None or not await is_group_admin(update, context):
        await _reply(update, Messages.ERROR_ADMIN_ONLY)
        return
    async with session_scope() as s:
        _, event = await seasons.activate_group(s, chat.id, chat.title or "")
        event_id = event.id
    logger.info("Group activated chat_id=%s", chat.id)
    await post_join_message(context.bot, event_id)


@require_group_chat
async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    if chat is None or user is None or user.is_bot:
        return
    async with session_scope() as s:
        group = await seasons.group_by_chat(s, chat.id)
        if group is None:
            await _reply(update, Messages.ERROR_GROUP_NOT_FOUND)
            return
        if not group.is_active:
            await _reply(update, Messages.ERROR_GROUP_INACTIVE)
            return
        event = await seasons.current_event(s, group.id)
        if event is None:
            await _reply(update, Messages.NO_SEASON)
            return
        existing = await seasons.find_participant(s, event.id, user.id)
        if existing is not None:
            text, markup = already_in(group, existing)
        else:
            await state.set_flow(s, user.id, state.REG_NAME, event_id=event.id, tg_name=truncate(user.full_name, 40))
            text, markup = await name_prompt(s, group, event, user)
        event_id = event.id

    # Everything happens in DM; the group only hears from the bot when the DM
    # is impossible.
    try:
        await context.bot.send_message(chat_id=user.id, text=text, reply_markup=markup)
    except Forbidden:
        # The user never opened a DM with the bot (or blocked it). The deep
        # link opens it and resumes registration via /start join_<event_id>.
        button = InlineKeyboardMarkup(
            [[InlineKeyboardButton(Messages.JOIN_DM_BUTTON, url=join_link(context.bot.username, event_id))]]
        )
        await _reply(update, render(Messages.JOIN_DM_FAILED, name=user.first_name), button)
    except TelegramError:
        logger.exception("Could not send registration DM to user_id=%s", user.id)
        await _reply(update, Messages.ERROR_SYSTEM)


@require_group_chat
async def kickitoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask before drawing: once people read their assignments it can't be taken back."""
    chat = update.effective_chat
    assert chat is not None
    if not await is_group_admin(update, context):
        await _reply(update, Messages.ERROR_ADMIN_ONLY)
        return

    async with session_scope() as s:
        group = await seasons.group_by_chat(s, chat.id)
        if group is None or not group.is_active:
            await _reply(update, Messages.ERROR_GROUP_NOT_FOUND)
            return
        event = await seasons.current_event(s, group.id)
        if event is None:
            await _reply(update, Messages.NO_SEASON)
            return
        if event.status == EventStatus.DRAWN:
            await _reply(update, Messages.DRAW_ALREADY_DONE)
            return
        try:
            pairs, _ = await seasons.plan_draw(s, event)  # fail now, not after the confirmation
        except NotEnoughParticipants:
            await _reply(update, Messages.ERROR_NOT_ENOUGH_PARTICIPANTS)
            return
        except ImpossibleDraw:
            await _reply(update, Messages.ERROR_ASSIGNMENT_IMPOSSIBLE)
            return
        unfinished = await unfinished_names(s, event.id)
        group_id = group.id

    note = render(Messages.DRAW_UNFINISHED, names=join(unfinished, sep=", ")) if unfinished else ""
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(Messages.DRAW_START_BUTTON, callback_data=callback("cf", CONFIRM_CODES["draw"], group_id)),
            InlineKeyboardButton(Messages.CONFIRM_NO_BUTTON, callback_data=callback("cx")),
        ]]
    )
    await _reply(update, render(Messages.DRAW_CONFIRM, count=len(pairs), unfinished=Safe(note)), markup)


async def unfinished_names(s: AsyncSession, event_id: int) -> list[str]:
    """Names of people who started registering for the event but haven't finished."""
    pending = await state.unfinished_registrations(s, event_id)
    joined = {p.telegram_id for p in await seasons.participants(s, event_id)}
    return sorted(truncate(name, 40) for telegram_id, name in pending.items() if telegram_id not in joined)


async def run_draw(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: int) -> None:
    """The draw itself, after an admin confirmed it (admin rights already re-checked)."""
    query = update.callback_query
    assert query is not None
    async with session_scope() as s:
        group = await seasons.get_group(s, group_id)
        event = await seasons.current_event(s, group.id) if group is not None and group.is_active else None
        if group is None or event is None:
            await query.answer(Messages.STALE_BUTTON, show_alert=True)
            return
        await seasons.lock_event(s, event)  # two admins tapping at once draw once
        if event.status == EventStatus.DRAWN:
            await query.answer(Messages.DRAW_STALE, show_alert=True)
            return
        try:
            rows = await seasons.draw(s, event)
        except NotEnoughParticipants:
            await query.answer()
            await _edit(update, Messages.ERROR_NOT_ENOUGH_PARTICIPANTS)
            return
        except ImpossibleDraw:
            await query.answer()
            await _edit(update, Messages.ERROR_ASSIGNMENT_IMPOSSIBLE)
            return
        deliveries = [(a.id, a.giver.telegram_id, a.giver.real_name, assignment_text(a.receiver, group.title)) for a in rows]
        event_id, chat_id = event.id, group.telegram_chat_id
    await query.answer()

    # The draw is committed before any DM goes out: a crash mid-way can't
    # leave half the group with assignments that are not in the database.
    delivered, failed_names = [], []
    for assignment_id, telegram_id, name, text in deliveries:
        if await send_dm(context.bot, telegram_id, text):
            delivered.append(assignment_id)
        else:
            failed_names.append(name)
    async with session_scope() as s:
        await seasons.mark_delivered(s, delivered)

    logger.info("Draw for event_id=%s: delivered %s/%s", event_id, len(delivered), len(deliveries))
    await _edit(update, Messages.ASSIGNMENTS_SENT)
    await refresh_join_message(context.bot, event_id)
    if failed_names:
        await post(context.bot, chat_id, render(Messages.DELIVERY_FAILED, names=join(sorted(failed_names), sep=", ")))


async def _edit(update: Update, text: str) -> None:
    query = update.callback_query
    assert query is not None
    try:
        await query.edit_message_text(Safe(text), reply_markup=None)
    except TelegramError:
        pass


async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Say hello when added to a group. An admin adding the bot gets the join
    post straight away, so a season starts without a single command."""
    message, chat = update.effective_message, update.effective_chat
    if message is None or chat is None or chat.type not in ("group", "supergroup"):
        return
    if not any(member.id == context.bot.id for member in message.new_chat_members or ()):
        return
    if update.effective_user is None or not await is_group_admin(update, context):
        await post(context.bot, chat.id, Safe(Messages.BOT_ADDED))
        return
    async with session_scope() as s:
        _, event = await seasons.activate_group(s, chat.id, chat.title or "")
        event_id = event.id
    logger.info("Group activated on add chat_id=%s", chat.id)
    await post(context.bot, chat.id, Safe(Messages.BOT_ADDED_BY_ADMIN))
    await post_join_message(context.bot, event_id)


@require_group_chat
async def newseason_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    assert chat is not None
    if not await is_group_admin(update, context):
        await _reply(update, Messages.ERROR_ADMIN_ONLY)
        return
    async with session_scope() as s:
        group = await seasons.group_by_chat(s, chat.id)
        if group is None or not group.is_active:
            await _reply(update, Messages.ERROR_GROUP_NOT_FOUND)
            return
        group_id = group.id
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(Messages.CONFIRM_YES_BUTTON, callback_data=callback("cf", CONFIRM_CODES["new_season"], group_id)),
            InlineKeyboardButton(Messages.CONFIRM_NO_BUTTON, callback_data=callback("cx")),
        ]]
    )
    await _reply(update, Messages.NEW_SEASON_CONFIRM, markup)


async def chat_migrated(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Basic group -> supergroup: Telegram assigns a new chat id."""
    message = update.effective_message
    if message is None:
        return
    if message.migrate_to_chat_id:
        old_id, new_id = message.chat.id, message.migrate_to_chat_id
    elif message.migrate_from_chat_id:
        old_id, new_id = message.migrate_from_chat_id, message.chat.id
    else:
        return
    async with session_scope() as s:
        if await seasons.migrate_chat(s, old_id, new_id):
            logger.info("Group migrated chat_id=%s -> %s", old_id, new_id)
