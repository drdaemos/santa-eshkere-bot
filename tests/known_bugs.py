"""Marker for tests that document current real-usage failures.

strict=True: once the bug is fixed the test XPASSes, which fails the run, so
the marker gets removed and the test becomes a regression guard.
"""

import pytest


def known_bug(reason: str) -> pytest.MarkDecorator:
    def apply(fn):
        return pytest.mark.known_bug(pytest.mark.xfail(strict=True, reason=reason)(fn))

    return apply  # type: ignore[return-value]
