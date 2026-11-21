"""Groups, seasons, participants, rules and draws: all DB operations.

Functions take an AsyncSession and never talk to Telegram, so handlers stay
thin and this module can be tested without the bot.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from ..database.models import Assignment, Event, EventStatus, Exclusion, Group, Participant
from .assignment import generate_assignments, repair_without, splice_in

# --- groups -------------------------------------------------------------------


async def group_by_chat(s: AsyncSession, chat_id: int) -> Group | None:
    return (await s.execute(select(Group).where(Group.telegram_chat_id == chat_id))).scalar_one_or_none()


async def get_group(s: AsyncSession, group_id: int) -> Group | None:
    return await s.get(Group, group_id)


async def activate_group(s: AsyncSession, chat_id: int, title: str) -> tuple[Group, Event]:
    """Create or reactivate the group and make sure it has a current season."""
    group = await group_by_chat(s, chat_id)
    if group is None:
        group = Group(telegram_chat_id=chat_id, group_name=title, is_active=True)
        s.add(group)
        await s.flush()
    else:
        group.group_name = title or group.group_name
        if not group.is_active:
            group.is_active = True
            group.activated_at = datetime.now()
            group.disbanded_at = None
    event = await current_event(s, group.id)
    if event is None:
        event = Event(group_id=group.id, status=EventStatus.OPEN)
        s.add(event)
        await s.flush()
    return group, event


async def disband_group(s: AsyncSession, group: Group) -> None:
    group.is_active = False
    group.disbanded_at = datetime.now()


async def migrate_chat(s: AsyncSession, old_chat_id: int, new_chat_id: int) -> bool:
    """Basic group upgraded to a supergroup: Telegram gives it a new chat id."""
    if await group_by_chat(s, new_chat_id) is not None:
        return False  # already migrated (Telegram sends both migrate_to and migrate_from)
    group = await group_by_chat(s, old_chat_id)
    if group is None:
        return False
    group.telegram_chat_id = new_chat_id
    return True


async def active_groups(s: AsyncSession) -> list[Group]:
    result = await s.execute(select(Group).where(Group.is_active.is_(True)).order_by(Group.activated_at.desc(), Group.id))
    return list(result.scalars().all())


# --- seasons ------------------------------------------------------------------


async def current_event(s: AsyncSession, group_id: int) -> Event | None:
    result = await s.execute(
        select(Event).where(Event.group_id == group_id, Event.status != EventStatus.CLOSED).order_by(Event.id.desc())
    )
    return result.scalars().first()


async def get_event(s: AsyncSession, event_id: int) -> Event | None:
    return await s.get(Event, event_id, options=[selectinload(Event.group)])


async def start_new_season(s: AsyncSession, group: Group) -> Event:
    event = await current_event(s, group.id)
    if event is not None:
        event.status = EventStatus.CLOSED
        event.closed_at = datetime.now()
        await s.flush()
    new_event = Event(group_id=group.id, status=EventStatus.OPEN)
    s.add(new_event)
    await s.flush()
    return new_event


# --- participants -------------------------------------------------------------


async def participants(s: AsyncSession, event_id: int) -> list[Participant]:
    result = await s.execute(
        select(Participant).where(Participant.event_id == event_id).order_by(Participant.real_name, Participant.id)
    )
    return list(result.scalars().all())


async def participant_count(s: AsyncSession, event_id: int) -> int:
    return (await s.execute(select(func.count(Participant.id)).where(Participant.event_id == event_id))).scalar_one()


async def find_participant(s: AsyncSession, event_id: int, telegram_id: int) -> Participant | None:
    result = await s.execute(
        select(Participant).where(Participant.event_id == event_id, Participant.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def previous_participation(s: AsyncSession, group_id: int, telegram_id: int, before_event_id: int) -> Participant | None:
    """The person's most recent entry in an earlier season of the same group."""
    result = await s.execute(
        select(Participant)
        .join(Event)
        .where(Event.group_id == group_id, Event.id < before_event_id, Participant.telegram_id == telegram_id)
        .order_by(Event.id.desc())
    )
    return result.scalars().first()


async def add_participant(
    s: AsyncSession, event: Event, telegram_id: int, username: str | None, name: str, wishlist: str
) -> Participant:
    participant = Participant(
        event_id=event.id, telegram_id=telegram_id, telegram_username=username, real_name=name, wishlist=wishlist
    )
    s.add(participant)
    await s.flush()
    return participant


@dataclass
class Membership:
    participant: Participant
    event: Event
    group: Group
    receiver: Participant | None  # whom they give to, once drawn


async def current_memberships(s: AsyncSession, telegram_id: int) -> list[Membership]:
    """The user's participations in current (not closed) seasons of active groups."""
    result = await s.execute(
        select(Participant, Event, Group)
        .join(Event, Participant.event_id == Event.id)
        .join(Group, Event.group_id == Group.id)
        .where(Participant.telegram_id == telegram_id, Event.status != EventStatus.CLOSED, Group.is_active.is_(True))
        .order_by(Group.id)
    )
    memberships = []
    for participant, event, group in result.all():
        receiver = None
        assignment = (
            await s.execute(
                select(Assignment).options(selectinload(Assignment.receiver)).where(Assignment.giver_id == participant.id)
            )
        ).scalar_one_or_none()
        if assignment is not None:
            receiver = assignment.receiver
        memberships.append(Membership(participant, event, group, receiver))
    return memberships


async def santas_of(s: AsyncSession, participant_ids: list[int]) -> list[tuple[Participant, Participant]]:
    """(giver, receiver) pairs where receiver is one of participant_ids."""
    result = await s.execute(
        select(Assignment)
        .options(selectinload(Assignment.giver), selectinload(Assignment.receiver))
        .where(Assignment.receiver_id.in_(participant_ids))
    )
    return [(a.giver, a.receiver) for a in result.scalars().all()]


# --- rules --------------------------------------------------------------------


async def group_rules(s: AsyncSession, group_id: int) -> list[Exclusion]:
    result = await s.execute(select(Exclusion).where(Exclusion.group_id == group_id).order_by(Exclusion.id))
    return list(result.scalars().all())


async def add_rule(s: AsyncSession, group_id: int, telegram_id_1: int, telegram_id_2: int) -> bool:
    """Returns False if the rule already exists."""
    if telegram_id_1 == telegram_id_2:
        raise ValueError("a rule needs two different people")
    a, b = sorted((telegram_id_1, telegram_id_2))
    exists = await s.execute(
        select(Exclusion.id).where(Exclusion.group_id == group_id, Exclusion.telegram_id_a == a, Exclusion.telegram_id_b == b)
    )
    if exists.first() is not None:
        return False
    s.add(Exclusion(group_id=group_id, telegram_id_a=a, telegram_id_b=b))
    await s.flush()
    return True


async def known_names(s: AsyncSession, group_id: int) -> dict[int, str]:
    """telegram_id -> most recent name used in this group."""
    result = await s.execute(
        select(Participant.telegram_id, Participant.real_name)
        .join(Event)
        .where(Event.group_id == group_id)
        .order_by(Event.id, Participant.id)
    )
    return dict(result.tuples().all())


# --- draw ---------------------------------------------------------------------


async def assignments(s: AsyncSession, event_id: int) -> list[Assignment]:
    result = await s.execute(
        select(Assignment)
        .options(selectinload(Assignment.giver), selectinload(Assignment.receiver))
        .where(Assignment.event_id == event_id)
    )
    return list(result.scalars().all())


async def plan_draw(s: AsyncSession, event: Event) -> tuple[list[tuple[Participant, Participant]], int]:
    """Compute a draw for the event without saving. Returns (pairs, rule_count).

    Raises NotEnoughParticipants / ImpossibleDraw.
    """
    people = await participants(s, event.id)
    by_id = {p.id: p for p in people}
    forbidden = await _forbidden_ids(s, event, people)
    pairs = generate_assignments([p.id for p in people], forbidden)
    return [(by_id[g], by_id[r]) for g, r in pairs], len(forbidden)


async def _forbidden_ids(s: AsyncSession, event: Event, people: list[Participant]) -> list[tuple[int, int]]:
    """The group's rules as participant-id pairs, for people in this season."""
    by_tg = {p.telegram_id: p for p in people}
    return [
        (by_tg[r.telegram_id_a].id, by_tg[r.telegram_id_b].id)
        for r in await group_rules(s, event.group_id)
        if r.telegram_id_a in by_tg and r.telegram_id_b in by_tg
    ]


async def draw(s: AsyncSession, event: Event) -> list[Assignment]:
    """Draw and persist; the event moves to DRAWN. Caller checks event.status first."""
    pairs, _ = await plan_draw(s, event)
    rows = [Assignment(event_id=event.id, giver_id=giver.id, receiver_id=receiver.id) for giver, receiver in pairs]
    s.add_all(rows)
    event.status = EventStatus.DRAWN
    event.drawn_at = datetime.now()
    await s.flush()
    return await assignments(s, event.id)


async def reset_draw(s: AsyncSession, event: Event) -> bool:
    if event.status != EventStatus.DRAWN:
        return False
    await s.execute(delete(Assignment).where(Assignment.event_id == event.id))
    event.status = EventStatus.OPEN
    event.drawn_at = None
    return True


async def mark_delivered(s: AsyncSession, assignment_ids: list[int]) -> None:
    if not assignment_ids:
        return
    result = await s.execute(select(Assignment).where(Assignment.id.in_(assignment_ids)))
    now = datetime.now()
    for assignment in result.scalars().all():
        assignment.delivered_at = now


# --- changes after the draw ---------------------------------------------------
#
# Invariant: in a drawn season every participant gives exactly once and
# receives exactly once. Leaving and late joining keep it, rewiring as few
# Santas as possible (services.assignment.repair_without / splice_in).


async def lock_event(s: AsyncSession, event: Event) -> None:
    """Serialize changes to one season (SELECT ... FOR UPDATE on Postgres; SQLite
    already serializes writers) and re-read its status.

    Only the status column is re-read: a full refresh would expire relationships
    that the async session can't lazy-load later."""
    status = (await s.execute(select(Event.status).where(Event.id == event.id).with_for_update())).scalar_one()
    set_committed_value(event, "status", status)


@dataclass
class Reassignment:
    """A giver whose assignment is new (a Santa who must be told)."""

    assignment_id: int
    giver: Participant
    receiver: Participant


async def _rewire(
    s: AsyncSession, event: Event, people: list[Participant], changes: dict[int, int], leaver_id: int | None = None
) -> list[Reassignment]:
    links = Assignment.giver_id.in_(list(changes))
    if leaver_id is not None:
        links = or_(links, Assignment.giver_id == leaver_id, Assignment.receiver_id == leaver_id)
    # delete first, then insert: the unique (event, giver) / (event, receiver)
    # constraints hold after every statement
    await s.execute(delete(Assignment).where(Assignment.event_id == event.id, links))
    await s.flush()
    rows = [Assignment(event_id=event.id, giver_id=g, receiver_id=r) for g, r in changes.items()]
    s.add_all(rows)
    await s.flush()
    by_id = {p.id: p for p in people}
    return [Reassignment(row.id, by_id[row.giver_id], by_id[row.receiver_id]) for row in rows]


async def remove_participant(s: AsyncSession, event: Event, participant: Participant) -> list[Reassignment]:
    """Remove someone from the season; in a drawn season, repair the chain.

    Raises NotEnoughParticipants / ImpossibleDraw (before changing anything)
    when a drawn season can't be repaired.
    """
    await lock_event(s, event)
    reassigned: list[Reassignment] = []
    if event.status == EventStatus.DRAWN:
        pairs = {a.giver_id: a.receiver_id for a in await assignments(s, event.id)}
        if participant.id in pairs:
            people = await participants(s, event.id)
            changes = repair_without(pairs, participant.id, await _forbidden_ids(s, event, people))
            reassigned = await _rewire(s, event, people, changes, leaver_id=participant.id)
    await s.execute(
        delete(Assignment).where(or_(Assignment.giver_id == participant.id, Assignment.receiver_id == participant.id))
    )
    await s.delete(participant)
    await s.flush()
    return reassigned


async def splice_late_participant(s: AsyncSession, event: Event, participant: Participant) -> list[Reassignment]:
    """Fit a just-added participant into a drawn season's chain.

    Returns the two new assignments (an existing Santa's and the newcomer's).
    Raises ImpossibleDraw when the rules leave no place; nothing is changed then.
    """
    pairs = {a.giver_id: a.receiver_id for a in await assignments(s, event.id)}
    people = await participants(s, event.id)
    changes = splice_in(pairs, participant.id, await _forbidden_ids(s, event, people))
    return await _rewire(s, event, people, changes)
