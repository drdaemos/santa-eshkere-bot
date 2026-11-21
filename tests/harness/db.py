"""Direct database access for assertions the chat transcript cannot show."""

from sqlalchemy import select

from src.database import session as session_module
from src.database.models import Assignment, Event, Exclusion, Participant


async def fetch_all(stmt):
    async with session_module.session_scope() as session:
        return list((await session.execute(stmt)).scalars().all())


async def participants_named(name: str) -> list[Participant]:
    return await fetch_all(select(Participant).where(Participant.real_name == name))


async def assignments(event_id: int | None = None) -> list[Assignment]:
    stmt = select(Assignment)
    if event_id is not None:
        stmt = stmt.where(Assignment.event_id == event_id)
    return await fetch_all(stmt)


async def exclusions() -> list[Exclusion]:
    return await fetch_all(select(Exclusion))


async def events() -> list[Event]:
    return await fetch_all(select(Event).order_by(Event.id))


async def set_wishlist(real_name: str, wishlist: str) -> None:
    """Seed a wishlist directly (bypasses input validation, like legacy rows)."""
    async with session_module.session_scope() as session:
        for participant in (await session.execute(select(Participant).where(Participant.real_name == real_name))).scalars():
            participant.wishlist = wishlist
