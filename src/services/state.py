"""Per-user DM conversation state, stored in the database.

Flows:
  reg_name       {"event_id", "tg_name"}         waiting for the participant's name
  reg_wishlist   {"event_id", "tg_name", "name"} waiting for the wishlist

tg_name is the Telegram name, so organizers can see who started registering
but never finished.
  edit_wishlist  {"participant_ids": [...]}      /wishlist was sent
  confirm_wishlist {"text"}                      free text sent: use it as the wishlist?
"""

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import DmState

REG_NAME = "reg_name"
REG_WISHLIST = "reg_wishlist"
EDIT_WISHLIST = "edit_wishlist"
CONFIRM_WISHLIST = "confirm_wishlist"


@dataclass
class Flow:
    name: str | None
    data: dict[str, Any] = field(default_factory=dict)


async def _row(s: AsyncSession, telegram_id: int) -> DmState:
    row = await s.get(DmState, telegram_id)
    if row is None:
        row = DmState(telegram_id=telegram_id)
        s.add(row)
    return row


async def get_flow(s: AsyncSession, telegram_id: int) -> Flow:
    row = await s.get(DmState, telegram_id)
    if row is None or row.flow is None:
        return Flow(None)
    return Flow(row.flow, json.loads(row.flow_data or "{}"))


async def set_flow(s: AsyncSession, telegram_id: int, flow: str, /, **data: object) -> None:
    row = await _row(s, telegram_id)
    row.flow = flow
    row.flow_data = json.dumps(data)


async def clear_flow(s: AsyncSession, telegram_id: int) -> bool:
    row = await s.get(DmState, telegram_id)
    if row is None or row.flow is None:
        return False
    row.flow = None
    row.flow_data = None
    return True


async def selected_group_id(s: AsyncSession, telegram_id: int) -> int | None:
    row = await s.get(DmState, telegram_id)
    return row.selected_group_id if row else None


async def select_group(s: AsyncSession, telegram_id: int, group_id: int) -> None:
    row = await _row(s, telegram_id)
    row.selected_group_id = group_id


async def unfinished_registrations(s: AsyncSession, event_id: int) -> dict[int, str]:
    """telegram_id -> best known name of everyone midway through registering for event_id."""
    rows = await s.execute(select(DmState).where(DmState.flow.in_([REG_NAME, REG_WISHLIST])))
    pending = {}
    for row in rows.scalars():
        data = json.loads(row.flow_data or "{}")
        if data.get("event_id") == event_id:
            pending[row.telegram_id] = str(data.get("name") or data.get("tg_name") or "без имени")
    return pending
