from datetime import datetime, timedelta

import pytest

from scheduling import (
    MIN_SHIFT_MINUTES,
    appointment_end,
    periods_overlap,
    staff_may_change_shift,
    validate_shift_period,
)


@pytest.mark.parametrize("minutes", [60, 90, 100, 120])
def test_appointment_end_uses_service_duration(minutes):
    start = datetime(2026, 8, 22, 16, 0)
    assert appointment_end(start, minutes) == start + timedelta(minutes=minutes)


def test_period_overlap_rules_allow_adjacent_bookings():
    first_start = datetime(2026, 8, 22, 16, 0)
    first_end = datetime(2026, 8, 22, 17, 30)
    assert not periods_overlap(first_start, first_end, first_end, datetime(2026, 8, 22, 19, 0))
    assert periods_overlap(first_start, first_end, datetime(2026, 8, 22, 17, 0), datetime(2026, 8, 22, 18, 0))


def test_shift_must_be_at_least_two_hours():
    start = datetime(2026, 8, 22, 18, 0)
    with pytest.raises(ValueError):
        validate_shift_period(start, start + timedelta(minutes=MIN_SHIFT_MINUTES - 1))
    assert validate_shift_period(start, start + timedelta(minutes=MIN_SHIFT_MINUTES)) == (
        start,
        start + timedelta(minutes=MIN_SHIFT_MINUTES),
    )


def test_staff_shift_lock_is_exactly_ninety_minutes():
    now = datetime(2026, 8, 22, 16, 0)
    assert not staff_may_change_shift(datetime(2026, 8, 22, 17, 30), now=now)
    assert staff_may_change_shift(datetime(2026, 8, 22, 17, 31), now=now)
