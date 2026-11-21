"""Group chat commands: /start, /join, /kickitoff, /newseason, chat migration"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import ContextTypes

from ..database.models import EventStatus
from ..database.session import session_scope
from ..formatting import Safe, join, render
from ..messages import Messages
from ..services import seasons, state
from ..services.assignment import ImpossibleDraw, NotEnoughParticipants
from ..services.notifications import assignment_text, send_dm
from ..utils.auth import is_group_admin, require_group_chat
from ..validation import CONFIRM_CODES, callback
from .registration import name_prompt

logger = logging.getLogger(__name__)


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    assert update.effective_message is not None
    await update.effective_message.reply_text(Safe(text), reply_markup=markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate the bot in this group; opens a season if there is none."""
    chat = update.effective_chat
    if chat is None or not await is_group_admin(update, context):
        await _reply(update, Messages.ERROR_ADMIN_ONLY)
        return
    async with session_scope() as s:
        await seasons.activate_group(s, chat.id, chat.title or "")
    logger.info("Group activated chat_id=%s", chat.id)
    await _reply(update, Messages.WELCOME)


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
        if event.status == EventStatus.DRAWN:
            await _reply(update, Messages.JOIN_AFTER_DRAW)
            return
        if await seasons.find_participant(s, event.id, user.id) is not None:
            await _reply(update, Messages.ERROR_ALREADY_REGISTERED)
            return
        await state.set_flow(s, user.id, state.REG_NAME, event_id=event.id)
        text, markup = await name_prompt(s, group, event, user.id)
        event_id = event.id

    try:
        await context.bot.send_message(chat_id=user.id, text=text, reply_markup=markup)
    except Forbidden:
        # The user never opened a DM with the bot. A deep link opens it and
        # resumes registration via /start join_<event_id>.
        link = f"https://t.me/{context.bot.username}?start=join_{event_id}"
        button = InlineKeyboardMarkup([[InlineKeyboardButton(Messages.JOIN_DM_BUTTON, url=link)]])
        await _reply(update, Messages.JOIN_DM_FAILED, button)
    except TelegramError:
        logger.exception("Could not send registration DM to user_id=%s", user.id)
        await _reply(update, Messages.ERROR_SYSTEM)


@require_group_chat
async def kickitoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            rows = await seasons.draw(s, event)
        except NotEnoughParticipants:
            await _reply(update, Messages.ERROR_NOT_ENOUGH_PARTICIPANTS)
            return
        except ImpossibleDraw:
            await _reply(update, Messages.ERROR_ASSIGNMENT_IMPOSSIBLE)
            return
        deliveries = [(a.id, a.giver.telegram_id, a.giver.real_name, assignment_text(a.receiver, group.title)) for a in rows]
        event_id = event.id

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
    await _reply(update, Messages.ASSIGNMENTS_SENT)
    if failed_names:
        await _reply(update, render(Messages.DELIVERY_FAILED, names=join(sorted(failed_names), sep=", ")))


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
