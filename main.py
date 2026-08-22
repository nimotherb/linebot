from fastapi import FastAPI, Request, Response, Depends, BackgroundTasks
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from dotenv import load_dotenv
import os
import logging
from datetime import datetime
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
    PostbackTemplateAction,
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

            elif data == "action=select_date":
                selected_dt = params.get("datetime")
                # 產生 5 個方案的 Carousel
                bubbles = []
                for plan_key, p_info in PLANS_INFO.items():
                    # 方案 A 不能指定師傅，直接跳到確認
                    postback_data = f"action=confirm_booking&staff_id=none&plan={plan_key}&datetime={selected_dt}" if plan_key == "A" else f"action=select_staff&plan={plan_key}&datetime={selected_dt}"
                    
                    bubbles.append({
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": p_info["name"], "weight": "bold", "size": "xl", "color": "#1DB446"},
                                {"type": "text", "text": f"NT$ {p_info['price']}", "weight": "bold", "size": "md", "margin": "sm"},
                                {"type": "text", "text": p_info["desc"], "size": "xs", "color": "#aaaaaa", "wrap": True, "margin": "sm"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical",
                            "contents": [{"type": "button", "style": "primary", "action": {"type": "postback", "label": "選擇此方案", "data": postback_data}}]
                        }
                    })
                bot_customer_api.reply_message(event.reply_token, FlexSendMessage(alt_text="請選擇服務方案", contents={"type": "carousel", "contents": bubbles}))

            elif "action=select_staff" in data:
                qs = parse_qs(data)
                plan = qs.get("plan", [None])[0]
                selected_dt = qs.get("datetime", [None])[0]

                online_staff = db.query(Staff).filter(Staff.is_online == True).all()
                if not online_staff:
                    bot_customer_api.reply_message(event.reply_token, TextSendMessage(text="目前正好沒有師傅在線上，請稍後再試喔！"))
                    return

                bubbles = []
                for s in online_staff:
                    info_text = f"身高:{s.height or '?'} 體重:{s.weight or '?'} 角色:{s.role or '?'}"
                    bubbles.append({
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
                            "contents": [{"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "預約這位", "data": f"action=confirm_booking&staff_id={s.id}&plan={plan}&datetime={selected_dt}"}}]
                        }
                    })
                # 不指定師傅卡片
                bubbles.append({
                    "type": "bubble",
                    "body": {
                        "type": "box", "layout": "vertical", "backgroundColor": "#000000",
                        "contents": [{"type": "text", "text": "不指定師傅", "weight": "bold", "size": "xl", "color": "#C0CAF5", "align": "center"}]
                    },
                    "footer": {
                        "type": "box", "layout": "vertical", "backgroundColor": "#111111",
                        "contents": [{"type": "button", "style": "primary", "color": "#9ECE6A", "action": {"type": "postback", "label": "由店長安排", "data": f"action=confirm_booking&staff_id=none&plan={plan}&datetime={selected_dt}"}}]
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
                staff_name = "未指定(由店長安排)"
                if staff_id != "none":
                    staff_obj = db.query(Staff).filter(Staff.id == int(staff_id)).first()
                    if staff_obj:
                        staff_name = staff_obj.name

                p_info = PLANS_INFO.get(plan_key, {"duration": 60, "price": 0, "name": "未知方案"})
                total_price = p_info["price"]

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

                payment_id = f"#{datetime.utcnow().strftime('%y%m%d')}{appointment.id:03d}"
                customer_vip_id = f"VIP-{user.id:04d}"
                customer_name = user_id
                try:
                    profile = bot_customer_api.get_profile(user_id)
                    customer_name = profile.display_name
                except:
                    pass

                time_str = datetime.fromisoformat(selected_dt).strftime("%m月%d日 %H:%M")

                receipt_flex = FlexSendMessage(
                    alt_text="預約確認明細",
                    contents={
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": "預約成功明細", "weight": "bold", "color": "#1DB446", "size": "sm"},
                                {"type": "text", "text": staff_name, "weight": "bold", "size": "xl", "margin": "md"},
                                {"type": "separator", "margin": "xl"},
                                {
                                    "type": "box", "layout": "vertical", "margin": "xl", "spacing": "sm",
                                    "contents": [
                                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "客戶 ID", "size": "sm", "color": "#555555"}, {"type": "text", "text": customer_vip_id, "size": "sm", "align": "end"}]},
                                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "客戶", "size": "sm", "color": "#555555"}, {"type": "text", "text": customer_name, "size": "sm", "align": "end"}]},
                                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "時段", "size": "sm", "color": "#555555"}, {"type": "text", "text": time_str, "size": "sm", "align": "end"}]},
                                        {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "方案", "size": "sm", "color": "#555555"}, {"type": "text", "text": p_info["name"], "size": "sm", "align": "end"}]},
                                        {"type": "separator", "margin": "lg"},
                                        {"type": "box", "layout": "horizontal", "margin": "lg", "contents": [{"type": "text", "text": "總計", "size": "md", "color": "#555555"}, {"type": "text", "text": f"NT$ {total_price:,}", "size": "md", "weight": "bold", "align": "end"}]}
                                    ]
                                },
                                {"type": "separator", "margin": "xl"},
                                {"type": "box", "layout": "horizontal", "margin": "md", "contents": [{"type": "text", "text": "ORDER ID", "size": "xs", "color": "#aaaaaa"}, {"type": "text", "text": payment_id, "color": "#aaaaaa", "size": "xs", "align": "end"}]}
                            ]
                        }
                    }
                )
                bot_customer_api.reply_message(event.reply_token, receipt_flex)

                # --- 派單邏輯：推送給師傅 ---
                if bot_staff_api:
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
                                    {"type": "text", "text": f"客戶：{customer_name}", "color": "#C0CAF5"},
                                    {"type": "text", "text": f"金額：{total_price}", "color": "#C0CAF5"}
                                ]
                            }
                        }
                    )
                    if staff_id == "none":
                        # 廣播給所有上線師傅
                        online_staff = db.query(Staff).filter(Staff.is_online == True).all()
                        for s in online_staff:
                            bot_staff_api.push_message(s.line_user_id, notify_msg)
                    else:
                        # 單獨推給指定師傅
                        if staff_obj:
                            bot_staff_api.push_message(staff_obj.line_user_id, notify_msg)

        except Exception:
            pass
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

                # 師傅手機綁定防呆
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
                    bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=f"設定完成！{text} 師傅您好。\n請輸入「我的檔案」來完善基本資料，或輸入「上線」開始接單！"))
                    return

                # --- 指令區 ---
                if text == "root":
                    root_menu = FlexSendMessage(
                        alt_text="系統管理員選單",
                        contents={
                            "type": "bubble", "styles": {"body": {"backgroundColor": "#4C1D95"}},
                            "body": {
                                "type": "box", "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "ROOT ADMIN", "weight": "bold", "color": "#FCD34D", "size": "xl"},
                                    {"type": "button", "style": "primary", "color": "#7C3AED", "margin": "md", "action": {"type": "postback", "label": "查看本日預約", "data": "action=admin_view"}},
                                    {"type": "button", "style": "primary", "color": "#7C3AED", "margin": "sm", "action": {"type": "postback", "label": "管理師傅", "data": "action=admin_staff"}}
                                ]
                            }
                        }
                    )
                    bot_staff_api.reply_message(event.reply_token, root_menu)
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
                    profile_txt = f"【基本資料】\n姓名：{staff.name}\n身高：{staff.height or '未設'}\n體重：{staff.weight or '未設'}\n角色：{staff.role or '未設'}\n\n如需更新，請直接輸入例如：\n「身高 180」\n「體重 75」\n「角色 攻擊手」"
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
                    guide_txt = "【伊果 SPA 派單小幫手】\n目前支援指令：\n🟢「上線」：開啟接單\n🔴「下線」：結束排班\n👤「我的檔案」：查看與更新資料\n\n更新資料請輸入例如：「身高 175」"
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
            elif "action=admin_" in data:
                bot_staff_api.reply_message(event.reply_token, TextSendMessage(text="【系統提示】詳細的資料總覽與排班修改，請至店內的 React 戰情室網頁操作喔！"))
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
