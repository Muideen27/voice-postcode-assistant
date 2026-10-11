"""warm.py window parsing (no Modal calls)."""

from datetime import datetime

import pytest

from scripts.warm import MAX_MINUTES, WAT, window_minutes


def test_minutes_and_end_times() -> None:
    now = datetime(2026, 10, 15, 8, 55, tzinfo=WAT)
    assert window_minutes("90") == 90
    assert window_minutes("17:00", now) == 485  # judging day: 08:55 -> 17:00 WAT
    assert window_minutes("08:00", now) == 0  # already past: rejected by main()
    assert MAX_MINUTES == 720


@pytest.mark.parametrize("bad", ["x", "25:99"])
def test_bad_input_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        window_minutes(bad, datetime(2026, 10, 15, 9, 0, tzinfo=WAT))
