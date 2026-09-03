"""FastAPI administration API for the Equal SPA operations dashboard.

The LINE webhook remains in ``main.py``. This module adds durable MySQL models,
role-based authentication, scheduling/room conflict checks, checkout records,
exports, and the staff no-password schedule link.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import logging
import os
import re
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scheduling import (
    CANCELLED_APPOINTMENT_STATUSES,
    appointment_end,
    now_taipei_naive,
    parse_local_datetime,
    staff_may_change_shift,
    validate_booking_start,
    validate_shift_period,
)
from identifiers import customer_serial


logger = logging.getLogger(__name__)
password_hash = PasswordHash.recommended()
DUMMY_PIN_HASH = password_hash.hash("000000-not-a-real-pin")
SESSION_HOURS = 8
MAX_LOGIN_FAILURES = 5
LOCK_MINUTES = 15
PUBLIC_BOOKING_WINDOW_MINUTES = 10
PUBLIC_BOOKING_MAX_ATTEMPTS = 8
_PUBLIC_BOOKING_ATTEMPTS: dict[str, list[datetime]] = {}
_PUBLIC_BOOKING_LOCK = threading.Lock()
LINE_USER_ID_PATTERN = re.compile(r"^U[0-9a-fA-F]{32}$")

STATUS_TO_ZH = {
    "pending": "待確認",
    "confirmed": "已確認",
    "checked_in": "已報到",
    "in_service": "服務中",
    "awaiting_checkout": "待結帳",
    "completed": "已完成",
    "cancelled": "已取消",
    "no_show": "未到店",
}
ZH_TO_STATUS = {value: key for key, value in STATUS_TO_ZH.items()}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    pin: str = Field(min_length=4, max_length=32, pattern=r"^\d+$")


class BookingDataResetIn(BaseModel):
    confirmation: Literal["DELETE_ALL_BOOKING_DATA"]


class AdminUserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    pin: str = Field(min_length=4, max_length=32, pattern=r"^\d+$")
    role: Literal["admin", "manager", "clerk"] = "clerk"
    can_override_time_rules: bool = False


class AdminUserPermissionIn(BaseModel):
    can_override_time_rules: bool


class AdminSelfUpdateIn(BaseModel):
    current_pin: str = Field(min_length=4, max_length=32, pattern=r"^\d+$")
    username: str | None = Field(default=None, min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    new_pin: str | None = Field(default=None, min_length=4, max_length=32, pattern=r"^\d+$")


class AppointmentCreateIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    service_plan_id: int
    start_time: datetime
    staff_id: int | None = None
    room_id: int | None = None
    venue_id: int | None = None
    promotion_id: int | None = None
    location_type: Literal["onsite", "external", "pending"] = "onsite"
    notes: str | None = Field(default=None, max_length=2000)


class AppointmentPatchIn(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=8, max_length=30)
    status: Literal["pending", "confirmed", "completed", "待確認", "已確認", "已完成"] | None = None
    staff_id: int | None = None
    room_id: int | None = None
    venue_id: int | None = None
    start_time: datetime | None = None
    service_plan_id: int | None = None
    promotion_id: int | None = None
    location_type: Literal["onsite", "external", "pending"] | None = None
    base_price: int | None = Field(default=None, ge=0)
    discount_amount: int | None = Field(default=None, ge=0)
    extra_amount: int | None = Field(default=None, ge=0)
    total_amount: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    force_reason: str | None = Field(default=None, max_length=500)


class ShiftCreateIn(BaseModel):
    staff_id: int
    start_time: datetime
    end_time: datetime
    source: Literal["admin", "manager", "staff_link"] = "admin"


class PublicShiftCreateIn(BaseModel):
    start_time: datetime
    end_time: datetime


class ServiceCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=30, le=480)
    price: int = Field(ge=0)
    description: str | None = Field(default=None, max_length=500)
    location_type: Literal["onsite", "external"] = "onsite"
    can_choose_staff: bool = True
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ServicePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    duration_minutes: int | None = Field(default=None, ge=30, le=480)
    price: int | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class PromotionCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    calculation_type: Literal["fixed_discount", "percent_discount", "fixed_fee", "per_30_minutes", "per_km"]
    value: int = Field(ge=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    stackable: bool = False
    description: str | None = Field(default=None, max_length=500)


class PromotionPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    calculation_type: Literal["fixed_discount", "percent_discount", "fixed_fee", "per_30_minutes", "per_km"] | None = None
    value: int | None = Field(default=None, ge=0)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    stackable: bool | None = None
    active: bool | None = None
    description: str | None = Field(default=None, max_length=500)


class CheckoutIn(BaseModel):
    amount: int = Field(ge=0)
    method: Literal["cash", "transfer"]
    received_by_staff_id: int | None = None
    note: str | None = Field(default=None, max_length=1000)


class StaffLoginIn(BaseModel):
    phone: str = Field(min_length=8, max_length=50)


class StaffMagicLoginIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class CustomerPatchIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    phones: list[str] = Field(min_length=1, max_length=10)
    customer_grade: Literal["SSR", "SR", "R", "N"] = "N"


class RoomCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RoomPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None


class VenuePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    room_name: str | None = Field(default=None, max_length=120)
    rental_cost: int | None = Field(default=None, ge=0)
    notes: str | None = None
    active: bool | None = None


class BulkDeleteIn(BaseModel):
    entity: Literal["appointments", "booking_requests", "shifts", "customers", "staff", "services", "promotions", "rooms", "venues", "users", "audit_logs"]
    ids: list[int] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=2, max_length=500)


class PublicBookingCreateIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    service_plan_id: int
    start_time: datetime
    staff_id: int | None = None
    promotion_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)
    id_token: str | None = Field(default=None, max_length=4096)
    idempotency_key: str = Field(min_length=16, max_length=80)
    source: Literal["booking_web", "official_website", "line_all_staff"] = "booking_web"
    website: str = Field(default="", max_length=0)


class BookingRequestPatchIn(BaseModel):
    staff_id: int | None = None
    service_plan_id: int | None = None
    promotion_id: int | None = None
    start_time: datetime | None = None
    customer_name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, min_length=8, max_length=30)
    notes: str | None = Field(default=None, max_length=1000)
    review_note: str | None = Field(default=None, max_length=500)


class StaffAppointmentCreateIn(AppointmentCreateIn):
    staff_id: int | None = None


class ReturnRulePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    amount: int | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, ge=30, le=480)
    active: bool | None = None


class StaffCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: Literal["straight", "gay", "bisexual"]
    line_user_id: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    return_rule_set_id: int | None = None
    photo_url: str | None = Field(default=None, max_length=1000)
    height: str | int | None = None
    weight: str | int | None = None
    role: Literal["攻擊手", "守備方", "無特定", "攻守兼備"] | None = None


class StaffStatusIn(BaseModel):
    employment_status: Literal["active", "retired"]
    reason: str = Field(min_length=1, max_length=500)


class StaffPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    category: Literal["straight", "gay", "bisexual"] | None = None
    return_rule_set_id: int | None = None
    photo_url: str | None = Field(default=None, max_length=1000)
    height: str | int | None = None
    weight: str | int | None = None
    role: Literal["攻擊手", "守備方", "無特定", "攻守兼備"] | None = None


class StaffLineLinkIn(BaseModel):
    line_user_id: str = Field(min_length=33, max_length=33)


class StaffPhotoIn(BaseModel):
    data_url: str = Field(min_length=32, max_length=4_500_000)


class VenueCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    room_name: str | None = Field(default=None, max_length=120)
    rental_cost: int = Field(default=0, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class PrivateHealthIn(BaseModel):
    prep: str | None = None
    doxy: str | None = None
    hpv: str | None = None
    mpox: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class SiteContentDraftIn(BaseModel):
    content: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=0)


class SiteContentPublishIn(BaseModel):
    expected_version: int | None = Field(default=None, ge=0)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="minutes") if value else None


def _model_dump(value: BaseModel) -> dict[str, Any]:
    """Support both Pydantic 1 and 2 while Render dependencies are upgraded."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value.dict()


def _model_dump_unset(value: BaseModel) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    return value.dict(exclude_unset=True)


def _verify_line_id_token(id_token: str) -> dict[str, str]:
    """Verify LIFF identity on LINE's server; never trust client-decoded profile data."""
    channel_id = os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()
    if not channel_id:
        raise HTTPException(status_code=503, detail="LINE LIFF 身分驗證尚未完成設定")
    request = UrlRequest(
        "https://api.line.me/oauth2/v2.1/verify",
        data=urlencode({"id_token": id_token, "client_id": channel_id}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        logger.warning("LINE ID token was rejected status=%s", exc.code)
        raise HTTPException(status_code=401, detail="LINE 登入已失效，請重新開啟預約頁") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        logger.exception("Unable to verify LINE ID token")
        raise HTTPException(status_code=503, detail="暫時無法驗證 LINE 身分，請稍後再試") from exc
    if payload.get("aud") != channel_id or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="LINE 身分驗證資料不正確")
    return {"sub": str(payload["sub"]), "name": str(payload.get("name") or "").strip()}


def _public_request_key(request: Request) -> str:
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    return (request.client.host if request.client else "unknown")[:80]


def _enforce_public_booking_rate(request: Request, phone: str) -> None:
    phone_key = re.sub(r"\D", "", phone)[-10:]
    key = f"{_public_request_key(request)}:{phone_key}"
    now = now_taipei_naive()
    cutoff = now - timedelta(minutes=PUBLIC_BOOKING_WINDOW_MINUTES)
    with _PUBLIC_BOOKING_LOCK:
        recent = [item for item in _PUBLIC_BOOKING_ATTEMPTS.get(key, []) if item > cutoff]
        if len(recent) >= PUBLIC_BOOKING_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="預約送出次數過多，請稍後再試或聯絡真人客服")
        recent.append(now)
        _PUBLIC_BOOKING_ATTEMPTS[key] = recent


def register_admin_api(
    app,
    *,
    Base,
    engine,
    SessionLocal,
    User,
    CustomerPhone,
    Staff,
    Appointment,
    appointment_notifier=None,
    booking_request_notifier=None,
    staff_line_notifier=None,
) -> None:
    """Register models, startup seeding, and all API endpoints."""

    class AdminUser(Base):
        __tablename__ = "admin_users"
        id = Column(Integer, primary_key=True)
        username = Column(String(80), unique=True, nullable=False, index=True)
        display_name = Column(String(120), nullable=False)
        pin_hash = Column(String(255), nullable=False)
        role = Column(String(30), nullable=False, default="clerk")
        line_user_id = Column(String(255), unique=True, nullable=True, index=True)
        can_override_time_rules = Column(Boolean, nullable=False, default=False)
        is_active = Column(Boolean, nullable=False, default=True)
        failed_attempts = Column(Integer, nullable=False, default=0)
        locked_until = Column(DateTime, nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class AdminSession(Base):
        __tablename__ = "admin_sessions"
        id = Column(Integer, primary_key=True)
        admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False, index=True)
        token_hash = Column(String(64), unique=True, nullable=False, index=True)
        expires_at = Column(DateTime, nullable=False, index=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        last_seen_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        user_agent = Column(String(500), nullable=True)
        ip_address = Column(String(80), nullable=True)

    class ServicePlan(Base):
        __tablename__ = "service_plans"
        id = Column(Integer, primary_key=True)
        code = Column(String(30), unique=True, nullable=False)
        name = Column(String(120), nullable=False)
        duration_minutes = Column(Integer, nullable=False)
        price = Column(Integer, nullable=False)
        description = Column(String(500), nullable=True)
        location_type = Column(String(30), nullable=False, default="onsite")
        can_choose_staff = Column(Boolean, nullable=False, default=True)
        active = Column(Boolean, nullable=False, default=True)
        effective_from = Column(DateTime, nullable=True)
        effective_to = Column(DateTime, nullable=True)
        deleted_at = Column(DateTime, nullable=True)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class Promotion(Base):
        __tablename__ = "promotions"
        id = Column(Integer, primary_key=True)
        name = Column(String(160), nullable=False)
        calculation_type = Column(String(40), nullable=False)
        value = Column(Integer, nullable=False)
        starts_at = Column(DateTime, nullable=True)
        ends_at = Column(DateTime, nullable=True)
        active = Column(Boolean, nullable=False, default=True)
        stackable = Column(Boolean, nullable=False, default=False)
        description = Column(String(500), nullable=True)
        deleted_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class Room(Base):
        __tablename__ = "rooms"
        id = Column(Integer, primary_key=True)
        name = Column(String(120), unique=True, nullable=False)
        active = Column(Boolean, nullable=False, default=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class Venue(Base):
        __tablename__ = "venues"
        id = Column(Integer, primary_key=True)
        name = Column(String(160), nullable=False)
        address = Column(String(500), nullable=True)
        room_name = Column(String(120), nullable=True)
        rental_cost = Column(Integer, nullable=False, default=0)
        notes = Column(Text, nullable=True)
        active = Column(Boolean, nullable=False, default=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class Shift(Base):
        __tablename__ = "shifts"
        id = Column(Integer, primary_key=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=False, index=True)
        start_time = Column(DateTime, nullable=False, index=True)
        end_time = Column(DateTime, nullable=False, index=True)
        status = Column(String(30), nullable=False, default="active")
        source = Column(String(30), nullable=False, default="admin")
        created_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        change_reason = Column(String(500), nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class AppointmentDetail(Base):
        __tablename__ = "appointment_details"
        id = Column(Integer, primary_key=True)
        appointment_id = Column(Integer, ForeignKey("appointments.id"), unique=True, nullable=False, index=True)
        service_plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=True)
        promotion_id = Column(Integer, ForeignKey("promotions.id"), nullable=True)
        room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
        venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True)
        service_name_snapshot = Column(String(160), nullable=True)
        promotion_name_snapshot = Column(String(160), nullable=True)
        room_name_snapshot = Column(String(160), nullable=True)
        venue_name_snapshot = Column(String(160), nullable=True)
        contact_phone = Column(String(20), nullable=True)
        base_price = Column(Integer, nullable=False, default=0)
        discount_amount = Column(Integer, nullable=False, default=0)
        extra_amount = Column(Integer, nullable=False, default=0)
        total_amount = Column(Integer, nullable=False, default=0)
        location_type = Column(String(30), nullable=False, default="onsite")
        notes = Column(Text, nullable=True)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class Payment(Base):
        __tablename__ = "payments"
        id = Column(Integer, primary_key=True)
        appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=False, index=True)
        amount = Column(Integer, nullable=False)
        method = Column(String(30), nullable=False)
        status = Column(String(30), nullable=False, default="paid")
        cash_return_status = Column(String(30), nullable=False, default="not_applicable")
        received_by_staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=True)
        confirmed_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        note = Column(Text, nullable=True)
        paid_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class AuditLog(Base):
        __tablename__ = "audit_logs"
        id = Column(Integer, primary_key=True)
        actor_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True, index=True)
        action = Column(String(100), nullable=False)
        entity_type = Column(String(80), nullable=False)
        entity_id = Column(String(120), nullable=True)
        reason = Column(String(500), nullable=True)
        before_json = Column(Text, nullable=True)
        after_json = Column(Text, nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive, index=True)

    class StaffScheduleToken(Base):
        __tablename__ = "staff_schedule_tokens"
        id = Column(Integer, primary_key=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), unique=True, nullable=False, index=True)
        token_hash = Column(String(64), unique=True, nullable=False, index=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)
        revoked_at = Column(DateTime, nullable=True)

    class StaffPrivateHealth(Base):
        __tablename__ = "staff_private_health"
        id = Column(Integer, primary_key=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), unique=True, nullable=False, index=True)
        encrypted_payload = Column(Text, nullable=False)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class StaffSession(Base):
        __tablename__ = "staff_sessions"
        id = Column(Integer, primary_key=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=False, index=True)
        token_hash = Column(String(64), unique=True, nullable=False, index=True)
        expires_at = Column(DateTime, nullable=False, index=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class StaffMagicLink(Base):
        __tablename__ = "staff_magic_links"
        id = Column(Integer, primary_key=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=False, index=True)
        token_hash = Column(String(64), unique=True, nullable=False, index=True)
        expires_at = Column(DateTime, nullable=False, index=True)
        used_at = Column(DateTime, nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class StaffPhoto(Base):
        __tablename__ = "staff_photos"
        id = Column(Integer, primary_key=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), unique=True, nullable=False, index=True)
        mime_type = Column(String(50), nullable=False)
        data_base64 = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class DeletedStaffIdentity(Base):
        __tablename__ = "deleted_staff_identities"
        id = Column(Integer, primary_key=True)
        normalized_name = Column(String(255), unique=True, nullable=False, index=True)
        original_name = Column(String(255), nullable=False)
        deleted_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        reason = Column(String(500), nullable=True)
        deleted_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class RevokedStaffLine(Base):
        __tablename__ = "revoked_staff_lines"
        id = Column(Integer, primary_key=True)
        line_user_id = Column(String(255), unique=True, nullable=False, index=True)
        staff_name = Column(String(255), nullable=False)
        revoked_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        revoked_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class ReturnRuleSet(Base):
        __tablename__ = "return_rule_sets"
        id = Column(Integer, primary_key=True)
        code = Column(String(40), unique=True, nullable=False)
        name = Column(String(160), nullable=False)
        active = Column(Boolean, nullable=False, default=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class ReturnRule(Base):
        __tablename__ = "return_rules"
        id = Column(Integer, primary_key=True)
        rule_set_id = Column(Integer, ForeignKey("return_rule_sets.id"), nullable=False, index=True)
        service_code = Column(String(30), nullable=False)
        name = Column(String(160), nullable=False)
        amount = Column(Integer, nullable=False)
        duration_minutes = Column(Integer, nullable=False)
        active = Column(Boolean, nullable=False, default=True)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)

    class StaffReturn(Base):
        __tablename__ = "staff_returns"
        id = Column(Integer, primary_key=True)
        appointment_id = Column(Integer, ForeignKey("appointments.id"), unique=True, nullable=False, index=True)
        staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=False, index=True)
        rule_id = Column(Integer, ForeignKey("return_rules.id"), nullable=True)
        amount = Column(Integer, nullable=False, default=0)
        status = Column(String(30), nullable=False, default="pending")
        confirmed_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        confirmed_at = Column(DateTime, nullable=True)
        note = Column(Text, nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive)

    class PublicBookingRequest(Base):
        __tablename__ = "public_booking_requests"
        id = Column(Integer, primary_key=True)
        idempotency_key = Column(String(80), unique=True, nullable=False, index=True)
        appointment_id = Column(Integer, ForeignKey("appointments.id"), unique=True, nullable=True, index=True)
        source = Column(String(30), nullable=False, default="web")
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive, index=True)

    class BookingRequest(Base):
        __tablename__ = "booking_requests"
        id = Column(Integer, primary_key=True)
        idempotency_key = Column(String(80), unique=True, nullable=False, index=True)
        user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
        requested_staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=True, index=True)
        service_plan_id = Column(Integer, ForeignKey("service_plans.id"), nullable=False)
        promotion_id = Column(Integer, ForeignKey("promotions.id"), nullable=True)
        start_time = Column(DateTime, nullable=False, index=True)
        end_time = Column(DateTime, nullable=False)
        contact_phone = Column(String(20), nullable=False)
        notes = Column(Text, nullable=True)
        source = Column(String(30), nullable=False, default="booking_web")
        status = Column(String(30), nullable=False, default="pending", index=True)
        appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True, index=True)
        reviewed_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        review_note = Column(String(500), nullable=True)
        created_at = Column(DateTime, nullable=False, default=now_taipei_naive, index=True)
        reviewed_at = Column(DateTime, nullable=True)

    class SiteContent(Base):
        __tablename__ = "site_contents"
        id = Column(Integer, primary_key=True)
        content_key = Column(String(80), unique=True, nullable=False, index=True)
        draft_json = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
        published_json = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
        draft_version = Column(Integer, nullable=False, default=0)
        published_version = Column(Integer, nullable=False, default=0)
        updated_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        published_by_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
        updated_at = Column(DateTime, nullable=False, default=now_taipei_naive, onupdate=now_taipei_naive)
        published_at = Column(DateTime, nullable=True)

    app.state.admin_models = {
        "AdminUser": AdminUser,
        "AdminSession": AdminSession,
        "ServicePlan": ServicePlan,
        "Promotion": Promotion,
        "Room": Room,
        "Venue": Venue,
        "Shift": Shift,
        "AppointmentDetail": AppointmentDetail,
        "Payment": Payment,
        "AuditLog": AuditLog,
        "StaffScheduleToken": StaffScheduleToken,
        "StaffPrivateHealth": StaffPrivateHealth,
        "StaffSession": StaffSession,
        "StaffMagicLink": StaffMagicLink,
        "StaffPhoto": StaffPhoto,
        "DeletedStaffIdentity": DeletedStaffIdentity,
        "RevokedStaffLine": RevokedStaffLine,
        "ReturnRuleSet": ReturnRuleSet,
        "ReturnRule": ReturnRule,
        "StaffReturn": StaffReturn,
        "PublicBookingRequest": PublicBookingRequest,
        "BookingRequest": BookingRequest,
        "SiteContent": SiteContent,
    }

    def normalize_phone(value: str | None) -> str:
        cleaned = re.sub(r"[\s()\-]", "", (value or "").strip())
        if cleaned.startswith("+886"):
            cleaned = "0" + cleaned[4:]
        if not re.fullmatch(r"09\d{8}", cleaned):
            raise HTTPException(status_code=422, detail="手機號碼必須是 09 開頭的 10 碼數字")
        return cleaned

    def normalize_staff_measurement(value: str | int | None, *, label: str, minimum: int, maximum: int) -> str | None:
        cleaned = str(value).strip() if value is not None else ""
        if not cleaned:
            return None
        if not re.fullmatch(r"\d{2,3}", cleaned) or not minimum <= int(cleaned) <= maximum:
            raise HTTPException(status_code=422, detail=f"{label}請填 {minimum} 到 {maximum} 的整數")
        return cleaned

    def unique_staff_phone(db: Session, value: str, *, exclude_staff_id: int | None = None) -> str:
        phone = normalize_phone(value)
        query = db.query(Staff).filter(Staff.phone == phone)
        if exclude_staff_id is not None:
            query = query.filter(Staff.id != exclude_staff_id)
        if query.first():
            raise HTTPException(status_code=409, detail="此手機 ID 已綁定其他師傅")
        return phone

    def customer_phone_rows(db: Session, customer) -> list:
        rows = db.query(CustomerPhone).filter(CustomerPhone.user_id == customer.id).order_by(CustomerPhone.is_primary.desc(), CustomerPhone.id).all()
        if not rows and customer.phone:
            try:
                normalized = normalize_phone(customer.phone)
            except HTTPException:
                return []
            owner = db.query(CustomerPhone).filter(CustomerPhone.phone == normalized).first()
            if not owner:
                owner = CustomerPhone(user_id=customer.id, phone=normalized, is_primary=True)
                db.add(owner)
                db.flush()
                rows = [owner]
        return rows

    def customer_for_phone(db: Session, phone: str):
        normalized = normalize_phone(phone)
        record = db.query(CustomerPhone).filter(CustomerPhone.phone == normalized).first()
        if record:
            return db.query(User).filter(User.id == record.user_id).first(), normalized
        return db.query(User).filter(User.phone == normalized).first(), normalized

    def sync_customer_phones(db: Session, customer, values: list[str]) -> list[str]:
        normalized_values = list(dict.fromkeys(normalize_phone(value) for value in values))
        for phone in normalized_values:
            owner = db.query(CustomerPhone).filter(CustomerPhone.phone == phone, CustomerPhone.user_id != customer.id).first()
            if owner:
                raise HTTPException(status_code=409, detail=f"手機號碼 {phone} 已屬於其他客戶")
        existing = {row.phone: row for row in db.query(CustomerPhone).filter(CustomerPhone.user_id == customer.id).all()}
        for phone, row in existing.items():
            if phone not in normalized_values:
                db.delete(row)
        for index, phone in enumerate(normalized_values):
            row = existing.get(phone)
            if row:
                row.is_primary = index == 0
            else:
                db.add(CustomerPhone(user_id=customer.id, phone=phone, is_primary=index == 0))
        customer.phone = normalized_values[0]
        return normalized_values

    def attach_customer_phone(db: Session, customer, phone: str) -> str:
        normalized = normalize_phone(phone)
        owner = db.query(CustomerPhone).filter(CustomerPhone.phone == normalized).first()
        if owner and owner.user_id != customer.id:
            raise HTTPException(status_code=409, detail="此手機號碼已綁定其他客戶，請聯絡真人客服協助合併")
        if not owner:
            db.add(CustomerPhone(user_id=customer.id, phone=normalized, is_primary=not bool(customer.phone)))
        if not customer.phone:
            customer.phone = normalized
        return normalized

    def resolve_public_customer(db: Session, payload: PublicBookingCreateIn):
        phone_customer, contact_phone = customer_for_phone(db, payload.phone)
        line_identity = _verify_line_id_token(payload.id_token) if payload.id_token else None
        customer = None
        if line_identity:
            customer = db.query(User).filter(User.line_user_id == line_identity["sub"]).first()
            if customer and phone_customer and customer.id != phone_customer.id:
                raise HTTPException(status_code=409, detail="LINE 帳號與手機屬於不同客戶，請聯絡真人客服協助合併")
            if not customer and phone_customer:
                if not str(phone_customer.line_user_id).startswith("manual:"):
                    raise HTTPException(status_code=409, detail="此手機已綁定其他 LINE，請聯絡真人客服")
                phone_customer.line_user_id = line_identity["sub"]
                customer = phone_customer
            if not customer:
                customer = User(
                    line_user_id=line_identity["sub"],
                    phone=contact_phone,
                    display_name=line_identity.get("name") or payload.customer_name.strip(),
                    customer_grade="R",
                )
                db.add(customer)
                db.flush()
            attach_customer_phone(db, customer, contact_phone)
            if not getattr(customer, "display_name", None):
                customer.display_name = line_identity.get("name") or payload.customer_name.strip()
            if getattr(customer, "customer_grade", "N") not in {"SSR", "SR"}:
                customer.customer_grade = "R"
            return customer, contact_phone, "liff"

        customer = phone_customer
        if not customer:
            customer = User(
                line_user_id=f"manual:{secrets.token_hex(16)}",
                phone=contact_phone,
                display_name=payload.customer_name.strip(),
                customer_grade="R",
            )
            db.add(customer)
            db.flush()
        attach_customer_phone(db, customer, contact_phone)
        if not getattr(customer, "display_name", None):
            customer.display_name = payload.customer_name.strip()
        if getattr(customer, "customer_grade", "N") not in {"SSR", "SR"}:
            customer.customer_grade = "R"
        return customer, contact_phone, "web"

    def available_staff(db: Session, start_dt: datetime, end_dt: datetime) -> list:
        # One correlated NOT EXISTS query replaces the former 1 + (2 × staff)
        # round trips. With 47 staff the old code could issue roughly 95 SQL
        # statements for a single availability check.
        appointment_conflict = db.query(Appointment.id).filter(
            Appointment.staff_id == Staff.id,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
            Appointment.start_time < end_dt,
            Appointment.end_time > start_dt,
        ).exists()
        return db.query(Staff).join(Shift, Shift.staff_id == Staff.id).filter(
            Staff.employment_status == "active",
            Shift.status == "active",
            Shift.start_time <= start_dt,
            Shift.end_time >= end_dt,
            ~appointment_conflict,
        ).distinct().order_by(Staff.name).all()

    app.state.available_staff = available_staff

    def room_capacity_available(db: Session, start_dt: datetime, end_dt: datetime) -> bool:
        room_count = db.query(Room).filter(Room.active.is_(True)).count()
        if room_count < 1:
            return False
        overlapping = db.query(Appointment).join(
            AppointmentDetail, AppointmentDetail.appointment_id == Appointment.id,
        ).filter(
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
            AppointmentDetail.location_type.in_(["onsite", "pending"]),
            Appointment.start_time < end_dt,
            Appointment.end_time > start_dt,
        ).count()
        return overlapping < room_count

    def issue_staff_magic_link(staff_obj, db: Session) -> str:
        raw_token = secrets.token_urlsafe(40)
        db.query(StaffMagicLink).filter(StaffMagicLink.staff_id == staff_obj.id, StaffMagicLink.used_at.is_(None)).update({StaffMagicLink.used_at: now_taipei_naive()})
        db.add(StaffMagicLink(
            staff_id=staff_obj.id,
            token_hash=_token_hash(raw_token),
            expires_at=now_taipei_naive() + timedelta(minutes=15),
        ))
        db.commit()
        return raw_token

    app.state.issue_staff_magic_link = issue_staff_magic_link

    allowed_origins = [value.strip() for value in os.getenv("ADMIN_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if value.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
    )

    def audit(
        db: Session,
        actor: Any | None,
        action: str,
        entity_type: str,
        entity_id: Any = None,
        *,
        reason: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> None:
        db.add(AuditLog(
            actor_user_id=getattr(actor, "id", None),
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            reason=reason,
            before_json=_json(before) if before is not None else None,
            after_json=_json(after) if after is not None else None,
        ))

    def permanently_delete_staff(
        staff_id: int,
        db: Session,
        *,
        actor_id: int | None = None,
        reason: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        item = db.query(Staff).filter(Staff.id == staff_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")

        actor = db.query(AdminUser).filter(AdminUser.id == actor_id).first() if actor_id else None
        normalized_name = item.name.strip().casefold()
        if normalized_name and not db.query(DeletedStaffIdentity).filter(DeletedStaffIdentity.normalized_name == normalized_name).first():
            db.add(DeletedStaffIdentity(
                normalized_name=normalized_name,
                original_name=item.name,
                deleted_by_user_id=actor_id,
                reason=reason,
            ))

        before = staff_dict(item)
        db.query(Appointment).filter(Appointment.staff_id == staff_id).update({
            Appointment.staff_name_snapshot: item.name,
            Appointment.staff_id: None,
        }, synchronize_session=False)
        db.query(BookingRequest).filter(BookingRequest.requested_staff_id == staff_id).update({BookingRequest.requested_staff_id: None}, synchronize_session=False)
        db.query(Payment).filter(Payment.received_by_staff_id == staff_id).update({Payment.received_by_staff_id: None}, synchronize_session=False)
        db.query(StaffReturn).filter(StaffReturn.staff_id == staff_id).delete(synchronize_session=False)
        db.query(Shift).filter(Shift.staff_id == staff_id).delete(synchronize_session=False)
        if item.line_user_id and not item.line_user_id.startswith(("pending:", "seeded:")) and not db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == item.line_user_id).first():
            db.add(RevokedStaffLine(line_user_id=item.line_user_id, staff_name=item.name, revoked_by_user_id=actor_id))
        for model in (StaffScheduleToken, StaffPrivateHealth, StaffSession, StaffMagicLink, StaffPhoto):
            db.query(model).filter(model.staff_id == staff_id).delete(synchronize_session=False)
        deleted_name = item.name
        db.delete(item)
        audit(db, actor, "permanent_delete", "staff", staff_id, reason=reason, before=before)
        if commit:
            db.commit()
        else:
            db.flush()
        return {"ok": True, "deleted_staff_id": staff_id, "deleted_staff_name": deleted_name}

    app.state.permanently_delete_staff = permanently_delete_staff

    def delete_appointment_record(db: Session, appointment_id: int) -> None:
        item = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到預約")
        db.query(StaffReturn).filter(StaffReturn.appointment_id == appointment_id).delete(synchronize_session=False)
        db.query(Payment).filter(Payment.appointment_id == appointment_id).delete(synchronize_session=False)
        db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment_id).delete(synchronize_session=False)
        db.query(BookingRequest).filter(BookingRequest.appointment_id == appointment_id).delete(synchronize_session=False)
        db.query(PublicBookingRequest).filter(PublicBookingRequest.appointment_id == appointment_id).delete(synchronize_session=False)
        db.delete(item)

    def delete_customer_record(db: Session, customer_id: int) -> None:
        item = db.query(User).filter(User.id == customer_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到客戶")
        appointment_ids = [row[0] for row in db.query(Appointment.id).filter(Appointment.user_id == customer_id).all()]
        for appointment_id in appointment_ids:
            delete_appointment_record(db, appointment_id)
        db.query(BookingRequest).filter(BookingRequest.user_id == customer_id).delete(synchronize_session=False)
        db.query(CustomerPhone).filter(CustomerPhone.user_id == customer_id).delete(synchronize_session=False)
        db.delete(item)

    def delete_service_record(db: Session, service_id: int) -> None:
        item = db.query(ServicePlan).filter(ServicePlan.id == service_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到服務方案")
        db.query(AppointmentDetail).filter(AppointmentDetail.service_plan_id == service_id).update({
            AppointmentDetail.service_name_snapshot: item.name,
            AppointmentDetail.service_plan_id: None,
        }, synchronize_session=False)
        db.query(BookingRequest).filter(BookingRequest.service_plan_id == service_id).delete(synchronize_session=False)
        db.delete(item)

    def delete_promotion_record(db: Session, promotion_id: int) -> None:
        item = db.query(Promotion).filter(Promotion.id == promotion_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到優惠")
        db.query(AppointmentDetail).filter(AppointmentDetail.promotion_id == promotion_id).update({
            AppointmentDetail.promotion_name_snapshot: item.name,
            AppointmentDetail.promotion_id: None,
        }, synchronize_session=False)
        db.query(BookingRequest).filter(BookingRequest.promotion_id == promotion_id).update({BookingRequest.promotion_id: None}, synchronize_session=False)
        db.delete(item)

    def delete_room_record(db: Session, room_id: int) -> None:
        item = db.query(Room).filter(Room.id == room_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到房間")
        db.query(AppointmentDetail).filter(AppointmentDetail.room_id == room_id).update({
            AppointmentDetail.room_name_snapshot: item.name,
            AppointmentDetail.room_id: None,
        }, synchronize_session=False)
        db.delete(item)

    def delete_venue_record(db: Session, venue_id: int) -> None:
        item = db.query(Venue).filter(Venue.id == venue_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到場地")
        db.query(AppointmentDetail).filter(AppointmentDetail.venue_id == venue_id).update({
            AppointmentDetail.venue_name_snapshot: item.name,
            AppointmentDetail.venue_id: None,
        }, synchronize_session=False)
        db.delete(item)

    def delete_admin_user_record(db: Session, user_id: int, actor) -> None:
        item = db.query(AdminUser).filter(AdminUser.id == user_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到後台帳號")
        if item.id == actor.id:
            raise HTTPException(status_code=422, detail="不能刪除目前登入中的自己")
        if item.role == "admin" and db.query(AdminUser).filter(AdminUser.role == "admin", AdminUser.id != item.id).count() == 0:
            raise HTTPException(status_code=422, detail="系統至少必須保留一個 Admin")
        db.query(AdminSession).filter(AdminSession.admin_user_id == user_id).delete(synchronize_session=False)
        for model, column in (
            (Shift, Shift.created_by_user_id),
            (BookingRequest, BookingRequest.reviewed_by_user_id),
            (Payment, Payment.confirmed_by_user_id),
            (StaffReturn, StaffReturn.confirmed_by_user_id),
            (AuditLog, AuditLog.actor_user_id),
            (DeletedStaffIdentity, DeletedStaffIdentity.deleted_by_user_id),
            (RevokedStaffLine, RevokedStaffLine.revoked_by_user_id),
            (SiteContent, SiteContent.updated_by_user_id),
            (SiteContent, SiteContent.published_by_user_id),
        ):
            db.query(model).filter(column == user_id).update({column: None}, synchronize_session=False)
        db.delete(item)

    def unlink_staff_line(staff_id: int, db: Session, *, actor_id: int | None = None):
        item = db.query(Staff).filter(Staff.id == staff_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")
        actor = db.query(AdminUser).filter(AdminUser.id == actor_id).first() if actor_id else None
        before = staff_dict(item)
        previous_line_user_id = item.line_user_id
        if previous_line_user_id and not previous_line_user_id.startswith(("pending:", "seeded:")) and not db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == previous_line_user_id).first():
            db.add(RevokedStaffLine(line_user_id=previous_line_user_id, staff_name=item.name, revoked_by_user_id=actor_id))
        item.line_user_id = f"pending:{secrets.token_hex(16)}"
        db.query(StaffSession).filter(StaffSession.staff_id == staff_id).delete(synchronize_session=False)
        db.query(StaffMagicLink).filter(StaffMagicLink.staff_id == staff_id).delete(synchronize_session=False)
        audit(db, actor, "line_unlink", "staff", staff_id, before=before, after={"line_connected": False})
        db.commit()
        return item

    app.state.unlink_staff_line = unlink_staff_line

    def bind_staff_line(
        staff_id: int,
        line_user_id: str,
        db: Session,
        *,
        actor_id: int | None = None,
        source: str = "管理後台",
    ):
        normalized_line_id = (line_user_id or "").strip()
        if not LINE_USER_ID_PATTERN.fullmatch(normalized_line_id):
            raise HTTPException(status_code=422, detail="LINE User ID 必須是 U 開頭加 32 位十六進位字元")

        item = db.query(Staff).filter(Staff.id == staff_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")
        duplicate = db.query(Staff).filter(Staff.line_user_id == normalized_line_id, Staff.id != staff_id).first()
        if duplicate:
            raise HTTPException(status_code=409, detail=f"這個 LINE 已綁定師傅 {duplicate.name}，請先解除原連結")

        actor = db.query(AdminUser).filter(AdminUser.id == actor_id).first() if actor_id else None
        before = staff_dict(item)
        previous_line_user_id = item.line_user_id
        if (
            previous_line_user_id
            and previous_line_user_id != normalized_line_id
            and not previous_line_user_id.startswith(("pending:", "seeded:"))
            and not db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == previous_line_user_id).first()
        ):
            db.add(RevokedStaffLine(
                line_user_id=previous_line_user_id,
                staff_name=item.name,
                revoked_by_user_id=actor_id,
            ))

        item.line_user_id = normalized_line_id
        db.query(RevokedStaffLine).filter(RevokedStaffLine.line_user_id == normalized_line_id).delete(synchronize_session=False)
        db.query(StaffSession).filter(StaffSession.staff_id == staff_id).delete(synchronize_session=False)
        db.query(StaffMagicLink).filter(StaffMagicLink.staff_id == staff_id).delete(synchronize_session=False)
        db.flush()

        if not staff_line_notifier:
            db.rollback()
            raise HTTPException(status_code=503, detail="派單 LINE Bot 尚未設定，未完成串接")
        try:
            staff_line_notifier(item, normalized_line_id, source=source)
        except Exception as exc:
            db.rollback()
            logger.exception("Unable to verify staff LINE binding staff_id=%s", staff_id)
            raise HTTPException(status_code=502, detail="通知無法送達此 LINE，未完成串接；請確認 LINE User ID 且已加入派單 Bot") from exc

        audit(
            db,
            actor,
            "line_link" if previous_line_user_id != normalized_line_id else "line_link_verify",
            "staff",
            staff_id,
            reason=source,
            before=before,
            after={**staff_dict(item), "notification_sent": True},
        )
        db.commit()
        return item

    app.state.bind_staff_line = bind_staff_line

    def decode_site_content(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            logger.exception("Unable to decode stored site content")
            return {}
        return decoded if isinstance(decoded, dict) else {}

    def encode_site_content(content: dict[str, Any]) -> str:
        encoded = _json(content)
        if len(encoded.encode("utf-8")) > 512 * 1024:
            raise HTTPException(status_code=413, detail="官網內容超過 512 KB，圖片請改存網址，不要直接貼入資料")
        return encoded

    def site_content_payload(item) -> dict[str, Any]:
        return {
            "content_key": item.content_key,
            "draft": decode_site_content(item.draft_json),
            "published": decode_site_content(item.published_json),
            "draft_version": item.draft_version,
            "published_version": item.published_version,
            "updated_at": _iso(item.updated_at),
            "published_at": _iso(item.published_at),
        }

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def current_admin(
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="尚未登入")
        raw_token = authorization.split(" ", 1)[1].strip()
        session = db.query(AdminSession).filter(AdminSession.token_hash == _token_hash(raw_token)).first()
        now = now_taipei_naive()
        if not session or session.expires_at <= now:
            if session:
                db.delete(session)
                db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登入已過期")
        user = db.query(AdminUser).filter(AdminUser.id == session.admin_user_id, AdminUser.is_active.is_(True)).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="帳號已停用")
        session.last_seen_at = now
        db.commit()
        return user

    def current_staff(
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="尚未選擇員工身分")
        raw_token = authorization.split(" ", 1)[1].strip()
        session = db.query(StaffSession).filter(StaffSession.token_hash == _token_hash(raw_token)).first()
        now = now_taipei_naive()
        if not session or session.expires_at <= now:
            if session:
                db.delete(session)
                db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="員工身分已過期")
        staff_obj = db.query(Staff).filter(Staff.id == session.staff_id, Staff.employment_status == "active").first()
        if not staff_obj:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="員工帳號目前不可使用")
        return staff_obj

    def require_roles(*roles: str) -> Callable:
        def dependency(user=Depends(current_admin)):
            if user.role not in roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="權限不足")
            return user
        return dependency

    def serialize_admin(user) -> dict[str, Any]:
        return {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
            "can_override_time_rules": user.role in {"admin", "manager"} or bool(getattr(user, "can_override_time_rules", False)),
        }

    def actor_can_override_time_rules(actor, db: Session) -> bool:
        if getattr(actor, "role", None) in {"admin", "manager"}:
            return True
        actor_id = getattr(actor, "id", None)
        account = db.query(AdminUser).filter(AdminUser.id == actor_id).first() if actor_id else None
        return bool(account and (account.role in {"admin", "manager"} or account.can_override_time_rules))

    def line_admin_identity(line_user_id: str, db: Session):
        user = db.query(AdminUser).filter(AdminUser.line_user_id == line_user_id, AdminUser.is_active.is_(True), AdminUser.role.in_(["admin", "manager"])).first()
        return serialize_admin(user) if user else None

    def bind_line_admin(line_user_id: str, pin: str, db: Session):
        candidates = db.query(AdminUser).filter(AdminUser.is_active.is_(True), AdminUser.role.in_(["admin", "manager"])).all()
        matched = None
        for candidate in candidates:
            if password_hash.verify(pin, candidate.pin_hash):
                matched = candidate
                break
        if not matched:
            return None
        existing = db.query(AdminUser).filter(AdminUser.line_user_id == line_user_id, AdminUser.id != matched.id).all()
        for item in existing:
            item.line_user_id = None
        matched.line_user_id = line_user_id
        audit(db, matched, "line_bind", "admin_user", matched.id)
        db.commit()
        return serialize_admin(matched)

    def unbind_line_admin(line_user_id: str, db: Session):
        user = db.query(AdminUser).filter(AdminUser.line_user_id == line_user_id).first()
        if not user:
            return None
        identity = serialize_admin(user)
        user.line_user_id = None
        audit(db, user, "line_unbind", "admin_user", user.id)
        db.commit()
        return identity

    def create_line_clerk(
        actor_id: int,
        username: str,
        display_name: str,
        pin: str,
        db: Session,
    ):
        actor = db.query(AdminUser).filter(
            AdminUser.id == actor_id,
            AdminUser.is_active.is_(True),
            AdminUser.role.in_(["admin", "manager"]),
        ).first()
        if not actor:
            raise HTTPException(status_code=403, detail="只有 Admin 或店長可新增客服帳號")
        normalized_username = (username or "").strip()
        normalized_name = (display_name or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]{3,80}", normalized_username):
            raise HTTPException(status_code=422, detail="客服帳號須為 3 至 80 位英數字、句點、底線或減號")
        if not normalized_name or len(normalized_name) > 120:
            raise HTTPException(status_code=422, detail="客服名稱不可空白且最多 120 字")
        if not re.fullmatch(r"\d{4}", pin or ""):
            raise HTTPException(status_code=422, detail="客服 PIN 必須是自訂 4 位數字")
        if db.query(AdminUser).filter(AdminUser.username == normalized_username).first():
            raise HTTPException(status_code=409, detail="登入帳號已存在")
        item = AdminUser(
            username=normalized_username,
            display_name=normalized_name,
            pin_hash=password_hash.hash(pin),
            role="clerk",
            is_active=True,
        )
        db.add(item)
        db.flush()
        audit(db, actor, "create_from_line", "admin_user", item.id, after=serialize_admin(item))
        db.commit()
        return serialize_admin(item)

    app.state.line_admin_identity = line_admin_identity
    app.state.bind_line_admin = bind_line_admin
    app.state.unbind_line_admin = unbind_line_admin
    app.state.create_line_clerk = create_line_clerk

    def service_dict(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "duration_minutes": item.duration_minutes,
            "price": item.price,
            "description": item.description,
            "location_type": item.location_type,
            "can_choose_staff": item.can_choose_staff,
            "active": item.active,
            "effective_from": _iso(item.effective_from),
            "effective_to": _iso(item.effective_to),
            "deleted_at": _iso(item.deleted_at),
        }

    def promotion_dict(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "calculation_type": item.calculation_type,
            "value": item.value,
            "active": item.active,
            "starts_at": _iso(item.starts_at),
            "ends_at": _iso(item.ends_at),
            "stackable": item.stackable,
            "description": item.description,
            "deleted_at": _iso(item.deleted_at),
        }

    def staff_dict(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "phone": item.phone,
            "category": getattr(item, "category", None),
            "employment_status": getattr(item, "employment_status", "active"),
            "line_connected": not item.line_user_id.startswith(("pending:", "seeded:")) if item.line_user_id else False,
            "is_online": bool(getattr(item, "is_online", False)),
            "online_start_time": _iso(getattr(item, "online_start_time", None)),
            "height": item.height,
            "weight": item.weight,
            "photo_url": getattr(item, "photo_url", None),
            "role": item.role,
            "return_rule_set_id": getattr(item, "return_rule_set_id", None),
        }

    def return_rule_sets_dict(db: Session) -> list[dict[str, Any]]:
        rule_sets = db.query(ReturnRuleSet).order_by(ReturnRuleSet.id).all()
        rules_by_set: dict[int, list] = {item.id: [] for item in rule_sets}
        for rule in db.query(ReturnRule).order_by(ReturnRule.rule_set_id, ReturnRule.id).all():
            rules_by_set.setdefault(rule.rule_set_id, []).append(rule)
        result = []
        for rule_set in rule_sets:
            rules = rules_by_set.get(rule_set.id, [])
            result.append({
                "id": rule_set.id,
                "code": rule_set.code,
                "name": rule_set.name,
                "active": rule_set.active,
                "rules": [{"id": rule.id, "service_code": rule.service_code, "name": rule.name, "amount": rule.amount, "duration_minutes": rule.duration_minutes, "active": rule.active} for rule in rules],
            })
        return result

    def promotion_discount(item, base_price: int) -> int:
        if not item or not item.active:
            return 0
        now = now_taipei_naive()
        if item.starts_at and item.starts_at > now:
            return 0
        if item.ends_at and item.ends_at < now:
            return 0
        if item.calculation_type == "fixed_discount":
            return min(base_price, item.value)
        if item.calculation_type == "percent_discount":
            return min(base_price, round(base_price * item.value / 100))
        return 0

    def return_rule_for_appointment(db: Session, appointment, detail=None):
        if not appointment.staff_id:
            return None
        staff_obj = db.query(Staff).filter(Staff.id == appointment.staff_id).first()
        rule_set_id = getattr(staff_obj, "return_rule_set_id", None) if staff_obj else None
        if not rule_set_id:
            first_set = db.query(ReturnRuleSet).filter(ReturnRuleSet.active.is_(True)).order_by(ReturnRuleSet.id).first()
            rule_set_id = first_set.id if first_set else None
        if not rule_set_id:
            return None
        if detail is None:
            detail = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment.id).first()
        plan = db.query(ServicePlan).filter(ServicePlan.id == detail.service_plan_id).first() if detail and detail.service_plan_id else None
        code = plan.code if plan else (appointment.plan_name or "").split("-", 1)[0]
        if code == "OUT":
            code = "E"
        return db.query(ReturnRule).filter(ReturnRule.rule_set_id == rule_set_id, ReturnRule.service_code == code, ReturnRule.active.is_(True)).first()

    def shift_dict(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "staff_id": item.staff_id,
            "start_time": _iso(item.start_time),
            "end_time": _iso(item.end_time),
            "status": item.status,
            "source": item.source,
            "locked": not staff_may_change_shift(item.start_time),
        }

    def appointment_price_from_legacy(appointment) -> int:
        fallback = {60: 2000, 90: 2500, 100: 3200, 120: 3000}
        return fallback.get(appointment.duration, 0)

    def _model_map(db: Session, model, ids: set[int]) -> dict[int, Any]:
        if not ids:
            return {}
        return {row.id: row for row in db.query(model).filter(model.id.in_(ids)).all()}

    def appointment_cache(db: Session, items: list) -> dict[str, Any]:
        appointment_ids = {item.id for item in items}
        details = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id.in_(appointment_ids)).all() if appointment_ids else []
        detail_map = {item.appointment_id: item for item in details}
        plans = _model_map(db, ServicePlan, {item.service_plan_id for item in details if item.service_plan_id})
        promotions = _model_map(db, Promotion, {item.promotion_id for item in details if item.promotion_id})
        rooms = _model_map(db, Room, {item.room_id for item in details if item.room_id})
        venues = _model_map(db, Venue, {item.venue_id for item in details if item.venue_id})
        users = _model_map(db, User, {item.user_id for item in items})
        staff = _model_map(db, Staff, {item.staff_id for item in items if item.staff_id})

        payment_map: dict[int, Any] = {}
        if appointment_ids:
            for payment in db.query(Payment).filter(
                Payment.appointment_id.in_(appointment_ids), Payment.status == "paid",
            ).order_by(Payment.appointment_id, Payment.id.desc()).all():
                payment_map.setdefault(payment.appointment_id, payment)
        staff_return_map = {
            item.appointment_id: item for item in db.query(StaffReturn).filter(StaffReturn.appointment_id.in_(appointment_ids)).all()
        } if appointment_ids else {}
        active_rule_sets = db.query(ReturnRuleSet).filter(ReturnRuleSet.active.is_(True)).order_by(ReturnRuleSet.id).all()
        rules = db.query(ReturnRule).filter(ReturnRule.active.is_(True)).order_by(ReturnRule.id).all()
        return {
            "details": detail_map,
            "plans": plans,
            "promotions": promotions,
            "rooms": rooms,
            "venues": venues,
            "users": users,
            "staff": staff,
            "payments": payment_map,
            "staff_returns": staff_return_map,
            "default_rule_set_id": active_rule_sets[0].id if active_rule_sets else None,
            "rules": {(item.rule_set_id, item.service_code): item for item in rules},
        }

    def appointment_dict(db: Session, item, cache: dict[str, Any] | None = None) -> dict[str, Any]:
        cache = cache or appointment_cache(db, [item])
        detail = cache["details"].get(item.id)
        plan = cache["plans"].get(detail.service_plan_id) if detail and detail.service_plan_id else None
        promotion = cache["promotions"].get(detail.promotion_id) if detail and detail.promotion_id else None
        room = cache["rooms"].get(detail.room_id) if detail and detail.room_id else None
        venue = cache["venues"].get(detail.venue_id) if detail and detail.venue_id else None
        user = cache["users"].get(item.user_id)
        staff_obj = cache["staff"].get(item.staff_id) if item.staff_id else None
        payment = cache["payments"].get(item.id)
        staff_return = cache["staff_returns"].get(item.id)
        rule_set_id = getattr(staff_obj, "return_rule_set_id", None) or cache["default_rule_set_id"]
        service_code = plan.code if plan else (item.plan_name or "").split("-", 1)[0]
        return_rule = cache["rules"].get((rule_set_id, "E" if service_code == "OUT" else service_code)) if rule_set_id else None
        phone = (detail.contact_phone if detail and detail.contact_phone else getattr(user, "phone", None)) or getattr(item, "customer_phone_snapshot", None)
        grade = getattr(user, "customer_grade", "N") if user else "N"
        canonical_status = "pending" if item.status == "pending" else "completed" if item.status == "completed" else "confirmed"
        return {
            "id": item.id,
            "order_id": f"AP-{item.start_time.strftime('%m%d')}-{item.id:03d}",
            "customer_id": item.user_id,
            "customer_serial": customer_serial(item.user_id, phone, grade),
            "customer_grade": grade,
            "customer_name": getattr(user, "display_name", None) or getattr(item, "customer_name_snapshot", None) or "未命名客戶",
            "phone": phone,
            "staff_id": item.staff_id,
            "staff_name": staff_obj.name if staff_obj else getattr(item, "staff_name_snapshot", None) or "未指定",
            "service_plan_id": plan.id if plan else None,
            "service_name": plan.name if plan else (getattr(detail, "service_name_snapshot", None) if detail else None) or item.plan_name or "未知方案",
            "promotion_id": promotion.id if promotion else None,
            "promotion_name": promotion.name if promotion else (getattr(detail, "promotion_name_snapshot", None) if detail else None),
            "duration_minutes": item.duration,
            "start_time": _iso(item.start_time),
            "end_time": _iso(item.end_time),
            "status": canonical_status,
            "status_label": STATUS_TO_ZH[canonical_status],
            "room_id": detail.room_id if detail else None,
            "room_name": room.name if room else (getattr(detail, "room_name_snapshot", None) if detail else None),
            "venue_id": detail.venue_id if detail else None,
            "venue_name": venue.name if venue else (getattr(detail, "venue_name_snapshot", None) if detail else None),
            "location_type": detail.location_type if detail else "pending",
            "base_price": detail.base_price if detail else appointment_price_from_legacy(item),
            "discount_amount": detail.discount_amount if detail else 0,
            "extra_amount": detail.extra_amount if detail else 0,
            "total_amount": detail.total_amount if detail else appointment_price_from_legacy(item),
            "notes": detail.notes if detail else None,
            "payment_status": payment.status if payment else "unpaid",
            "payment_method": payment.method if payment else None,
            "cash_return_status": payment.cash_return_status if payment else None,
            "expected_return_amount": staff_return.amount if staff_return else (return_rule.amount if return_rule else 0),
            "staff_return_status": staff_return.status if staff_return else "not_created",
        }

    def appointment_dicts(db: Session, items: list, *, public: bool = False) -> list[dict[str, Any]]:
        cache = appointment_cache(db, items)
        return [public_appointment_dict(db, item, cache) if public else appointment_dict(db, item, cache) for item in items]

    def public_appointment_dict(db: Session, item, cache: dict[str, Any] | None = None) -> dict[str, Any]:
        row = appointment_dict(db, item, cache)
        for key in ("customer_id", "customer_serial", "customer_name", "phone", "base_price", "discount_amount", "extra_amount", "total_amount", "notes", "payment_method", "cash_return_status", "expected_return_amount", "staff_return_status"):
            row.pop(key, None)
        row["customer_name"] = "已隱藏"
        row["phone"] = None
        row["total_amount"] = 0
        row["notes"] = None
        return row

    def customer_cache(db: Session, items: list) -> dict[str, Any]:
        user_ids = {item.id for item in items}
        phones_by_user: dict[int, list[str]] = {user_id: [] for user_id in user_ids}
        if user_ids:
            phone_rows = db.query(CustomerPhone).filter(CustomerPhone.user_id.in_(user_ids)).order_by(
                CustomerPhone.user_id, CustomerPhone.is_primary.desc(), CustomerPhone.id,
            ).all()
            for row in phone_rows:
                phones_by_user.setdefault(row.user_id, []).append(row.phone)
        visits_by_user: dict[int, list] = {user_id: [] for user_id in user_ids}
        visits = db.query(Appointment).filter(
            Appointment.user_id.in_(user_ids),
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
        ).all() if user_ids else []
        for appointment in visits:
            visits_by_user.setdefault(appointment.user_id, []).append(appointment)
        appointment_ids = {item.id for item in visits}
        details = {
            item.appointment_id: item for item in db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id.in_(appointment_ids)).all()
        } if appointment_ids else {}
        return {"phones": phones_by_user, "visits": visits_by_user, "details": details}

    def customer_dict(db: Session, item, cache: dict[str, Any] | None = None) -> dict[str, Any]:
        cache = cache or customer_cache(db, [item])
        visits = cache["visits"].get(item.id, [])
        spent = sum(
            cache["details"][appointment.id].total_amount if appointment.id in cache["details"] else appointment_price_from_legacy(appointment)
            for appointment in visits
        )
        phones = cache["phones"].get(item.id, [])
        return {
            "id": item.id,
            "customer_grade": getattr(item, "customer_grade", "N"),
            "vip_serial": customer_serial(item.id, phones[0] if phones else item.phone, getattr(item, "customer_grade", "N")),
            "display_name": getattr(item, "display_name", None),
            "primary_phone": phones[0] if phones else item.phone,
            "phones": phones or ([item.phone] if item.phone else []),
            "visits": len(visits),
            "spent": spent,
            "last_visit": _iso(max((appointment.start_time for appointment in visits), default=None)),
        }

    def customer_dicts(db: Session, items: list) -> list[dict[str, Any]]:
        cache = customer_cache(db, items)
        return [customer_dict(db, item, cache) for item in items]

    def booking_request_cache(db: Session, items: list) -> dict[str, dict[int, Any]]:
        return {
            "customers": _model_map(db, User, {item.user_id for item in items}),
            "staff": _model_map(db, Staff, {item.requested_staff_id for item in items if item.requested_staff_id}),
            "plans": _model_map(db, ServicePlan, {item.service_plan_id for item in items}),
            "promotions": _model_map(db, Promotion, {item.promotion_id for item in items if item.promotion_id}),
            "reviewers": _model_map(db, AdminUser, {item.reviewed_by_user_id for item in items if item.reviewed_by_user_id}),
        }

    def booking_request_dict(db: Session, item, cache: dict[str, dict[int, Any]] | None = None) -> dict[str, Any]:
        cache = cache or booking_request_cache(db, [item])
        customer = cache["customers"].get(item.user_id)
        staff_obj = cache["staff"].get(item.requested_staff_id) if item.requested_staff_id else None
        plan = cache["plans"].get(item.service_plan_id)
        promotion = cache["promotions"].get(item.promotion_id) if item.promotion_id else None
        reviewer = cache["reviewers"].get(item.reviewed_by_user_id) if item.reviewed_by_user_id else None
        return {
            "id": item.id,
            "request_id": f"BR-{item.start_time.strftime('%m%d')}-{item.id:03d}",
            "customer_id": item.user_id,
            "customer_serial": customer_serial(item.user_id, item.contact_phone, getattr(customer, "customer_grade", "N")),
            "customer_grade": getattr(customer, "customer_grade", "N"),
            "customer_name": getattr(customer, "display_name", None) or "未命名客戶",
            "phone": item.contact_phone,
            "staff_id": item.requested_staff_id,
            "staff_name": staff_obj.name if staff_obj else "未指定",
            "service_plan_id": item.service_plan_id,
            "service_name": plan.name if plan else "未知方案",
            "promotion_id": item.promotion_id,
            "promotion_name": promotion.name if promotion else None,
            "start_time": _iso(item.start_time),
            "end_time": _iso(item.end_time),
            "status": item.status,
            "status_label": {"pending": "待客服確認", "confirmed": "已轉正式訂單", "cancelled": "已取消"}.get(item.status, item.status),
            "source": item.source,
            "notes": item.notes,
            "appointment_id": item.appointment_id,
            "review_note": item.review_note,
            "reviewed_by": reviewer.display_name if reviewer else None,
            "created_at": _iso(item.created_at),
            "reviewed_at": _iso(item.reviewed_at),
        }

    def booking_request_dicts(db: Session, items: list) -> list[dict[str, Any]]:
        cache = booking_request_cache(db, items)
        return [booking_request_dict(db, item, cache) for item in items]

    def staff_appointment_conflict(db: Session, staff_id: int, start: datetime, end: datetime, exclude_id: int | None = None):
        query = db.query(Appointment).filter(
            Appointment.staff_id == staff_id,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
            Appointment.start_time < end,
            Appointment.end_time > start,
        )
        if exclude_id:
            query = query.filter(Appointment.id != exclude_id)
        return query.first()

    def room_appointment_conflict(db: Session, room_id: int, start: datetime, end: datetime, exclude_id: int | None = None):
        query = db.query(Appointment).join(AppointmentDetail, AppointmentDetail.appointment_id == Appointment.id).filter(
            AppointmentDetail.room_id == room_id,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
            Appointment.start_time < end,
            Appointment.end_time > start,
        )
        if exclude_id:
            query = query.filter(Appointment.id != exclude_id)
        return query.first()

    def shift_conflict(db: Session, staff_id: int, start: datetime, end: datetime, exclude_id: int | None = None):
        query = db.query(Shift).filter(
            Shift.staff_id == staff_id,
            Shift.status == "active",
            Shift.start_time < end,
            Shift.end_time > start,
        )
        if exclude_id:
            query = query.filter(Shift.id != exclude_id)
        return query.first()

    def create_booking_request_record(
        db: Session,
        *,
        customer,
        contact_phone: str,
        service_plan_id: int,
        start_time: datetime,
        staff_id: int | None,
        promotion_id: int | None,
        notes: str | None,
        source: str,
        idempotency_key: str,
    ):
        existing = db.query(BookingRequest).filter(BookingRequest.idempotency_key == idempotency_key).first()
        if existing:
            return existing, True
        plan = db.query(ServicePlan).filter(ServicePlan.id == service_plan_id, ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        promotion = None
        if promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == promotion_id, Promotion.active.is_(True), Promotion.deleted_at.is_(None)).first()
            if not promotion or promotion_discount(promotion, plan.price) <= 0:
                raise HTTPException(status_code=404, detail="這個優惠目前無法使用")
        staff_obj = None
        if staff_id:
            staff_obj = db.query(Staff).filter(Staff.id == staff_id, Staff.employment_status == "active").first()
            if not staff_obj:
                raise HTTPException(status_code=404, detail="找不到可提出預約通知的師傅")
        start_dt = parse_local_datetime(start_time)
        try:
            validate_booking_start(start_dt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        item = BookingRequest(
            idempotency_key=idempotency_key,
            user_id=customer.id,
            requested_staff_id=staff_obj.id if staff_obj else None,
            service_plan_id=plan.id,
            promotion_id=promotion.id if promotion else None,
            start_time=start_dt,
            end_time=appointment_end(start_dt, plan.duration_minutes),
            contact_phone=contact_phone,
            notes=(notes or "").strip() or None,
            source=source,
            status="pending",
        )
        db.add(item)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            duplicate = db.query(BookingRequest).filter(BookingRequest.idempotency_key == idempotency_key).first()
            if duplicate:
                return duplicate, True
            raise HTTPException(status_code=409, detail="預約通知正在處理中，請勿重複送出")
        audit(db, None, "create_booking_request", "booking_request", item.id, reason=source, after=booking_request_dict(db, item))
        db.commit()
        db.refresh(item)
        if booking_request_notifier:
            try:
                booking_request_notifier(item, db, origin=source)
            except Exception:
                logger.exception("Unable to push booking request notification booking_request_id=%s", item.id)
        return item, False

    def confirm_booking_request_record(request_id: int, db: Session, actor=None):
        item = db.query(BookingRequest).filter(BookingRequest.id == request_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到預約通知")
        if item.status == "confirmed" and item.appointment_id:
            appointment = db.query(Appointment).filter(Appointment.id == item.appointment_id).first()
            return item, appointment, True
        if item.status != "pending":
            raise HTTPException(status_code=409, detail="這筆預約通知已處理")
        override_time_rules = actor_can_override_time_rules(actor, db)
        if not override_time_rules and item.start_time <= now_taipei_naive():
            raise HTTPException(status_code=422, detail="預約時間已過，請先修改時間")
        plan = db.query(ServicePlan).filter(ServicePlan.id == item.service_plan_id, ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).first()
        if not plan:
            raise HTTPException(status_code=422, detail="原服務方案已停用，請先修改預約通知")
        staff_obj = None
        if item.requested_staff_id:
            staff_obj = db.query(Staff).filter(Staff.id == item.requested_staff_id, Staff.employment_status == "active").first()
            if not staff_obj:
                raise HTTPException(status_code=422, detail="原指定師傅已停用，請先修改預約通知")
            conflict = None if override_time_rules else staff_appointment_conflict(db, staff_obj.id, item.start_time, item.end_time)
            if conflict:
                raise HTTPException(status_code=409, detail=f"指定師傅與訂單 AP-{conflict.id} 時間重疊，請先修改")
        customer_conflict = None if override_time_rules else db.query(Appointment).filter(
            Appointment.user_id == item.user_id,
            Appointment.start_time == item.start_time,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
        ).first()
        if customer_conflict:
            raise HTTPException(status_code=409, detail=f"客戶同時段已有訂單 AP-{customer_conflict.id}")
        promotion = db.query(Promotion).filter(Promotion.id == item.promotion_id).first() if item.promotion_id else None
        discount = promotion_discount(promotion, plan.price)
        appointment = Appointment(
            user_id=item.user_id,
            staff_id=item.requested_staff_id,
            duration=plan.duration_minutes,
            plan_name=f"{plan.code}-{plan.name}",
            start_time=item.start_time,
            end_time=item.end_time,
            status="confirmed",
            customer_name_snapshot=getattr(db.query(User).filter(User.id == item.user_id).first(), "display_name", None),
            customer_phone_snapshot=item.contact_phone,
            staff_name_snapshot=staff_obj.name if item.requested_staff_id else None,
        )
        db.add(appointment)
        db.flush()
        db.add(AppointmentDetail(
            appointment_id=appointment.id,
            service_plan_id=plan.id,
            promotion_id=promotion.id if promotion else None,
            service_name_snapshot=plan.name,
            promotion_name_snapshot=promotion.name if promotion else None,
            contact_phone=item.contact_phone,
            base_price=plan.price,
            discount_amount=discount,
            total_amount=max(0, plan.price - discount),
            location_type="external" if plan.location_type == "external" else "pending",
            notes=f"由預約通知 {booking_request_dict(db, item)['request_id']} 確認成立" + (f"\n客戶備註：{item.notes}" if item.notes else ""),
        ))
        item.status = "confirmed"
        item.appointment_id = appointment.id
        item.reviewed_by_user_id = getattr(actor, "id", None)
        item.reviewed_at = now_taipei_naive()
        audit(db, actor, "confirm", "booking_request", item.id, after={"appointment_id": appointment.id})
        db.commit()
        db.refresh(appointment)
        if appointment_notifier:
            try:
                appointment_notifier(appointment, db, origin="客服確認預約通知")
            except Exception:
                logger.exception("Unable to push confirmed booking request appointment_id=%s", appointment.id)
        return item, appointment, False

    def cancel_booking_request_record(request_id: int, db: Session, actor=None, review_note: str | None = None):
        item = db.query(BookingRequest).filter(BookingRequest.id == request_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到預約通知")
        if item.status == "confirmed":
            raise HTTPException(status_code=409, detail="已成立正式訂單，請改到訂單管理取消")
        if item.status == "cancelled":
            return item
        item.status = "cancelled"
        item.review_note = (review_note or "").strip() or None
        item.reviewed_by_user_id = getattr(actor, "id", None)
        item.reviewed_at = now_taipei_naive()
        audit(db, actor, "cancel", "booking_request", item.id, reason=item.review_note)
        db.commit()
        return item

    app.state.create_booking_request_record = create_booking_request_record
    app.state.confirm_booking_request_record = confirm_booking_request_record
    app.state.cancel_booking_request_record = cancel_booking_request_record

    def require_fernet():
        key = os.getenv("STAFF_HEALTH_ENCRYPTION_KEY")
        if not key:
            raise HTTPException(status_code=503, detail="尚未設定 STAFF_HEALTH_ENCRYPTION_KEY")
        try:
            from cryptography.fernet import Fernet
            return Fernet(key.encode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="健康資料加密金鑰無效") from exc

    @app.on_event("startup")
    def seed_admin_data():
        db = SessionLocal()
        try:
            initial_users = [
                ("admin", "Admin", "admin", os.getenv("ADMIN_INITIAL_PIN") or "0206"),
                ("jerry", "Jerry", "manager", os.getenv("MANAGER_INITIAL_PIN") or "1355"),
            ]
            existing_usernames = {row[0] for row in db.query(AdminUser.username).all()}
            for username, display_name, role_name, pin in initial_users:
                if username in existing_usernames:
                    continue
                if not pin:
                    logger.warning("%s was not seeded because its initial PIN environment variable is missing", username)
                    continue
                db.add(AdminUser(username=username, display_name=display_name, role=role_name, pin_hash=password_hash.hash(pin)))

            seed_plans = [
                ("A", "舒壓方案", 60, 1500, "不指定優惠／指壓或油壓", "onsite", False),
                ("B", "愉悅方案", 60, 2000, "可指定師傅／體推與機能保養", "onsite", True),
                ("C", "享受方案", 90, 2500, "可指定師傅／體推與機能保養", "onsite", True),
                ("D", "極緻方案", 120, 3000, "指壓、油壓、體推與機能保養", "onsite", True),
                ("OUT", "隨享外出方案", 100, 3200, "含獅子林起算三公里", "external", True),
            ]
            existing_plan_codes = {row[0] for row in db.query(ServicePlan.code).all()}
            for code, name, duration, price, description, location, choose_staff in seed_plans:
                if code not in existing_plan_codes:
                    db.add(ServicePlan(code=code, name=name, duration_minutes=duration, price=price, description=description, location_type=location, can_choose_staff=choose_staff))

            legacy_room_names = {"房間 1": "657上", "房間 2": "657下"}
            for old_name, new_name in legacy_room_names.items():
                room = db.query(Room).filter(Room.name == old_name).first()
                if room and not db.query(Room).filter(Room.name == new_name).first():
                    room.name = new_name
            existing_room_names = {row[0] for row in db.query(Room.name).all()}
            for room_name in ("657上", "657下"):
                if room_name not in existing_room_names:
                    db.add(Room(name=room_name))

            existing_venue_names = {row[0] for row in db.query(Venue.name).all()}
            for venue_name in ("外租旅館", "外出場地"):
                if venue_name not in existing_venue_names:
                    db.add(Venue(name=venue_name, address=None, room_name=None, rental_cost=0))

            seed_promotions = [
                ("生日月優惠", "fixed_discount", 300, "當月壽星出示證明可使用。"),
                ("新進師傅體驗優惠", "fixed_discount", 200, "預約新進師傅的期間限定體驗折扣。"),
                ("平日下午優惠", "fixed_discount", 200, "週一至週五 17:00 前指定時段適用。"),
                ("首次到店優惠", "fixed_discount", 200, "第一次完成預約的客戶適用。"),
                ("好友推薦優惠", "fixed_discount", 200, "由既有客戶推薦的新客可使用。"),
                ("午夜服務費", "fixed_fee", 600, "午夜時段的服務附加費。"),
                ("預約加時（每 30 分鐘）", "per_30_minutes", 500, "預約時先選擇的加時費。"),
                ("現場加時（每 30 分鐘）", "per_30_minutes", 700, "服務現場臨時增加的加時費。"),
                ("外出里程費（每公里）", "per_km", 80, "超出基本距離後按公里計算。"),
            ]
            existing_promotion_names = {row[0] for row in db.query(Promotion.name).all()}
            for name, calculation_type, value, description in seed_promotions:
                if name not in existing_promotion_names:
                    db.add(Promotion(name=name, calculation_type=calculation_type, value=value, description=description))

            return_tables = [
                ("TABLE_1", "回帳表一（A–E／借房）", [("A", "A方案", 700, 60), ("B", "B方案", 800, 60), ("C", "C方案", 1000, 90), ("D", "D方案", 1200, 120), ("E", "E方案", 1200, 100), ("BORROW", "借房", 300, 60)]),
                ("TABLE_2", "回帳表二（A–D）", [("A", "A方案", 300, 60), ("B", "B方案", 300, 60), ("C", "C方案", 400, 90), ("D", "D方案", 500, 120)]),
            ]
            rule_sets_by_code = {item.code: item for item in db.query(ReturnRuleSet).all()}
            for code, name, rules in return_tables:
                rule_set = rule_sets_by_code.get(code)
                if not rule_set:
                    rule_set = ReturnRuleSet(code=code, name=name)
                    db.add(rule_set)
                    rule_sets_by_code[code] = rule_set
            db.flush()
            existing_rule_keys = {(row.rule_set_id, row.service_code) for row in db.query(ReturnRule).all()}
            for code, _name, rules in return_tables:
                rule_set = rule_sets_by_code[code]
                for service_code, rule_name, amount, duration in rules:
                    if (rule_set.id, service_code) not in existing_rule_keys:
                        db.add(ReturnRule(rule_set_id=rule_set.id, service_code=service_code, name=rule_name, amount=amount, duration_minutes=duration))
            if "official_site" not in {row[0] for row in db.query(SiteContent.content_key).all()}:
                db.add(SiteContent(content_key="official_site"))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Unable to seed admin data")
        finally:
            db.close()

    @app.get("/api/admin/health")
    def admin_health():
        return {"status": "ok", "service": "equalspa-admin-api", "time": _iso(now_taipei_naive())}

    @app.get("/api/public/site-content")
    def public_site_content(db: Session = Depends(get_db)):
        item = db.query(SiteContent).filter(SiteContent.content_key == "official_site").first()
        if not item:
            return {"content": {}, "version": 0, "published_at": None}
        return {
            "content": decode_site_content(item.published_json),
            "version": item.published_version,
            "published_at": _iso(item.published_at),
        }

    @app.get("/api/public/therapists")
    def public_therapists(db: Session = Depends(get_db)):
        items = db.query(Staff).filter(Staff.employment_status == "active").order_by(Staff.name).all()
        return [{
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "height": item.height,
            "weight": item.weight,
            "role": item.role,
            "photo_url": item.photo_url,
        } for item in items]

    @app.get("/api/public/staff/{staff_id}/photo")
    def public_staff_photo(staff_id: int, db: Session = Depends(get_db)):
        photo = db.query(StaffPhoto).filter(StaffPhoto.staff_id == staff_id).first()
        if not photo:
            raise HTTPException(status_code=404, detail="找不到師傅照片")
        try:
            content = base64.b64decode(photo.data_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=500, detail="照片資料已損壞") from exc
        return Response(
            content=content,
            media_type=photo.mime_type,
            headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"},
        )

    @app.get("/api/public/booking/options")
    def public_booking_options(db: Session = Depends(get_db)):
        now = now_taipei_naive()
        services = db.query(ServicePlan).filter(ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).order_by(ServicePlan.id).all()
        promotions = db.query(Promotion).filter(
            Promotion.active.is_(True),
            Promotion.deleted_at.is_(None),
            Promotion.calculation_type.in_(["fixed_discount", "percent_discount"]),
        ).order_by(Promotion.id).all()
        promotions = [item for item in promotions if (not item.starts_at or item.starts_at <= now) and (not item.ends_at or item.ends_at >= now)]
        liff_id = os.getenv("LINE_LIFF_ID", "").strip()
        return {
            "services": [service_dict(item) for item in services],
            "promotions": [promotion_dict(item) for item in promotions],
            "staff": [{
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "employment_status": item.employment_status,
                "line_connected": False,
                "height": item.height,
                "weight": item.weight,
                "photo_url": item.photo_url,
            } for item in db.query(Staff).filter(Staff.employment_status == "active").order_by(Staff.name).all()],
            "minimum_lead_minutes": 90,
            "support_url": os.getenv("CUSTOMER_SERVICE_URL", "https://lin.ee/vOq3Xvt"),
            "liff_id": liff_id or None,
            "line_login_enabled": bool(liff_id and os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()),
        }

    @app.get("/api/public/booking/availability")
    def public_booking_availability(
        service_plan_id: int,
        start_time: datetime,
        requested_staff_id: int | None = None,
        request_only: bool = False,
        db: Session = Depends(get_db),
    ):
        plan = db.query(ServicePlan).filter(ServicePlan.id == service_plan_id, ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        start_dt = parse_local_datetime(start_time)
        try:
            validate_booking_start(start_dt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        end_dt = appointment_end(start_dt, plan.duration_minutes)
        staff_items = available_staff(db, start_dt, end_dt)
        if request_only and requested_staff_id:
            requested_staff = db.query(Staff).filter(Staff.id == requested_staff_id, Staff.employment_status == "active").first()
            if not requested_staff:
                raise HTTPException(status_code=404, detail="指定師傅目前無法提出預約通知")
            available_ids = {item.id for item in staff_items}
            return {
                "start_time": _iso(start_dt),
                "end_time": _iso(end_dt),
                "can_choose_staff": True,
                "request_only": True,
                "available_for_instant_booking": requested_staff.id in available_ids and (plan.location_type != "onsite" or room_capacity_available(db, start_dt, end_dt)),
                "staff": [{"id": requested_staff.id, "name": requested_staff.name, "category": requested_staff.category}],
            }
        if not staff_items:
            raise HTTPException(status_code=409, detail="這個時段目前沒有可預約師傅，請改選其他時間")
        if plan.location_type == "onsite" and not room_capacity_available(db, start_dt, end_dt):
            raise HTTPException(status_code=409, detail="這個時段兩間房都已使用，請改選其他時間")
        return {
            "start_time": _iso(start_dt),
            "end_time": _iso(end_dt),
            "can_choose_staff": plan.can_choose_staff,
            "staff": [{"id": item.id, "name": item.name, "category": item.category} for item in staff_items],
        }

    @app.post("/api/public/booking/requests", status_code=201)
    def create_public_booking_request(payload: PublicBookingCreateIn, request: Request, db: Session = Depends(get_db)):
        _enforce_public_booking_rate(request, payload.phone)
        customer, contact_phone, identity_source = resolve_public_customer(db, payload)
        source = payload.source if payload.source != "booking_web" else ("booking_web_liff" if identity_source == "liff" else "booking_web")
        item, duplicate = create_booking_request_record(
            db,
            customer=customer,
            contact_phone=contact_phone,
            service_plan_id=payload.service_plan_id,
            start_time=payload.start_time,
            staff_id=payload.staff_id,
            promotion_id=payload.promotion_id,
            notes=payload.notes,
            source=source,
            idempotency_key=payload.idempotency_key,
        )
        receipt = booking_request_dict(db, item)
        receipt.pop("customer_id", None)
        receipt.pop("customer_serial", None)
        receipt.pop("customer_grade", None)
        return {"duplicate": duplicate, "booking_request": receipt}

    @app.post("/api/staff/auth/login")
    def staff_login(payload: StaffLoginIn, db: Session = Depends(get_db)):
        phone = normalize_phone(payload.phone)
        matches = db.query(Staff).filter(
            Staff.phone == phone,
            Staff.employment_status == "active",
        ).limit(2).all()
        if not matches:
            raise HTTPException(status_code=401, detail="手機 ID 不正確或員工帳號已停用")
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail="此手機 ID 綁定多位師傅，請聯絡店長修正")
        staff_obj = matches[0]
        raw_token = secrets.token_urlsafe(40)
        db.add(StaffSession(staff_id=staff_obj.id, token_hash=_token_hash(raw_token), expires_at=now_taipei_naive() + timedelta(hours=24)))
        audit(db, None, "staff_login", "staff", staff_obj.id, reason="passwordless staff identity")
        db.commit()
        return {"access_token": raw_token, "expires_in": 86400, "staff": {"id": staff_obj.id, "name": staff_obj.name, "role": "staff"}}

    @app.post("/api/staff/auth/line")
    def staff_line_login(payload: StaffMagicLoginIn, db: Session = Depends(get_db)):
        now = now_taipei_naive()
        link = db.query(StaffMagicLink).filter(
            StaffMagicLink.token_hash == _token_hash(payload.token),
            StaffMagicLink.used_at.is_(None),
            StaffMagicLink.expires_at > now,
        ).with_for_update().first()
        if not link:
            raise HTTPException(status_code=401, detail="LINE 登入連結已失效，請回到派單 Bot 重新輸入「後台」")
        staff_obj = db.query(Staff).filter(Staff.id == link.staff_id, Staff.employment_status == "active").first()
        if not staff_obj:
            raise HTTPException(status_code=401, detail="員工帳號目前不可使用")
        raw_token = secrets.token_urlsafe(40)
        link.used_at = now
        db.add(StaffSession(staff_id=staff_obj.id, token_hash=_token_hash(raw_token), expires_at=now + timedelta(hours=24)))
        audit(db, None, "staff_line_login", "staff", staff_obj.id, reason="signed LINE magic link")
        db.commit()
        return {"access_token": raw_token, "expires_in": 86400, "staff": {"id": staff_obj.id, "name": staff_obj.name, "role": "staff"}}

    @app.post("/api/staff/auth/logout")
    def staff_logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            session = db.query(StaffSession).filter(StaffSession.token_hash == _token_hash(token)).first()
            if session:
                db.delete(session)
                db.commit()
        return {"ok": True}

    @app.get("/api/staff/bootstrap")
    def staff_bootstrap(db: Session = Depends(get_db), staff_obj=Depends(current_staff)):
        appointments = db.query(Appointment).filter(Appointment.staff_id == staff_obj.id).order_by(Appointment.start_time.desc()).limit(300).all()
        shifts = db.query(Shift).filter(Shift.staff_id == staff_obj.id, Shift.status == "active").order_by(Shift.start_time).limit(500).all()
        return {
            "mode": "staff",
            "staff_user": {"id": staff_obj.id, "name": staff_obj.name, "role": "staff"},
            "appointments": appointment_dicts(db, appointments),
            "staff": [staff_dict(staff_obj)],
            "shifts": [shift_dict(item) | {"staff_name": staff_obj.name} for item in shifts],
            "services": [service_dict(item) for item in db.query(ServicePlan).filter(ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).order_by(ServicePlan.id).all()],
            "promotions": [promotion_dict(item) for item in db.query(Promotion).filter(Promotion.active.is_(True), Promotion.deleted_at.is_(None)).order_by(Promotion.id).all()],
            "rooms": [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).filter(Room.active.is_(True)).order_by(Room.id).all()],
            "customers": [],
            "admin_users": [],
            "return_rule_sets": [],
        }

    @app.patch("/api/staff/appointments/{appointment_id}/complete")
    def staff_complete_appointment(appointment_id: int, db: Session = Depends(get_db), staff_obj=Depends(current_staff)):
        _ = (appointment_id, db, staff_obj)
        raise HTTPException(status_code=403, detail="訂單完成與回帳已合併，請由店長或後台管理人員標記已完成")

    @app.post("/api/admin/auth/login")
    def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
        username = payload.username.strip().lower()
        user = db.query(AdminUser).filter(AdminUser.username == username).first()
        now = now_taipei_naive()
        if user and user.locked_until and user.locked_until > now:
            raise HTTPException(status_code=429, detail="登入錯誤次數過多，請稍後再試")
        valid = password_hash.verify(payload.pin, user.pin_hash if user else DUMMY_PIN_HASH)
        if not user or not valid or not user.is_active:
            if user:
                user.failed_attempts += 1
                if user.failed_attempts >= MAX_LOGIN_FAILURES:
                    user.failed_attempts = 0
                    user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                db.commit()
            raise HTTPException(status_code=401, detail="帳號或 PIN 錯誤")

        user.failed_attempts = 0
        user.locked_until = None
        raw_token = secrets.token_urlsafe(40)
        db.add(AdminSession(
            admin_user_id=user.id,
            token_hash=_token_hash(raw_token),
            expires_at=now + timedelta(hours=SESSION_HOURS),
            user_agent=request.headers.get("user-agent", "")[:500],
            ip_address=(request.client.host if request.client else None),
        ))
        audit(db, user, "login", "admin_user", user.id)
        db.commit()
        return {"access_token": raw_token, "token_type": "bearer", "expires_in": SESSION_HOURS * 3600, "user": serialize_admin(user)}

    @app.post("/api/admin/auth/logout")
    def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            session = db.query(AdminSession).filter(AdminSession.token_hash == _token_hash(token)).first()
            if session:
                db.delete(session)
                db.commit()
        return {"ok": True}

    @app.get("/api/admin/auth/me")
    def me(user=Depends(current_admin)):
        return serialize_admin(user)

    @app.patch("/api/admin/auth/me")
    def update_me(payload: AdminSelfUpdateIn, db: Session = Depends(get_db), user=Depends(current_admin)):
        if not password_hash.verify(payload.current_pin, user.pin_hash):
            raise HTTPException(status_code=401, detail="目前 PIN 不正確")
        before = serialize_admin(user)
        if payload.username:
            username = payload.username.strip().lower()
            duplicate = db.query(AdminUser).filter(AdminUser.username == username, AdminUser.id != user.id).first()
            if duplicate:
                raise HTTPException(status_code=409, detail="登入帳號已存在")
            user.username = username
        if payload.display_name:
            user.display_name = payload.display_name.strip()
        if payload.new_pin:
            user.pin_hash = password_hash.hash(payload.new_pin)
        audit(db, user, "update_own_credentials", "admin_user", user.id, before=before, after=serialize_admin(user))
        db.query(AdminSession).filter(AdminSession.admin_user_id == user.id).delete(synchronize_session=False)
        db.commit()
        return {"ok": True, "user": serialize_admin(user), "login_required": True}

    @app.get("/api/admin/bootstrap")
    def bootstrap(db: Session = Depends(get_db), user=Depends(current_admin)):
        appointments = db.query(Appointment).filter(Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES)).order_by(Appointment.start_time.desc()).limit(300).all()
        booking_requests = db.query(BookingRequest).order_by(BookingRequest.created_at.desc()).limit(500).all()
        shift_rows = db.query(Shift).filter(Shift.status == "active").order_by(Shift.start_time).limit(500).all()
        shift_staff = _model_map(db, Staff, {item.staff_id for item in shift_rows})
        customers = db.query(User).order_by(User.created_at.desc()).limit(1000).all()
        audit_rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(20).all()
        audit_actors = _model_map(db, AdminUser, {item.actor_user_id for item in audit_rows if item.actor_user_id})
        return {
            "user": serialize_admin(user),
            "appointments": appointment_dicts(db, appointments),
            "booking_requests": booking_request_dicts(db, booking_requests),
            "staff": [staff_dict(item) for item in db.query(Staff).order_by(Staff.name).all()],
            "shifts": [shift_dict(item) | {"staff_name": shift_staff[item.staff_id].name if item.staff_id in shift_staff else "未知"} for item in shift_rows],
            "services": [service_dict(item) for item in db.query(ServicePlan).filter(ServicePlan.deleted_at.is_(None)).order_by(ServicePlan.id).all()],
            "promotions": [promotion_dict(item) for item in db.query(Promotion).filter(Promotion.deleted_at.is_(None)).order_by(Promotion.id).all()],
            "rooms": [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).order_by(Room.id).all()],
            "venues": [{"id": item.id, "name": item.name, "address": item.address, "room_name": item.room_name, "rental_cost": item.rental_cost, "notes": item.notes, "active": item.active} for item in db.query(Venue).order_by(Venue.name).all()],
            "customers": customer_dicts(db, customers),
            "admin_users": [serialize_admin(item) for item in db.query(AdminUser).order_by(AdminUser.id).all()] if user.role in {"admin", "manager"} else [],
            "return_rule_sets": return_rule_sets_dict(db),
            "audit_logs": [{
                "id": item.id,
                "actor_name": audit_actors[item.actor_user_id].display_name if item.actor_user_id in audit_actors else "系統／員工",
                "action": item.action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "reason": item.reason,
                "created_at": _iso(item.created_at),
            } for item in audit_rows],
        }

    @app.get("/api/admin/booking-requests")
    def list_booking_requests(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        items = db.query(BookingRequest).order_by(BookingRequest.created_at.desc()).limit(1000).all()
        return booking_request_dicts(db, items)

    @app.patch("/api/admin/booking-requests/{request_id}")
    def update_booking_request(request_id: int, payload: BookingRequestPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        item = db.query(BookingRequest).filter(BookingRequest.id == request_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到預約通知")
        if item.status != "pending":
            raise HTTPException(status_code=409, detail="只有待確認通知可以修改")
        before = booking_request_dict(db, item)
        changes = _model_dump_unset(payload)
        if "customer_name" in changes and changes["customer_name"]:
            customer = db.query(User).filter(User.id == item.user_id).first()
            customer.display_name = changes.pop("customer_name").strip()
        if "phone" in changes and changes["phone"]:
            customer = db.query(User).filter(User.id == item.user_id).first()
            item.contact_phone = attach_customer_phone(db, customer, changes.pop("phone"))
        if "staff_id" in changes:
            staff_id = changes.pop("staff_id")
            if staff_id and not db.query(Staff).filter(Staff.id == staff_id, Staff.employment_status == "active").first():
                raise HTTPException(status_code=404, detail="找不到啟用中的師傅")
            item.requested_staff_id = staff_id
        if "service_plan_id" in changes and changes["service_plan_id"] is not None:
            plan = db.query(ServicePlan).filter(ServicePlan.id == changes.pop("service_plan_id"), ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).first()
            if not plan:
                raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
            item.service_plan_id = plan.id
        if "promotion_id" in changes:
            promotion_id = changes.pop("promotion_id")
            if promotion_id and not db.query(Promotion).filter(Promotion.id == promotion_id, Promotion.active.is_(True), Promotion.deleted_at.is_(None)).first():
                raise HTTPException(status_code=404, detail="找不到啟用中的優惠")
            item.promotion_id = promotion_id
        if "start_time" in changes and changes["start_time"] is not None:
            item.start_time = parse_local_datetime(changes.pop("start_time"))
            if item.start_time <= now_taipei_naive():
                raise HTTPException(status_code=422, detail="預約時間必須晚於現在")
        if "notes" in changes:
            item.notes = changes.pop("notes")
        if "review_note" in changes:
            item.review_note = changes.pop("review_note")
        plan = db.query(ServicePlan).filter(ServicePlan.id == item.service_plan_id).first()
        item.end_time = appointment_end(item.start_time, plan.duration_minutes)
        audit(db, actor, "update", "booking_request", item.id, before=before, after=booking_request_dict(db, item))
        db.commit()
        return booking_request_dict(db, item)

    @app.post("/api/admin/booking-requests/{request_id}/confirm")
    def confirm_booking_request(request_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        item, appointment, duplicate = confirm_booking_request_record(request_id, db, actor)
        return {"duplicate": duplicate, "booking_request": booking_request_dict(db, item), "appointment": appointment_dict(db, appointment)}

    @app.post("/api/admin/booking-requests/{request_id}/cancel")
    def cancel_booking_request(request_id: int, payload: BookingRequestPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        item = cancel_booking_request_record(request_id, db, actor, payload.review_note)
        return booking_request_dict(db, item)

    @app.delete("/api/admin/booking-requests/{request_id}")
    def delete_booking_request(request_id: int, reason: str = Query(min_length=2, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(BookingRequest).filter(BookingRequest.id == request_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到預約通知")
        db.delete(item)
        audit(db, actor, "permanent_delete", "booking_request", request_id, reason=reason)
        db.commit()
        return {"ok": True, "id": request_id}

    @app.post("/api/admin/maintenance/reset-booking-data")
    def reset_booking_data(payload: BookingDataResetIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
        """Delete booking/test transaction rows while preserving operational master data."""
        _ = payload
        audit_entity_types = ["appointment", "booking_request", "payment"]
        counts = {
            "staff_returns": db.query(StaffReturn).count(),
            "payments": db.query(Payment).count(),
            "appointment_details": db.query(AppointmentDetail).count(),
            "booking_requests": db.query(BookingRequest).count(),
            "public_booking_requests": db.query(PublicBookingRequest).count(),
            "appointments": db.query(Appointment).count(),
            "booking_audit_logs": db.query(AuditLog).filter(AuditLog.entity_type.in_(audit_entity_types)).count(),
        }
        db.query(StaffReturn).delete(synchronize_session=False)
        db.query(Payment).delete(synchronize_session=False)
        db.query(AppointmentDetail).delete(synchronize_session=False)
        db.query(BookingRequest).delete(synchronize_session=False)
        db.query(PublicBookingRequest).delete(synchronize_session=False)
        db.query(Appointment).delete(synchronize_session=False)
        db.query(AuditLog).filter(AuditLog.entity_type.in_(audit_entity_types)).delete(synchronize_session=False)
        audit(db, actor, "reset_booking_data", "maintenance", None, reason="production_launch_cleanup", after=counts)
        db.commit()
        if db.get_bind().dialect.name == "mysql":
            for table_name in ("staff_returns", "payments", "appointment_details", "booking_requests", "public_booking_requests", "appointments"):
                db.execute(text(f"ALTER TABLE {table_name} AUTO_INCREMENT = 1"))
            db.commit()
        return {
            "deleted": counts,
            "preserved": ["staffs", "users", "customer_phones", "shifts", "service_plans", "promotions", "rooms", "admin_users"],
        }

    @app.get("/api/admin/appointments")
    def list_appointments(
        start: datetime | None = Query(default=None),
        end: datetime | None = Query(default=None),
        db: Session = Depends(get_db),
        user=Depends(current_admin),
    ):
        query = db.query(Appointment).filter(Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES))
        if start:
            query = query.filter(Appointment.start_time >= parse_local_datetime(start))
        if end:
            query = query.filter(Appointment.start_time < parse_local_datetime(end))
        return appointment_dicts(db, query.order_by(Appointment.start_time.desc()).limit(1000).all())

    @app.get("/api/admin/customers")
    def list_customers(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        return customer_dicts(db, db.query(User).order_by(User.created_at.desc()).limit(1000).all())

    @app.patch("/api/admin/customers/{customer_id}")
    def update_customer(customer_id: int, payload: CustomerPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        customer = db.query(User).filter(User.id == customer_id).with_for_update().first()
        if not customer:
            raise HTTPException(status_code=404, detail="找不到客戶")
        before = customer_dict(db, customer)
        customer.display_name = payload.display_name.strip()
        if actor.role not in {"admin", "manager"} and payload.customer_grade != getattr(customer, "customer_grade", "N"):
            raise HTTPException(status_code=403, detail="只有 Admin 或店長可以調整客戶等級")
        customer.customer_grade = payload.customer_grade
        sync_customer_phones(db, customer, payload.phones)
        db.flush()
        after = customer_dict(db, customer)
        audit(db, actor, "update", "customer", customer.id, before=before, after=after)
        db.commit()
        return after

    @app.delete("/api/admin/customers/{customer_id}")
    def delete_customer(customer_id: int, reason: str = Query(min_length=2, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        before = customer_dict(db, db.query(User).filter(User.id == customer_id).first()) if db.query(User).filter(User.id == customer_id).first() else None
        delete_customer_record(db, customer_id)
        audit(db, actor, "permanent_delete", "customer", customer_id, reason=reason, before=before)
        db.commit()
        return {"ok": True, "id": customer_id}

    @app.post("/api/admin/appointments", status_code=201)
    def create_appointment(payload: AppointmentCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id, ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        promotion = None
        if payload.promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == payload.promotion_id, Promotion.active.is_(True), Promotion.deleted_at.is_(None)).first()
            if not promotion:
                raise HTTPException(status_code=404, detail="找不到啟用中的優惠")
        start_dt = parse_local_datetime(payload.start_time)
        override_time_rules = actor_can_override_time_rules(actor, db)
        if not override_time_rules:
            try:
                validate_booking_start(start_dt)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        end_dt = appointment_end(start_dt, plan.duration_minutes)

        if payload.staff_id:
            staff_obj = db.query(Staff).filter(Staff.id == payload.staff_id).with_for_update().first()
            if not staff_obj or getattr(staff_obj, "employment_status", "active") != "active":
                raise HTTPException(status_code=404, detail="找不到可排班師傅")
            conflict = None if override_time_rules else staff_appointment_conflict(db, payload.staff_id, start_dt, end_dt)
            if conflict:
                raise HTTPException(status_code=409, detail=f"師傅與訂單 AP-{conflict.id} 時間重疊")

        if payload.location_type == "onsite":
            if not payload.room_id:
                raise HTTPException(status_code=422, detail="店內預約必須選擇房間")
            room = db.query(Room).filter(Room.id == payload.room_id, Room.active.is_(True)).with_for_update().first()
            if not room:
                raise HTTPException(status_code=404, detail="找不到房間")
            conflict = None if override_time_rules else room_appointment_conflict(db, payload.room_id, start_dt, end_dt)
            if conflict:
                raise HTTPException(status_code=409, detail=f"房間與訂單 AP-{conflict.id} 時間重疊")

        customer, contact_phone = customer_for_phone(db, payload.phone)
        if not customer:
            customer = User(line_user_id=f"manual:{secrets.token_hex(16)}", phone=contact_phone, display_name=payload.customer_name, customer_grade="N")
            db.add(customer)
            db.flush()
            sync_customer_phones(db, customer, [contact_phone])
        elif not getattr(customer, "display_name", None):
            customer.display_name = payload.customer_name
        customer = db.query(User).filter(User.id == customer.id).with_for_update().first()
        duplicate = None if override_time_rules else db.query(Appointment).filter(
            Appointment.user_id == customer.id,
            Appointment.start_time == start_dt,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
        ).first()
        if duplicate:
            raise HTTPException(status_code=409, detail=f"此客戶在相同時間已有訂單 AP-{duplicate.id}")

        appointment = Appointment(
            user_id=customer.id,
            staff_id=payload.staff_id,
            duration=plan.duration_minutes,
            plan_name=f"{plan.code}-{plan.name}",
            start_time=start_dt,
            end_time=end_dt,
            status="confirmed",
            customer_name_snapshot=customer.display_name,
            customer_phone_snapshot=contact_phone,
            staff_name_snapshot=staff_obj.name if payload.staff_id else None,
        )
        db.add(appointment)
        db.flush()
        detail = AppointmentDetail(
            appointment_id=appointment.id,
            service_plan_id=plan.id,
            promotion_id=promotion.id if promotion else None,
            room_id=payload.room_id,
            venue_id=payload.venue_id,
            service_name_snapshot=plan.name,
            promotion_name_snapshot=promotion.name if promotion else None,
            room_name_snapshot=(db.query(Room).filter(Room.id == payload.room_id).first().name if payload.room_id else None),
            venue_name_snapshot=(db.query(Venue).filter(Venue.id == payload.venue_id).first().name if payload.venue_id else None),
            contact_phone=contact_phone,
            base_price=plan.price,
            discount_amount=promotion_discount(promotion, plan.price),
            total_amount=plan.price - promotion_discount(promotion, plan.price),
            location_type=payload.location_type,
            notes=payload.notes,
        )
        db.add(detail)
        audit(db, actor, "create", "appointment", appointment.id, after={"start": start_dt, "end": end_dt, "staff_id": payload.staff_id, "room_id": payload.room_id, "promotion_id": payload.promotion_id})
        db.commit()
        db.refresh(appointment)
        if appointment_notifier:
            try:
                appointment_notifier(appointment, db, origin="後台建立")
            except Exception:
                logger.exception("Unable to push appointment notification appointment_id=%s", appointment.id)
        return appointment_dict(db, appointment)

    @app.post("/api/public/booking/appointments", status_code=201)
    def create_public_booking(payload: PublicBookingCreateIn, request: Request, db: Session = Depends(get_db)):
        _enforce_public_booking_rate(request, payload.phone)
        claim = PublicBookingRequest(idempotency_key=payload.idempotency_key, source="liff" if payload.id_token else "web")
        db.add(claim)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            existing = db.query(PublicBookingRequest).filter(PublicBookingRequest.idempotency_key == payload.idempotency_key).first()
            if existing and existing.appointment_id:
                appointment = db.query(Appointment).filter(Appointment.id == existing.appointment_id).first()
                if appointment:
                    receipt = appointment_dict(db, appointment)
                    receipt.pop("customer_id", None)
                    receipt.pop("customer_serial", None)
                    receipt.pop("customer_grade", None)
                    return {"duplicate": True, "appointment": receipt}
            raise HTTPException(status_code=409, detail="預約正在處理中，請勿重複送出")

        plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id, ServicePlan.active.is_(True), ServicePlan.deleted_at.is_(None)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        promotion = None
        if payload.promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == payload.promotion_id, Promotion.active.is_(True), Promotion.deleted_at.is_(None)).first()
            if not promotion or promotion_discount(promotion, plan.price) <= 0:
                raise HTTPException(status_code=404, detail="這個優惠目前無法使用")

        start_dt = parse_local_datetime(payload.start_time)
        try:
            validate_booking_start(start_dt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        end_dt = appointment_end(start_dt, plan.duration_minutes)
        staff_items = available_staff(db, start_dt, end_dt)
        if not staff_items:
            raise HTTPException(status_code=409, detail="這個時段目前沒有可預約師傅，請改選其他時間")
        available_ids = {item.id for item in staff_items}
        if payload.staff_id:
            if not plan.can_choose_staff:
                raise HTTPException(status_code=422, detail="這個方案由店長安排師傅")
            if payload.staff_id not in available_ids:
                raise HTTPException(status_code=409, detail="這位師傅在該時段已無法預約")
        # 進到正式預訂端點代表使用「目前排班師傅」流程；未指定時由
        # 系統從當下可用班表中直接指派一位，讓訂單能立即派給師傅。
        assigned_staff_id = payload.staff_id or staff_items[0].id
        if plan.location_type == "onsite" and not room_capacity_available(db, start_dt, end_dt):
            raise HTTPException(status_code=409, detail="這個時段兩間房都已使用，請改選其他時間")

        customer, contact_phone, source = resolve_public_customer(db, payload)
        customer = db.query(User).filter(User.id == customer.id).with_for_update().first()
        duplicate = db.query(Appointment).filter(
            Appointment.user_id == customer.id,
            Appointment.start_time == start_dt,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
        ).first()
        if duplicate:
            claim.appointment_id = duplicate.id
            db.commit()
            receipt = appointment_dict(db, duplicate)
            receipt.pop("customer_id", None)
            receipt.pop("customer_serial", None)
            receipt.pop("customer_grade", None)
            return {"duplicate": True, "appointment": receipt}

        appointment = Appointment(
            user_id=customer.id,
            staff_id=assigned_staff_id,
            duration=plan.duration_minutes,
            plan_name=f"{plan.code}-{plan.name}",
            start_time=start_dt,
            end_time=end_dt,
            status="confirmed",
            customer_name_snapshot=customer.display_name,
            customer_phone_snapshot=contact_phone,
            staff_name_snapshot=db.query(Staff).filter(Staff.id == assigned_staff_id).first().name,
        )
        db.add(appointment)
        db.flush()
        discount = promotion_discount(promotion, plan.price)
        source_label = "LINE LIFF 網頁預約" if source == "liff" else "網頁預約"
        notes = f"來源：{source_label}"
        if payload.notes and payload.notes.strip():
            notes += f"\n客戶備註：{payload.notes.strip()}"
        db.add(AppointmentDetail(
            appointment_id=appointment.id,
            service_plan_id=plan.id,
            promotion_id=promotion.id if promotion else None,
            service_name_snapshot=plan.name,
            promotion_name_snapshot=promotion.name if promotion else None,
            contact_phone=contact_phone,
            base_price=plan.price,
            discount_amount=discount,
            total_amount=max(0, plan.price - discount),
            location_type="external" if plan.location_type == "external" else "pending",
            notes=notes,
        ))
        claim.appointment_id = appointment.id
        audit(db, None, "create_public_booking", "appointment", appointment.id, reason=source_label, after={
            "start": start_dt,
            "end": end_dt,
            "staff_id": assigned_staff_id,
            "promotion_id": payload.promotion_id,
        })
        db.commit()
        db.refresh(appointment)
        if appointment_notifier:
            try:
                # 已有正式排班並直接成立的訂單只派給該師傅；指定／全師傅
                # 的預約通知使用另一個 requests 端點，仍由客服審核。
                appointment_notifier(appointment, db, origin=source_label, notify_management=False)
            except Exception:
                logger.exception("Unable to push public booking notification appointment_id=%s", appointment.id)
        receipt = appointment_dict(db, appointment)
        receipt.pop("customer_id", None)
        receipt.pop("customer_serial", None)
        receipt.pop("customer_grade", None)
        return {"duplicate": False, "appointment": receipt}

    @app.delete("/api/admin/appointments/{appointment_id}")
    def delete_appointment(appointment_id: int, reason: str = Query(min_length=2, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Appointment).filter(Appointment.id == appointment_id).first()
        before = appointment_dict(db, item) if item else None
        delete_appointment_record(db, appointment_id)
        audit(db, actor, "permanent_delete", "appointment", appointment_id, reason=reason, before=before)
        db.commit()
        return {"ok": True, "id": appointment_id}

    @app.post("/api/staff/appointments", status_code=201)
    def create_staff_appointment(payload: StaffAppointmentCreateIn, db: Session = Depends(get_db), staff_obj=Depends(current_staff)):
        values = _model_dump(payload)
        values["staff_id"] = staff_obj.id
        normalized = AppointmentCreateIn(**values)
        actor = type("StaffActor", (), {"id": None, "role": "staff"})()
        return create_appointment(normalized, db, actor)

    @app.patch("/api/admin/appointments/{appointment_id}")
    def update_appointment(appointment_id: int, payload: AppointmentPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).with_for_update().first()
        if not appointment:
            raise HTTPException(status_code=404, detail="找不到預約")
        detail = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment.id).first()
        before = appointment_dict(db, appointment)
        changes = _model_dump_unset(payload)
        monetary_fields = {"base_price", "discount_amount", "extra_amount", "total_amount"}
        if actor.role == "clerk" and monetary_fields.intersection(changes):
            raise HTTPException(status_code=403, detail="客服不能直接覆寫金額，請由店長或 Admin 處理")
        customer = db.query(User).filter(User.id == appointment.user_id).first()
        if customer and payload.customer_name is not None:
            customer.display_name = payload.customer_name
        if customer and payload.phone is not None:
            contact_phone = normalize_phone(payload.phone)
            owner = db.query(CustomerPhone).filter(CustomerPhone.phone == contact_phone).first()
            if owner and owner.user_id != customer.id:
                raise HTTPException(status_code=409, detail="此手機號碼已屬於其他客戶")
            if not owner:
                db.add(CustomerPhone(user_id=customer.id, phone=contact_phone, is_primary=not bool(customer.phone)))
            if not customer.phone:
                customer.phone = contact_phone
        plan = None
        if payload.service_plan_id is not None:
            plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id, ServicePlan.deleted_at.is_(None)).first()
            if not plan:
                raise HTTPException(status_code=404, detail="找不到服務方案")
        promotion = None
        promotion_changed = "promotion_id" in changes
        if promotion_changed and payload.promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == payload.promotion_id, Promotion.active.is_(True), Promotion.deleted_at.is_(None)).first()
            if not promotion:
                raise HTTPException(status_code=404, detail="找不到啟用中的優惠")
        start_dt = parse_local_datetime(payload.start_time) if payload.start_time else appointment.start_time
        override_time_rules = actor_can_override_time_rules(actor, db)
        if payload.start_time is not None and not override_time_rules:
            try:
                validate_booking_start(start_dt)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        duration = plan.duration_minutes if plan else appointment.duration
        end_dt = appointment_end(start_dt, duration)
        staff_id = payload.staff_id if "staff_id" in changes else appointment.staff_id
        room_id = payload.room_id if "room_id" in changes else (detail.room_id if detail else None)
        if not override_time_rules and staff_id and staff_appointment_conflict(db, staff_id, start_dt, end_dt, appointment.id):
            raise HTTPException(status_code=409, detail="師傅時間重疊")
        if not override_time_rules and room_id and room_appointment_conflict(db, room_id, start_dt, end_dt, appointment.id):
            raise HTTPException(status_code=409, detail="房間時間重疊")
        appointment.start_time = start_dt
        appointment.end_time = end_dt
        appointment.duration = duration
        appointment.staff_id = staff_id
        if payload.status:
            appointment.status = ZH_TO_STATUS.get(payload.status, payload.status)
        if not detail:
            detail = AppointmentDetail(appointment_id=appointment.id, base_price=0, total_amount=0)
            db.add(detail)
        if payload.phone is not None:
            detail.contact_phone = normalize_phone(payload.phone)
        if plan:
            detail.service_plan_id = plan.id
            detail.base_price = plan.price
            appointment.plan_name = f"{plan.code}-{plan.name}"
        if promotion_changed:
            detail.promotion_id = promotion.id if promotion else None
            detail.discount_amount = promotion_discount(promotion, detail.base_price)
        if plan or promotion_changed:
            current_promotion = promotion if promotion_changed else (db.query(Promotion).filter(Promotion.id == detail.promotion_id).first() if detail.promotion_id else None)
            detail.discount_amount = promotion_discount(current_promotion, detail.base_price)
            detail.total_amount = max(0, detail.base_price - detail.discount_amount + detail.extra_amount)
        if "room_id" in changes:
            detail.room_id = payload.room_id
        if "venue_id" in changes:
            detail.venue_id = payload.venue_id
        if payload.location_type is not None:
            detail.location_type = payload.location_type
        if payload.notes is not None:
            detail.notes = payload.notes
        if actor.role in {"admin", "manager"}:
            for field in monetary_fields:
                if field in changes:
                    setattr(detail, field, changes[field])
            if monetary_fields.intersection(changes) and "total_amount" not in changes:
                detail.total_amount = max(0, detail.base_price - detail.discount_amount + detail.extra_amount)
        after = appointment_dict(db, appointment)
        audit(db, actor, "update", "appointment", appointment.id, reason=payload.force_reason, before=before, after=after)
        db.commit()
        return appointment_dict(db, appointment)

    @app.get("/api/admin/shifts")
    def list_shifts(start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db), user=Depends(current_admin)):
        query = db.query(Shift).filter(Shift.status == "active")
        if start:
            query = query.filter(Shift.end_time > parse_local_datetime(start))
        if end:
            query = query.filter(Shift.start_time < parse_local_datetime(end))
        result = []
        for item in query.order_by(Shift.start_time).all():
            staff_obj = db.query(Staff).filter(Staff.id == item.staff_id).first()
            result.append(shift_dict(item) | {"staff_name": staff_obj.name if staff_obj else "未知"})
        return result

    @app.post("/api/admin/shifts", status_code=201)
    def create_shift(payload: ShiftCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        start_dt, end_dt = validate_shift_period(payload.start_time, payload.end_time)
        override_time_rules = actor_can_override_time_rules(actor, db)
        staff_obj = db.query(Staff).filter(Staff.id == payload.staff_id).with_for_update().first()
        if not staff_obj or getattr(staff_obj, "employment_status", "active") != "active":
            raise HTTPException(status_code=404, detail="找不到在職師傅")
        if not override_time_rules and not staff_may_change_shift(start_dt):
            raise HTTPException(status_code=422, detail="開始時間已進入 90 分鐘鎖定範圍，請聯絡店長或開啟客服強制權限")
        if not override_time_rules and shift_conflict(db, payload.staff_id, start_dt, end_dt):
            raise HTTPException(status_code=409, detail="此師傅的排班時間重疊")
        item = Shift(staff_id=payload.staff_id, start_time=start_dt, end_time=end_dt, source=actor.role, created_by_user_id=actor.id)
        db.add(item)
        db.flush()
        audit(db, actor, "create", "shift", item.id, after={"staff_id": item.staff_id, "start": start_dt, "end": end_dt})
        db.commit()
        return shift_dict(item) | {"staff_name": staff_obj.name}

    @app.delete("/api/admin/shifts/{shift_id}")
    def delete_shift(shift_id: int, reason: str | None = Query(default=None, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        item = db.query(Shift).filter(Shift.id == shift_id, Shift.status == "active").with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到排班")
        locked = not staff_may_change_shift(item.start_time)
        if locked and not actor_can_override_time_rules(actor, db):
            raise HTTPException(status_code=422, detail="此班已鎖定，請由店長、Admin 或具強制權限的客服處理")
        before = shift_dict(item)
        if actor.role in {"admin", "manager"}:
            db.delete(item)
            action = "permanent_delete"
        else:
            item.status = "cancelled"
            item.change_reason = reason
            action = "cancel"
        audit(db, actor, action, "shift", item.id, reason=reason, before=before)
        db.commit()
        return {"ok": True, "locked_override": locked}

    @app.get("/api/admin/services")
    def list_services(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [service_dict(item) for item in db.query(ServicePlan).filter(ServicePlan.deleted_at.is_(None)).order_by(ServicePlan.id).all()]

    @app.post("/api/admin/services", status_code=201)
    def create_service(payload: ServiceCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        code = payload.code.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]+", code):
            raise HTTPException(status_code=422, detail="方案代碼只能使用英文字母、數字、底線或連字號")
        if db.query(ServicePlan).filter(ServicePlan.code == code).first():
            raise HTTPException(status_code=409, detail="方案代碼已使用；已刪除方案的代碼也會保留給歷史訂單")
        item = ServicePlan(
            code=code,
            name=payload.name.strip(),
            duration_minutes=payload.duration_minutes,
            price=payload.price,
            description=payload.description,
            location_type=payload.location_type,
            can_choose_staff=payload.can_choose_staff,
            active=True,
            effective_from=parse_local_datetime(payload.effective_from) if payload.effective_from else None,
            effective_to=parse_local_datetime(payload.effective_to) if payload.effective_to else None,
        )
        db.add(item)
        db.flush()
        audit(db, actor, "create", "service_plan", item.id, after=service_dict(item))
        db.commit()
        db.refresh(item)
        return service_dict(item)

    @app.get("/api/admin/site-content")
    def get_site_content(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(SiteContent).filter(SiteContent.content_key == "official_site").first()
        if not item:
            item = SiteContent(content_key="official_site")
            db.add(item)
            db.commit()
            db.refresh(item)
        return site_content_payload(item)

    @app.put("/api/admin/site-content/draft")
    def save_site_content_draft(payload: SiteContentDraftIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(SiteContent).filter(SiteContent.content_key == "official_site").with_for_update().first()
        if not item:
            item = SiteContent(content_key="official_site")
            db.add(item)
            db.flush()
        if payload.expected_version is not None and payload.expected_version != item.draft_version:
            raise HTTPException(status_code=409, detail="官網內容已被其他人更新，請重新讀取後再儲存")
        previous_version = item.draft_version
        item.draft_json = encode_site_content(payload.content)
        item.draft_version += 1
        item.updated_by_user_id = actor.id
        item.updated_at = now_taipei_naive()
        audit(
            db,
            actor,
            "save_draft",
            "site_content",
            item.content_key,
            before={"draft_version": previous_version},
            after={"draft_version": item.draft_version},
        )
        db.commit()
        db.refresh(item)
        return site_content_payload(item)

    @app.post("/api/admin/site-content/publish")
    def publish_site_content(payload: SiteContentPublishIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(SiteContent).filter(SiteContent.content_key == "official_site").with_for_update().first()
        if not item or item.draft_json is None:
            raise HTTPException(status_code=422, detail="目前沒有可發布的官網草稿")
        if payload.expected_version is not None and payload.expected_version != item.draft_version:
            raise HTTPException(status_code=409, detail="草稿版本已更新，請重新讀取後再發布")
        previous_version = item.published_version
        item.published_json = item.draft_json
        item.published_version = item.draft_version
        item.published_by_user_id = actor.id
        item.published_at = now_taipei_naive()
        audit(
            db,
            actor,
            "publish",
            "site_content",
            item.content_key,
            before={"published_version": previous_version},
            after={"published_version": item.published_version},
        )
        db.commit()
        db.refresh(item)
        return site_content_payload(item)

    @app.patch("/api/admin/services/{service_id}")
    def update_service(service_id: int, payload: ServicePatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(ServicePlan).filter(ServicePlan.id == service_id, ServicePlan.deleted_at.is_(None)).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到服務方案")
        before = service_dict(item)
        for field in ("name", "duration_minutes", "price", "description", "active"):
            value = getattr(payload, field)
            if value is not None:
                setattr(item, field, value)
        if payload.effective_from is not None:
            item.effective_from = parse_local_datetime(payload.effective_from)
        if payload.effective_to is not None:
            item.effective_to = parse_local_datetime(payload.effective_to)
        audit(db, actor, "update", "service_plan", item.id, before=before, after=service_dict(item))
        db.commit()
        return service_dict(item)

    @app.delete("/api/admin/services/{service_id}")
    def delete_service(service_id: int, reason: str | None = Query(default=None, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(ServicePlan).filter(ServicePlan.id == service_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到服務方案")
        before = service_dict(item)
        item_id = item.id
        delete_service_record(db, item_id)
        audit(db, actor, "permanent_delete", "service_plan", item_id, reason=reason or "刪除方案", before=before)
        db.commit()
        return {"ok": True, "id": item_id, "history_preserved": True}

    @app.get("/api/admin/promotions")
    def list_promotions(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [promotion_dict(item) for item in db.query(Promotion).filter(Promotion.deleted_at.is_(None)).order_by(Promotion.id).all()]

    @app.post("/api/admin/promotions", status_code=201)
    def create_promotion(payload: PromotionCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = Promotion(name=payload.name, calculation_type=payload.calculation_type, value=payload.value, starts_at=parse_local_datetime(payload.starts_at) if payload.starts_at else None, ends_at=parse_local_datetime(payload.ends_at) if payload.ends_at else None, stackable=payload.stackable, description=payload.description)
        db.add(item)
        db.flush()
        audit(db, actor, "create", "promotion", item.id, after=_model_dump(payload))
        db.commit()
        return promotion_dict(item)

    @app.patch("/api/admin/promotions/{promotion_id}")
    def update_promotion(promotion_id: int, payload: PromotionPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Promotion).filter(Promotion.id == promotion_id, Promotion.deleted_at.is_(None)).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到優惠")
        before = promotion_dict(item)
        for field, value in _model_dump_unset(payload).items():
            if field in {"starts_at", "ends_at"} and value is not None:
                value = parse_local_datetime(value)
            setattr(item, field, value)
        audit(db, actor, "update", "promotion", item.id, before=before, after=promotion_dict(item))
        db.commit()
        return promotion_dict(item)

    @app.delete("/api/admin/promotions/{promotion_id}")
    def delete_promotion(promotion_id: int, reason: str | None = Query(default=None, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Promotion).filter(Promotion.id == promotion_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到優惠")
        before = promotion_dict(item)
        item_id = item.id
        delete_promotion_record(db, item_id)
        audit(db, actor, "permanent_delete", "promotion", item_id, reason=reason or "刪除優惠", before=before)
        db.commit()
        return {"ok": True, "id": item_id, "history_preserved": True}

    @app.get("/api/admin/staff")
    def list_staff(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [staff_dict(item) for item in db.query(Staff).order_by(Staff.name).all()]

    @app.get("/api/admin/return-rules")
    def list_return_rules(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        return return_rule_sets_dict(db)

    @app.patch("/api/admin/return-rules/{rule_id}")
    def update_return_rule(rule_id: int, payload: ReturnRulePatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(ReturnRule).filter(ReturnRule.id == rule_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到回帳規則")
        before = {"name": item.name, "amount": item.amount, "duration_minutes": item.duration_minutes, "active": item.active}
        for field, value in _model_dump_unset(payload).items():
            setattr(item, field, value)
        after = {"name": item.name, "amount": item.amount, "duration_minutes": item.duration_minutes, "active": item.active}
        audit(db, actor, "update", "return_rule", item.id, before=before, after=after)
        db.commit()
        return {"id": item.id, "service_code": item.service_code, **after}

    @app.post("/api/admin/staff", status_code=201)
    def create_staff(payload: StaffCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        requested_line_user_id = (payload.line_user_id or "").strip() or None
        line_user_id = f"pending:{secrets.token_hex(16)}"
        photo_url = (payload.photo_url or "").strip()
        if photo_url and not photo_url.startswith(("https://", "http://")):
            raise HTTPException(status_code=422, detail="照片網址必須以 https:// 或 http:// 開頭；本機照片請使用上傳功能")
        phone = unique_staff_phone(db, payload.phone) if payload.phone else None
        item = Staff(
            line_user_id=line_user_id,
            name=payload.name,
            phone=phone,
            category=payload.category,
            employment_status="active",
            return_rule_set_id=payload.return_rule_set_id,
            photo_url=photo_url or None,
            height=normalize_staff_measurement(payload.height, label="身高", minimum=100, maximum=250),
            weight=normalize_staff_measurement(payload.weight, label="體重", minimum=30, maximum=250),
            role=payload.role,
        )
        db.add(item)
        db.flush()
        audit(db, actor, "create", "staff", item.id, after=staff_dict(item))
        if requested_line_user_id:
            item = bind_staff_line(
                item.id,
                requested_line_user_id,
                db,
                actor_id=actor.id,
                source="建立員工時串接",
            )
            return {**staff_dict(item), "notification_sent": True}
        db.commit()
        return staff_dict(item)

    @app.patch("/api/admin/staff/{staff_id}")
    def update_staff(staff_id: int, payload: StaffPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Staff).filter(Staff.id == staff_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")
        changes = _model_dump_unset(payload)
        if "phone" in changes:
            changes["phone"] = unique_staff_phone(db, changes["phone"], exclude_staff_id=staff_id) if changes["phone"] else None
        if "photo_url" in changes:
            photo_url = (changes["photo_url"] or "").strip()
            if photo_url and not photo_url.startswith(("https://", "http://", "/api/public/staff/")):
                raise HTTPException(status_code=422, detail="照片網址必須以 https:// 或 http:// 開頭；本機照片請使用上傳功能")
            changes["photo_url"] = photo_url or None
        if "height" in changes:
            changes["height"] = normalize_staff_measurement(changes["height"], label="身高", minimum=100, maximum=250)
        if "weight" in changes:
            changes["weight"] = normalize_staff_measurement(changes["weight"], label="體重", minimum=30, maximum=250)
        if "return_rule_set_id" in changes and changes["return_rule_set_id"] is not None:
            if not db.query(ReturnRuleSet).filter(ReturnRuleSet.id == changes["return_rule_set_id"], ReturnRuleSet.active.is_(True)).first():
                raise HTTPException(status_code=404, detail="找不到回帳表")
        before = staff_dict(item)
        for field, value in changes.items():
            setattr(item, field, value)
        audit(db, actor, "update", "staff", item.id, before=before, after=staff_dict(item))
        db.commit()
        return staff_dict(item)

    @app.put("/api/admin/staff/{staff_id}/photo")
    def upload_staff_photo(staff_id: int, payload: StaffPhotoIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Staff).filter(Staff.id == staff_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")
        matched = re.fullmatch(r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)", payload.data_url)
        if not matched:
            raise HTTPException(status_code=422, detail="只接受 JPEG、PNG 或 WebP 圖片")
        mime_type, encoded = matched.groups()
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=422, detail="照片內容無法讀取") from exc
        if not content or len(content) > 3 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="照片大小必須小於 3 MB")
        photo = db.query(StaffPhoto).filter(StaffPhoto.staff_id == staff_id).first()
        if photo:
            photo.mime_type = mime_type
            photo.data_base64 = encoded
        else:
            db.add(StaffPhoto(staff_id=staff_id, mime_type=mime_type, data_base64=encoded))
        item.photo_url = f"/api/public/staff/{staff_id}/photo"
        audit(db, actor, "upload_photo", "staff", staff_id, after={"mime_type": mime_type, "bytes": len(content)})
        db.commit()
        return staff_dict(item)

    @app.patch("/api/admin/staff/{staff_id}/status")
    def update_staff_status(staff_id: int, payload: StaffStatusIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Staff).filter(Staff.id == staff_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")
        before = staff_dict(item)
        item.employment_status = payload.employment_status
        audit(db, actor, "status_change", "staff", item.id, reason=payload.reason, before=before, after=staff_dict(item))
        db.commit()
        return staff_dict(item)

    @app.delete("/api/admin/staff/{staff_id}/line-link")
    def unlink_staff_line_endpoint(staff_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = unlink_staff_line(staff_id, db, actor_id=actor.id)
        return staff_dict(item)

    @app.put("/api/admin/staff/{staff_id}/line-link")
    def link_staff_line_endpoint(
        staff_id: int,
        payload: StaffLineLinkIn,
        db: Session = Depends(get_db),
        actor=Depends(require_roles("admin", "manager")),
    ):
        item = bind_staff_line(
            staff_id,
            payload.line_user_id,
            db,
            actor_id=actor.id,
            source="管理後台串接",
        )
        return {**staff_dict(item), "notification_sent": True}

    @app.delete("/api/admin/staff/{staff_id}")
    def delete_staff_permanently(
        staff_id: int,
        reason: str = Query(min_length=3, max_length=500),
        db: Session = Depends(get_db),
        actor=Depends(require_roles("admin", "manager")),
    ):
        return permanently_delete_staff(staff_id, db, actor_id=actor.id, reason=reason)

    @app.post("/api/admin/staff/{staff_id}/schedule-link")
    def rotate_staff_schedule_link(staff_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        staff_obj = db.query(Staff).filter(Staff.id == staff_id).first()
        if not staff_obj:
            raise HTTPException(status_code=404, detail="找不到員工")
        raw_token = secrets.token_urlsafe(32)
        existing = db.query(StaffScheduleToken).filter(StaffScheduleToken.staff_id == staff_id).first()
        if existing:
            existing.token_hash = _token_hash(raw_token)
            existing.revoked_at = None
            existing.created_at = now_taipei_naive()
        else:
            db.add(StaffScheduleToken(staff_id=staff_id, token_hash=_token_hash(raw_token)))
        audit(db, actor, "rotate_schedule_link", "staff", staff_id)
        db.commit()
        base = os.getenv("STAFF_SCHEDULE_BASE_URL", "http://localhost:3000/?staff_token=")
        return {"token": raw_token, "url": f"{base}{raw_token}", "staff_name": staff_obj.name}

    @app.get("/api/admin/staff/{staff_id}/private-health")
    def get_private_health(staff_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
        record = db.query(StaffPrivateHealth).filter(StaffPrivateHealth.staff_id == staff_id).first()
        if not record:
            return {"staff_id": staff_id, "data": None}
        fernet = require_fernet()
        return {"staff_id": staff_id, "data": json.loads(fernet.decrypt(record.encrypted_payload.encode("utf-8")).decode("utf-8")), "updated_at": _iso(record.updated_at)}

    @app.put("/api/admin/staff/{staff_id}/private-health")
    def put_private_health(staff_id: int, payload: PrivateHealthIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
        if not db.query(Staff).filter(Staff.id == staff_id).first():
            raise HTTPException(status_code=404, detail="找不到員工")
        fernet = require_fernet()
        encrypted = fernet.encrypt(_json(_model_dump(payload)).encode("utf-8")).decode("utf-8")
        record = db.query(StaffPrivateHealth).filter(StaffPrivateHealth.staff_id == staff_id).first()
        if record:
            record.encrypted_payload = encrypted
        else:
            db.add(StaffPrivateHealth(staff_id=staff_id, encrypted_payload=encrypted))
        audit(db, actor, "update_private_health", "staff", staff_id, reason="restricted encrypted update")
        db.commit()
        return {"ok": True}

    @app.get("/api/admin/venues")
    def list_venues(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [{"id": item.id, "name": item.name, "address": item.address, "room_name": item.room_name, "rental_cost": item.rental_cost, "notes": item.notes, "active": item.active} for item in db.query(Venue).order_by(Venue.name).all()]

    @app.post("/api/admin/venues", status_code=201)
    def create_venue(payload: VenueCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = Venue(**_model_dump(payload))
        db.add(item)
        db.flush()
        audit(db, actor, "create", "venue", item.id, after=_model_dump(payload))
        db.commit()
        return {"id": item.id, **_model_dump(payload), "active": True}

    @app.patch("/api/admin/venues/{venue_id}")
    def update_venue(venue_id: int, payload: VenuePatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Venue).filter(Venue.id == venue_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到場地")
        before = {"name": item.name, "address": item.address, "room_name": item.room_name, "rental_cost": item.rental_cost, "notes": item.notes, "active": item.active}
        for field, value in _model_dump_unset(payload).items():
            setattr(item, field, value)
        audit(db, actor, "update", "venue", item.id, before=before, after=_model_dump_unset(payload))
        db.commit()
        return {"id": item.id, "name": item.name, "address": item.address, "room_name": item.room_name, "rental_cost": item.rental_cost, "notes": item.notes, "active": item.active}

    @app.delete("/api/admin/venues/{venue_id}")
    def delete_venue(venue_id: int, reason: str = Query(min_length=2, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        delete_venue_record(db, venue_id)
        audit(db, actor, "permanent_delete", "venue", venue_id, reason=reason)
        db.commit()
        return {"ok": True, "id": venue_id}

    @app.get("/api/admin/rooms")
    def list_rooms(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        return [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).order_by(Room.id).all()]

    @app.post("/api/admin/rooms", status_code=201)
    def create_room(payload: RoomCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        name = payload.name.strip()
        if db.query(Room).filter(Room.name == name).first():
            raise HTTPException(status_code=409, detail="房間名稱已存在")
        item = Room(name=name, active=True)
        db.add(item)
        db.flush()
        audit(db, actor, "create", "room", item.id, after={"name": name})
        db.commit()
        return {"id": item.id, "name": item.name, "active": item.active}

    @app.patch("/api/admin/rooms/{room_id}")
    def update_room(room_id: int, payload: RoomPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Room).filter(Room.id == room_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到房間")
        before = {"name": item.name, "active": item.active}
        if payload.name is not None:
            item.name = payload.name.strip()
        if payload.active is not None:
            item.active = payload.active
        audit(db, actor, "update", "room", item.id, before=before, after={"name": item.name, "active": item.active})
        db.commit()
        return {"id": item.id, "name": item.name, "active": item.active}

    @app.delete("/api/admin/rooms/{room_id}")
    def delete_room(room_id: int, reason: str = Query(min_length=2, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        delete_room_record(db, room_id)
        audit(db, actor, "permanent_delete", "room", room_id, reason=reason)
        db.commit()
        return {"ok": True, "id": room_id}

    @app.post("/api/admin/appointments/{appointment_id}/checkout")
    def checkout(appointment_id: int, payload: CheckoutIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).with_for_update().first()
        if not appointment:
            raise HTTPException(status_code=404, detail="找不到訂單")
        if db.query(Payment).filter(Payment.appointment_id == appointment_id, Payment.status == "paid").first():
            raise HTTPException(status_code=409, detail="訂單已付款")
        payment = Payment(
            appointment_id=appointment_id,
            amount=payload.amount,
            method=payload.method,
            status="paid",
            cash_return_status="confirmed" if payload.method == "cash" else "not_applicable",
            received_by_staff_id=payload.received_by_staff_id,
            confirmed_by_user_id=actor.id,
            note=payload.note,
        )
        db.add(payment)
        appointment.status = "completed"
        db.flush()
        audit(db, actor, "checkout", "appointment", appointment_id, after={"amount": payload.amount, "method": payload.method})
        db.commit()
        return {"ok": True, "payment_id": payment.id, "cash_return_status": payment.cash_return_status, "return_amount": 0, "staff_return_id": None, "appointment": appointment_dict(db, appointment)}

    @app.post("/api/admin/payments/{payment_id}/confirm-cash-return")
    def confirm_cash_return(payment_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        payment = db.query(Payment).filter(Payment.id == payment_id).with_for_update().first()
        if not payment:
            raise HTTPException(status_code=404, detail="找不到付款紀錄")
        if payment.method != "cash":
            raise HTTPException(status_code=422, detail="只有現金付款需要確認回帳")
        if payment.cash_return_status == "confirmed":
            return {"ok": True, "cash_return_status": "confirmed"}
        payment.cash_return_status = "confirmed"
        payment.confirmed_by_user_id = actor.id
        staff_return = db.query(StaffReturn).filter(StaffReturn.appointment_id == payment.appointment_id).first()
        if staff_return:
            staff_return.status = "confirmed"
            staff_return.confirmed_by_user_id = actor.id
            staff_return.confirmed_at = now_taipei_naive()
        audit(db, actor, "confirm_cash_return", "payment", payment.id, after={"status": "confirmed"})
        db.commit()
        return {"ok": True, "cash_return_status": "confirmed"}

    @app.get("/api/admin/staff-returns")
    def list_staff_returns(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        items = db.query(StaffReturn).order_by(StaffReturn.created_at.desc()).limit(1000).all()
        appointments = _model_map(db, Appointment, {item.appointment_id for item in items})
        staff = _model_map(db, Staff, {item.staff_id for item in items})
        result = []
        for item in items:
            appointment = appointments.get(item.appointment_id)
            staff_obj = staff.get(item.staff_id)
            result.append({
                "id": item.id,
                "appointment_id": item.appointment_id,
                "order_id": f"AP-{appointment.start_time.strftime('%m%d')}-{appointment.id:03d}" if appointment else str(item.appointment_id),
                "staff_id": item.staff_id,
                "staff_name": staff_obj.name if staff_obj else "未知",
                "amount": item.amount,
                "status": item.status,
                "confirmed_at": _iso(item.confirmed_at),
                "created_at": _iso(item.created_at),
            })
        return result

    @app.get("/api/admin/users")
    def list_admin_users(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        return [serialize_admin(item) for item in db.query(AdminUser).order_by(AdminUser.id).all()]

    @app.post("/api/admin/users", status_code=201)
    def create_admin_user(payload: AdminUserCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        if actor.role == "manager" and payload.role != "clerk":
            raise HTTPException(status_code=403, detail="店長只能新增客服帳號")
        if db.query(AdminUser).filter(AdminUser.username == payload.username.lower()).first():
            raise HTTPException(status_code=409, detail="登入帳號已存在")
        item = AdminUser(
            username=payload.username.lower(),
            display_name=payload.display_name,
            role=payload.role,
            pin_hash=password_hash.hash(payload.pin),
            can_override_time_rules=payload.can_override_time_rules if payload.role == "clerk" else False,
        )
        db.add(item)
        db.flush()
        audit(db, actor, "create", "admin_user", item.id, after=serialize_admin(item))
        db.commit()
        return serialize_admin(item)

    @app.patch("/api/admin/users/{user_id}/permissions")
    def update_admin_user_permissions(
        user_id: int,
        payload: AdminUserPermissionIn,
        db: Session = Depends(get_db),
        actor=Depends(require_roles("admin", "manager")),
    ):
        item = db.query(AdminUser).filter(AdminUser.id == user_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到後台帳號")
        if item.role != "clerk":
            raise HTTPException(status_code=422, detail="這個開關只適用客服帳號")
        before = serialize_admin(item)
        item.can_override_time_rules = payload.can_override_time_rules
        audit(db, actor, "update_permissions", "admin_user", item.id, before=before, after=serialize_admin(item))
        db.commit()
        return serialize_admin(item)

    @app.delete("/api/admin/users/{user_id}")
    def deactivate_admin_user(user_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        delete_admin_user_record(db, user_id, actor)
        db.commit()
        return {"ok": True, "id": user_id}

    @app.get("/api/admin/audit-logs")
    def list_audit_logs(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        items = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
        users = _model_map(db, AdminUser, {item.actor_user_id for item in items if item.actor_user_id})
        result = []
        for item in items:
            user = users.get(item.actor_user_id) if item.actor_user_id else None
            result.append({"id": item.id, "actor": user.display_name if user else "系統", "action": item.action, "entity_type": item.entity_type, "entity_id": item.entity_id, "reason": item.reason, "created_at": _iso(item.created_at)})
        return result

    @app.delete("/api/admin/audit-logs/{audit_id}")
    def delete_audit_log(audit_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        _ = actor
        item = db.query(AuditLog).filter(AuditLog.id == audit_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到操作紀錄")
        db.delete(item)
        db.commit()
        return {"ok": True, "id": audit_id}

    @app.post("/api/admin/bulk-delete")
    def bulk_delete(payload: BulkDeleteIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        ids = list(dict.fromkeys(payload.ids))
        deleted: list[int] = []
        for item_id in ids:
            if payload.entity == "appointments":
                delete_appointment_record(db, item_id)
            elif payload.entity == "booking_requests":
                item = db.query(BookingRequest).filter(BookingRequest.id == item_id).first()
                if not item:
                    raise HTTPException(status_code=404, detail=f"找不到預約通知 #{item_id}")
                db.delete(item)
            elif payload.entity == "shifts":
                item = db.query(Shift).filter(Shift.id == item_id).first()
                if not item:
                    raise HTTPException(status_code=404, detail=f"找不到排班 #{item_id}")
                db.delete(item)
            elif payload.entity == "customers":
                delete_customer_record(db, item_id)
            elif payload.entity == "staff":
                permanently_delete_staff(item_id, db, actor_id=actor.id, reason=payload.reason, commit=False)
            elif payload.entity == "services":
                delete_service_record(db, item_id)
            elif payload.entity == "promotions":
                delete_promotion_record(db, item_id)
            elif payload.entity == "rooms":
                delete_room_record(db, item_id)
            elif payload.entity == "venues":
                delete_venue_record(db, item_id)
            elif payload.entity == "users":
                delete_admin_user_record(db, item_id, actor)
            elif payload.entity == "audit_logs":
                item = db.query(AuditLog).filter(AuditLog.id == item_id).first()
                if not item:
                    raise HTTPException(status_code=404, detail=f"找不到操作紀錄 #{item_id}")
                db.delete(item)
            deleted.append(item_id)
        audit(db, actor, "bulk_permanent_delete", payload.entity, reason=payload.reason, after={"ids": deleted})
        db.commit()
        return {"ok": True, "entity": payload.entity, "deleted_ids": deleted}

    @app.get("/api/admin/export/{dataset}")
    def export_dataset(dataset: Literal["appointments", "shifts", "customers", "staff_returns"], start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db), actor=Depends(current_admin)):
        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)
        if dataset == "appointments":
            query = db.query(Appointment)
            if start:
                query = query.filter(Appointment.start_time >= parse_local_datetime(start))
            if end:
                query = query.filter(Appointment.start_time < parse_local_datetime(end))
            writer.writerow(["訂單編號", "日期", "開始", "結束", "客戶", "電話", "師傅", "方案", "場地", "狀態", "金額"])
            items = query.order_by(Appointment.start_time).all()
            for item, row in zip(items, appointment_dicts(db, items)):
                writer.writerow([row["order_id"], item.start_time.date(), item.start_time.strftime("%H:%M"), item.end_time.strftime("%H:%M"), row["customer_name"], row["phone"], row["staff_name"], row["service_name"], row["room_name"] or row["venue_name"] or row["location_type"], row["status_label"], row["total_amount"]])
        elif dataset == "shifts":
            writer.writerow(["排班編號", "師傅", "日期", "開始", "結束", "來源", "狀態"])
            query = db.query(Shift)
            if start:
                query = query.filter(Shift.start_time >= parse_local_datetime(start))
            if end:
                query = query.filter(Shift.start_time < parse_local_datetime(end))
            items = query.order_by(Shift.start_time).all()
            staff = _model_map(db, Staff, {item.staff_id for item in items})
            for item in items:
                staff_obj = staff.get(item.staff_id)
                writer.writerow([item.id, staff_obj.name if staff_obj else item.staff_id, item.start_time.date(), item.start_time.strftime("%H:%M"), item.end_time.strftime("%H:%M"), item.source, item.status])
        elif dataset == "customers":
            writer.writerow(["內部識別（等級-手機後四碼）", "客戶名稱", "手機 ID（可多支）", "建立日期"])
            query = db.query(User)
            if start:
                query = query.filter(User.created_at >= parse_local_datetime(start))
            if end:
                query = query.filter(User.created_at < parse_local_datetime(end))
            items = query.order_by(User.id).all()
            customers = {item["id"]: item for item in customer_dicts(db, items)}
            for item in items:
                phones = customers[item.id]["phones"]
                writer.writerow([customer_serial(item.id, phones[0] if phones else item.phone, getattr(item, "customer_grade", "N")), getattr(item, "display_name", None) or "未命名客戶", "、".join(phones), item.created_at])
        else:
            writer.writerow(["回帳編號", "訂單編號", "師傅", "應回帳", "狀態", "建立時間", "確認時間"])
            query = db.query(StaffReturn)
            if start:
                query = query.filter(StaffReturn.created_at >= parse_local_datetime(start))
            if end:
                query = query.filter(StaffReturn.created_at < parse_local_datetime(end))
            items = query.order_by(StaffReturn.created_at).all()
            appointments = _model_map(db, Appointment, {item.appointment_id for item in items})
            staff = _model_map(db, Staff, {item.staff_id for item in items})
            for item in items:
                appointment = appointments.get(item.appointment_id)
                staff_obj = staff.get(item.staff_id)
                writer.writerow([item.id, f"AP-{appointment.start_time.strftime('%m%d')}-{appointment.id:03d}" if appointment else item.appointment_id, staff_obj.name if staff_obj else item.staff_id, item.amount, item.status, item.created_at, item.confirmed_at])
        audit(db, actor, "export", dataset, reason=f"start={start};end={end}")
        db.commit()
        output.seek(0)
        filename = f"equalspa-{dataset}-{now_taipei_naive().strftime('%Y%m%d')}.csv"
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    def staff_from_token(token: str, db: Session):
        record = db.query(StaffScheduleToken).filter(StaffScheduleToken.token_hash == _token_hash(token), StaffScheduleToken.revoked_at.is_(None)).first()
        if not record:
            raise HTTPException(status_code=404, detail="班表連結無效或已撤銷")
        staff_obj = db.query(Staff).filter(Staff.id == record.staff_id, Staff.employment_status == "active").first()
        if not staff_obj:
            raise HTTPException(status_code=404, detail="師傅帳號目前不可使用")
        return staff_obj

    @app.get("/api/staff/schedule/{token}")
    def public_staff_schedule(token: str, start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db)):
        staff_obj = staff_from_token(token, db)
        query = db.query(Shift).filter(Shift.staff_id == staff_obj.id, Shift.status == "active")
        if start:
            query = query.filter(Shift.end_time > parse_local_datetime(start))
        if end:
            query = query.filter(Shift.start_time < parse_local_datetime(end))
        return {"staff": {"id": staff_obj.id, "name": staff_obj.name}, "rules": {"minimum_hours": 0, "lock_minutes": 90}, "shifts": [shift_dict(item) for item in query.order_by(Shift.start_time).all()]}

    @app.post("/api/staff/schedule/{token}", status_code=201)
    def public_staff_create_shift(token: str, payload: PublicShiftCreateIn, db: Session = Depends(get_db)):
        staff_obj = staff_from_token(token, db)
        start_dt, end_dt = validate_shift_period(payload.start_time, payload.end_time)
        if not staff_may_change_shift(start_dt):
            raise HTTPException(status_code=422, detail="開始時間已進入 90 分鐘鎖定範圍，請聯絡店長")
        if shift_conflict(db, staff_obj.id, start_dt, end_dt):
            raise HTTPException(status_code=409, detail="排班時間重疊")
        item = Shift(staff_id=staff_obj.id, start_time=start_dt, end_time=end_dt, source="staff_link")
        db.add(item)
        db.flush()
        audit(db, None, "create", "shift", item.id, reason="staff schedule link", after=shift_dict(item))
        db.commit()
        return shift_dict(item)

    @app.delete("/api/staff/schedule/{token}/{shift_id}")
    def public_staff_delete_shift(token: str, shift_id: int, db: Session = Depends(get_db)):
        staff_obj = staff_from_token(token, db)
        item = db.query(Shift).filter(Shift.id == shift_id, Shift.staff_id == staff_obj.id, Shift.status == "active").first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到排班")
        if not staff_may_change_shift(item.start_time):
            raise HTTPException(status_code=422, detail="此班已鎖定，請聯絡店長")
        item.status = "cancelled"
        item.change_reason = "staff self-cancelled"
        audit(db, None, "cancel", "shift", item.id, reason="staff schedule link")
        db.commit()
        return {"ok": True}

    @app.post("/api/staff/shifts", status_code=201)
    def staff_session_create_shift(payload: PublicShiftCreateIn, db: Session = Depends(get_db), staff_obj=Depends(current_staff)):
        start_dt, end_dt = validate_shift_period(payload.start_time, payload.end_time)
        if not staff_may_change_shift(start_dt):
            raise HTTPException(status_code=422, detail="開始時間已進入 90 分鐘鎖定範圍，請聯絡店長")
        if shift_conflict(db, staff_obj.id, start_dt, end_dt):
            raise HTTPException(status_code=409, detail="排班時間重疊")
        item = Shift(staff_id=staff_obj.id, start_time=start_dt, end_time=end_dt, source="staff_link")
        db.add(item)
        db.flush()
        audit(db, None, "create", "shift", item.id, reason=f"staff session {staff_obj.id}", after=shift_dict(item))
        db.commit()
        return shift_dict(item) | {"staff_name": staff_obj.name}

    @app.delete("/api/staff/shifts/{shift_id}")
    def staff_session_delete_shift(shift_id: int, db: Session = Depends(get_db), staff_obj=Depends(current_staff)):
        item = db.query(Shift).filter(Shift.id == shift_id, Shift.staff_id == staff_obj.id, Shift.status == "active").first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到自己的排班")
        if not staff_may_change_shift(item.start_time):
            raise HTTPException(status_code=422, detail="此班已鎖定，請聯絡店長")
        item.status = "cancelled"
        item.change_reason = "staff self-cancelled"
        audit(db, None, "cancel", "shift", item.id, reason=f"staff session {staff_obj.id}")
        db.commit()
        return {"ok": True}
