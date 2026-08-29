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
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
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


class AdminUserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    pin: str = Field(min_length=4, max_length=32, pattern=r"^\d+$")
    role: Literal["admin", "manager", "clerk"] = "clerk"


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
    status: str | None = None
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


class ServicePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    duration_minutes: int | None = Field(default=None, ge=30, le=480)
    price: int | None = Field(default=None, ge=0)
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
    staff_id: int | None = None
    phone: str | None = Field(default=None, min_length=8, max_length=50)


class StaffMagicLoginIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class CustomerPatchIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    phones: list[str] = Field(min_length=1, max_length=10)


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
    website: str = Field(default="", max_length=0)


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


class StaffStatusIn(BaseModel):
    employment_status: Literal["active", "retired"]
    reason: str = Field(min_length=1, max_length=500)


class StaffPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    category: Literal["straight", "gay", "bisexual"] | None = None
    return_rule_set_id: int | None = None
    photo_url: str | None = Field(default=None, max_length=1000)


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
        "ReturnRuleSet": ReturnRuleSet,
        "ReturnRule": ReturnRule,
        "StaffReturn": StaffReturn,
        "PublicBookingRequest": PublicBookingRequest,
        "SiteContent": SiteContent,
    }

    def normalize_phone(value: str | None) -> str:
        cleaned = re.sub(r"[\s()\-]", "", (value or "").strip())
        if cleaned.startswith("+886"):
            cleaned = "0" + cleaned[4:]
        if not re.fullmatch(r"09\d{8}", cleaned):
            raise HTTPException(status_code=422, detail="手機號碼必須是 09 開頭的 10 碼數字")
        return cleaned

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
                )
                db.add(customer)
                db.flush()
            attach_customer_phone(db, customer, contact_phone)
            if not getattr(customer, "display_name", None):
                customer.display_name = line_identity.get("name") or payload.customer_name.strip()
            return customer, contact_phone, "liff"

        customer = phone_customer
        if not customer:
            customer = User(
                line_user_id=f"manual:{secrets.token_hex(16)}",
                phone=contact_phone,
                display_name=payload.customer_name.strip(),
            )
            db.add(customer)
            db.flush()
        attach_customer_phone(db, customer, contact_phone)
        if not getattr(customer, "display_name", None):
            customer.display_name = payload.customer_name.strip()
        return customer, contact_phone, "web"

    def available_staff(db: Session, start_dt: datetime, end_dt: datetime) -> list:
        result = []
        active_staff = db.query(Staff).filter(Staff.employment_status == "active").order_by(Staff.name).all()
        for staff_obj in active_staff:
            on_shift = db.query(Shift).filter(
                Shift.staff_id == staff_obj.id,
                Shift.status == "active",
                Shift.start_time <= start_dt,
                Shift.end_time >= end_dt,
            ).first()
            if on_shift and not staff_appointment_conflict(db, staff_obj.id, start_dt, end_dt):
                result.append(staff_obj)
        return result

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
    ) -> dict[str, Any]:
        item = db.query(Staff).filter(Staff.id == staff_id).with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")

        dependencies = {
            "預約": db.query(Appointment).filter(Appointment.staff_id == staff_id).count(),
            "排班": db.query(Shift).filter(Shift.staff_id == staff_id).count(),
            "付款": db.query(Payment).filter(Payment.received_by_staff_id == staff_id).count(),
            "回帳": db.query(StaffReturn).filter(StaffReturn.staff_id == staff_id).count(),
        }
        retained = [f"{label} {count} 筆" for label, count in dependencies.items() if count]
        if retained:
            raise HTTPException(
                status_code=409,
                detail=f"{item.name} 仍有{'、'.join(retained)}歷史，不能永久刪除；請改用暫時退役以保留帳務與稽核紀錄。",
            )

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
        for model in (StaffScheduleToken, StaffPrivateHealth, StaffSession, StaffMagicLink, StaffPhoto):
            db.query(model).filter(model.staff_id == staff_id).delete(synchronize_session=False)
        deleted_name = item.name
        db.delete(item)
        audit(db, actor, "permanent_delete", "staff", staff_id, reason=reason, before=before)
        db.commit()
        return {"ok": True, "deleted_staff_id": staff_id, "deleted_staff_name": deleted_name}

    app.state.permanently_delete_staff = permanently_delete_staff

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
        return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "is_active": user.is_active}

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

    app.state.line_admin_identity = line_admin_identity
    app.state.bind_line_admin = bind_line_admin
    app.state.unbind_line_admin = unbind_line_admin

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
        }

    def staff_dict(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "phone": item.phone,
            "category": getattr(item, "category", None),
            "employment_status": getattr(item, "employment_status", "active"),
            "line_connected": not item.line_user_id.startswith(("pending:", "seeded:")) if item.line_user_id else False,
            "height": item.height,
            "weight": item.weight,
            "photo_url": getattr(item, "photo_url", None),
            "role": item.role,
            "return_rule_set_id": getattr(item, "return_rule_set_id", None),
        }

    def return_rule_sets_dict(db: Session) -> list[dict[str, Any]]:
        result = []
        for rule_set in db.query(ReturnRuleSet).order_by(ReturnRuleSet.id).all():
            rules = db.query(ReturnRule).filter(ReturnRule.rule_set_id == rule_set.id).order_by(ReturnRule.id).all()
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

    def appointment_dict(db: Session, item) -> dict[str, Any]:
        detail = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == item.id).first()
        plan = db.query(ServicePlan).filter(ServicePlan.id == detail.service_plan_id).first() if detail and detail.service_plan_id else None
        promotion = db.query(Promotion).filter(Promotion.id == detail.promotion_id).first() if detail and detail.promotion_id else None
        room = db.query(Room).filter(Room.id == detail.room_id).first() if detail and detail.room_id else None
        venue = db.query(Venue).filter(Venue.id == detail.venue_id).first() if detail and detail.venue_id else None
        user = db.query(User).filter(User.id == item.user_id).first()
        staff_obj = db.query(Staff).filter(Staff.id == item.staff_id).first() if item.staff_id else None
        payment = db.query(Payment).filter(Payment.appointment_id == item.id, Payment.status == "paid").order_by(Payment.id.desc()).first()
        staff_return = db.query(StaffReturn).filter(StaffReturn.appointment_id == item.id).first()
        return_rule = return_rule_for_appointment(db, item, detail)
        return {
            "id": item.id,
            "order_id": f"AP-{item.start_time.strftime('%m%d')}-{item.id:03d}",
            "customer_id": item.user_id,
            "customer_serial": customer_serial(item.user_id),
            "customer_name": getattr(user, "display_name", None) or "未命名客戶",
            "phone": (detail.contact_phone if detail and detail.contact_phone else user.phone) if user else None,
            "staff_id": item.staff_id,
            "staff_name": staff_obj.name if staff_obj else "未指定",
            "service_plan_id": plan.id if plan else None,
            "service_name": plan.name if plan else item.plan_name or "未知方案",
            "promotion_id": promotion.id if promotion else None,
            "promotion_name": promotion.name if promotion else None,
            "duration_minutes": item.duration,
            "start_time": _iso(item.start_time),
            "end_time": _iso(item.end_time),
            "status": item.status,
            "status_label": STATUS_TO_ZH.get(item.status, item.status),
            "room_id": detail.room_id if detail else None,
            "room_name": room.name if room else None,
            "venue_id": detail.venue_id if detail else None,
            "venue_name": venue.name if venue else None,
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

    def public_appointment_dict(db: Session, item) -> dict[str, Any]:
        row = appointment_dict(db, item)
        for key in ("customer_id", "customer_serial", "customer_name", "phone", "base_price", "discount_amount", "extra_amount", "total_amount", "notes", "payment_method", "cash_return_status", "expected_return_amount", "staff_return_status"):
            row.pop(key, None)
        row["customer_name"] = "已隱藏"
        row["phone"] = None
        row["total_amount"] = 0
        row["notes"] = None
        return row

    def customer_dict(db: Session, item) -> dict[str, Any]:
        visits = db.query(Appointment).filter(
            Appointment.user_id == item.id,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
        ).all()
        spent = 0
        for appointment in visits:
            detail = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment.id).first()
            spent += detail.total_amount if detail else appointment_price_from_legacy(appointment)
        phones = [row.phone for row in customer_phone_rows(db, item)]
        return {
            "id": item.id,
            "vip_serial": customer_serial(item.id),
            "display_name": getattr(item, "display_name", None),
            "primary_phone": phones[0] if phones else item.phone,
            "phones": phones or ([item.phone] if item.phone else []),
            "visits": len(visits),
            "spent": spent,
            "last_visit": _iso(max((appointment.start_time for appointment in visits), default=None)),
        }

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
            for username, display_name, role_name, pin in initial_users:
                if db.query(AdminUser).filter(AdminUser.username == username).first():
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
            for code, name, duration, price, description, location, choose_staff in seed_plans:
                if not db.query(ServicePlan).filter(ServicePlan.code == code).first():
                    db.add(ServicePlan(code=code, name=name, duration_minutes=duration, price=price, description=description, location_type=location, can_choose_staff=choose_staff))

            for room_name in ("房間 1", "房間 2"):
                if not db.query(Room).filter(Room.name == room_name).first():
                    db.add(Room(name=room_name))

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
            for name, calculation_type, value, description in seed_promotions:
                if not db.query(Promotion).filter(Promotion.name == name).first():
                    db.add(Promotion(name=name, calculation_type=calculation_type, value=value, description=description))

            return_tables = [
                ("TABLE_1", "回帳表一（A–E／借房）", [("A", "A方案", 700, 60), ("B", "B方案", 800, 60), ("C", "C方案", 1000, 90), ("D", "D方案", 1200, 120), ("E", "E方案", 1200, 100), ("BORROW", "借房", 300, 60)]),
                ("TABLE_2", "回帳表二（A–D）", [("A", "A方案", 300, 60), ("B", "B方案", 300, 60), ("C", "C方案", 400, 90), ("D", "D方案", 500, 120)]),
            ]
            for code, name, rules in return_tables:
                rule_set = db.query(ReturnRuleSet).filter(ReturnRuleSet.code == code).first()
                if not rule_set:
                    rule_set = ReturnRuleSet(code=code, name=name)
                    db.add(rule_set)
                    db.flush()
                for service_code, rule_name, amount, duration in rules:
                    if not db.query(ReturnRule).filter(ReturnRule.rule_set_id == rule_set.id, ReturnRule.service_code == service_code).first():
                        db.add(ReturnRule(rule_set_id=rule_set.id, service_code=service_code, name=rule_name, amount=amount, duration_minutes=duration))
            if not db.query(SiteContent).filter(SiteContent.content_key == "official_site").first():
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

    @app.get("/api/public/bootstrap")
    def public_bootstrap(db: Session = Depends(get_db)):
        appointments = db.query(Appointment).order_by(Appointment.start_time.desc()).limit(300).all()
        shifts = db.query(Shift).filter(Shift.status == "active").order_by(Shift.start_time).limit(500).all()
        return {
            "mode": "public",
            "user": None,
            "appointments": [public_appointment_dict(db, item) for item in appointments],
            "staff": [{"id": item.id, "name": item.name, "category": item.category, "employment_status": item.employment_status, "line_connected": False} for item in db.query(Staff).filter(Staff.employment_status == "active").order_by(Staff.name).all()],
            "shifts": [shift_dict(item) | {"staff_name": (db.query(Staff).filter(Staff.id == item.staff_id).first().name if db.query(Staff).filter(Staff.id == item.staff_id).first() else "未知")} for item in shifts],
            "services": [service_dict(item) for item in db.query(ServicePlan).filter(ServicePlan.active.is_(True)).order_by(ServicePlan.id).all()],
            "promotions": [promotion_dict(item) for item in db.query(Promotion).filter(Promotion.active.is_(True)).order_by(Promotion.id).all()],
            "rooms": [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).filter(Room.active.is_(True)).order_by(Room.id).all()],
            "customers": [],
            "admin_users": [],
            "return_rule_sets": [],
        }

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
        services = db.query(ServicePlan).filter(ServicePlan.active.is_(True)).order_by(ServicePlan.id).all()
        promotions = db.query(Promotion).filter(
            Promotion.active.is_(True),
            Promotion.calculation_type.in_(["fixed_discount", "percent_discount"]),
        ).order_by(Promotion.id).all()
        promotions = [item for item in promotions if (not item.starts_at or item.starts_at <= now) and (not item.ends_at or item.ends_at >= now)]
        liff_id = os.getenv("LINE_LIFF_ID", "").strip()
        return {
            "services": [service_dict(item) for item in services],
            "promotions": [promotion_dict(item) for item in promotions],
            "minimum_lead_minutes": 90,
            "support_url": os.getenv("CUSTOMER_SERVICE_URL", "https://lin.ee/vOq3Xvt"),
            "liff_id": liff_id or None,
            "line_login_enabled": bool(liff_id and os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()),
        }

    @app.get("/api/public/booking/availability")
    def public_booking_availability(service_plan_id: int, start_time: datetime, db: Session = Depends(get_db)):
        plan = db.query(ServicePlan).filter(ServicePlan.id == service_plan_id, ServicePlan.active.is_(True)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        start_dt = parse_local_datetime(start_time)
        try:
            validate_booking_start(start_dt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        end_dt = appointment_end(start_dt, plan.duration_minutes)
        staff_items = available_staff(db, start_dt, end_dt)
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

    @app.post("/api/staff/auth/login")
    def staff_login(payload: StaffLoginIn, db: Session = Depends(get_db)):
        if not payload.staff_id or not payload.phone:
            raise HTTPException(status_code=422, detail="請同時選擇自己的名字並輸入手機號碼")
        phone = normalize_phone(payload.phone)
        staff_obj = db.query(Staff).filter(
            Staff.id == payload.staff_id,
            Staff.phone == phone,
            Staff.employment_status == "active",
        ).first()
        if not staff_obj:
            raise HTTPException(status_code=401, detail="姓名與手機號碼不相符")
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
            "appointments": [appointment_dict(db, item) for item in appointments],
            "staff": [staff_dict(staff_obj)],
            "shifts": [shift_dict(item) | {"staff_name": staff_obj.name} for item in shifts],
            "services": [service_dict(item) for item in db.query(ServicePlan).filter(ServicePlan.active.is_(True)).order_by(ServicePlan.id).all()],
            "promotions": [promotion_dict(item) for item in db.query(Promotion).filter(Promotion.active.is_(True)).order_by(Promotion.id).all()],
            "rooms": [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).filter(Room.active.is_(True)).order_by(Room.id).all()],
            "customers": [],
            "admin_users": [],
            "return_rule_sets": [],
        }

    @app.patch("/api/staff/appointments/{appointment_id}/complete")
    def staff_complete_appointment(appointment_id: int, db: Session = Depends(get_db), staff_obj=Depends(current_staff)):
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.staff_id == staff_obj.id).with_for_update().first()
        if not appointment:
            raise HTTPException(status_code=404, detail="找不到自己的訂單")
        if appointment.status in CANCELLED_APPOINTMENT_STATUSES:
            raise HTTPException(status_code=422, detail="已取消訂單不能標記完成")
        appointment.status = "awaiting_checkout"
        audit(db, None, "staff_complete", "appointment", appointment.id, reason=f"staff_id={staff_obj.id}")
        db.commit()
        return appointment_dict(db, appointment)

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

    @app.get("/api/admin/bootstrap")
    def bootstrap(db: Session = Depends(get_db), user=Depends(current_admin)):
        appointments = db.query(Appointment).order_by(Appointment.start_time.desc()).limit(300).all()
        shift_rows = db.query(Shift).filter(Shift.status == "active").order_by(Shift.start_time).limit(500).all()
        audit_rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(20).all()
        return {
            "user": serialize_admin(user),
            "appointments": [appointment_dict(db, item) for item in appointments],
            "staff": [staff_dict(item) for item in db.query(Staff).order_by(Staff.name).all()],
            "shifts": [shift_dict(item) | {"staff_name": db.query(Staff).filter(Staff.id == item.staff_id).first().name} for item in shift_rows],
            "services": [service_dict(item) for item in db.query(ServicePlan).order_by(ServicePlan.id).all()],
            "promotions": [promotion_dict(item) for item in db.query(Promotion).order_by(Promotion.id).all()],
            "rooms": [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).order_by(Room.id).all()],
            "venues": [{"id": item.id, "name": item.name, "address": item.address, "room_name": item.room_name, "rental_cost": item.rental_cost, "notes": item.notes, "active": item.active} for item in db.query(Venue).filter(Venue.active.is_(True)).all()],
            "customers": [customer_dict(db, item) for item in db.query(User).order_by(User.created_at.desc()).limit(1000).all()],
            "admin_users": [serialize_admin(item) for item in db.query(AdminUser).order_by(AdminUser.id).all()] if user.role in {"admin", "manager"} else [],
            "return_rule_sets": return_rule_sets_dict(db),
            "audit_logs": [{
                "id": item.id,
                "actor_name": (db.query(AdminUser).filter(AdminUser.id == item.actor_user_id).first().display_name if item.actor_user_id and db.query(AdminUser).filter(AdminUser.id == item.actor_user_id).first() else "系統／員工"),
                "action": item.action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "reason": item.reason,
                "created_at": _iso(item.created_at),
            } for item in audit_rows],
        }

    @app.get("/api/admin/appointments")
    def list_appointments(
        start: datetime | None = Query(default=None),
        end: datetime | None = Query(default=None),
        db: Session = Depends(get_db),
        user=Depends(current_admin),
    ):
        query = db.query(Appointment)
        if start:
            query = query.filter(Appointment.start_time >= parse_local_datetime(start))
        if end:
            query = query.filter(Appointment.start_time < parse_local_datetime(end))
        return [appointment_dict(db, item) for item in query.order_by(Appointment.start_time.desc()).limit(1000).all()]

    @app.get("/api/admin/customers")
    def list_customers(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        return [customer_dict(db, item) for item in db.query(User).order_by(User.created_at.desc()).limit(1000).all()]

    @app.patch("/api/admin/customers/{customer_id}")
    def update_customer(customer_id: int, payload: CustomerPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        customer = db.query(User).filter(User.id == customer_id).with_for_update().first()
        if not customer:
            raise HTTPException(status_code=404, detail="找不到客戶")
        before = customer_dict(db, customer)
        customer.display_name = payload.display_name.strip()
        sync_customer_phones(db, customer, payload.phones)
        db.flush()
        after = customer_dict(db, customer)
        audit(db, actor, "update", "customer", customer.id, before=before, after=after)
        db.commit()
        return after

    @app.post("/api/admin/appointments", status_code=201)
    def create_appointment(payload: AppointmentCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id, ServicePlan.active.is_(True)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        promotion = None
        if payload.promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == payload.promotion_id, Promotion.active.is_(True)).first()
            if not promotion:
                raise HTTPException(status_code=404, detail="找不到啟用中的優惠")
        start_dt = parse_local_datetime(payload.start_time)
        try:
            validate_booking_start(start_dt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        end_dt = appointment_end(start_dt, plan.duration_minutes)

        if payload.staff_id:
            staff_obj = db.query(Staff).filter(Staff.id == payload.staff_id).with_for_update().first()
            if not staff_obj or getattr(staff_obj, "employment_status", "active") != "active":
                raise HTTPException(status_code=404, detail="找不到可排班師傅")
            conflict = staff_appointment_conflict(db, payload.staff_id, start_dt, end_dt)
            if conflict:
                raise HTTPException(status_code=409, detail=f"師傅與訂單 AP-{conflict.id} 時間重疊")

        if payload.location_type == "onsite":
            if not payload.room_id:
                raise HTTPException(status_code=422, detail="店內預約必須選擇房間")
            room = db.query(Room).filter(Room.id == payload.room_id, Room.active.is_(True)).with_for_update().first()
            if not room:
                raise HTTPException(status_code=404, detail="找不到房間")
            conflict = room_appointment_conflict(db, payload.room_id, start_dt, end_dt)
            if conflict:
                raise HTTPException(status_code=409, detail=f"房間與訂單 AP-{conflict.id} 時間重疊")

        customer, contact_phone = customer_for_phone(db, payload.phone)
        if not customer:
            customer = User(line_user_id=f"manual:{secrets.token_hex(16)}", phone=contact_phone, display_name=payload.customer_name)
            db.add(customer)
            db.flush()
            sync_customer_phones(db, customer, [contact_phone])
        elif not getattr(customer, "display_name", None):
            customer.display_name = payload.customer_name
        customer = db.query(User).filter(User.id == customer.id).with_for_update().first()
        duplicate = db.query(Appointment).filter(
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
        )
        db.add(appointment)
        db.flush()
        detail = AppointmentDetail(
            appointment_id=appointment.id,
            service_plan_id=plan.id,
            promotion_id=promotion.id if promotion else None,
            room_id=payload.room_id,
            venue_id=payload.venue_id,
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
                    return {"duplicate": True, "appointment": appointment_dict(db, appointment)}
            raise HTTPException(status_code=409, detail="預約正在處理中，請勿重複送出")

        plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id, ServicePlan.active.is_(True)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        promotion = None
        if payload.promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == payload.promotion_id, Promotion.active.is_(True)).first()
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
            return {"duplicate": True, "appointment": appointment_dict(db, duplicate)}

        appointment = Appointment(
            user_id=customer.id,
            staff_id=payload.staff_id,
            duration=plan.duration_minutes,
            plan_name=f"{plan.code}-{plan.name}",
            start_time=start_dt,
            end_time=end_dt,
            status="confirmed",
        )
        db.add(appointment)
        db.flush()
        discount = promotion_discount(promotion, plan.price)
        source_label = "LINE LIFF 備用預約" if source == "liff" else "網頁備用預約"
        notes = f"來源：{source_label}"
        if payload.notes and payload.notes.strip():
            notes += f"\n客戶備註：{payload.notes.strip()}"
        db.add(AppointmentDetail(
            appointment_id=appointment.id,
            service_plan_id=plan.id,
            promotion_id=promotion.id if promotion else None,
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
            "staff_id": payload.staff_id,
            "promotion_id": payload.promotion_id,
        })
        db.commit()
        db.refresh(appointment)
        if appointment_notifier:
            try:
                appointment_notifier(appointment, db, origin=source_label)
            except Exception:
                logger.exception("Unable to push public booking notification appointment_id=%s", appointment.id)
        return {"duplicate": False, "appointment": appointment_dict(db, appointment)}

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
            plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id).first()
            if not plan:
                raise HTTPException(status_code=404, detail="找不到服務方案")
        promotion = None
        promotion_changed = "promotion_id" in changes
        if promotion_changed and payload.promotion_id:
            promotion = db.query(Promotion).filter(Promotion.id == payload.promotion_id, Promotion.active.is_(True)).first()
            if not promotion:
                raise HTTPException(status_code=404, detail="找不到啟用中的優惠")
        start_dt = parse_local_datetime(payload.start_time) if payload.start_time else appointment.start_time
        if payload.start_time is not None:
            try:
                validate_booking_start(start_dt)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        duration = plan.duration_minutes if plan else appointment.duration
        end_dt = appointment_end(start_dt, duration)
        staff_id = payload.staff_id if "staff_id" in changes else appointment.staff_id
        room_id = payload.room_id if "room_id" in changes else (detail.room_id if detail else None)
        if staff_id and staff_appointment_conflict(db, staff_id, start_dt, end_dt, appointment.id):
            raise HTTPException(status_code=409, detail="師傅時間重疊")
        if room_id and room_appointment_conflict(db, room_id, start_dt, end_dt, appointment.id):
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
    def create_shift(payload: ShiftCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        start_dt, end_dt = validate_shift_period(payload.start_time, payload.end_time)
        staff_obj = db.query(Staff).filter(Staff.id == payload.staff_id).with_for_update().first()
        if not staff_obj or getattr(staff_obj, "employment_status", "active") != "active":
            raise HTTPException(status_code=404, detail="找不到在職師傅")
        if shift_conflict(db, payload.staff_id, start_dt, end_dt):
            raise HTTPException(status_code=409, detail="此師傅的排班時間重疊")
        item = Shift(staff_id=payload.staff_id, start_time=start_dt, end_time=end_dt, source=actor.role, created_by_user_id=actor.id)
        db.add(item)
        db.flush()
        audit(db, actor, "create", "shift", item.id, after={"staff_id": item.staff_id, "start": start_dt, "end": end_dt})
        db.commit()
        return shift_dict(item) | {"staff_name": staff_obj.name}

    @app.delete("/api/admin/shifts/{shift_id}")
    def delete_shift(shift_id: int, reason: str | None = Query(default=None, max_length=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Shift).filter(Shift.id == shift_id, Shift.status == "active").with_for_update().first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到排班")
        locked = not staff_may_change_shift(item.start_time)
        if locked and not reason:
            raise HTTPException(status_code=422, detail="鎖定班表必須填寫強制撤銷原因")
        item.status = "cancelled"
        item.change_reason = reason
        audit(db, actor, "cancel", "shift", item.id, reason=reason, before=shift_dict(item))
        db.commit()
        return {"ok": True, "locked_override": locked}

    @app.get("/api/admin/services")
    def list_services(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [service_dict(item) for item in db.query(ServicePlan).order_by(ServicePlan.id).all()]

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
        item = db.query(ServicePlan).filter(ServicePlan.id == service_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到服務方案")
        before = service_dict(item)
        for field in ("name", "duration_minutes", "price", "active"):
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

    @app.get("/api/admin/promotions")
    def list_promotions(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [promotion_dict(item) for item in db.query(Promotion).order_by(Promotion.id).all()]

    @app.post("/api/admin/promotions", status_code=201)
    def create_promotion(payload: PromotionCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = Promotion(name=payload.name, calculation_type=payload.calculation_type, value=payload.value, starts_at=parse_local_datetime(payload.starts_at) if payload.starts_at else None, ends_at=parse_local_datetime(payload.ends_at) if payload.ends_at else None, stackable=payload.stackable)
        db.add(item)
        db.flush()
        audit(db, actor, "create", "promotion", item.id, after=_model_dump(payload))
        db.commit()
        return promotion_dict(item)

    @app.patch("/api/admin/promotions/{promotion_id}")
    def update_promotion(promotion_id: int, payload: PromotionPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Promotion).filter(Promotion.id == promotion_id).first()
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
        line_user_id = payload.line_user_id or f"pending:{secrets.token_hex(16)}"
        if db.query(Staff).filter(Staff.line_user_id == line_user_id).first():
            raise HTTPException(status_code=409, detail="LINE 帳號已存在")
        photo_url = (payload.photo_url or "").strip()
        if photo_url and not photo_url.startswith(("https://", "http://")):
            raise HTTPException(status_code=422, detail="照片網址必須以 https:// 或 http:// 開頭；本機照片請使用上傳功能")
        item = Staff(
            line_user_id=line_user_id,
            name=payload.name,
            phone=payload.phone,
            category=payload.category,
            employment_status="active",
            return_rule_set_id=payload.return_rule_set_id,
            photo_url=photo_url or None,
        )
        db.add(item)
        db.flush()
        audit(db, actor, "create", "staff", item.id, after=staff_dict(item))
        db.commit()
        return staff_dict(item)

    @app.patch("/api/admin/staff/{staff_id}")
    def update_staff(staff_id: int, payload: StaffPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(Staff).filter(Staff.id == staff_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到員工")
        changes = _model_dump_unset(payload)
        if "photo_url" in changes:
            photo_url = (changes["photo_url"] or "").strip()
            if photo_url and not photo_url.startswith(("https://", "http://", "/api/public/staff/")):
                raise HTTPException(status_code=422, detail="照片網址必須以 https:// 或 http:// 開頭；本機照片請使用上傳功能")
            changes["photo_url"] = photo_url or None
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

    @app.delete("/api/admin/staff/{staff_id}")
    def delete_staff_permanently(
        staff_id: int,
        reason: str = Query(min_length=3, max_length=500),
        db: Session = Depends(get_db),
        actor=Depends(require_roles("admin")),
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
            cash_return_status="pending" if payload.method == "cash" else "not_applicable",
            received_by_staff_id=payload.received_by_staff_id,
            confirmed_by_user_id=actor.id if payload.method == "transfer" else None,
            note=payload.note,
        )
        db.add(payment)
        appointment.status = "completed"
        db.flush()
        return_amount = 0
        staff_return = None
        if payload.method == "cash" and payload.received_by_staff_id:
            if appointment.staff_id and appointment.staff_id != payload.received_by_staff_id:
                raise HTTPException(status_code=422, detail="代收師傅必須與訂單師傅相同")
            rule = return_rule_for_appointment(db, appointment)
            return_amount = rule.amount if rule else 0
            staff_return = StaffReturn(
                appointment_id=appointment.id,
                staff_id=payload.received_by_staff_id,
                rule_id=rule.id if rule else None,
                amount=return_amount,
                status="pending",
                note=payload.note,
            )
            db.add(staff_return)
        audit(db, actor, "checkout", "appointment", appointment_id, after={"amount": payload.amount, "method": payload.method})
        db.commit()
        return {"ok": True, "payment_id": payment.id, "cash_return_status": payment.cash_return_status, "return_amount": return_amount, "staff_return_id": staff_return.id if staff_return else None, "appointment": appointment_dict(db, appointment)}

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
        result = []
        for item in db.query(StaffReturn).order_by(StaffReturn.created_at.desc()).limit(1000).all():
            appointment = db.query(Appointment).filter(Appointment.id == item.appointment_id).first()
            staff_obj = db.query(Staff).filter(Staff.id == item.staff_id).first()
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
    def create_admin_user(payload: AdminUserCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin"))):
        if db.query(AdminUser).filter(AdminUser.username == payload.username.lower()).first():
            raise HTTPException(status_code=409, detail="登入帳號已存在")
        item = AdminUser(username=payload.username.lower(), display_name=payload.display_name, role=payload.role, pin_hash=password_hash.hash(payload.pin))
        db.add(item)
        db.flush()
        audit(db, actor, "create", "admin_user", item.id, after=serialize_admin(item))
        db.commit()
        return serialize_admin(item)

    @app.delete("/api/admin/users/{user_id}")
    def deactivate_admin_user(user_id: int, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = db.query(AdminUser).filter(AdminUser.id == user_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="找不到後台帳號")
        if item.id == actor.id:
            raise HTTPException(status_code=422, detail="不能停用目前登入中的自己")
        if actor.role == "manager" and item.role != "clerk":
            raise HTTPException(status_code=403, detail="店長只能停用客服帳號")
        if item.role == "admin" and item.is_active:
            active_admins = db.query(AdminUser).filter(AdminUser.role == "admin", AdminUser.is_active.is_(True)).count()
            if active_admins <= 1:
                raise HTTPException(status_code=422, detail="系統至少必須保留一個啟用中的 Admin")
        if not item.is_active:
            return serialize_admin(item)
        before = serialize_admin(item)
        item.is_active = False
        db.query(AdminSession).filter(AdminSession.admin_user_id == item.id).delete(synchronize_session=False)
        audit(db, actor, "deactivate", "admin_user", item.id, before=before, after=serialize_admin(item))
        db.commit()
        return serialize_admin(item)

    @app.get("/api/admin/audit-logs")
    def list_audit_logs(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        result = []
        for item in db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all():
            user = db.query(AdminUser).filter(AdminUser.id == item.actor_user_id).first() if item.actor_user_id else None
            result.append({"id": item.id, "actor": user.display_name if user else "系統", "action": item.action, "entity_type": item.entity_type, "entity_id": item.entity_id, "reason": item.reason, "created_at": _iso(item.created_at)})
        return result

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
            for item in query.order_by(Appointment.start_time).all():
                row = appointment_dict(db, item)
                writer.writerow([row["order_id"], item.start_time.date(), item.start_time.strftime("%H:%M"), item.end_time.strftime("%H:%M"), row["customer_name"], row["phone"], row["staff_name"], row["service_name"], row["room_name"] or row["venue_name"] or row["location_type"], row["status_label"], row["total_amount"]])
        elif dataset == "shifts":
            writer.writerow(["排班編號", "師傅", "日期", "開始", "結束", "來源", "狀態"])
            query = db.query(Shift)
            if start:
                query = query.filter(Shift.start_time >= parse_local_datetime(start))
            if end:
                query = query.filter(Shift.start_time < parse_local_datetime(end))
            for item in query.order_by(Shift.start_time).all():
                staff_obj = db.query(Staff).filter(Staff.id == item.staff_id).first()
                writer.writerow([item.id, staff_obj.name if staff_obj else item.staff_id, item.start_time.date(), item.start_time.strftime("%H:%M"), item.end_time.strftime("%H:%M"), item.source, item.status])
        elif dataset == "customers":
            writer.writerow(["客戶流水", "客戶名稱", "客戶 ID（手機，可多支）", "建立日期"])
            query = db.query(User)
            if start:
                query = query.filter(User.created_at >= parse_local_datetime(start))
            if end:
                query = query.filter(User.created_at < parse_local_datetime(end))
            for item in query.order_by(User.id).all():
                phones = [row.phone for row in customer_phone_rows(db, item)]
                writer.writerow([customer_serial(item.id), getattr(item, "display_name", None) or "未命名客戶", "、".join(phones), item.created_at])
        else:
            writer.writerow(["回帳編號", "訂單編號", "師傅", "應回帳", "狀態", "建立時間", "確認時間"])
            query = db.query(StaffReturn)
            if start:
                query = query.filter(StaffReturn.created_at >= parse_local_datetime(start))
            if end:
                query = query.filter(StaffReturn.created_at < parse_local_datetime(end))
            for item in query.order_by(StaffReturn.created_at).all():
                appointment = db.query(Appointment).filter(Appointment.id == item.appointment_id).first()
                staff_obj = db.query(Staff).filter(Staff.id == item.staff_id).first()
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
        return {"staff": {"id": staff_obj.id, "name": staff_obj.name}, "rules": {"minimum_hours": 2, "lock_minutes": 90}, "shifts": [shift_dict(item) for item in query.order_by(Shift.start_time).all()]}

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
