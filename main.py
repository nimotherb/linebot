from fastapi import FastAPI, Request, Response, BackgroundTasks
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from dotenv import load_dotenv
import os
import logging
from datetime import datetime, date
import re
from urllib.parse import parse_qs

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
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- SQLAlchemy models ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=True)
    phone_temp = Column(String(50), nullable=True)
    utm_source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    appointments = relationship("Appointment", back_populates="user", cascade="all, delete-orphan")

class Staff(Base):
    __tablename__ = "staffs"
    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=True)
    phone_temp = Column(String(50), nullable=True)
    name = Column(String(255), nullable=False)
    height = Column(String(20), nullable=True)
    weight = Column(String(20), nullable=True)
    role = Column(String(50), nullable=True)
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

bot_customer_api = LineBotApi(LINE_TOKEN_CUSTOMER) if LINE_TOKEN_CUSTOMER else None
handler_customer = WebhookHandler(LINE_SECRET_CUSTOMER) if LINE_SECRET_CUSTOMER else None

bot_staff_api = LineBotApi(LINE_TOKEN_STAFF) if LINE_TOKEN_STAFF else None
handler_staff = WebhookHandler(LINE_SECRET_STAFF) if LINE_SECRET_STAFF else None

logging.basicConfig(level=logging.INFO)

# 方案設定字典
PLANS_INFO = {
    "A": {"name": "A-舒壓方案", "duration": 60, "price": 1500, "desc": "不指定優惠 / 指油壓"},
    "B": {"name": "B-愉悅方案", "duration": 60, "price": 2000, "desc": "指定師傅 / 體推保養"},
    "C": {"name": "C-享受方案", "duration": 90, "price": 2500, "desc": "指定師傅 / 體推保養"},
    "D": {"name": "D-極緻方案", "duration": 120, "price": 3000, "desc": "指定師傅 / 體推保養"},
    "Out": {"name": "外出-隨享", "duration": 100, "price": 3200, "desc": "指定師傅 / 獅子林起算"}
}

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
def build_root_admin_menu():
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
                    {"type": "button", "style": "primary", "color": "#7C3AED", "margin": "md", "action": {"type": "postback", "label": "查看本日預約", "data": "action=admin_view"}},
                    {"type": "button", "style": "primary", "color": "#7C3AED", "margin": "sm", "action": {"type": "postback", "label": "管理師傅", "data": "action=admin_staff"}}
                ]
            }
        }
    )

# --- 共用：生成預約單 Carousel Bubble ---
def build_appointment_bubble(appointment):
    staff_name = appointment.staff.name if appointment.staff else "未指定(由店長安排)"
    staff_info = ""
    if appointment.staff:
        h = appointment.staff.height or "?"
        w = appointment.staff.weight or "?"
        staff_info = f"身高: {h} / 體重: {w}"
    
    customer_name = "客戶"
    if appointment.user:
        try:
            profile = bot_staff_api.get_profile(appointment.user.line_user_id)
            customer_name = profile.display_name
        except:
            customer_name = f"用戶 {appointment.user.id}"
    
    start_time_str = appointment.start_time.strftime("%m月%d日 %H:%M") if appointment.start_time else "未定"
    plan_name = appointment.plan_name or "未知方案"
    
    price = 0
    discount = 200 # 固定優惠測試
    for plan_key, plan_info in PLANS_INFO.items():
        if plan_info["name"] == plan_name:
            price = plan_info["price"]
            break
    
    total = price - discount if price > 0 else 0
    payment_id = f"#{appointment.created_at.strftime('%y%m%d')}{appointment.id:03d}"
    
    bubble = {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "今日預約", "weight": "bold", "color": "#1DB446", "size": "sm"},
                {"type": "text", "text": staff_name, "weight": "bold", "size": "xxl", "margin": "md"},
                {"type": "text", "text": staff_info, "size": "xs", "color": "#aaaaaa", "wrap": True},
                {"type": "separator", "margin": "xxl"},
                {
                    "type": "box", "layout": "vertical", "margin": "xxl", "spacing": "sm",
                    "contents": [
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "客戶", "size": "sm", "color": "#555555"}, {"type": "text", "text": customer_name, "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "時段", "size": "sm", "color": "#555555", "flex": 0}, {"type": "text", "text": start_time_str, "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "方案", "size": "sm", "color": "#555555", "flex": 0}, {"type": "text", "text": plan_name, "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "separator", "margin": "xxl"},
                        {"type": "box", "layout": "horizontal", "margin": "xxl", "contents": [{"type": "text", "text": "方案定價", "size": "sm", "color": "#555555"}, {"type": "text", "text": f"NT$ {price}", "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "優惠", "size": "sm", "color": "#555555"}, {"type": "text", "text": f"-NT$ {discount}", "size": "sm", "color": "#111111", "align": "end"}]},
                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "總計", "size": "sm", "color": "#555555"}, {"type": "text", "text": f"NT$ {total}", "size": "sm", "color": "#111111", "align": "end"}]}
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
    is_online_text = "上線中" if staff.is_online else "下線"
    height = staff.height or "?"
    weight = staff.weight or "?"
    
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "text", "text": staff.name, "wrap": True, "weight": "bold", "size": "xxl"},
                {
                    "type": "box", "layout": "baseline",
                    "contents": [
                        {"type": "text", "text": f"身高: {height} / 體重: {weight} / 狀態: {is_online_text}", "wrap": True, "weight": "regular", "size": "md", "flex": 0}
                    ]
                }
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {"type": "button", "style": "primary", "color": "#e11d48", "action": {"type": "postback", "label": "刪除", "data": f"action=delete_staff&staff_id={staff.id}"}},
                {"type": "button", "action": {"type": "postback", "label": "暫不上架", "data": f"action=toggle_staff&staff_id={staff.id}"}}
            ]
        }
    }

def handle_root_action(data, user_id, db, is_staff_side=False):
    api = bot_staff_api if is_staff_side else bot_customer_api
    
    if "action=admin_view" in data:
        today = date.today()
        appointments = db.query(Appointment).filter(
            Appointment.start_time >= datetime.combine(today, datetime.min.time()),
            Appointment.start_time < datetime.combine(today, datetime.max.time())
        ).all()
        
        if not appointments:
            return TextSendMessage(text="今日目前無預約")
        
        bubbles = [build_appointment_bubble(appt) for appt in appointments]
        return FlexSendMessage(alt_text="本日預約", contents={"type": "carousel", "contents": bubbles})
    
    elif "action=admin_staff" in data:
        staffs = db.query(Staff).all()
        if not staffs:
            return TextSendMessage(text="目前無師傅資料")
        bubbles = [build_staff_bubble(staff) for staff in staffs]
        return FlexSendMessage(alt_text="師傅管理", contents={"type": "carousel", "contents": bubbles})
    
    elif "action=delete_staff" in data:
        qs = parse_qs(data)
        staff_id = qs.get("staff_id", [None])[0]
        if staff_id:
            staff = db.query(Staff).filter(Staff.id == int(staff_id)).first()
            if staff:
                db.delete(staff)
                db.commit()
                return TextSendMessage(text=f"已刪除師傅 {staff.name}")
    
    elif "action=toggle_staff" in data:
        qs = parse_qs(data)
        staff_id = qs.get("staff_id", [None])[0]
        if staff_id:
            staff = db.query(Staff).filter(Staff.id == int(staff_id)).first()
            if staff:
                staff.is_online = not staff.is_online
                db.commit()
                status = "上線" if staff.is_online else "下線"
                return TextSendMessage(text=f"已將 {staff.name} 切換為 {status}")
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
                user = db.query(User).filter(User.line_user_id == user_id).first()
                if not user:
                    user = User(line_user_id=user_id)
                    db.add(user)
                    db.commit()

                if text == "root":
                    bot_customer_api.reply_message(event.reply_token, build_root_admin_menu())
                    return

                if text == "預約":
                    if not user.phone:
                        bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="為了保障您的預約權益，請在下方輸入您的 10 碼手機號碼（例如：0912345678）"))
                    else:
                        dt_action = DatetimePickerTemplateAction(label="選擇時間", data="action=select_date", mode="datetime")
                        bot_customer_api.reply_message(event.reply_token, TemplateSendMessage(alt_text="請選擇時間", template=ButtonsTemplate(text="請選擇您想預約的時間", actions=[dt_action])))
                    return

                if not user.phone and re.match(r"^09\d{8}$", text):
                    user.phone_temp = text
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
                            "contents": [{"type": "button", "style": "primary", "action": {"type": "message", "label": "線上預約", "text": "預約"}}]
                        }
                    }
                )
                bot_customer_api.reply_message(event.reply_token, flex_message)
            except Exception:
                pass
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
                bot_customer_api.reply_message(event.reply_token, root_response)
                return

            if "action=confirm_customer_phone" in data:
                qs = parse_qs(data)
                result = qs.get("result", [None])[0]
                user = db.query(User).filter(User.line_user_id == user_id).first()
                if user:
                    if result == "yes":
                        user.phone = user.phone_temp
                        user.phone_temp = None
                        db.commit()
                        dt_action = DatetimePickerTemplateAction(label="選擇時間", data="action=select_date", mode="datetime")
                        bot_customer_api.reply_message(event.reply_token, TemplateSendMessage(alt_text="請選擇時間", template=ButtonsTemplate(text="感謝綁定！現在請選擇想預約的時間", actions=[dt_action])))
                    else:
                        user.phone_temp = None
                        db.commit()
                        bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="請再次輸入您的 10 碼手機號碼："))

            # 選擇日期後 -> 彈出各方案的輪播卡片
            elif data == "action=select_date":
                selected_dt = params.get("datetime")
                bubbles = []
                for plan_key, p_info in PLANS_INFO.items():
                    # 方案A直接跳確認，其他方案帶入 offset=0 準備進入師傅輪播
                    postback_data = f"action=confirm_booking&staff_id=none&plan={plan_key}&datetime={selected_dt}" if plan_key == "A" else f"action=select_staff&plan={plan_key}&datetime={selected_dt}&offset=0"
                    
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

            # 選擇方案後 -> 師傅分頁輪播 (分頁處理，避開 LINE 10 張限制)
            elif "action=select_staff" in data:
                qs = parse_qs(data)
                plan = qs.get("plan", [None])[0]
                selected_dt = qs.get("datetime", [None])[0]
                offset = int(qs.get("offset", ["0"])[0])

                # 每次往資料庫抓 10 個
                online_staff = db.query(Staff).filter(Staff.is_online == True).offset(offset).limit(10).all()
                
                if not online_staff and offset == 0:
                    bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="目前正好沒有師傅在線上，請稍後再試喔！"))
                    return
                elif not online_staff:
                    bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="沒有更多師傅囉！"))
                    return

                # 判斷是否滿 10 個（代表還有下一頁）
                has_more = len(online_staff) == 10
                # 畫面上最多只顯示 9 位師傅
                display_staff = online_staff[:9]

                bubbles = []
                for s in display_staff:
                    info_text = f"身高:{s.height or '?'} 體重:{s.weight or '?'} 角色:{s.role or '?'}"
                    bubbles.append({
                        "type": "bubble",
                        "hero": {
                            "type": "image", "size": "full", "aspectRatio": "10:8", "aspectMode": "cover",
                            "url": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=500&h=400&fit=crop" # ←在此抽換照片網址
                        },
                        "body": {
                            "type": "box", "layout": "vertical", "backgroundColor": "#000000",
                            "contents": [
                                {"type": "text", "text": s.name, "weight": "bold", "size": "xxl", "color": "#C0CAF5"},
                                {"type": "text", "text": info_text, "size": "sm", "color": "#9ECE6A", "margin": "md"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical", "backgroundColor": "#111111",
                            "contents": [{"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "預約這位", "data": f"action=confirm_booking&staff_id={s.id}&plan={plan}&datetime={selected_dt}"}}]
                        }
                    })

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
                            "contents": [{"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "下一頁", "data": f"action=select_staff&plan={plan}&datetime={selected_dt}&offset={next_offset}"}}]
                        }
                    })

                bot_customer_api.reply_message(event.reply_token, FlexSendMessage(alt_text="請選擇師傅", contents={"type": "carousel", "contents": bubbles}))

            elif "action=confirm_booking" in data:
                qs = parse_qs(data)
                staff_id = qs.get("staff_id", [None])[0]
                plan_key = qs.get("plan", [None])[0]
                selected_dt = qs.get("datetime", [None])[0]

                user = db.query(User).filter(User.line_user_id == user_id).first()
                staff_obj = None
                
                if staff_id != "none":
                    staff_obj = db.query(Staff).filter(Staff.id == int(staff_id)).first()

                p_info = PLANS_INFO.get(plan_key, {"duration": 60, "price": 0, "name": "未知方案"})
                
                appointment = Appointment(
                    user_id=user.id,
                    staff_id=int(staff_id) if staff_id != "none" else None,
                    duration=p_info["duration"],
                    plan_name=p_info["name"],
                    start_time=datetime.fromisoformat(selected_dt),
                    end_time=datetime.fromisoformat(selected_dt),
                    status="confirmed"
                )
                db.add(appointment)
                db.commit()
                db.refresh(appointment)

                time_str = datetime.fromisoformat(selected_dt).strftime("%m月%d日 %H:%M")

                receipt_flex = build_appointment_bubble(appointment)
                bot_customer_api.reply_message(event.reply_token, FlexSendMessage(alt_text="預約確認明細", contents=receipt_flex))

                # --- 派單邏輯：推送給師傅 ---
                if bot_staff_api:
                    customer_name = "貴賓"
                    try:
                        profile = bot_customer_api.get_profile(user_id)
                        customer_name = profile.display_name
                    except:
                        pass

                    notify_msg = FlexSendMessage(
                        alt_text="新派單通知",
                        contents={
                            "type": "bubble", "styles": {"body": {"backgroundColor": "#1A1B26"}},
                            "body": {
                                "type": "box", "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "🔔 新派單通知", "weight": "bold", "color": "#9ECE6A"},
                                    {"type": "text", "text": f"時間：{time_str}", "color": "#C0CAF5", "margin": "md"},
                                    {"type": "text", "text": f"方案：{p_info['name']}", "color": "#C0CAF5"},
                                    {"type": "text", "text": f"客戶：{customer_name}", "color": "#C0CAF5"}
                                ]
                            }
                        }
                    )
                    if staff_id == "none":
                        online_staff = db.query(Staff).filter(Staff.is_online == True).all()
                        for s in online_staff:
                            bot_staff_api.push_message(s.line_user_id, notify_msg)
                    else:
                        if staff_obj:
                            bot_staff_api.push_message(staff_obj.line_user_id, notify_msg)

        except Exception as e:
            logging.error(f"Customer Postback Error: {e}")
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
                staff = db.query(Staff).filter(Staff.line_user_id == user_id).first()
                if not staff:
                    staff = Staff(line_user_id=user_id, name="新進員工")
                    db.add(staff)
                    db.commit()

                if not staff.phone:
                    if re.match(r"^09\d{8}$", text):
                        staff.phone_temp = text
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

                if text == "root":
                    bot_staff_api.reply_message(event.reply_token, build_root_admin_menu())
                    return
                elif text == "上線":
                    staff.is_online = True
                    staff.online_start_time = datetime.utcnow()
                    db.commit()
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"【狀態更新】{staff.name} 師傅，已為您切換為上線模式！"))
                elif text == "下線":
                    staff.is_online = False
                    db.commit()
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"辛苦了 {staff.name} 師傅！已為您切換為下線模式。"))
                elif text == "我的檔案":
                    profile_txt = f"【基本資料】\n姓名：{staff.name}\n身高：{staff.height or '未設'}\n體重：{staff.weight or '未設'}\n角色：{staff.role or '未設'}\n\n如需修改，請分別輸入：\n身高 170\n體重 65\n角色 泰式"
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
                    staff.role = text.replace("角色 ", "").strip()
                    db.commit()
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"已更新角色為 {staff.role}"))
                else:
                    guide_txt = "【伊果 SPA 派單小幫手】\n目前支援指令：\n🟢「上線」：開啟接單\n🔴「下線」：結束排班\n👤「我的檔案」：查看與更新資料\n🔧「root」：管理員功能"
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=guide_txt))

            except Exception:
                pass
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
                bot_staff_api.reply_message(event.reply_token, root_response)
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
            pass
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

app = FastAPI(title="SPA 智能客服與預約系統")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        queries = [
            "ALTER TABLE users ADD COLUMN phone_temp VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN phone VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN phone_temp VARCHAR(50);",
            "ALTER TABLE staffs ADD COLUMN height VARCHAR(20);",
            "ALTER TABLE staffs ADD COLUMN weight VARCHAR(20);",
            "ALTER TABLE staffs ADD COLUMN role VARCHAR(50);",
            "ALTER TABLE appointments ADD COLUMN plan_name VARCHAR(50);"
        ]
        for q in queries:
            try:
                conn.execute(text(q))
            except Exception:
                pass
    
    # 自動建立假資料測試
    db = SessionLocal()
    try:
        if db.query(Staff).count() == 0:
            seed_staff = []
            for i in range(1, 15):
                seed_staff.append(
                    Staff(
                        line_user_id=f"seed{i}", 
                        name=f"測試師傅 {i}號", 
                        height="175", 
                        weight="70", 
                        role="M痘", 
                        is_online=True
                    )
                )
            db.add_all(seed_staff)
            db.commit()
    except Exception:
        pass
    finally:
        db.close()

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
