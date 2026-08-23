"""Stable public identifiers used across the Bot and administration API."""

from __future__ import annotations

import os


DEFAULT_CUSTOMER_SERIAL_START = 4800


def customer_serial(user_id: int | None) -> str:
    """Return the display-only VIP sequence without exposing the database id."""
    if user_id is None:
        return "VIP-Unknown"
    try:
        configured_start = int(os.getenv("CUSTOMER_SERIAL_START", str(DEFAULT_CUSTOMER_SERIAL_START)))
    except ValueError:
        configured_start = DEFAULT_CUSTOMER_SERIAL_START
    start = max(1, configured_start)
    return f"VIP-{start + int(user_id) - 1:04d}"
