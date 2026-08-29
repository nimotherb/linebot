from fastapi import FastAPI, Request, Response, BackgroundTasks
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from dotenv import load_dotenv
import os
import logging
import secrets
import threading
from datetime import datetime, date, timedelta
import re
from urllib.parse import parse_qs

from scheduling import appointment_end, now_taipei_naive, parse_local_datetime, validate_booking_start
from identifiers import customer_serial
from therapist_catalog import THERAPIST_PROFILES, therapist_photo_url

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    PostbackEvent,
    TemplateSendMessage,
    ButtonsTemplate,
    DatetimePickerTemplateAction,
    FlexSendMessage,
)

# 讀取本地 .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("環境變數 DATABASE_URL 未設定")

# 建立 SQLAlchemy engine 與 Session 工廠
engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

LINE_ADMIN_PENDING: dict[str, datetime] = {}
VALID_STAFF_ROLES = {"攻擊手", "守備方", "無特定", "攻守兼備"}
SUPPORT_URL = os.getenv("CUSTOMER_SERVICE_URL", "https://lin.ee/vOq3Xvt")
BOOKING_WEB_URL = os.getenv("BOOKING_WEB_URL", "https://equalspa-admin.pages.dev/booking")
RENDER_LOGS_URL = os.getenv("RENDER_LOGS_URL", "https://dashboard.render.com/web/srv-da059bgjo6nc73doq380/logs")
_DISPATCH_ALERTED_AT: dict[str, datetime] = {}
_HEARTBEAT_STOP = threading.Event()

# --- SQLAlchemy models ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=True)
    phone_temp = Column(String(50), nullable=True)
    display_name = Column(String(255), nullable=True)
    utm_source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    appointments = relationship("Appointment", back_populates="user", cascade="all, delete-orphan")
    phones = relationship("CustomerPhone", back_populates="user", cascade="all, delete-orphan")


class CustomerPhone(Base):
    __tablename__ = "customer_phones"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user = relationship("User", back_populates="phones")

class Staff(Base):
    __tablename__ = "staffs"
    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=True)
    phone_temp = Column(String(50), nullable=True)
    name = Column(String(255), nullable=False)
    height = Column(String(20), nullable=True)
    weight = Column(String(20), nullable=True)
    photo_url = Column(String(1000), nullable=True)
    role = Column(String(50), nullable=True)
    category = Column(String(50), nullable=True)
    employment_status = Column(String(30), default="active", nullable=False)
    return_rule_set_id = Column(Integer, nullable=True)
    is_online = Column(Boolean, default=False, nullable=False)
    online_start_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    appointments = relationship("Appointment", back_populates="staff", cascade="all, delete-orphan")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=True)
    duration = Column(Integer, nullable=False)
    plan_name = Column(String(50), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user = relationship("User", back_populates="appointments")
    staff = relationship("Staff", back_populates="appointments")

# --- Helper Functions ---
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

LINE_SECRET_CUSTOMER = os.getenv("LINE_SECRET_CUSTOMER")
LINE_TOKEN_CUSTOMER = os.getenv("LINE_TOKEN_CUSTOMER")
LINE_SECRET_STAFF = os.getenv("LINE_SECRET_STAFF")
LINE_TOKEN_STAFF = os.getenv("LINE_TOKEN_STAFF")

def line_admin_identity(user_id: str | None, db: Session):
    if not user_id:
        return None
    resolver = getattr(getattr(app, "state", None), "line_admin_identity", None)
    return resolver(user_id, db) if resolver else None


def is_line_manager(user_id: str | None, db: Session) -> bool:
    """LINE 管理權限必須先輸入 root，再以後台 PIN 綁定。"""
    return bool(line_admin_identity(user_id, db))


def handle_line_admin_message(text_value: str, user_id: str, db: Session):
    identity = line_admin_identity(user_id, db)
    if text_value in {"管理員登出", "登出管理員"}:
        unbind = getattr(getattr(app, "state", None), "unbind_line_admin", None)
        if identity and unbind:
            unbind(user_id, db)
            LINE_ADMIN_PENDING.pop(user_id, None)
            return TextSendMessage(text="管理員帳戶已從這個 LINE 登出。")
        return TextSendMessage(text="這個 LINE 目前沒有綁定管理員帳戶。")
    if text_value in {"root", "管理員", "管理選單"}:
        if identity:
            return build_root_admin_menu(identity)
        LINE_ADMIN_PENDING[user_id] = datetime.utcnow() + timedelta(minutes=5)
        return TextSendMessage(text="請在 5 分鐘內輸入您的管理 PIN。必須先輸入 root 再輸入 PIN，才會綁定這個 LINE。")
    pending_until = LINE_ADMIN_PENDING.get(user_id)
    if pending_until and pending_until < datetime.utcnow():
        LINE_ADMIN_PENDING.pop(user_id, None)
        pending_until = None
    if pending_until and re.fullmatch(r"\d{4,32}", text_value):
        binder = getattr(getattr(app, "state", None), "bind_line_admin", None)
        identity = binder(user_id, text_value, db) if binder else None
        LINE_ADMIN_PENDING.pop(user_id, None)
        if not identity:
            return TextSendMessage(text="PIN 不正確，未綁定管理員帳戶。請重新輸入 root 再試一次。")
        return build_root_admin_menu(identity)
    return None

bot_customer_api = LineBotApi(LINE_TOKEN_CUSTOMER) if LINE_TOKEN_CUSTOMER else None
handler_customer = WebhookHandler(LINE_SECRET_CUSTOMER) if LINE_SECRET_CUSTOMER else None

bot_staff_api = LineBotApi(LINE_TOKEN_STAFF) if LINE_TOKEN_STAFF else None
handler_staff = WebhookHandler(LINE_SECRET_STAFF) if LINE_SECRET_STAFF else None

logging.basicConfig(level=logging.INFO)


def normalize_phone(value: str | None) -> str:
    """Normalize a Taiwanese mobile number used as a customer/staff identity."""
    cleaned = re.sub(r"[\s()\-]", "", (value or "").strip())
    if cleaned.startswith("+886"):
        cleaned = "0" + cleaned[4:]
    if not re.fullmatch(r"09\d{8}", cleaned):
        raise ValueError("手機號碼必須是 09 開頭的 10 碼數字")
    return cleaned


def vip_serial(user: User | None) -> str:
    return customer_serial(user.id if user else None)


def valid_staff_role(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized if normalized in VALID_STAFF_ROLES else None


def customer_phone_values(db: Session, user: User | None) -> list[str]:
    if not user:
        return []
    values = [row.phone for row in db.query(CustomerPhone).filter(CustomerPhone.user_id == user.id).order_by(CustomerPhone.is_primary.desc(), CustomerPhone.id).all()]
    if not values and user.phone:
        values.append(user.phone)
    return values


def customer_by_phone(db: Session, phone: str) -> User | None:
    normalized = normalize_phone(phone)
    record = db.query(CustomerPhone).filter(CustomerPhone.phone == normalized).first()
    if record:
        return db.query(User).filter(User.id == record.user_id).first()
    return db.query(User).filter(User.phone == normalized).first()


def add_customer_phone(db: Session, user: User, phone: str, *, primary: bool = False) -> str:
    normalized = normalize_phone(phone)
    existing = db.query(CustomerPhone).filter(CustomerPhone.phone == normalized).first()
    if existing and existing.user_id != user.id:
        raise ValueError("此手機號碼已屬於其他客戶")
    if primary:
        db.query(CustomerPhone).filter(CustomerPhone.user_id == user.id).update({CustomerPhone.is_primary: False})
    if not existing:
        db.add(CustomerPhone(user_id=user.id, phone=normalized, is_primary=primary))
    elif primary:
        existing.is_primary = True
    if primary or not user.phone:
        user.phone = normalized
    return normalized


def _trace_id() -> str:
    return f"{datetime.utcnow().strftime('%m%d%H%M%S')}-{secrets.token_hex(2)}"


def notify_dispatch_error(db: Session, context: str, trace_id: str) -> None:
    """Alert bound customer-service accounts, never ordinary staff accounts."""
    if not bot_staff_api or not hasattr(app.state, "admin_models"):
        return
    cooldown_key = context.split(":", 1)[0]
    now = datetime.utcnow()
    if now - _DISPATCH_ALERTED_AT.get(cooldown_key, datetime.min) < timedelta(minutes=5):
        return
    _DISPATCH_ALERTED_AT[cooldown_key] = now
    AdminUser = app.state.admin_models.get("AdminUser")
    if not AdminUser:
        return
    alert = TextSendMessage(text=f"⚠️ LINE Bot 顯示失敗\n位置：{context}\n追蹤碼：{trace_id}\n系統紀錄：{RENDER_LOGS_URL}")
    for admin_user in db.query(AdminUser).filter(AdminUser.is_active.is_(True), AdminUser.line_user_id.isnot(None)).all():
        try:
            bot_staff_api.push_message(admin_user.line_user_id, alert)
        except Exception:
            logging.exception("無法推送客服錯誤通知 admin_user_id=%s trace=%s", admin_user.id, trace_id)


def reply_with_fallback(bot_api, reply_token: str, message, *, db: Session | None = None, context: str = "LINE 選單", admin: bool = False) -> bool:
    """Reply safely and fall back to plain text when a Flex payload is rejected."""
    try:
        bot_api.reply_message(reply_token, message)
        return True
    except Exception:
        trace_id = _trace_id()
        logging.exception("LINE 回覆失敗 context=%s trace=%s", context, trace_id)
        fallback = (
            f"系統暫時無法顯示管理選單。請稍後再試。\n追蹤碼：{trace_id}\n系統紀錄：{RENDER_LOGS_URL}"
            if admin else
            f"系統暫時無法顯示選單。您可改用備用網頁預約：{BOOKING_WEB_URL}\n真人客服：{SUPPORT_URL}\n追蹤碼：{trace_id}"
        )
        try:
            bot_api.reply_message(reply_token, TextSendMessage(text=fallback))
        except Exception:
            logging.exception("LINE 文字備援也失敗 context=%s trace=%s", context, trace_id)
        if db is not None:
            notify_dispatch_error(db, context, trace_id)
        return False

# 方案設定字典
PLANS_INFO = {
    "A": {"name": "A-舒壓方案", "duration": 60, "price": 1500, "desc": "不指定優惠 / 指油壓"},
    "B": {"name": "B-愉悅方案", "duration": 60, "price": 2000, "desc": "指定師傅 / 體推保養"},
    "C": {"name": "C-享受方案", "duration": 90, "price": 2500, "desc": "指定師傅 / 體推保養"},
    "D": {"name": "D-極緻方案", "duration": 120, "price": 3000, "desc": "指定師傅 / 體推保養"},
    "Out": {"name": "外出-隨享", "duration": 100, "price": 3200, "desc": "指定師傅 / 獅子林起算"}
}


def build_promotion_flex(promotions, plan_key: str, selected_dt: str):
    choices = [(None, "不使用優惠", "原價方案", "不套用折扣")]
    for promotion in promotions[:8]:
        if promotion.calculation_type not in {"fixed_discount", "percent_discount"}:
            continue
        amount_text = f"現折 NT$ {promotion.value}" if promotion.calculation_type == "fixed_discount" else f"{promotion.value}% OFF"
        choices.append((promotion.id, promotion.name, amount_text, promotion.description or "期間限定優惠"))
    bubbles = []
    for promotion_id, name, amount_text, description in choices:
        promotion_value = promotion_id or 0
        next_action = "preview_booking" if plan_key == "A" else "select_staff"
        next_data = f"action={next_action}&staff_id=none&plan={plan_key}&promotion_id={promotion_value}&datetime={selected_dt}&offset=0"
        bubbles.append({
            "type": "bubble",
            "styles": {"body": {"backgroundColor": "#1A1B26"}, "footer": {"backgroundColor": "#1A1B26"}},
            "body": {
                "type": "box", "layout": "vertical", "paddingAll": "24px",
                "contents": [
                    {"type": "text", "text": name, "weight": "bold", "size": "xl", "color": "#9ECE6A", "wrap": True},
                    {"type": "text", "text": amount_text, "weight": "bold", "size": "lg", "color": "#C0CAF5", "margin": "lg"},
                    {"type": "text", "text": description, "size": "sm", "color": "#7A84A8", "wrap": True, "margin": "md"},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "paddingAll": "16px",
                "contents": [{"type": "button", "style": "primary", "color": "#24283B", "action": {"type": "postback", "label": "▶ 選擇此優惠", "data": next_data}}],
            },
        })
    return FlexSendMessage(alt_text="請選擇優惠", contents={"type": "carousel", "contents": bubbles})


def build_booking_preview_flex(*, staff, plan_key: str, promotion, selected_dt: str):
    plan = PLANS_INFO.get(plan_key, {"name": "未知方案", "duration": 60, "price": 0})
    base_price = plan["price"]
    discount = 0
    if promotion:
        if promotion.calculation_type == "fixed_discount":
            discount = min(base_price, promotion.value)
        elif promotion.calculation_type == "percent_discount":
            discount = min(base_price, round(base_price * promotion.value / 100))
    staff_name = staff.name if staff else "不指定（由店長安排）"
    promotion_name = promotion.name if promotion else "不使用優惠"
    time_text = parse_local_datetime(selected_dt).strftime("%m月%d日 %H:%M")
    staff_value = staff.id if staff else "none"
    promotion_value = promotion.id if promotion else 0
    confirm_data = f"action=confirm_booking&staff_id={staff_value}&plan={plan_key}&promotion_id={promotion_value}&datetime={selected_dt}"
    rows = [
        ("時間", time_text),
        ("方案", f"{plan['name']}・{plan['duration']} 分"),
        ("師傅", staff_name),
        ("優惠", promotion_name),
        ("預估金額", f"NT$ {max(0, base_price - discount)}"),
    ]
    return FlexSendMessage(
        alt_text="請確認預約內容",
        contents={
            "type": "bubble",
            "styles": {"header": {"backgroundColor": "#123F37"}, "footer": {"backgroundColor": "#F7F3EA"}},
            "header": {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "送出前再次確認", "weight": "bold", "size": "xl", "color": "#F7D7A3"},
                {"type": "text", "text": "此時尚未建立訂單", "size": "sm", "color": "#D1FAE5", "margin": "sm"},
            ]},
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                *[{"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": label, "size": "sm", "color": "#777777", "flex": 2},
                    {"type": "text", "text": value, "size": "sm", "color": "#222222", "weight": "bold", "align": "end", "wrap": True, "flex": 5},
                ]} for label, value in rows],
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "確認並送出預約", "data": confirm_data}},
            ]},
        },
    )

# --- 共用：手機號碼確認 Flex ---
def build_phone_confirm_flex(phone_num, action_prefix):
    return FlexSendMessage(
        alt_text="確認手機號碼",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "確認手機號碼", "weight": "bold", "size": "lg", "color": "#1DB446"},
                    {
                        "type": "box", "layout": "vertical", "margin": "md",
                        "contents": [
                            {"type": "text", "text": f"您輸入的是 {phone_num}", "weight": "bold", "size": "md"},
                            {"type": "text", "text": "請問正確嗎？", "size": "sm", "color": "#555555"}
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box", "layout": "horizontal", "spacing": "sm",
                "contents": [
                    {"type": "button", "style": "primary", "action": {"type": "postback", "label": "正確", "data": f"action={action_prefix}&result=yes"}},
                    {"type": "button", "style": "secondary", "action": {"type": "postback", "label": "重輸", "data": f"action={action_prefix}&result=no"}}
                ]
            }
        }
    )

# --- 共用：Root Admin 管理員選單 Flex ---
def build_root_admin_menu(identity=None):
    display_name = identity.get("display_name", "管理員") if isinstance(identity, dict) else "管理員"
    role_label = "系統管理員" if isinstance(identity, dict) and identity.get("role") == "admin" else "店長"
    dashboard_url = os.getenv("ADMIN_DASHBOARD_URL", "https://equalspa-admin.pages.dev/")
    return FlexSendMessage(
        alt_text="系統管理員選單",
        contents={
            "type": "bubble",
            "styles": {"body": {"backgroundColor": "#4C1D95"}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "ROOT ADMIN", "weight": "bold", "color": "#FCD34D", "size": "xl"},
                    {"type": "text", "text": f"{display_name}・{role_label}", "color": "#E9D5FF", "size": "sm", "margin": "sm"},
                    {"type": "button", "style": "primary", "color": "#7C3AED", "margin": "md", "action": {"type": "postback", "label": "查看本日預約", "data": "action=admin_view"}},
                    {"type": "button", "style": "primary", "color": "#7C3AED", "margin": "sm", "action": {"type": "postback", "label": "管理師傅", "data": "action=admin_staff"}},
                    {"type": "button", "style": "primary", "color": "#312E81", "margin": "sm", "action": {"type": "uri", "label": "開啟營運後台", "uri": dashboard_url}},
                    {"type": "button", "style": "secondary", "margin": "sm", "action": {"type": "postback", "label": "登出管理員", "data": "action=admin_logout"}}
                ]
            }
        }
    )


def build_staff_backend_link(staff, db: Session):
    dashboard_url = os.getenv("ADMIN_DASHBOARD_URL", "https://equalspa-admin.pages.dev/").rstrip("/")
    issuer = getattr(getattr(app, "state", None), "issue_staff_magic_link", None)
    login_token = issuer(staff, db) if issuer else None
    target_url = f"{dashboard_url}/?staff_login={login_token}" if login_token else dashboard_url
    return FlexSendMessage(
        alt_text="開啟伊果 SPA 師傅後台",
        contents={
            "type": "bubble",
            "styles": {"body": {"backgroundColor": "#123F37"}, "footer": {"backgroundColor": "#123F37"}},
            "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "伊果 SPA 師傅後台", "weight": "bold", "size": "xl", "color": "#F7D7A3"},
                {"type": "text", "text": f"{staff.name}，可查看自己的訂單並設定排班。", "size": "sm", "color": "#D1FAE5", "wrap": True, "margin": "md"},
            ]},
            "footer": {"type": "box", "layout": "vertical", "contents": [
                {"type": "button", "style": "primary", "color": "#D8A862", "action": {"type": "uri", "label": "開啟後台／排班", "uri": target_url}},
            ]},
        },
    )

# --- 共用：生成預約單 Carousel Bubble ---
def build_appointment_bubble(appointment, is_staff_notify=False, db=None, show_return=False):
    staff_name = appointment.staff.name if appointment.staff else "未指定(由店長安排)"
    staff_info_parts = []
    if appointment.staff:
        if appointment.staff.height:
            staff_info_parts.append(f"身高: {appointment.staff.height}")
        if appointment.staff.weight:
            staff_info_parts.append(f"體重: {appointment.staff.weight}")
        role = valid_staff_role(appointment.staff.role)
        if role:
            staff_info_parts.append(f"角色: {role}")
    staff_info = " / ".join(staff_info_parts)
    
    customer_name = "客戶"
    if appointment.user:
        customer_name = appointment.user.display_name or "未命名客戶"
    customer_vip_id = vip_serial(appointment.user)
    customer_phone = appointment.user.phone if appointment.user else None
    if db is not None and hasattr(app.state, "admin_models"):
        AppointmentDetail = app.state.admin_models.get("AppointmentDetail")
        if AppointmentDetail:
            contact = db.query(AppointmentDetail).filter(AppointmentDetail.appointment_id == appointment.id).first()
            customer_phone = getattr(contact, "contact_phone", None) or customer_phone
    
    start_time_str = appointment.start_time.strftime("%m月%d日 %H:%M") if appointment.start_time else "未定"
    plan_name = appointment.plan_name or "未知方案"
    
    price = 0
    discount = 0
    promotion_name = "無"
    return_amount = 0
    return_status = "尚未建立"
    for plan_key, plan_info in PLANS_INFO.items():
        if plan_info["name"] == plan_name:
            price = plan_info["price"]
            break
    if db is not None and hasattr(app.state, "admin_models"):
        models = app.state.admin_models
        detail = db.query(models["AppointmentDetail"]).filter(models["AppointmentDetail"].appointment_id == appointment.id).first()
        if detail:
            service_plan = db.query(models["ServicePlan"]).filter(models["ServicePlan"].id == detail.service_plan_id).first() if detail.service_plan_id else None
            price = detail.base_price
            discount = detail.discount_amount
            if detail.promotion_id:
                promotion = db.query(models["Promotion"]).filter(models["Promotion"].id == detail.promotion_id).first()
                promotion_name = promotion.name if promotion else "優惠"
            StaffReturn = models.get("StaffReturn")
            ReturnRuleSet = models.get("ReturnRuleSet")
            ReturnRule = models.get("ReturnRule")
            staff_return = db.query(StaffReturn).filter(StaffReturn.appointment_id == appointment.id).first() if StaffReturn else None
            if staff_return:
                return_amount = staff_return.amount
                return_status = "已確認" if staff_return.status == "confirmed" else "待確認"
            elif appointment.staff and ReturnRuleSet and ReturnRule:
                rule_set_id = appointment.staff.return_rule_set_id
                if not rule_set_id:
                    first_set = db.query(ReturnRuleSet).filter(ReturnRuleSet.active.is_(True)).order_by(ReturnRuleSet.id).first()
                    rule_set_id = first_set.id if first_set else None
                service_code = service_plan.code if 'service_plan' in locals() and service_plan else (appointment.plan_name or "").split("-", 1)[0]
                if service_code == "OUT":
                    service_code = "E"
                rule = db.query(ReturnRule).filter(ReturnRule.rule_set_id == rule_set_id, ReturnRule.service_code == service_code, ReturnRule.active.is_(True)).first() if rule_set_id else None
                return_amount = rule.amount if rule else 0
    
    total = max(0, price - discount) if price > 0 else 0
    payment_id = f"#{appointment.created_at.strftime('%y%m%d')}{appointment.id:03d}"
    
    bubble = {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "🔔 新派單通知" if is_staff_notify else "今日預約", "weight": "bold", "color": "#EAB308" if is_staff_notify else "#1DB446", "size": "sm"},
                {"type": "text", "text": staff_name, "weight": "bold", "size": "xxl", "margin": "md"},
                *([{"type": "text", "text": staff_info, "size": "xs", "color": "#aaaaaa", "wrap": True}] if staff_info else []),
                {"type": "separator", "margin": "xxl"},
                {
                    "type": "box", "layout": "vertical", "margin": "xxl", "spacing": "sm",
                    "contents": [
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "客戶流水", "size": "sm", "color": "#555555"}, {"type": "text", "text": customer_vip_id, "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "客戶", "size": "sm", "color": "#555555"}, {"type": "text", "text": customer_name, "size": "sm", "color": "#111111", "align": "end"}]},
                        *([{"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "客戶 ID（手機）", "size": "sm", "color": "#555555", "flex": 0}, {"type": "text", "text": customer_phone, "size": "sm", "color": "#111111", "align": "end"}]}] if customer_phone else []),
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "時段", "size": "sm", "color": "#555555", "flex": 0}, {"type": "text", "text": start_time_str, "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "方案", "size": "sm", "color": "#555555", "flex": 0}, {"type": "text", "text": plan_name, "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "separator", "margin": "xxl"},
                        {"type": "box", "layout": "horizontal", "margin": "xxl", "contents": [{"type": "text", "text": "方案定價", "size": "sm", "color": "#555555"}, {"type": "text", "text": f"NT$ {price}", "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": f"優惠・{promotion_name}", "size": "sm", "color": "#555555", "flex": 2, "wrap": True}, {"type": "text", "text": f"-NT$ {discount}", "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "總計", "size": "sm", "color": "#555555"}, {"type": "text", "text": f"NT$ {total}", "size": "sm", "color": "#111111", "align": "end"}]},
                        *([{"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "師傅應回帳", "size": "sm", "color": "#555555"}, {"type": "text", "text": f"NT$ {return_amount}・{return_status}", "size": "sm", "color": "#B45309", "align": "end"}]}] if (show_return or is_staff_notify) else [])
                    ]
                },
                {"type": "separator", "margin": "xxl"},
                {"type": "box", "layout": "horizontal", "margin": "md", "contents": [{"type": "text", "text": "PAYMENT ID", "size": "xs", "color": "#aaaaaa", "flex": 0}, {"type": "text", "text": payment_id, "color": "#aaaaaa", "size": "xs", "align": "end"}]}
            ]
        },
        "styles": {"footer": {"separator": True}}
    }
    return bubble

def build_staff_bubble(staff):
    profile = []
    if staff.height:
        profile.append(f"身高: {staff.height}")
    if staff.weight:
        profile.append(f"體重: {staff.weight}")
    role = valid_staff_role(staff.role)
    if role:
        profile.append(f"角色: {role}")
    
    bubble = {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": staff.name, "wrap": True, "weight": "bold", "size": "xxl"},
                {"type": "text", "text": "在職" if staff.employment_status == "active" else "暫時退役", "size": "sm", "color": "#059669" if staff.employment_status == "active" else "#9CA3AF"},
                {
                    "type": "box", "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": " / ".join(profile) or "基本資料尚未設定", "wrap": True, "weight": "regular", "size": "md", "flex": 0}
                    ]
                }
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#6B7280", "action": {"type": "postback", "label": "恢復在職" if staff.employment_status == "retired" else "暫時退役", "data": f"action=toggle_staff&staff_id={staff.id}"}},
                {"type": "button", "style": "primary", "color": "#e11d48", "action": {"type": "postback", "label": "永久刪除", "data": f"action=request_permanent_delete_staff&staff_id={staff.id}"}}
            ]
        }
    }
    if staff.photo_url:
        bubble["hero"] = {
            "type": "image",
            "url": staff.photo_url,
            "size": "full",
            "aspectRatio": "4:5",
            "aspectMode": "cover",
        }
    return bubble


def build_permanent_delete_staff_confirmation(staff):
    return FlexSendMessage(
        alt_text=f"確認永久刪除 {staff.name}",
        contents={
            "type": "bubble",
            "header": {"type": "box", "layout": "vertical", "backgroundColor": "#991B1B", "contents": [
                {"type": "text", "text": "永久刪除師傅", "weight": "bold", "size": "xl", "color": "#FFFFFF"},
            ]},
            "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                {"type": "text", "text": f"確定永久刪除「{staff.name}」？", "weight": "bold", "size": "lg", "wrap": True},
                {"type": "text", "text": "這會移除 LINE 綁定、登入連結與私密資料，無法復原。若已有預約、班表、付款或回帳歷史，系統會拒絕刪除並要求改用暫時退役。", "size": "sm", "color": "#6B7280", "wrap": True},
            ]},
            "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [
                {"type": "button", "style": "primary", "color": "#DC2626", "action": {"type": "postback", "label": "確認永久刪除", "data": f"action=confirm_permanent_delete_staff&staff_id={staff.id}"}},
                {"type": "button", "style": "secondary", "action": {"type": "postback", "label": "取消", "data": "action=admin_staff&offset=0"}},
            ]},
        },
    )


def build_staff_week_appointments(staff, db: Session):
    """Build a compact Flex carousel of this staff member's next seven days."""
    start = now_taipei_naive().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    appointments = db.query(Appointment).filter(
        Appointment.staff_id == staff.id,
        Appointment.status.notin_(["cancelled", "已取消"]),
        Appointment.start_time >= start,
        Appointment.start_time < end,
    ).order_by(Appointment.start_time).all()
    if not appointments:
        return TextSendMessage(text=f"{staff.name}，未來 7 天目前沒有預約。")

    visible = appointments[:11]
    bubbles = []
    status_labels = {
        "pending": "待確認", "confirmed": "已確認", "checked_in": "已報到",
        "in_service": "服務中", "awaiting_checkout": "待結帳", "completed": "已完成",
        "cancelled": "已取消", "no_show": "未到店",
    }
    for appointment in visible:
        bubble = build_appointment_bubble(appointment, db=db, show_return=True)
        bubble["body"]["contents"][0]["text"] = "📅 我的預約"
        bubble["body"]["contents"][0]["color"] = "#0F766E"
        bubble["body"]["contents"].insert(1, {
            "type": "text",
            "text": f"狀態：{status_labels.get(appointment.status, appointment.status)}",
            "size": "xs",
            "color": "#6B7280",
            "margin": "sm",
        })
        bubbles.append(bubble)
    if len(appointments) > len(visible):
        bubbles.append({
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "28px",
                "contents": [
                    {"type": "text", "text": "還有更多預約", "weight": "bold", "size": "xl", "align": "center"},
                    {"type": "text", "text": f"未來 7 天共有 {len(appointments)} 筆，請到個人後台查看完整清單。", "size": "sm", "color": "#777777", "wrap": True, "align": "center", "margin": "md"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [{"type": "button", "style": "primary", "action": {"type": "message", "label": "開啟我的後台", "text": "後台"}}],
            },
        })
    return FlexSendMessage(alt_text=f"{staff.name}未來一週預約", contents={"type": "carousel", "contents": bubbles})

def handle_root_action(data, user_id, db, is_staff_side=False):
    """處理管理員（root）相關的 Postback 動作"""
    if not any(action in data for action in ("action=admin_", "action=delete_staff", "action=toggle_staff", "action=request_permanent_delete_staff", "action=confirm_permanent_delete_staff")):
        return None
    if not is_line_manager(user_id, db):
        return TextSendMessage(text="此功能只開放管理帳號使用。")

    if "action=admin_logout" in data:
        unbind = getattr(getattr(app, "state", None), "unbind_line_admin", None)
        if unbind:
            unbind(user_id, db)
        return TextSendMessage(text="管理員帳戶已從這個 LINE 登出。")
    
    if "action=admin_view" in data:
        today = date.today()
        appointments = db.query(Appointment).filter(
            Appointment.start_time >= datetime.combine(today, datetime.min.time()),
            Appointment.start_time < datetime.combine(today, datetime.max.time())
        ).all()
        
        if not appointments:
            return TextSendMessage(text="今日目前無預約")
        
        bubbles = [build_appointment_bubble(appt, db=db, show_return=True) for appt in appointments[:10]]
        return FlexSendMessage(alt_text="本日預約", contents={"type": "carousel", "contents": bubbles})
    
    elif "action=admin_staff" in data:
        # LINE carousel 上限為 12 張；以 10 位師傅加 1 張下一頁卡片分頁。
        qs = parse_qs(data)
        offset = max(0, int(qs.get("offset", ["0"])[0] or 0))
        staffs = db.query(Staff).filter(Staff.employment_status.in_(["active", "retired"])).order_by(Staff.id).offset(offset).limit(11).all()
        if not staffs:
            return TextSendMessage(text="目前無師傅資料")
        has_more = len(staffs) > 10
        bubbles = [build_staff_bubble(staff) for staff in staffs[:10]]
        if has_more:
            bubbles.append({
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "paddingAll": "28px", "contents": [
                    {"type": "text", "text": "更多師傅", "weight": "bold", "size": "xl", "align": "center"},
                    {"type": "text", "text": f"繼續查看第 {offset + 11} 位起的資料", "size": "sm", "color": "#777777", "wrap": True, "align": "center", "margin": "md"},
                ]},
                "footer": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "button", "style": "primary", "action": {"type": "postback", "label": "下一頁", "data": f"action=admin_staff&offset={offset + 10}"}}
                ]},
            })
        return FlexSendMessage(alt_text="師傅管理", contents={"type": "carousel", "contents": bubbles})
    
    elif "action=request_permanent_delete_staff" in data:
        qs = parse_qs(data)
        staff_id = qs.get("staff_id", [None])[0]
        staff = db.query(Staff).filter(Staff.id == int(staff_id)).first() if staff_id else None
        return build_permanent_delete_staff_confirmation(staff) if staff else TextSendMessage(text="查無師傅資料")

    elif "action=confirm_permanent_delete_staff" in data:
        qs = parse_qs(data)
        staff_id = qs.get("staff_id", [None])[0]
        delete_staff = getattr(getattr(app, "state", None), "permanently_delete_staff", None)
        identity_getter = getattr(getattr(app, "state", None), "line_admin_identity", None)
        if not staff_id or not delete_staff:
            return TextSendMessage(text="永久刪除功能目前無法使用，請改從後台操作。")
        identity = identity_getter(user_id, db) if identity_getter else None
        try:
            result = delete_staff(int(staff_id), db, actor_id=identity.get("id") if identity else None, reason="LINE Bot 管理員確認永久刪除")
            return TextSendMessage(text=f"已永久刪除師傅 {result['deleted_staff_name']}。")
        except Exception as exc:
            return TextSendMessage(text=getattr(exc, "detail", "永久刪除失敗，請改從後台查看原因。"))

    elif "action=delete_staff" in data:
        # 保留歷史訂單，僅將師傅標為暫時退役
        qs = parse_qs(data)
        staff_id = qs.get("staff_id", [None])[0]
        if staff_id:
            staff = db.query(Staff).filter(Staff.id == int(staff_id)).first()
            if staff:
                staff.employment_status = "retired"
                db.commit()
                return TextSendMessage(text=f"已將師傅 {staff.name} 設為暫時退役")
        return TextSendMessage(text="更新失敗")
    
    elif "action=toggle_staff" in data:
        qs = parse_qs(data)
        staff_id = qs.get("staff_id", [None])[0]
        if staff_id:
            staff = db.query(Staff).filter(Staff.id == int(staff_id)).first()
            if staff:
                staff.employment_status = "active" if staff.employment_status == "retired" else "retired"
                db.commit()
                return TextSendMessage(text=f"{staff.name} 已{'恢復在職' if staff.employment_status == 'active' else '設為暫時退役'}。")
        return TextSendMessage(text="查無師傅資料")
    return None

# --- 客人端：引導建檔與對話邏輯 ---
if handler_customer:
    @handler_customer.add(MessageEvent, message=TextMessage)
    def handle_customer_message(event):
        user_id = getattr(getattr(event, "source", None), "user_id", None)
        text = getattr(event.message, "text", "").strip()
        
        if user_id:
            db = SessionLocal()
            try:
                admin_response = handle_line_admin_message(text, user_id, db)
                if admin_response:
                    bot_customer_api.reply_message(event.reply_token, admin_response)
                    return
                user = db.query(User).filter(User.line_user_id == user_id).first()
                if not user:
                    display_name = None
                    try:
                        display_name = bot_customer_api.get_profile(user_id).display_name
                    except Exception:
                        logging.info("暫時無法取得 LINE 顯示名稱 user_id=%s", user_id)
                    user = User(line_user_id=user_id, display_name=display_name)
                    db.add(user)
                    db.commit()

                if text in {"網頁預約", "備用預約", "預約網頁"}:
                    reply_with_fallback(
                        bot_customer_api,
                        event.reply_token,
                        TextSendMessage(text=f"請由備用預約頁完成預約：\n{BOOKING_WEB_URL}\n\n若仍無法操作，請聯絡真人客服：{SUPPORT_URL}"),
                        db=db,
                        context="備用網頁預約連結",
                    )
                    return

                if text == "預約":
                    if not user.phone:
                        bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="為了保障您的預約權益，請在下方輸入您的 10 碼手機號碼（例如：0912345678）"))
                    else:
                        dt_action = DatetimePickerTemplateAction(label="選擇時間", data="action=select_date", mode="datetime")
                        bot_customer_api.reply_message(event.reply_token, TemplateSendMessage(alt_text="請選擇時間", template=ButtonsTemplate(text="請選擇您想預約的時間", actions=[dt_action])))
                    return

                if not user.phone and re.match(r"^09\d{8}$", text):
                    user.phone_temp = normalize_phone(text)
                    db.commit()
                    bot_customer_api.reply_message(event.reply_token, build_phone_confirm_flex(text, "confirm_customer_phone"))
                    return

                flex_message = FlexSendMessage(
                    alt_text="歡迎預約",
                    contents={
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": "歡迎來到伊果 SPA", "weight": "bold", "size": "lg", "color": "#1DB446"},
                                {"type": "text", "text": "很高興為您服務", "size": "sm", "color": "#555555", "margin": "md"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "button", "style": "primary", "action": {"type": "message", "label": "LINE 內預約", "text": "預約"}},
                                {"type": "button", "style": "secondary", "margin": "sm", "action": {"type": "uri", "label": "備用網頁預約", "uri": BOOKING_WEB_URL}},
                            ]
                        }
                    }
                )
                reply_with_fallback(bot_customer_api, event.reply_token, flex_message, db=db, context="客戶歡迎選單")
            except Exception:
                logging.exception("處理客戶文字訊息失敗 user_id=%s", user_id)
                reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text=f"系統暫時忙碌，請改用備用網頁預約：{BOOKING_WEB_URL}"), db=db, context="客戶文字訊息")
            finally:
                db.close()

    @handler_customer.add(PostbackEvent)
    def handle_customer_postback(event):
        data = getattr(getattr(event, "postback", None), "data", "")
        params = getattr(getattr(event, "postback", None), "params", None) or {}
        user_id = getattr(getattr(event, "source", None), "user_id", None)

        db = SessionLocal()
        try:
            root_response = handle_root_action(data, user_id, db, is_staff_side=False)
            if root_response:
                reply_with_fallback(bot_customer_api, event.reply_token, root_response, db=db, context="客戶端管理員選單", admin=True)
                return

            if "action=confirm_customer_phone" in data:
                qs = parse_qs(data)
                result = qs.get("result", [None])[0]
                user = db.query(User).filter(User.line_user_id == user_id).first()
                if user:
                    if result == "yes":
                        confirmed_phone = normalize_phone(user.phone_temp)
                        existing_customer = customer_by_phone(db, confirmed_phone)
                        if existing_customer and existing_customer.id != user.id:
                            if existing_customer.line_user_id.startswith("manual:") and not user.appointments:
                                line_name = user.display_name
                                db.delete(user)
                                db.flush()
                                existing_customer.line_user_id = user_id
                                existing_customer.display_name = line_name or existing_customer.display_name
                                user = existing_customer
                            else:
                                user.phone_temp = None
                                db.commit()
                                reply_with_fallback(
                                    bot_customer_api,
                                    event.reply_token,
                                    TextSendMessage(text=f"此手機號碼已綁定其他客戶資料，請聯絡真人客服協助：{SUPPORT_URL}"),
                                    db=db,
                                    context="客戶手機綁定衝突",
                                )
                                return
                        add_customer_phone(db, user, confirmed_phone, primary=True)
                        user.phone_temp = None
                        db.commit()
                        dt_action = DatetimePickerTemplateAction(label="選擇時間", data="action=select_date", mode="datetime")
                        reply_with_fallback(bot_customer_api, event.reply_token, TemplateSendMessage(alt_text="請選擇時間", template=ButtonsTemplate(text="感謝綁定！現在請選擇想預約的時間", actions=[dt_action])), db=db, context="客戶手機綁定完成")
                    else:
                        user.phone_temp = None
                        db.commit()
                        bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="請再次輸入您的 10 碼手機號碼："))

            # 選擇日期後 -> 彈出各方案的輪播卡片
            elif data == "action=select_date":
                selected_dt = params.get("datetime")
                bubbles = []
                for plan_key, p_info in PLANS_INFO.items():
                    postback_data = f"action=select_promotion&plan={plan_key}&datetime={selected_dt}"
                    
                    bubbles.append({
                        "type": "bubble",
                        "styles": {"body": {"backgroundColor": "#1A1B26"}, "footer": {"backgroundColor": "#1A1B26"}},
                        "body": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": p_info["name"], "weight": "bold", "size": "xl", "color": "#9ECE6A"},
                                {"type": "text", "text": f"NT$ {p_info['price']}", "weight": "bold", "size": "md", "color": "#C0CAF5", "margin": "sm"},
                                {"type": "text", "text": p_info["desc"], "size": "xs", "color": "#565F89", "wrap": True, "margin": "sm"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical",
                            "contents": [{"type": "button", "style": "primary", "color": "#24283B", "action": {"type": "postback", "label": "▶ 選擇此方案", "data": postback_data}}]
                        }
                    })
                bot_customer_api.reply_message(event.reply_token, FlexSendMessage(alt_text="請選擇服務方案", contents={"type": "carousel", "contents": bubbles}))

            elif "action=select_promotion" in data:
                qs = parse_qs(data)
                plan = qs.get("plan", [None])[0]
                promotion_id = qs.get("promotion_id", ["0"])[0]
                selected_dt = qs.get("datetime", [None])[0]
                Promotion = getattr(app.state, "admin_models", {}).get("Promotion")
                promotions = []
                if Promotion:
                    now = datetime.utcnow()
                    promotions = db.query(Promotion).filter(Promotion.active.is_(True)).all()
                    promotions = [item for item in promotions if (not item.starts_at or item.starts_at <= now) and (not item.ends_at or item.ends_at >= now)]
                bot_customer_api.reply_message(event.reply_token, build_promotion_flex(promotions, plan, selected_dt))

            # 選擇方案後 -> 師傅分頁輪播 (分頁處理，避開 LINE 10 張限制)
            elif "action=select_staff" in data:
                qs = parse_qs(data)
                plan = qs.get("plan", [None])[0]
                promotion_id = qs.get("promotion_id", ["0"])[0]
                selected_dt = qs.get("datetime", [None])[0]
                offset = int(qs.get("offset", ["0"])[0])

                p_info = PLANS_INFO.get(plan, {"duration": 60})
                booking_start = parse_local_datetime(selected_dt)
                booking_end = appointment_end(booking_start, p_info["duration"])
                models = getattr(app.state, "admin_models", {})
                Shift = models.get("Shift")
                staff_query = db.query(Staff).filter(Staff.employment_status == "active")
                if Shift:
                    scheduled_ids = [row[0] for row in db.query(Shift.staff_id).filter(
                        Shift.status == "active",
                        Shift.start_time <= booking_start,
                        Shift.end_time >= booking_end,
                    ).distinct().all()]
                    staff_query = staff_query.filter(Staff.id.in_(scheduled_ids)) if scheduled_ids else staff_query.filter(Staff.id == -1)
                eligible_staff = []
                for candidate in staff_query.order_by(Staff.id).all():
                    conflict = db.query(Appointment).filter(
                        Appointment.staff_id == candidate.id,
                        Appointment.status.notin_(["cancelled", "已取消"]),
                        Appointment.start_time < booking_end,
                        Appointment.end_time > booking_start,
                    ).first()
                    if not conflict:
                        eligible_staff.append(candidate)
                active_staff = eligible_staff[offset:offset + 10]

                if not active_staff:
                    message = f"目前此時段沒有可安排的師傅，請改選時間或聯絡真人客服：{SUPPORT_URL}" if offset == 0 else "沒有更多師傅囉！"
                    reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text=message), db=db, context="選擇師傅無可用班表")
                    return

                # 判斷是否滿 10 個（代表還有下一頁）
                has_more = len(active_staff) == 10
                # 畫面上最多只顯示 9 位師傅
                display_staff = active_staff[:9]

                bubbles = []
                for s in display_staff:
                    info_parts = []
                    if s.height:
                        info_parts.append(f"身高:{s.height}")
                    if s.weight:
                        info_parts.append(f"體重:{s.weight}")
                    role = valid_staff_role(s.role)
                    if role:
                        info_parts.append(f"角色:{role}")
                    info_text = " ".join(info_parts) or "基本資料更新中"
                    staff_bubble = {
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical", "backgroundColor": "#000000",
                            "contents": [
                                {"type": "text", "text": s.name, "weight": "bold", "size": "xxl", "color": "#C0CAF5"},
                                {"type": "text", "text": info_text, "size": "sm", "color": "#9ECE6A", "margin": "md"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical", "backgroundColor": "#111111",
                            "contents": [{"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "預約這位", "data": f"action=preview_booking&staff_id={s.id}&plan={plan}&promotion_id={promotion_id}&datetime={selected_dt}"}}]
                        }
                    }
                    if s.photo_url:
                        staff_bubble["hero"] = {
                            "type": "image", "size": "full", "aspectRatio": "4:5", "aspectMode": "cover", "url": s.photo_url
                        }
                    bubbles.append(staff_bubble)

                # 如果有下一頁，第 10 張卡片放「看更多」
                if has_more:
                    next_offset = offset + 9
                    bubbles.append({
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical", "backgroundColor": "#000000", "paddingAll": "30px",
                            "contents": [
                                {"type": "text", "text": "看更多選擇", "weight": "bold", "size": "xl", "color": "#C0CAF5", "align": "center", "wrap": True},
                                {"type": "text", "text": "瀏覽其他在線師傅", "size": "sm", "color": "#aaaaaa", "align": "center", "wrap": True, "margin": "lg"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical", "backgroundColor": "#111111",
                            "contents": [{"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "下一頁", "data": f"action=select_staff&plan={plan}&promotion_id={promotion_id}&datetime={selected_dt}&offset={next_offset}"}}]
                        }
                    })

                reply_with_fallback(bot_customer_api, event.reply_token, FlexSendMessage(alt_text="請選擇師傅", contents={"type": "carousel", "contents": bubbles}), db=db, context="選擇師傅 Flex")

            elif "action=preview_booking" in data:
                qs = parse_qs(data)
                staff_id = qs.get("staff_id", ["none"])[0]
                plan_key = qs.get("plan", [None])[0]
                promotion_id = int(qs.get("promotion_id", ["0"])[0] or 0)
                selected_dt = qs.get("datetime", [None])[0]
                try:
                    validate_booking_start(selected_dt)
                except ValueError as exc:
                    reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text=f"{exc}。請重新選擇預約時間。"), db=db, context="確認頁提前時間不足")
                    return
                staff_obj = db.query(Staff).filter(Staff.id == int(staff_id), Staff.employment_status == "active").first() if staff_id != "none" else None
                if staff_id != "none" and not staff_obj:
                    reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text="這位師傅目前無法預約，請重新選擇。"), db=db, context="確認頁師傅已不可用")
                    return
                Promotion = getattr(app.state, "admin_models", {}).get("Promotion")
                promotion = db.query(Promotion).filter(Promotion.id == promotion_id, Promotion.active.is_(True)).first() if Promotion and promotion_id else None
                reply_with_fallback(
                    bot_customer_api,
                    event.reply_token,
                    build_booking_preview_flex(staff=staff_obj, plan_key=plan_key, promotion=promotion, selected_dt=selected_dt),
                    db=db,
                    context="預約送出前確認 Flex",
                )

            elif "action=confirm_booking" in data:
                qs = parse_qs(data)
                staff_id = qs.get("staff_id", [None])[0]
                plan_key = qs.get("plan", [None])[0]
                promotion_id = int(qs.get("promotion_id", ["0"])[0] or 0)
                selected_dt = qs.get("datetime", [None])[0]

                # Lock the customer row so rapid repeated taps are serialized in MySQL.
                user = db.query(User).filter(User.line_user_id == user_id).with_for_update().first()
                if not user:
                    reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text="找不到客戶資料，請輸入「預約」重新開始。"), db=db, context="確認預約找不到客戶")
                    return
                staff_obj = None
                
                if staff_id != "none":
                    staff_obj = db.query(Staff).filter(Staff.id == int(staff_id)).first()
                    if not staff_obj or staff_obj.employment_status != "active":
                        reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text="這位師傅目前無法預約，請重新選擇。"), db=db, context="送出預約師傅已不可用")
                        return

                p_info = PLANS_INFO.get(plan_key, {"duration": 60, "price": 0, "name": "未知方案"})
                booking_start = parse_local_datetime(selected_dt)
                booking_end = appointment_end(booking_start, p_info["duration"])
                try:
                    validate_booking_start(booking_start)
                except ValueError as exc:
                    reply_with_fallback(bot_customer_api, event.reply_token, TextSendMessage(text=f"{exc}。請重新選擇預約時間。"), db=db, context="預約提前時間不足")
                    return

                existing_booking = db.query(Appointment).filter(
                    Appointment.user_id == user.id,
                    Appointment.staff_id == (int(staff_id) if staff_id != "none" else None),
                    Appointment.start_time == booking_start,
                    Appointment.end_time == booking_end,
                    Appointment.status.notin_(["cancelled", "已取消"]),
                ).order_by(Appointment.id.desc()).first()
                if existing_booking:
                    reply_with_fallback(
                        bot_customer_api,
                        event.reply_token,
                        FlexSendMessage(alt_text="此預約已建立", contents=build_appointment_bubble(existing_booking, db=db)),
                        db=db,
                        context="重複預約攔截",
                    )
                    return

                if staff_obj:
                    conflict = db.query(Appointment).filter(
                        Appointment.staff_id == staff_obj.id,
                        Appointment.status.notin_(["cancelled", "已取消"]),
                        Appointment.start_time < booking_end,
                        Appointment.end_time > booking_start,
                    ).first()
                    if conflict:
                        reply_with_fallback(
                            bot_customer_api,
                            event.reply_token,
                            TextSendMessage(text="這位師傅在該時段已有預約，請重新選擇時間或師傅。"),
                            db=db,
                            context="師傅預約衝突",
                        )
                        return

                try:
                    profile = bot_customer_api.get_profile(user_id)
                    user.display_name = profile.display_name
                except Exception:
                    logging.exception("無法讀取 LINE 顯示名稱 user_id=%s", user_id)
                appointment = Appointment(
                    user_id=user.id,
                    staff_id=int(staff_id) if staff_id != "none" else None,
                    duration=p_info["duration"],
                    plan_name=p_info["name"],
                    start_time=booking_start,
                    end_time=booking_end,
                    status="confirmed"
                )
                db.add(appointment)
                db.flush()
                models = getattr(app.state, "admin_models", {})
                AppointmentDetail = models.get("AppointmentDetail")
                ServicePlan = models.get("ServicePlan")
                Promotion = models.get("Promotion")
                if AppointmentDetail and ServicePlan:
                    service_code = "OUT" if plan_key == "Out" else plan_key
                    service_plan = db.query(ServicePlan).filter(ServicePlan.code == service_code).first()
                    promotion = db.query(Promotion).filter(Promotion.id == promotion_id, Promotion.active.is_(True)).first() if Promotion and promotion_id else None
                    base_price = service_plan.price if service_plan else p_info["price"]
                    discount = 0
                    if promotion:
                        discount = min(base_price, promotion.value) if promotion.calculation_type == "fixed_discount" else min(base_price, round(base_price * promotion.value / 100)) if promotion.calculation_type == "percent_discount" else 0
                    db.add(AppointmentDetail(
                        appointment_id=appointment.id,
                        service_plan_id=service_plan.id if service_plan else None,
                        promotion_id=promotion.id if promotion else None,
                        contact_phone=user.phone,
                        base_price=base_price,
                        discount_amount=discount,
                        total_amount=max(0, base_price - discount),
                        location_type="external" if plan_key == "Out" else "pending",
                    ))
                db.commit()
                db.refresh(appointment)

                receipt_flex = build_appointment_bubble(appointment, db=db)
                reply_with_fallback(bot_customer_api, event.reply_token, FlexSendMessage(alt_text="預約確認明細", contents=receipt_flex), db=db, context="預約確認 Flex")

                notify_appointment_parties(appointment, db, origin="LINE 客戶預約")

        except Exception:
            logging.exception("處理客戶 postback 失敗")
        finally:
            db.close()


# --- 員工端：引導建檔與上下線邏輯 ---
if handler_staff:
    @handler_staff.add(MessageEvent, message=TextMessage)
    def handle_staff_message(event):
        user_id = getattr(getattr(event, "source", None), "user_id", None)
        text = getattr(event.message, "text", "").strip()
        
        if user_id:
            db = SessionLocal()
            try:
                admin_response = handle_line_admin_message(text, user_id, db)
                if admin_response:
                    bot_staff_api.reply_message(event.reply_token, admin_response)
                    return
                staff = db.query(Staff).filter(Staff.line_user_id == user_id).first()
                if not staff:
                    staff = Staff(line_user_id=user_id, name="新進員工")
                    db.add(staff)
                    db.commit()

                if not staff.phone:
                    if re.match(r"^09\d{8}$", text):
                        staff.phone_temp = normalize_phone(text)
                        db.commit()
                        bot_staff_api.reply_message(event.reply_token, build_phone_confirm_flex(text, "confirm_staff_phone"))
                    else:
                        bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="師傅您好，初次使用請先輸入您的 10 碼手機號碼綁定身分（例如：0912345678）"))
                    return

                if staff.name == "新進員工":
                    staff.name = text
                    db.commit()
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"設定完成！{text} 師傅您好。\n請輸入「我的檔案」來完善基本資料，或輸入「上線」開始接單。"))
                    return

                if text == "預約":
                    reply_with_fallback(
                        bot_staff_api,
                        event.reply_token,
                        build_staff_week_appointments(staff, db),
                        db=db,
                        context="師傅未來一週預約 Flex",
                    )
                elif text in {"後台", "後臺", "排班"}:
                    reply_with_fallback(bot_staff_api, event.reply_token, build_staff_backend_link(staff, db), db=db, context="師傅 LINE 直登入連結")
                elif text == "上線":
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="「師傅在線」已停用，請使用個人班表連結新增正式排班。"))
                elif text == "下線":
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="「師傅在線」已停用；如需取消班表，請使用個人班表連結，鎖定時段請洽店長。"))
                elif text == "我的檔案":
                    profile_lines = ["【基本資料】", f"姓名：{staff.name}"]
                    if staff.height:
                        profile_lines.append(f"身高：{staff.height}")
                    if staff.weight:
                        profile_lines.append(f"體重：{staff.weight}")
                    role = valid_staff_role(staff.role)
                    if role:
                        profile_lines.append(f"角色：{role}")
                    profile_txt = "\n".join(profile_lines) + "\n\n如需修改，請分別輸入：\n身高 170\n體重 65\n角色 攻擊手\n\n角色僅可填：攻擊手／守備方／無特定／攻守兼備"
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=profile_txt))
                elif text.startswith("身高 "):
                    staff.height = text.replace("身高 ", "").strip()
                    db.commit()
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新身高為 {staff.height}"))
                elif text.startswith("體重 "):
                    staff.weight = text.replace("體重 ", "").strip()
                    db.commit()
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新體重為 {staff.weight}"))
                elif text.startswith("角色 "):
                    requested_role = text.replace("角色 ", "").strip()
                    if requested_role not in VALID_STAFF_ROLES:
                        bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="角色格式不正確。僅可輸入：\n角色 攻擊手\n角色 守備方\n角色 無特定\n角色 攻守兼備"))
                    else:
                        staff.role = requested_role
                        db.commit()
                        bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新角色為 {staff.role}"))
                else:
                    guide_txt = "【伊果 SPA 派單小幫手】\n目前支援指令：\n📋「預約」：查看未來一週自己的預約\n👤「我的檔案」：查看與更新資料\n📅「排班」或「後台」：開啟自己的後台\n🔧「root」：管理員需再輸入 PIN 綁定"
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=guide_txt))

            except Exception:
                logging.exception("處理師傅訊息失敗")
            finally:
                db.close()

    @handler_staff.add(PostbackEvent)
    def handle_staff_postback(event):
        data = getattr(getattr(event, "postback", None), "data", "")
        user_id = getattr(getattr(event, "source", None), "user_id", None)
        
        db = SessionLocal()
        try:
            root_response = handle_root_action(data, user_id, db, is_staff_side=True)
            if root_response:
                reply_with_fallback(bot_staff_api, event.reply_token, root_response, db=db, context="派單端管理員選單", admin=True)
                return

            if "action=confirm_staff_phone" in data:
                qs = parse_qs(data)
                result = qs.get("result", [None])[0]
                staff = db.query(Staff).filter(Staff.line_user_id == user_id).first()
                if staff:
                    if result == "yes":
                        staff.phone = staff.phone_temp
                        staff.phone_temp = None
                        db.commit()
                        bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="綁定成功！請回覆您的「姓名」或「稱呼」來建立檔案。"))
                    else:
                        staff.phone_temp = None
                        db.commit()
                        bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="請再次輸入您的 10 碼手機號碼："))
        except Exception:
            logging.exception("處理師傅 postback 失敗")
        finally:
            db.close()

# --- Webhook 背景工作 ---
def _process_webhook(body: bytes, signature: str, bot_api, handler):
    if not handler:
        return
    try:
        handler.handle(body.decode("utf-8"), signature)
    except Exception:
        pass


def notify_appointment_parties(appointment, db: Session, *, origin: str = "後台建立") -> None:
    """Push a new order to bound customer-service accounts and the assigned staff only."""
    if not bot_staff_api:
        logging.warning("略過派單通知：LINE_TOKEN_STAFF 未設定 appointment_id=%s", appointment.id)
        return
    models = getattr(app.state, "admin_models", {})
    AdminUser = models.get("AdminUser")
    service_message = FlexSendMessage(
        alt_text=f"{origin}・新訂單",
        contents=build_appointment_bubble(appointment, is_staff_notify=True, db=db, show_return=True),
    )
    recipients: dict[str, str] = {}
    if AdminUser:
        for account in db.query(AdminUser).filter(AdminUser.is_active.is_(True), AdminUser.line_user_id.isnot(None)).all():
            recipients[account.line_user_id] = f"客服帳號 {account.username}"
    if appointment.staff and appointment.staff.line_user_id and not appointment.staff.line_user_id.startswith(("pending:", "seeded:")):
        recipients[appointment.staff.line_user_id] = f"師傅 {appointment.staff.name}"
    for line_user_id, label in recipients.items():
        try:
            bot_staff_api.push_message(line_user_id, service_message)
        except Exception:
            logging.exception("派單推送失敗 recipient=%s appointment_id=%s", label, appointment.id)

app = FastAPI(title="SPA 智能客服與預約系統")


def _database_heartbeat_loop(interval_seconds: int) -> None:
    while not _HEARTBEAT_STOP.wait(interval_seconds):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logging.info("Database heartbeat succeeded")
        except Exception:
            logging.exception("Database heartbeat failed")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        queries = [
            "ALTER TABLE users ADD COLUMN phone_temp VARCHAR(50);",
            "ALTER TABLE users ADD COLUMN display_name VARCHAR(255);",
            "ALTER TABLE staffs ADD COLUMN phone VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN phone_temp VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN height VARCHAR(20);",
            "ALTER TABLE staffs ADD COLUMN weight VARCHAR(20);",
            "ALTER TABLE staffs ADD COLUMN photo_url VARCHAR(1000);",
            "ALTER TABLE staffs ADD COLUMN role VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN category VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN employment_status VARCHAR(30) NOT NULL DEFAULT 'active';",
            "ALTER TABLE staffs ADD COLUMN return_rule_set_id INTEGER;",
            "ALTER TABLE admin_users ADD COLUMN line_user_id VARCHAR(255);",
            "ALTER TABLE promotions ADD COLUMN description VARCHAR(500);",
            "ALTER TABLE appointment_details ADD COLUMN promotion_id INTEGER;",
            "ALTER TABLE appointment_details ADD COLUMN contact_phone VARCHAR(20);",
            "ALTER TABLE appointments ADD COLUMN plan_name VARCHAR(50);"
        ]
        for q in queries:
            try:
                conn.execute(text(q))
            except Exception:
                # These compatibility ALTERs are intentionally idempotent. A
                # duplicate-column error simply means the migration ran before.
                pass
        if engine.dialect.name == "mysql":
            conn.execute(text(
                "UPDATE appointments "
                "SET end_time = DATE_ADD(start_time, INTERVAL duration MINUTE) "
                "WHERE end_time <= start_time"
            ))

    db = SessionLocal()
    try:
        admin_models = getattr(app.state, "admin_models", {})
        DeletedStaffIdentity = admin_models.get("DeletedStaffIdentity")
        deleted_staff_names = {
            item.normalized_name for item in db.query(DeletedStaffIdentity).all()
        } if DeletedStaffIdentity else set()
        existing_staff = {item.name.strip().casefold(): item for item in db.query(Staff).all()}
        for profile in THERAPIST_PROFILES:
            if profile.name.strip().casefold() in deleted_staff_names:
                continue
            staff_obj = existing_staff.get(profile.name.casefold())
            if not staff_obj:
                staff_obj = Staff(
                    line_user_id=f"seeded:{profile.category}:{profile.slug}",
                    name=profile.name,
                    employment_status="active",
                    is_online=False,
                )
                db.add(staff_obj)
                existing_staff[profile.name.casefold()] = staff_obj
            if not staff_obj.height:
                staff_obj.height = profile.height
            if not staff_obj.weight:
                staff_obj.weight = profile.weight
            if not staff_obj.category:
                staff_obj.category = profile.category
            staff_obj.photo_url = therapist_photo_url(profile)
        for customer in db.query(User).filter(User.phone.isnot(None)).order_by(User.id).all():
            try:
                normalized = normalize_phone(customer.phone)
            except ValueError:
                logging.warning("略過無法正規化的舊客戶手機 user_id=%s", customer.id)
                continue
            owner = db.query(CustomerPhone).filter(CustomerPhone.phone == normalized).first()
            if not owner:
                db.add(CustomerPhone(user_id=customer.id, phone=normalized, is_primary=True))
                customer.phone = normalized
            elif owner.user_id == customer.id:
                owner.is_primary = True
        db.commit()
    except Exception:
        db.rollback()
        logging.exception("無法補齊師傅名單")
    finally:
        db.close()

    interval = max(60, int(os.getenv("DATABASE_HEARTBEAT_SECONDS", "720")))
    heartbeat = getattr(app.state, "database_heartbeat_thread", None)
    if not heartbeat or not heartbeat.is_alive():
        _HEARTBEAT_STOP.clear()
        heartbeat = threading.Thread(target=_database_heartbeat_loop, args=(interval,), daemon=True, name="aiven-heartbeat")
        heartbeat.start()
        app.state.database_heartbeat_thread = heartbeat


@app.on_event("shutdown")
def on_shutdown():
    _HEARTBEAT_STOP.set()

@app.get("/")
def read_root():
    return {"message": "Hello from SPA FastAPI"}

@app.post("/webhook/customer")
async def webhook_customer(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    background_tasks.add_task(_process_webhook, body, signature, bot_customer_api, handler_customer)
    return Response(status_code=200)

@app.post("/webhook/staff")
async def webhook_staff(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    background_tasks.add_task(_process_webhook, body, signature, bot_staff_api, handler_staff)
    return Response(status_code=200)


from admin_api import register_admin_api

register_admin_api(
    app,
    Base=Base,
    engine=engine,
    SessionLocal=SessionLocal,
    User=User,
    CustomerPhone=CustomerPhone,
    Staff=Staff,
    Appointment=Appointment,
    appointment_notifier=notify_appointment_parties,
)
