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
# There is intentionally no business minimum for a shift.  A positive period
# is still required so malformed zero/negative ranges never reach MySQL.
MIN_SHIFT_MINUTES = 0
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


def parse_extended_local_datetime(value: str | datetime) -> tuple[datetime, bool]:
    """Parse a shift timestamp whose clock may be 24:00 through 48:00.

    The API accepts normal ISO datetimes as well as values such as
    ``2026-09-10T27:00``.  The returned datetime is normalized to the next
    calendar day and the boolean records that the original value crossed
    midnight.  This keeps MySQL timestamps valid while preserving the user's
    cross-day intent.
    """
    if isinstance(value, datetime):
        return parse_local_datetime(value), False
    raw = str(value).strip()
    match = __import__("re").match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$", raw)
    if match and int(match.group(2)) <= 48:
        hour = int(match.group(2))
        minute = int(match.group(3))
        if minute >= 60 or (hour == 48 and minute > 0):
            raise ValueError("時間格式錯誤，分鐘必須介於 00 到 59")
        base = parse_local_datetime(f"{match.group(1)}T{min(hour, 23):02d}:{minute:02d}:00")
        if hour >= 24:
            base += timedelta(days=1)
            base = base.replace(hour=hour - 24)
            return base, True
        return base, False
    return parse_local_datetime(value), False


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
    return start_dt, end_dt


def validate_extended_shift_period(
    start: str | datetime,
    end: str | datetime,
    *,
    is_next_day: bool = False,
) -> tuple[datetime, datetime, bool]:
    """Validate a shift and normalize an end clock in the 24:00-48:00 range."""
    start_dt, start_cross_day = parse_extended_local_datetime(start)
    end_dt, end_cross_day = parse_extended_local_datetime(end)
    cross_day = bool(is_next_day or start_cross_day or end_cross_day)
    if cross_day and not end_cross_day and end_dt <= start_dt:
        end_dt += timedelta(days=1)
    if end_dt <= start_dt:
        raise ValueError("排班結束時間必須晚於開始時間")
    if end_dt - start_dt > timedelta(hours=24):
        raise ValueError("單段排班最多支援 24 小時")
    return start_dt, end_dt, cross_day


def staff_may_change_shift(start: str | datetime, *, now: datetime | None = None) -> bool:
    """Staff cannot change a shift once it is within 90 minutes of starting."""
    current = parse_local_datetime(now or now_taipei_naive())
    start_dt = parse_local_datetime(start)
    return start_dt > current + timedelta(minutes=SHIFT_LOCK_MINUTES)
