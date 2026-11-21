"""Per-user DM conversation state, stored in the database.

Flows:
  reg_name       {"event_id"}                    waiting for the participant's name
  reg_wishlist   {"event_id", "name"}            waiting for the wishlist
  edit_wishlist  {"participant_ids": [...]}      /wishlist was sent
"""

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import DmState

REG_NAME = "reg_name"
REG_WISHLIST = "reg_wishlist"
EDIT_WISHLIST = "edit_wishlist"


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
