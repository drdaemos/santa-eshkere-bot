"""Secret Santa draw: a random perfect matching givers -> receivers.

The draw is a bipartite matching problem (giver g may give to receiver r
unless g == r or {g, r} is excluded). Kuhn's augmenting-path algorithm finds
a perfect matching in O(V * E) or proves none exists, so impossible rule sets
fail instantly instead of after exploring (n-1)! arrangements. Randomness
comes from shuffling the order of givers and of each giver's candidates.
"""

import random
from collections.abc import Hashable, Iterable, Sequence
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
