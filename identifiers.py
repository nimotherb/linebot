"""Stable internal customer identifiers used by administration surfaces."""

from __future__ import annotations

import re


CUSTOMER_GRADES = ("SSR", "SR", "R", "N")


def customer_serial(
    user_id: int | None = None,
    phone: str | None = None,
    grade: str | None = None,
) -> str:
    """Return the internal ``GRADE-last4`` identifier.

    The database id is accepted only for backwards-compatible callers and is
    never included in the result.  Customer-facing responses must omit this
    internal identifier entirely.
    """
    del user_id
    normalized_grade = (grade or "N").strip().upper()
    if normalized_grade not in CUSTOMER_GRADES:
        normalized_grade = "N"
    digits = re.sub(r"\D", "", phone or "")
    suffix = digits[-4:] if len(digits) >= 4 else "????"
    return f"{normalized_grade}-{suffix}"
