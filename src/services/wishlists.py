"""Changing a wishlist after registration: add to it (the default), replace
it, and undo the last change.

Retyping a whole wishlist on a phone is painful and one careless message used
to wipe it, so text sent to the bot is appended unless the person explicitly
asks to replace, and every change can be taken back once.

A person in several groups has one participant row per group; a change
applies to all the rows it names, each keeping its own previous text.
"""

import zlib
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..validation import WISHLIST_MAX_LENGTH, ValidationError
from . import seasons

APPEND = "append"
REPLACE = "replace"


@dataclass
class Changed:
    membership: seasons.Membership
    added: str | None  # the appended text, or None for a replace / undo


def combine(current: str | None, addition: str) -> str:
    current = (current or "").rstrip()
    return f"{current}\n{addition}" if current else addition


def undo_token(wishlists: list[str]) -> int:
    """Identifies the result of a change; an undo button only works while the
    wishlists are still exactly what that change left."""
    return zlib.crc32("\x00".join(wishlists).encode())


async def change(s: AsyncSession, telegram_id: int, participant_ids: list[int], text: str, mode: str) -> list[Changed]:
    """Apply an already validated text to the user's own participations among
    participant_ids. Raises ValidationError when appending makes it too long
    (then nothing changes)."""
    memberships = {m.participant.id: m for m in await seasons.current_memberships(s, telegram_id)}
    targets = [memberships[pid] for pid in participant_ids if pid in memberships]  # never someone else's row
    new = {m.participant.id: combine(m.participant.wishlist, text) if mode == APPEND else text for m in targets}
    longest = max((len(w) for w in new.values()), default=0)
    if longest > WISHLIST_MAX_LENGTH:
        raise ValidationError(
            f"Вместе с добавкой вишлист выйдет {longest} символов, а можно до {WISHLIST_MAX_LENGTH}. "
            "Сократи добавку или замени вишлист целиком."
        )
    changed = []
    for m in targets:
        if new[m.participant.id] == m.participant.wishlist:
            continue
        m.participant.previous_wishlist = m.participant.wishlist
        m.participant.wishlist = new[m.participant.id]
        changed.append(Changed(m, text if mode == APPEND else None))
    return changed


def token_for(changed: list[Changed]) -> int:
    return undo_token([c.membership.participant.wishlist for c in sorted(changed, key=lambda c: c.membership.participant.id)])


async def undo(s: AsyncSession, telegram_id: int, token: int) -> list[Changed] | None:
    """Put back what the last change replaced, if that change is still the
    latest one (token). None when there is nothing (left) to undo."""
    memberships = sorted(
        (m for m in await seasons.current_memberships(s, telegram_id) if m.participant.previous_wishlist is not None),
        key=lambda m: m.participant.id,
    )
    if not memberships or undo_token([m.participant.wishlist for m in memberships]) != token:
        return None
    for m in memberships:
        m.participant.wishlist, m.participant.previous_wishlist = m.participant.previous_wishlist, None
    return [Changed(m, None) for m in memberships]
