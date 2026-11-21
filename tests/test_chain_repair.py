"""Property tests for changing a finished draw: someone leaves, someone joins late.

The promise to participants: the result is still a valid draw (everyone gives
once and receives once, no self-gifts, rules respected) and as few Santas as
possible get a new assignment: one when possible, never more than two.
"""

import itertools
import random

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.services.assignment import (
    ImpossibleDraw,
    NotEnoughParticipants,
    generate_assignments,
    repair_without,
    splice_in,
)


@st.composite
def drawn_group(draw, min_size=3, max_size=8):
    """A group with rules and a valid draw for it: (pairs, forbidden)."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    ids = list(range(1, n + 1))
    all_pairs = list(itertools.combinations(ids, 2))
    rules = draw(st.lists(st.sampled_from(all_pairs), unique=True, max_size=n))
    seed = draw(st.integers(0, 2**32))
    try:
        pairs = dict(generate_assignments(ids, rules, random.Random(seed)))
    except ImpossibleDraw:
        assume(False)
    return pairs, {frozenset(r) for r in rules}


def is_valid_draw(mapping: dict[int, int], people: set[int], forbidden: set[frozenset[int]]) -> bool:
    return (
        set(mapping) == people
        and set(mapping.values()) == people
        and all(g != r and frozenset((g, r)) not in forbidden for g, r in mapping.items())
    )


def apply(pairs: dict[int, int], changes: dict[int, int], without: int | None = None) -> dict[int, int]:
    result = {g: r for g, r in pairs.items() if g != without}
    result.update(changes)
    return result


# --- someone leaves -----------------------------------------------------------


@settings(max_examples=400, deadline=None)
@given(drawn_group(min_size=4), st.data())
def test_leaving_keeps_a_valid_draw_and_touches_at_most_two_santas(case, data):
    pairs, forbidden = case
    leaver = data.draw(st.sampled_from(sorted(pairs)))
    remaining = set(pairs) - {leaver}
    try:
        changes = repair_without(pairs, leaver, [tuple(f) for f in forbidden], random.Random(0))
    except ImpossibleDraw:
        assert not small_repair_exists(pairs, leaver, forbidden), "a repair touching <= 2 Santas was missed"
        return
    assert 1 <= len(changes) <= 2
    assert set(changes) <= remaining
    assert is_valid_draw(apply(pairs, changes, without=leaver), remaining, forbidden)
    # one Santa when the simple fix works
    giver = next(g for g, r in pairs.items() if r == leaver)
    if pairs[leaver] != giver and frozenset((giver, pairs[leaver])) not in forbidden:
        assert changes == {giver: pairs[leaver]}


def small_repair_exists(pairs, leaver, forbidden) -> bool:
    """Brute force: any valid draw of the others that changes at most two Santas?"""
    remaining = set(pairs) - {leaver}
    base = {g: r for g, r in pairs.items() if g != leaver}
    for size in (1, 2):
        for changed in itertools.combinations(sorted(remaining), size):
            for receivers in itertools.product(sorted(remaining), repeat=size):
                candidate = base | dict(zip(changed, receivers, strict=True))
                if is_valid_draw(candidate, remaining, forbidden):
                    return True
    return False


def test_simple_case_only_the_leavers_santa_changes():
    # 1 -> 2 -> 3 -> 4 -> 1, person 3 leaves: 2 now gives to 4
    assert repair_without({1: 2, 2: 3, 3: 4, 4: 1}, 3) == {2: 4}


def test_mutual_pair_is_split_into_another_link():
    # 1 <-> 2 and 3 -> 4 -> 5 -> 3; 2 leaves, so 1 has neither Santa nor receiver
    changes = repair_without({1: 2, 2: 1, 3: 4, 4: 5, 5: 3}, 2, rng=random.Random(1))
    assert len(changes) == 2 and 1 in changes
    assert is_valid_draw(apply({1: 2, 2: 1, 3: 4, 4: 5, 5: 3}, changes, without=2), {1, 3, 4, 5}, set())


def test_rule_blocks_the_simple_fix():
    # 1 -> 2 -> 3 -> 4 -> 5 -> 1 and "1 and 3 never pair": 2 leaves, 1 -> 3 is forbidden
    # the only small fix: 1 -> 5 and 4 -> 3
    assert repair_without({1: 2, 2: 3, 3: 4, 4: 5, 5: 1}, 2, [(1, 3)]) == {1: 5, 4: 3}


def test_impossible_when_rules_leave_no_draw_at_all():
    # 1 -> 2 -> 3 -> 4 -> 1, "1 and 3 never pair", 2 leaves: {1, 3, 4} has no valid draw
    with pytest.raises(ImpossibleDraw):
        repair_without({1: 2, 2: 3, 3: 4, 4: 1}, 2, [(1, 3)])


def test_cannot_drop_below_three():
    with pytest.raises(NotEnoughParticipants):
        repair_without({1: 2, 2: 3, 3: 1}, 1)


# --- someone joins late -------------------------------------------------------


@settings(max_examples=400, deadline=None)
@given(drawn_group(), st.data())
def test_late_joiner_changes_exactly_one_santa(case, data):
    pairs, forbidden = case
    newcomer = max(pairs) + 1
    blocked = data.draw(st.lists(st.sampled_from(sorted(pairs)), unique=True))
    forbidden = forbidden | {frozenset((newcomer, p)) for p in blocked}
    people = set(pairs) | {newcomer}
    try:
        changes = splice_in(pairs, newcomer, [tuple(f) for f in forbidden], random.Random(0))
    except ImpossibleDraw:
        assert not any(
            frozenset((c, newcomer)) not in forbidden and frozenset((newcomer, d)) not in forbidden for c, d in pairs.items()
        )
        return
    assert newcomer in changes and len(changes) == 2
    assert is_valid_draw(apply(pairs, changes), people, forbidden)


def test_late_joiner_with_rules_against_everyone_is_impossible():
    with pytest.raises(ImpossibleDraw):
        splice_in({1: 2, 2: 3, 3: 1}, 4, [(4, 1), (4, 2), (4, 3)])


def test_splice_is_random_among_valid_links():
    seen = {tuple(sorted(splice_in({1: 2, 2: 3, 3: 1}, 4, rng=random.Random(seed)).items())) for seed in range(50)}
    assert len(seen) == 3, "every existing link should be a possible insertion point"
