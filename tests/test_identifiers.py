from datetime import datetime

from identifiers import customer_serial, mask_phone


def test_customer_serial_uses_immutable_registration_phone_over_current_phone():
    assert customer_serial(phone="0987654321", original_phone="0912345678", grade="SR") == "SR-5678"


def test_customer_serial_falls_back_to_registered_month_and_day():
    assert customer_serial(phone="not-a-phone", original_phone="", registered_at=datetime(2026, 9, 3), grade="N") == "N-0903"
    assert customer_serial(phone="0912345678", original_phone=None, registered_at=datetime(2026, 9, 3), grade="N") == "N-0903"


def test_mask_phone_never_returns_the_complete_number():
    assert mask_phone("0912345678") == "09******78"
    assert mask_phone("invalid") is None
