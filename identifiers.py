"""Stable internal customer identifiers used by administration surfaces."""

from __future__ import annotations

import re


CUSTOMER_GRADES = ("SSR", "SR", "R", "N")
_TAIWAN_MOBILE = re.compile(r"^09\d{8}$")


def _valid_mobile_digits(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits if _TAIWAN_MOBILE.fullmatch(digits) else None


def mask_phone(value: str | None) -> str | None:
    """Return a safe display value without exposing a complete phone number."""
    digits = _valid_mobile_digits(value)
    if digits is None:
        return None
    return f"{digits[:2]}{'*' * 6}{digits[-2:]}"


def customer_serial(
    user_id: int | None = None,
    phone: str | None = None,
    grade: str | None = None,
    *,
    original_phone: str | None = None,
    registered_at=None,
) -> str:
    """Return the internal ``GRADE-last4`` identifier.

    The database id is accepted only for backwards-compatible callers and is
    never included in the result. ``original_phone`` is the immutable first
    phone captured at registration; later phone edits must not change the
    identifier. Existing callers may continue passing ``phone`` while their
    records are migrated. If no valid historical phone exists, the registered
    month/day is used as a stable four-digit fallback.
    """
    del user_id
    normalized_grade = (grade or "N").strip().upper()
    if normalized_grade not in CUSTOMER_GRADES:
        normalized_grade = "N"
    digits = _valid_mobile_digits(original_phone)
    # Legacy callers without a registration timestamp may still pass the
    # current phone. Once a record has a timestamp, an absent/invalid
    # immutable snapshot must use the deterministic MMDD fallback instead of
    # silently changing identity when the current phone changes.
    if digits is None and original_phone is None and registered_at is None:
        digits = _valid_mobile_digits(phone)
    if digits is not None:
        suffix = digits[-4:]
    elif registered_at is not None and hasattr(registered_at, "strftime"):
        suffix = registered_at.strftime("%m%d")
    else:
        suffix = "????"
    return f"{normalized_grade}-{suffix}"
