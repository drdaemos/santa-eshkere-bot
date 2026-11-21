"""Secret Santa draw: a random perfect matching givers -> receivers.

The draw is a bipartite matching problem (giver g may give to receiver r
unless g == r or {g, r} is excluded). Kuhn's augmenting-path algorithm finds
a perfect matching in O(V * E) or proves none exists, so impossible rule sets
fail instantly instead of after exploring (n-1)! arrangements. Randomness
comes from shuffling the order of givers and of each giver's candidates.
"""

import random
from collections.abc import Hashable, Iterable, Mapping, Sequence
from typing import TypeVar

MIN_PARTICIPANTS = 3

T = TypeVar("T", bound=Hashable)


class DrawError(ValueError):
    pass


class NotEnoughParticipants(DrawError):
    pass


class ImpossibleDraw(DrawError):
    pass


def generate_assignments(
    ids: Sequence[T],
    forbidden_pairs: Iterable[tuple[T, T]] = (),
    rng: random.Random | None = None,
) -> list[tuple[T, T]]:
    """Return (giver, receiver) pairs covering everyone exactly once each way.

    forbidden_pairs are unordered: (a, b) forbids a->b and b->a.
    """
    rng = rng or random.Random()
    if len(ids) < MIN_PARTICIPANTS:
        raise NotEnoughParticipants(f"need at least {MIN_PARTICIPANTS} participants")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate participant ids")

    forbidden = {frozenset(p) for p in forbidden_pairs}
    candidates = {g: [r for r in ids if r != g and frozenset((g, r)) not in forbidden] for g in ids}
    for options in candidates.values():
        rng.shuffle(options)

    giver_of: dict[T, T] = {}  # receiver -> giver

    def augment(giver: T, visited: set[T]) -> bool:
        for receiver in candidates[giver]:
            if receiver in visited:
                continue
            visited.add(receiver)
            if receiver not in giver_of or augment(giver_of[receiver], visited):
                giver_of[receiver] = giver
                return True
        return False

    order = list(ids)
    rng.shuffle(order)
    for giver in order:
        if not augment(giver, set()):
            raise ImpossibleDraw("exclusion rules leave no valid assignment")

    return [(giver, receiver) for receiver, giver in giver_of.items()]


# --- changing a draw that already happened ------------------------------------
#
# After the draw people have started shopping, so a late change must touch as
# few Santas as possible. Both operations return {giver: new receiver} for the
# givers whose assignment changes; everyone else keeps theirs.


def _allowed(giver: T, receiver: T, forbidden: set[frozenset[T]]) -> bool:
    return giver != receiver and frozenset((giver, receiver)) not in forbidden


def repair_without(
    pairs: Mapping[T, T],
    leaver: T,
    forbidden_pairs: Iterable[tuple[T, T]] = (),
    rng: random.Random | None = None,
) -> dict[T, T]:
    """Changes that close the gap when `leaver` drops out of a complete draw.

    The leaver's Santa (a) loses their receiver and the leaver's receiver (b)
    loses their Santa. Preferably a gives to b (one Santa affected). If that is
    forbidden, or a and b are the same person (a <-> leaver gave to each
    other), one more pair c -> d is rewired: a -> d, c -> b (two Santas).
    """
    rng = rng or random.Random()
    forbidden = {frozenset(p) for p in forbidden_pairs}
    if leaver not in pairs:
        raise ValueError("leaver is not part of the draw")
    if len(pairs) - 1 < MIN_PARTICIPANTS:
        raise NotEnoughParticipants(f"need at least {MIN_PARTICIPANTS} participants")
    giver_of = {receiver: giver for giver, receiver in pairs.items()}
    a, b = giver_of[leaver], pairs[leaver]
    if a != b and _allowed(a, b, forbidden):
        return {a: b}
    options = [
        (c, d)
        for c, d in pairs.items()
        if c not in (a, leaver) and _allowed(a, d, forbidden) and _allowed(c, b, forbidden)
    ]
    if not options:
        raise ImpossibleDraw("no small repair respects the exclusion rules")
    c, d = rng.choice(options)
    return {a: d, c: b}


def splice_in(
    pairs: Mapping[T, T],
    newcomer: T,
    forbidden_pairs: Iterable[tuple[T, T]] = (),
    rng: random.Random | None = None,
) -> dict[T, T]:
    """Changes that add `newcomer` to a complete draw: some c -> d becomes
    c -> newcomer -> d, so exactly one existing Santa (c) is affected."""
    rng = rng or random.Random()
    forbidden = {frozenset(p) for p in forbidden_pairs}
    if newcomer in pairs:
        raise ValueError("newcomer is already part of the draw")
    options = [(c, d) for c, d in pairs.items() if _allowed(c, newcomer, forbidden) and _allowed(newcomer, d, forbidden)]
    if not options:
        raise ImpossibleDraw("exclusion rules leave no place for the newcomer")
    c, d = rng.choice(options)
    return {c: newcomer, newcomer: d}
