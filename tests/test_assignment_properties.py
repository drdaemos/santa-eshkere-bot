"""Property tests for the draw algorithm, independent of Telegram and the DB."""

import itertools
import multiprocessing
from collections import Counter
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.services.assignment import AssignmentGenerator
from tests.known_bugs import known_bug


def people(n: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=i) for i in range(1, n + 1)]


def rules(pairs) -> list[SimpleNamespace]:
    return [SimpleNamespace(user1_id=min(a, b), user2_id=max(a, b)) for a, b in pairs]


def feasible(n: int, forbidden: set[frozenset[int]]) -> bool:
    ids = range(1, n + 1)
    return any(
        all(g != r and frozenset((g, r)) not in forbidden for g, r in zip(ids, perm, strict=True))
        for perm in itertools.permutations(ids)
    )


@st.composite
def group_with_rules(draw):
    n = draw(st.integers(min_value=3, max_value=7))
    all_pairs = list(itertools.combinations(range(1, n + 1), 2))
    chosen = draw(st.lists(st.sampled_from(all_pairs), unique=True, max_size=len(all_pairs)))
    return n, chosen


@settings(max_examples=300, deadline=None)
@given(group_with_rules())
def test_result_is_valid_or_correctly_impossible(case):
    n, pairs = case
    forbidden = {frozenset(p) for p in pairs}
    try:
        result = AssignmentGenerator.generate_assignments(people(n), rules(pairs))
    except ValueError:
        assert not feasible(n, forbidden), "reported impossible but a valid draw exists"
        return
    givers = [g for g, _ in result]
    receivers = [r for _, r in result]
    assert sorted(givers) == list(range(1, n + 1))
    assert sorted(receivers) == list(range(1, n + 1))
    for g, r in result:
        assert g != r
        assert frozenset((g, r)) not in forbidden


def test_fewer_than_three_is_rejected():
    with pytest.raises(ValueError):
        AssignmentGenerator.generate_assignments(people(2), [])


def test_every_derangement_is_reachable():
    # 4 people have 9 derangements; a fair-ish draw should hit all of them
    seen = Counter(tuple(AssignmentGenerator.generate_assignments(people(4), [])) for _ in range(600))
    assert len(seen) == 9


def _isolated_person_draw(n: int) -> None:
    # The last person is excluded from everyone: impossible, and the worst case
    # for naive backtracking, which retries every arrangement of the others.
    group = people(n)
    AssignmentGenerator.generate_assignments(group, rules((n, i) for i in range(1, n)))


@known_bug("Backtracking explores ~(n-1)! arrangements before declaring an isolated person impossible; this blocks the event loop")
def test_impossible_draw_fails_fast():
    proc = multiprocessing.get_context("spawn").Process(target=_isolated_person_draw, args=(12,))
    proc.start()
    proc.join(timeout=5)
    finished = not proc.is_alive()
    if not finished:
        proc.terminate()
        proc.join()
    assert finished, "draw with 12 participants did not finish within 5s"
