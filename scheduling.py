"""Shared scheduling rules for appointments and staff shifts.

Database timestamps are stored as naive Asia/Taipei wall-clock values for
compatibility with the existing production rows. All comparisons pass through
these helpers so a future UTC migration has one well-defined boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


TAIPEI = ZoneInfo("Asia/Taipei")
SHIFT_LOCK_MINUTES = 90
MIN_SHIFT_MINUTES = 120
BOOKING_LEAD_MINUTES = 90
CANCELLED_APPOINTMENT_STATUSES = {"cancelled", "已取消"}


def now_taipei_naive() -> datetime:
    return datetime.now(TAIPEI).replace(tzinfo=None)


def parse_local_datetime(value: str | datetime) -> datetime:
    """Return a naive Taipei datetime from LINE/API ISO input."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(TAIPEI).replace(tzinfo=None)
    return parsed.replace(second=0, microsecond=0)


def appointment_end(start: str | datetime, duration_minutes: int) -> datetime:
    if duration_minutes <= 0:
        raise ValueError("服務時間必須大於 0 分鐘")
    return parse_local_datetime(start) + timedelta(minutes=duration_minutes)


def validate_booking_start(start: str | datetime, *, now: datetime | None = None) -> datetime:
    """Every booking channel must schedule at least 90 minutes ahead."""
    current = parse_local_datetime(now or now_taipei_naive())
    start_dt = parse_local_datetime(start)
    if start_dt < current + timedelta(minutes=BOOKING_LEAD_MINUTES):
        raise ValueError("預約時間必須至少晚於現在 90 分鐘；例如 09:00 最早可預約 10:30")
    return start_dt


def periods_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    """Adjacent periods are allowed; any positive overlap is rejected."""
    return first_start < second_end and first_end > second_start


def validate_shift_period(start: str | datetime, end: str | datetime) -> tuple[datetime, datetime]:
    start_dt = parse_local_datetime(start)
    end_dt = parse_local_datetime(end)
    if end_dt <= start_dt:
        raise ValueError("排班結束時間必須晚於開始時間")
    if end_dt - start_dt < timedelta(minutes=MIN_SHIFT_MINUTES):
        raise ValueError("排班至少需要 2 小時")
    return start_dt, end_dt


def staff_may_change_shift(start: str | datetime, *, now: datetime | None = None) -> bool:
    """Staff cannot change a shift once it is within 90 minutes of starting."""
    current = parse_local_datetime(now or now_taipei_naive())
    start_dt = parse_local_datetime(start)
    return start_dt > current + timedelta(minutes=SHIFT_LOCK_MINUTES)
