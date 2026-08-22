"""FastAPI administration API for the Equal SPA operations dashboard.

The LINE webhook remains in ``main.py``. This module adds durable MySQL models,
role-based authentication, scheduling/room conflict checks, checkout records,
exports, and the staff no-password schedule link.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Session

from scheduling import (
    CANCELLED_APPOINTMENT_STATUSES,
    appointment_end,
    now_taipei_naive,
    parse_local_datetime,
    staff_may_change_shift,
    validate_shift_period,
)


logger = logging.getLogger(__name__)
password_hash = PasswordHash.recommended()
DUMMY_PIN_HASH = password_hash.hash("000000-not-a-real-pin")
SESSION_HOURS = 8
MAX_LOGIN_FAILURES = 5
LOCK_MINUTES = 15

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
    pin: str = Field(min_length=6, max_length=32, pattern=r"^\d+$")
    role: Literal["admin", "manager", "clerk"] = "clerk"


class AppointmentCreateIn(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    service_plan_id: int
    start_time: datetime
    staff_id: int | None = None
    room_id: int | None = None
    venue_id: int | None = None
    location_type: Literal["onsite", "external", "pending"] = "onsite"
    notes: str | None = Field(default=None, max_length=2000)


class AppointmentPatchIn(BaseModel):
    status: str | None = None
    staff_id: int | None = None
    room_id: int | None = None
    venue_id: int | None = None
    start_time: datetime | None = None
    service_plan_id: int | None = None
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


class CheckoutIn(BaseModel):
    amount: int = Field(ge=0)
    method: Literal["cash", "transfer"]
    received_by_staff_id: int | None = None
    note: str | None = Field(default=None, max_length=1000)


class StaffCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: Literal["straight", "gay", "bisexual"]
    line_user_id: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


class StaffStatusIn(BaseModel):
    employment_status: Literal["active", "retired"]
    reason: str = Field(min_length=1, max_length=500)


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


def register_admin_api(
    app,
    *,
    Base,
    engine,
    SessionLocal,
    User,
    Staff,
    Appointment,
) -> None:
    """Register models, startup seeding, and all API endpoints."""

    class AdminUser(Base):
        __tablename__ = "admin_users"
        id = Column(Integer, primary_key=True)
        username = Column(String(80), unique=True, nullable=False, index=True)
        display_name = Column(String(120), nullable=False)
        pin_hash = Column(String(255), nullable=False)
        role = Column(String(30), nullable=False, default="clerk")
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
        room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
        venue_id = Column(Integer, ForeignKey("venues.id"), nullable=True)
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
    }

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

    def require_roles(*roles: str) -> Callable:
        def dependency(user=Depends(current_admin)):
            if user.role not in roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="權限不足")
            return user
        return dependency

    def serialize_admin(user) -> dict[str, Any]:
        return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "is_active": user.is_active}

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

    def staff_dict(item) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "phone": item.phone,
            "category": getattr(item, "category", None),
            "employment_status": getattr(item, "employment_status", "active"),
            "line_connected": not item.line_user_id.startswith("pending:") if item.line_user_id else False,
            "height": item.height,
            "weight": item.weight,
            "role": item.role,
        }

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
        room = db.query(Room).filter(Room.id == detail.room_id).first() if detail and detail.room_id else None
        venue = db.query(Venue).filter(Venue.id == detail.venue_id).first() if detail and detail.venue_id else None
        user = db.query(User).filter(User.id == item.user_id).first()
        staff_obj = db.query(Staff).filter(Staff.id == item.staff_id).first() if item.staff_id else None
        payment = db.query(Payment).filter(Payment.appointment_id == item.id, Payment.status == "paid").order_by(Payment.id.desc()).first()
        return {
            "id": item.id,
            "order_id": f"AP-{item.start_time.strftime('%m%d')}-{item.id:03d}",
            "customer_id": item.user_id,
            "customer_name": getattr(user, "display_name", None) or f"VIP-{item.user_id:04d}",
            "phone": user.phone if user else None,
            "staff_id": item.staff_id,
            "staff_name": staff_obj.name if staff_obj else "未指定",
            "service_plan_id": plan.id if plan else None,
            "service_name": plan.name if plan else item.plan_name or "未知方案",
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
        }

    def customer_dict(db: Session, item) -> dict[str, Any]:
        visits = db.query(Appointment).filter(
            Appointment.user_id == item.id,
            Appointment.status.notin_(CANCELLED_APPOINTMENT_STATUSES),
        ).all()
        spent = 0
        for appointment in visits:
            detail = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment.id).first()
            spent += detail.total_amount if detail else appointment_price_from_legacy(appointment)
        return {
            "id": item.id,
            "vip_id": f"VIP-{item.id:04d}",
            "display_name": getattr(item, "display_name", None),
            "phone": item.phone,
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
                ("admin", "Admin", "admin", os.getenv("ADMIN_INITIAL_PIN")),
                ("jerry", "Jerry", "manager", os.getenv("MANAGER_INITIAL_PIN")),
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
                ("午夜服務費", "fixed_fee", 600),
                ("預約加時（每 30 分鐘）", "per_30_minutes", 500),
                ("現場加時（每 30 分鐘）", "per_30_minutes", 700),
                ("外出里程費（每公里）", "per_km", 80),
            ]
            for name, calculation_type, value in seed_promotions:
                if not db.query(Promotion).filter(Promotion.name == name).first():
                    db.add(Promotion(name=name, calculation_type=calculation_type, value=value))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Unable to seed admin data")
        finally:
            db.close()

    @app.get("/api/admin/health")
    def admin_health():
        return {"status": "ok", "service": "equalspa-admin-api", "time": _iso(now_taipei_naive())}

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
        return {
            "user": serialize_admin(user),
            "appointments": [appointment_dict(db, item) for item in appointments],
            "staff": [staff_dict(item) for item in db.query(Staff).order_by(Staff.name).all()],
            "shifts": [shift_dict(item) | {"staff_name": db.query(Staff).filter(Staff.id == item.staff_id).first().name} for item in shift_rows],
            "services": [service_dict(item) for item in db.query(ServicePlan).order_by(ServicePlan.id).all()],
            "promotions": [{"id": item.id, "name": item.name, "calculation_type": item.calculation_type, "value": item.value, "active": item.active, "starts_at": _iso(item.starts_at), "ends_at": _iso(item.ends_at), "stackable": item.stackable} for item in db.query(Promotion).order_by(Promotion.id).all()],
            "rooms": [{"id": item.id, "name": item.name, "active": item.active} for item in db.query(Room).order_by(Room.id).all()],
            "venues": [{"id": item.id, "name": item.name, "address": item.address, "room_name": item.room_name, "rental_cost": item.rental_cost, "notes": item.notes, "active": item.active} for item in db.query(Venue).filter(Venue.active.is_(True)).all()],
            "customers": [customer_dict(db, item) for item in db.query(User).order_by(User.created_at.desc()).limit(1000).all()],
            "admin_users": [serialize_admin(item) for item in db.query(AdminUser).order_by(AdminUser.id).all()] if user.role in {"admin", "manager"} else [],
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

    @app.post("/api/admin/appointments", status_code=201)
    def create_appointment(payload: AppointmentCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id, ServicePlan.active.is_(True)).first()
        if not plan:
            raise HTTPException(status_code=404, detail="找不到啟用中的服務方案")
        start_dt = parse_local_datetime(payload.start_time)
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

        customer = db.query(User).filter(User.phone == payload.phone).first()
        if not customer:
            customer = User(line_user_id=f"manual:{secrets.token_hex(16)}", phone=payload.phone, display_name=payload.customer_name)
            db.add(customer)
            db.flush()
        elif not getattr(customer, "display_name", None):
            customer.display_name = payload.customer_name

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
            room_id=payload.room_id,
            venue_id=payload.venue_id,
            base_price=plan.price,
            total_amount=plan.price,
            location_type=payload.location_type,
            notes=payload.notes,
        )
        db.add(detail)
        audit(db, actor, "create", "appointment", appointment.id, after={"start": start_dt, "end": end_dt, "staff_id": payload.staff_id, "room_id": payload.room_id})
        db.commit()
        db.refresh(appointment)
        return appointment_dict(db, appointment)

    @app.patch("/api/admin/appointments/{appointment_id}")
    def update_appointment(appointment_id: int, payload: AppointmentPatchIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager", "clerk"))):
        appointment = db.query(Appointment).filter(Appointment.id == appointment_id).with_for_update().first()
        if not appointment:
            raise HTTPException(status_code=404, detail="找不到預約")
        detail = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment.id).first()
        before = appointment_dict(db, appointment)
        plan = None
        if payload.service_plan_id:
            plan = db.query(ServicePlan).filter(ServicePlan.id == payload.service_plan_id).first()
            if not plan:
                raise HTTPException(status_code=404, detail="找不到服務方案")
        start_dt = parse_local_datetime(payload.start_time) if payload.start_time else appointment.start_time
        duration = plan.duration_minutes if plan else appointment.duration
        end_dt = appointment_end(start_dt, duration)
        staff_id = payload.staff_id if payload.staff_id is not None else appointment.staff_id
        room_id = payload.room_id if payload.room_id is not None else (detail.room_id if detail else None)
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
        if plan:
            detail.service_plan_id = plan.id
            detail.base_price = plan.price
            detail.total_amount = plan.price - detail.discount_amount + detail.extra_amount
            appointment.plan_name = f"{plan.code}-{plan.name}"
        if payload.room_id is not None:
            detail.room_id = payload.room_id
        if payload.venue_id is not None:
            detail.venue_id = payload.venue_id
        if payload.notes is not None:
            detail.notes = payload.notes
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
        return [{"id": item.id, "name": item.name, "calculation_type": item.calculation_type, "value": item.value, "active": item.active, "starts_at": _iso(item.starts_at), "ends_at": _iso(item.ends_at), "stackable": item.stackable} for item in db.query(Promotion).order_by(Promotion.id).all()]

    @app.post("/api/admin/promotions", status_code=201)
    def create_promotion(payload: PromotionCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        item = Promotion(name=payload.name, calculation_type=payload.calculation_type, value=payload.value, starts_at=parse_local_datetime(payload.starts_at) if payload.starts_at else None, ends_at=parse_local_datetime(payload.ends_at) if payload.ends_at else None, stackable=payload.stackable)
        db.add(item)
        db.flush()
        audit(db, actor, "create", "promotion", item.id, after=_model_dump(payload))
        db.commit()
        return {"id": item.id, **_model_dump(payload), "active": True}

    @app.get("/api/admin/staff")
    def list_staff(db: Session = Depends(get_db), user=Depends(current_admin)):
        return [staff_dict(item) for item in db.query(Staff).order_by(Staff.name).all()]

    @app.post("/api/admin/staff", status_code=201)
    def create_staff(payload: StaffCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        line_user_id = payload.line_user_id or f"pending:{secrets.token_hex(16)}"
        if db.query(Staff).filter(Staff.line_user_id == line_user_id).first():
            raise HTTPException(status_code=409, detail="LINE 帳號已存在")
        item = Staff(line_user_id=line_user_id, name=payload.name, phone=payload.phone, category=payload.category, employment_status="active")
        db.add(item)
        db.flush()
        audit(db, actor, "create", "staff", item.id, after=staff_dict(item))
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
        audit(db, actor, "checkout", "appointment", appointment_id, after={"amount": payload.amount, "method": payload.method})
        db.commit()
        return {"ok": True, "payment_id": payment.id, "cash_return_status": payment.cash_return_status, "appointment": appointment_dict(db, appointment)}

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
        audit(db, actor, "confirm_cash_return", "payment", payment.id, after={"status": "confirmed"})
        db.commit()
        return {"ok": True, "cash_return_status": "confirmed"}

    @app.get("/api/admin/users")
    def list_admin_users(db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        return [serialize_admin(item) for item in db.query(AdminUser).order_by(AdminUser.id).all()]

    @app.post("/api/admin/users", status_code=201)
    def create_admin_user(payload: AdminUserCreateIn, db: Session = Depends(get_db), actor=Depends(require_roles("admin", "manager"))):
        if actor.role == "manager" and payload.role != "clerk":
            raise HTTPException(status_code=403, detail="店長只能新增櫃台帳號")
        if db.query(AdminUser).filter(AdminUser.username == payload.username.lower()).first():
            raise HTTPException(status_code=409, detail="登入帳號已存在")
        item = AdminUser(username=payload.username.lower(), display_name=payload.display_name, role=payload.role, pin_hash=password_hash.hash(payload.pin))
        db.add(item)
        db.flush()
        audit(db, actor, "create", "admin_user", item.id, after=serialize_admin(item))
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
    def export_dataset(dataset: Literal["appointments", "shifts", "customers"], start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db), actor=Depends(current_admin)):
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
        else:
            writer.writerow(["客戶編號", "LINE 顯示名稱", "電話", "建立日期"])
            query = db.query(User)
            if start:
                query = query.filter(User.created_at >= parse_local_datetime(start))
            if end:
                query = query.filter(User.created_at < parse_local_datetime(end))
            for item in query.order_by(User.id).all():
                writer.writerow([f"VIP-{item.id:04d}", getattr(item, "display_name", None), item.phone, item.created_at])
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
