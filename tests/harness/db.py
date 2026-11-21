"""Direct database access for assertions the chat transcript cannot show."""

from sqlalchemy import select

from src.database import session as session_module
from src.database.models import Assignment, Exclusion, User


async def fetch_all(stmt):
    async with session_module._async_session_maker() as session:
        return list((await session.execute(stmt)).scalars().all())


async def users_named(name: str) -> list[User]:
    return await fetch_all(select(User).where(User.real_name == name))


async def assignments() -> list[Assignment]:
    return await fetch_all(select(Assignment))


async def exclusions() -> list[Exclusion]:
    return await fetch_all(select(Exclusion))


async def set_wishlist(real_name: str, wishlist: str) -> None:
    """Seed a wishlist directly (bypasses the chat flow)."""
    async with session_module._async_session_maker() as session:
        user = (await session.execute(select(User).where(User.real_name == real_name))).scalar_one()
        user.wishlist = wishlist
        await session.commit()
