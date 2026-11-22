"""Admin DM commands and every inline-button callback.

Callbacks are stateless: each button carries the ids it acts on
(validation.callback). Because callback data is client input, every callback
re-checks that the clicking user is currently an admin of the group the ids
belong to, and that the ids belong together.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..database.models import Event, EventStatus, Exclusion, Group, Participant
from ..database.session import session_scope
from ..formatting import Safe, join, render, truncate
from ..messages import Messages
from ..services import seasons, state, wishlists
from ..services.assignment import ImpossibleDraw, NotEnoughParticipants
from ..services.join_post import post_join_message, refresh_join_message
from ..services.notifications import deliver, reassignment_notices, send_dm
from ..utils.auth import is_chat_admin, require_private_chat
from ..validation import CONFIRM_ACTIONS, CONFIRM_CODES, ValidationError, callback, parse_callback, parse_index
from . import chat as chat_handlers
from . import group as group_handlers
from . import registration, user

logger = logging.getLogger(__name__)

PAGE_SIZE = 8


async def _reply(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    assert update.effective_message is not None
    await update.effective_message.reply_text(Safe(text), reply_markup=markup)


def _confirm_markup(action: str, group_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(Messages.CONFIRM_YES_BUTTON, callback_data=callback("cf", CONFIRM_CODES[action], group_id)),
            InlineKeyboardButton(Messages.CONFIRM_NO_BUTTON, callback_data=callback("cx")),
        ]]
    )


async def _admin_groups(s: AsyncSession, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> list[Group]:
    return [g for g in await seasons.active_groups(s) if await is_chat_admin(g.telegram_chat_id, user_id, context.bot)]


async def _selected_group(s: AsyncSession, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Group | None:
    """The admin's selected group (or their only group), re-verifying admin
    rights; replies on failure."""
    user = update.effective_user
    assert user is not None
    group_id = await state.selected_group_id(s, user.id)
    if group_id is None:
        # nothing to choose between: most admins run a single group
        groups = await _admin_groups(s, context, user.id)
        if len(groups) != 1:
            await _reply(update, Messages.ERROR_NO_GROUP_SELECTED)
            return None
        await state.select_group(s, user.id, groups[0].id)
        return groups[0]
    group = await seasons.get_group(s, group_id)
    if group is None:
        await _reply(update, Messages.ERROR_GROUP_NOT_FOUND)
        return None
    if not await is_chat_admin(group.telegram_chat_id, user.id, context.bot):
        await _reply(update, Messages.ERROR_ADMIN_ONLY)
        return None
    return group


async def _selected_event(s: AsyncSession, update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[Group, Event] | None:
    group = await _selected_group(s, update, context)
    if group is None:
        return None
    event = await seasons.current_event(s, group.id)
    if event is None:
        await _reply(update, Messages.NO_SEASON)
        return None
    return group, event


def _person_label(p: Participant) -> str:
    return f"{p.real_name} (@{p.telegram_username})" if p.telegram_username else p.real_name


def _people_keyboard(people: list[Participant], page: int, pick: object, nav: object) -> InlineKeyboardMarkup:
    """Paginated people picker. pick(pid) / nav(page) build callback data."""
    pages = max(1, (len(people) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    rows = [
        [InlineKeyboardButton(truncate(_person_label(p), 60), callback_data=pick(p.id))]  # type: ignore[operator]
        for p in people[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    if pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(Messages.PREV_PAGE_BUTTON, callback_data=nav(page - 1)))  # type: ignore[operator]
        nav_row.append(InlineKeyboardButton(f"· {page + 1}/{pages} ·", callback_data=callback("noop")))
        if page < pages - 1:
            nav_row.append(InlineKeyboardButton(Messages.NEXT_PAGE_BUTTON, callback_data=nav(page + 1)))  # type: ignore[operator]
        rows.append(nav_row)
    return InlineKeyboardMarkup(rows)


# --- commands -----------------------------------------------------------------


@require_private_chat
async def listgroups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        groups = await _admin_groups(s, context, user.id)
        if not groups:
            await _reply(update, Messages.NO_GROUPS)
            return
        entries = []
        for index, group in enumerate(groups, 1):
            event = await seasons.current_event(s, group.id)
            count = await seasons.participant_count(s, event.id) if event else 0
            drawn = event is not None and event.status == EventStatus.DRAWN
            entries.append(
                render(
                    Messages.GROUP_LIST_ENTRY,
                    index=index,
                    group_name=group.title,
                    chat_id=group.telegram_chat_id,
                    activated_at=group.activated_at.strftime("%Y-%m-%d"),
                    participants=count,
                    assignment_status=Messages.ASSIGNMENT_STATUS_SENT if drawn else Messages.ASSIGNMENT_STATUS_NOT_SENT,
                )
            )
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(truncate(g.title, 60), callback_data=callback("sg", g.id))] for g in groups]
        )
    await _reply(update, render(Messages.LIST_GROUPS, groups_list=join(entries, sep="\n\n")), markup)


@require_private_chat
async def selectgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    assert user is not None
    async with session_scope() as s:
        groups = await _admin_groups(s, context, user.id)
        try:
            group = groups[parse_index(context.args or [], len(groups))]
        except ValidationError as e:
            await _reply(update, render(Messages.INVALID_INPUT, reason=f"Неправильный формат. {e}"))
            return
        await state.select_group(s, user.id, group.id)
        await _reply(update, render(Messages.GROUP_SELECTED, group_name=group.title))


@require_private_chat
async def listjoined_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        selected = await _selected_event(s, update, context)
        if selected is None:
            return
        group, event = selected
        people = sorted(await seasons.participants(s, event.id), key=lambda p: p.joined_at)
        unfinished = await seasons.unfinished_names(s, event.id)
        undelivered = sorted(a.giver.real_name for a in await seasons.assignments(s, event.id) if a.delivered_at is None)
    if not people and not unfinished:
        await _reply(update, Messages.NO_PARTICIPANTS)
        return
    lines = [
        render(Messages.USER_ENTRY, name=p.real_name, username=p.telegram_username)
        if p.telegram_username
        else render(Messages.USER_ENTRY_NO_USERNAME, name=p.real_name)
        for p in people
    ]
    extra = {
        "unfinished": render(Messages.LIST_JOINED_UNFINISHED, names=join(unfinished, sep=", ")) if unfinished else "",
        "undelivered": render(Messages.LIST_JOINED_UNDELIVERED, names=join(undelivered, sep=", ")) if undelivered else "",
    }
    text = render(Messages.LIST_JOINED, group_name=group.title, count=len(people), users_list=join(lines), **extra)
    await _reply(update, text)


@require_private_chat
async def removeparticipant_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        selected = await _selected_event(s, update, context)
        if selected is None:
            return
        _, event = selected
        people = await seasons.participants(s, event.id)
    if not people:
        await _reply(update, Messages.NO_PARTICIPANTS)
        return
    await _reply(update, Messages.REMOVE_PARTICIPANT_SELECT, _removal_keyboard(event.id, people, 0))


def _removal_keyboard(event_id: int, people: list[Participant], page: int) -> InlineKeyboardMarkup:
    return _people_keyboard(people, page, lambda pid: callback("pr", event_id, pid), lambda pg: callback("pp", event_id, pg))


@require_private_chat
async def addrule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        selected = await _selected_event(s, update, context)
        if selected is None:
            return
        _, event = selected
        people = await seasons.participants(s, event.id)
    if len(people) < 2:
        await _reply(update, Messages.ADDRULE_NOT_ENOUGH)
        return
    markup = _people_keyboard(people, 0, lambda pid: callback("rf", event.id, pid), lambda page: callback("ra", event.id, page))
    await _reply(update, Messages.ADDRULE_SELECT_FIRST, markup)


async def _rule_lines(s: AsyncSession, group: Group, rules: list[Exclusion]) -> list[tuple[Exclusion, str]]:
    names = await seasons.known_names(s, group.id)
    event = await seasons.current_event(s, group.id)
    in_season = {p.telegram_id for p in await seasons.participants(s, event.id)} if event else set()

    def label(telegram_id: int) -> str:
        name = names.get(telegram_id, str(telegram_id))
        return name if telegram_id in in_season else name + Messages.RULE_NOT_IN_SEASON

    return [(r, f"{label(r.telegram_id_a)} ↔ {label(r.telegram_id_b)}") for r in rules]


@require_private_chat
async def listrules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        group = await _selected_group(s, update, context)
        if group is None:
            return
        rules = await _rule_lines(s, group, await seasons.group_rules(s, group.id))
    if not rules:
        await _reply(update, Messages.NO_RULES)
        return
    lines = [render("• {rule}", rule=text) for _, text in rules]
    await _reply(update, render(Messages.LIST_RULES, group_name=group.title, rules_list=join(lines), count=len(rules)))


@require_private_chat
async def removerule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        group = await _selected_group(s, update, context)
        if group is None:
            return
        rules = await _rule_lines(s, group, await seasons.group_rules(s, group.id))
    if not rules:
        await _reply(update, Messages.NO_RULES)
        return
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(truncate(text, 60), callback_data=callback("rr", rule.id))] for rule, text in rules]
    )
    await _reply(update, Messages.REMOVE_RULE_SELECT, markup)


@require_private_chat
async def dryrun_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        selected = await _selected_event(s, update, context)
        if selected is None:
            return
        group, event = selected
        try:
            pairs, rule_count = await seasons.plan_draw(s, event)
        except NotEnoughParticipants:
            await _reply(update, Messages.ERROR_NOT_ENOUGH_PARTICIPANTS)
            return
        except ImpossibleDraw:
            await _reply(update, Messages.ERROR_ASSIGNMENT_IMPOSSIBLE)
            return
    # Pairs are never shown: the admin usually takes part too.
    await _reply(update, render(Messages.DRY_RUN, group_name=group.title, participants=len(pairs), rules=rule_count))


@require_private_chat
async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        selected = await _selected_event(s, update, context)
        if selected is None:
            return
        group, event = selected
    if event.status != EventStatus.DRAWN:
        await _reply(update, Messages.RESET_NOTHING)
        return
    await _reply(update, render(Messages.RESET_CONFIRM, group_name=group.title), _confirm_markup("reset", group.id))


@require_private_chat
async def disband_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with session_scope() as s:
        group = await _selected_group(s, update, context)
        if group is None:
            return
    await _reply(update, render(Messages.DISBAND_CONFIRM, group_name=group.title), _confirm_markup("disband", group.id))


@require_private_chat
async def adminhelp_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, Messages.ADMIN_HELP)


# --- callbacks ----------------------------------------------------------------


async def _event_as_admin(s: AsyncSession, update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int) -> Event | None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    event = await seasons.get_event(s, event_id)
    if event is None or event.status == EventStatus.CLOSED:
        await query.answer(Messages.STALE_BUTTON, show_alert=True)
        return None
    if not await is_chat_admin(event.group.telegram_chat_id, user.id, context.bot):
        await query.answer(Messages.ERROR_ADMIN_ONLY, show_alert=True)
        return None
    return event


async def _edit(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    query = update.callback_query
    assert query is not None
    await query.edit_message_text(Safe(text), reply_markup=markup)


async def on_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: int) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        group = await seasons.get_group(s, group_id)
        if group is None or not group.is_active:
            await query.answer()
            await _edit(update, Messages.ERROR_GROUP_NOT_FOUND)
            return
        if not await is_chat_admin(group.telegram_chat_id, user.id, context.bot):
            await query.answer()
            await _edit(update, Messages.ERROR_ADMIN_ONLY)
            return
        await state.select_group(s, user.id, group.id)
    await query.answer()
    await _edit(update, render(Messages.GROUP_SELECTED, group_name=group.title))
    logger.info("user_id=%s selected group_id=%s", user.id, group_id)


async def on_rule_page(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, first_id: int | None, page: int) -> None:
    query = update.callback_query
    assert query is not None
    async with session_scope() as s:
        event = await _event_as_admin(s, update, context, event_id)
        if event is None:
            return
        people = await seasons.participants(s, event.id)
        first = next((p for p in people if p.id == first_id), None)
    await query.answer()
    if first_id is None:
        markup = _people_keyboard(people, page, lambda pid: callback("rf", event_id, pid), lambda pg: callback("ra", event_id, pg))
        await _edit(update, Messages.ADDRULE_SELECT_FIRST, markup)
    elif first is not None:
        others = [p for p in people if p.id != first.id]
        markup = _people_keyboard(
            others, page, lambda pid: callback("rs", event_id, first.id, pid), lambda pg: callback("rb", event_id, first.id, pg)
        )
        await _edit(update, render(Messages.ADDRULE_SELECT_SECOND, first_name=first.real_name), markup)


async def on_rule_first(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, participant_id: int) -> None:
    async with session_scope() as s:
        event = await _event_as_admin(s, update, context, event_id)
        if event is None:
            return
        if participant_id not in {p.id for p in await seasons.participants(s, event.id)}:
            assert update.callback_query is not None
            await update.callback_query.answer(Messages.STALE_BUTTON, show_alert=True)
            return
    await on_rule_page(update, context, event_id, participant_id, 0)


async def on_rule_second(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, first_id: int, second_id: int) -> None:
    query = update.callback_query
    assert query is not None
    async with session_scope() as s:
        event = await _event_as_admin(s, update, context, event_id)
        if event is None:
            return
        people = {p.id: p for p in await seasons.participants(s, event.id)}
        first, second = people.get(first_id), people.get(second_id)
        if first is None or second is None or first.telegram_id == second.telegram_id:
            await query.answer(Messages.STALE_BUTTON, show_alert=True)
            return
        created = await seasons.add_rule(s, event.group_id, first.telegram_id, second.telegram_id)
        group_title = event.group.title
    await query.answer()
    if created:
        logger.info("Rule added in group_id=%s", event.group_id)
        await _edit(update, render(Messages.ADDRULE_COMPLETE, group_name=group_title, name1=first.real_name, name2=second.real_name))
    else:
        await _edit(update, Messages.ERROR_DUPLICATE_RULE)


async def on_remove_rule(update: Update, context: ContextTypes.DEFAULT_TYPE, rule_id: int) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    async with session_scope() as s:
        rule = await s.get(Exclusion, rule_id)
        if rule is None:
            await query.answer(Messages.STALE_BUTTON, show_alert=True)
            return
        group = await seasons.get_group(s, rule.group_id)
        if group is None or not await is_chat_admin(group.telegram_chat_id, user.id, context.bot):
            await query.answer(Messages.ERROR_ADMIN_ONLY, show_alert=True)
            return
        await s.delete(rule)
    await query.answer()
    await _edit(update, Messages.RULE_REMOVED)
    logger.info("Rule %s removed by user_id=%s", rule_id, user.id)


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, action_code: int, group_id: int) -> None:
    query, user = update.callback_query, update.effective_user
    assert query is not None and user is not None
    action = CONFIRM_ACTIONS.get(action_code)
    async with session_scope() as s:
        group = await seasons.get_group(s, group_id)
        if action is None or group is None:
            await query.answer(Messages.STALE_BUTTON, show_alert=True)
            return
        # rights are checked at click time, not when the prompt was shown
        if not await is_chat_admin(group.telegram_chat_id, user.id, context.bot):
            await query.answer(Messages.ERROR_ADMIN_ONLY, show_alert=True)
            return
        if action != "draw":
            text, refresh, new_event_id = await _apply(s, action, group)
    if action == "draw":
        await group_handlers.run_draw(update, context, group_id)
        return
    await query.answer()
    await _edit(update, text)
    # the join post follows the season: reopened, closed, or a new one posted
    for event_id in refresh:
        await refresh_join_message(context.bot, event_id)
    if new_event_id is not None:
        await post_join_message(context.bot, new_event_id)
    logger.info("Confirmed %s for group_id=%s by user_id=%s", action, group_id, user.id)


async def _apply(s: AsyncSession, action: str, group: Group) -> tuple[str, list[int], int | None]:
    """Run a confirmed reset / disband / new season: (reply, join posts to refresh, new season id)."""
    event = await seasons.current_event(s, group.id)
    refresh = [event.id] if event else []
    if action == "reset":
        return (Messages.RESET_COMPLETE if event and await seasons.reset_draw(s, event) else Messages.RESET_NOTHING), refresh, None
    if action == "disband":
        await seasons.disband_group(s, group)
        return Messages.GROUP_DISBANDED, refresh, None
    return Messages.NEW_SEASON_OPENED, refresh, (await seasons.start_new_season(s, group)).id


async def on_removal_page(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, page: int) -> None:
    query = update.callback_query
    assert query is not None
    async with session_scope() as s:
        event = await _event_as_admin(s, update, context, event_id)
        if event is None:
            return
        people = await seasons.participants(s, event.id)
    await query.answer()
    await _edit(update, Messages.REMOVE_PARTICIPANT_SELECT, _removal_keyboard(event_id, people, page))


async def _participant_in(s: AsyncSession, update: Update, event: Event, participant_id: int) -> Participant | None:
    participant = await s.get(Participant, participant_id)
    if participant is None or participant.event_id != event.id:
        assert update.callback_query is not None
        await update.callback_query.answer(Messages.STALE_BUTTON, show_alert=True)
        return None
    return participant


async def on_removal_pick(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, participant_id: int) -> None:
    query = update.callback_query
    assert query is not None
    async with session_scope() as s:
        event = await _event_as_admin(s, update, context, event_id)
        if event is None:
            return
        participant = await _participant_in(s, update, event, participant_id)
        if participant is None:
            return
        text = render(
            Messages.REMOVE_PARTICIPANT_CONFIRM,
            name=participant.real_name,
            group_name=event.group.title,
            drawn_note=Messages.DRAWN_REPAIR_NOTE if event.status == EventStatus.DRAWN else "",
        )
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton(Messages.CONFIRM_YES_BUTTON, callback_data=callback("px", event_id, participant_id)),
            InlineKeyboardButton(Messages.CONFIRM_NO_BUTTON, callback_data=callback("cx")),
        ]]
    )
    await query.answer()
    await _edit(update, text, markup)


async def on_removal_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, event_id: int, participant_id: int) -> None:
    query, admin = update.callback_query, update.effective_user
    assert query is not None and admin is not None
    async with session_scope() as s:
        # rights are checked at click time, not when the prompt was shown
        event = await _event_as_admin(s, update, context, event_id)
        if event is None:
            return
        participant = await _participant_in(s, update, event, participant_id)
        if participant is None:
            return
        name, removed_telegram_id = participant.real_name, participant.telegram_id
        group = event.group
        try:
            reassigned = await seasons.remove_participant(s, event, participant)
        except NotEnoughParticipants:
            await query.answer()
            await _edit(update, Messages.REPAIR_TOO_FEW)
            return
        except ImpossibleDraw:
            await query.answer()
            await _edit(update, Messages.REPAIR_IMPOSSIBLE)
            return
        notices = await reassignment_notices(s, reassigned, group)
        group_title = group.title
    logger.info("Participant removed from event_id=%s by user_id=%s (%s reassigned)", event_id, admin.id, len(reassigned))
    await query.answer()
    # the admin learns how many Santas changed, never who gives to whom
    done = render(Messages.REMOVE_PARTICIPANT_DONE, name=name)
    if reassigned:
        done = Safe(done + render(Messages.REMOVE_PARTICIPANT_REASSIGNED, count=len(reassigned)))
    await _edit(update, done)
    if removed_telegram_id != admin.id:
        await send_dm(context.bot, removed_telegram_id, render(Messages.REMOVED_BY_ADMIN, group_name=group_title))
    await refresh_join_message(context.bot, event_id)
    await deliver(context.bot, notices)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    cb = parse_callback(query.data)
    if cb is None:
        await query.answer(Messages.STALE_BUTTON)
        return
    a = cb.args
    match cb.kind:
        case "sg":
            await on_select_group(update, context, a[0])
        case "ra":
            await on_rule_page(update, context, a[0], None, a[1])
        case "rb":
            await on_rule_page(update, context, a[0], a[1], a[2])
        case "rf":
            await on_rule_first(update, context, a[0], a[1])
        case "rs":
            await on_rule_second(update, context, a[0], a[1], a[2])
        case "rr":
            await on_remove_rule(update, context, a[0])
        case "cf":
            await on_confirm(update, context, a[0], a[1])
        case "cx":
            await query.answer()
            await _edit(update, Messages.CANCELLED)
        case "rn" | "rw" | "tn":
            await registration.reuse_callback(update, context, cb.kind, a[0])
        case "ew":
            await user.on_edit_wishlist_button(update, context)
        case "wy":
            await user.on_confirm_free_wishlist(update, context, wishlists.REPLACE)
        case "wa":
            await user.on_confirm_free_wishlist(update, context, wishlists.APPEND)
        case "wm":
            await user.on_replace_mode(update, context)
        case "wu":
            await user.on_undo(update, context, a[0])
        case "lw":
            await user.on_leave_button(update, context)
        case "lq":
            await user.on_leave_pick(update, context, a[0])
        case "lv":
            await user.on_leave_confirm(update, context, a[0])
        case "pp":
            await on_removal_page(update, context, a[0], a[1])
        case "pr":
            await on_removal_pick(update, context, a[0], a[1])
        case "px":
            await on_removal_confirm(update, context, a[0], a[1])
        case "ms":
            await chat_handlers.on_compose(update, context, a[0])
        case "mx":
            await chat_handlers.on_cancel(update, context)
        case _:
            await query.answer()
