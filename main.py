from fastapi import FastAPI, Request, Response, Depends, BackgroundTasks
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from dotenv import load_dotenv
import os
import logging
from datetime import datetime
import re
from urllib.parse import parse_qs
import json

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
    raise RuntimeError("環境變數 DATABASE_URL 未設定，請設定為 mysql+pymysql://user:pass@host:port/dbname")

# 建立 SQLAlchemy engine 與 Session 工廠
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- SQLAlchemy models: Users, Staffs, Appointments ---
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    phone = Column(String(50), nullable=True)
    phone_temp = Column(String(50), nullable=True)  # 暫存未確認的手機號碼
    utm_source = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    appointments = relationship("Appointment", back_populates="user", cascade="all, delete-orphan")


class Staff(Base):
    __tablename__ = "staffs"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
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
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="appointments")
    staff = relationship("Staff", back_populates="appointments")

# --------------------------------------------------

# DB session dependency
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 讀取 LINE 相關環境變數
LINE_SECRET_CUSTOMER = os.getenv("LINE_SECRET_CUSTOMER")
LINE_TOKEN_CUSTOMER = os.getenv("LINE_TOKEN_CUSTOMER")
LINE_SECRET_STAFF = os.getenv("LINE_SECRET_STAFF")
LINE_TOKEN_STAFF = os.getenv("LINE_TOKEN_STAFF")

# 建立 LineBotApi / WebhookHandler 實例
bot_customer_api = LineBotApi(LINE_TOKEN_CUSTOMER) if LINE_TOKEN_CUSTOMER else None
handler_customer = WebhookHandler(LINE_SECRET_CUSTOMER) if LINE_SECRET_CUSTOMER else None

bot_staff_api = LineBotApi(LINE_TOKEN_STAFF) if LINE_TOKEN_STAFF else None
handler_staff = WebhookHandler(LINE_SECRET_STAFF) if LINE_SECRET_STAFF else None

# 設定基本 logging
logging.basicConfig(level=logging.INFO)

# --- 客人端：引導建檔與對話邏輯 ---
if handler_customer:
    @handler_customer.add(MessageEvent, message=TextMessage)
    def handle_customer_message(event):
        user_id = getattr(getattr(event, "source", None), "user_id", None)
        text = getattr(event.message, "text", "").strip()
        reply_text = text

        if user_id:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.line_user_id == user_id).first()
                if not user:
                    user = User(line_user_id=user_id)
                    db.add(user)
                    db.commit()

                # 預約防呆流程第一步：若客人輸入「預約」
                if text == "預約":
                    # 檢查 user.phone 是否有值
                    if not user.phone:
                        # 若沒有，回傳提示卡片（FlexSendMessage）
                        flex_message = FlexSendMessage(
                            alt_text="請輸入手機號碼",
                            contents={
                                "type": "bubble",
                                "body": {
                                    "type": "box",
                                    "layout": "vertical",
                                    "contents": [
                                        {
                                            "type": "text",
                                            "text": "為了保障您的預約權益",
                                            "weight": "bold",
                                            "size": "lg",
                                            "color": "#1DB446",
                                            "wrap": True
                                        },
                                        {
                                            "type": "text",
                                            "text": "請在下方對話框輸入您的 10 碼手機號碼",
                                            "size": "sm",
                                            "color": "#555555",
                                            "wrap": True,
                                            "margin": "md"
                                        },
                                        {
                                            "type": "text",
                                            "text": "例如：0912345678",
                                            "size": "xs",
                                            "color": "#aaaaaa",
                                            "wrap": True,
                                            "margin": "sm",
                                            "style": "italic"
                                        }
                                    ]
                                }
                            }
                        )
                        if bot_customer_api:
                            bot_customer_api.reply_message(event.reply_token, flex_message)
                    else:
                        # 若 user.phone 已有值，直接回傳 DatetimePickerTemplateAction 按鈕
                        datetime_action = DatetimePickerTemplateAction(
                            label="選擇時間",
                            data="action=select_date",
                            mode="datetime",
                        )
                        buttons = ButtonsTemplate(
                            text="請選擇您想預約的時間",
                            actions=[datetime_action],
                        )
                        template_message = TemplateSendMessage(alt_text="請選擇您想預約的時間", template=buttons)
                        if bot_customer_api:
                            bot_customer_api.reply_message(event.reply_token, template_message)
                    return

                # 預約防呆流程第一步：若客人的 user.phone 為空，且輸入 10 碼數字
                if not user.phone and re.match(r"^09\d{8}$", text):
                    # 將 10 碼存入 user.phone_temp 並 commit
                    user.phone_temp = text
                    db.commit()
                    
                    # 回傳 FlexSendMessage，包含兩個按鈕
                    flex_message = FlexSendMessage(
                        alt_text="確認手機號碼",
                        contents={
                            "type": "bubble",
                            "body": {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {
                                        "type": "text",
                                        "text": "確認手機號碼",
                                        "weight": "bold",
                                        "size": "lg",
                                        "color": "#1DB446",
                                        "wrap": True
                                    },
                                    {
                                        "type": "box",
                                        "layout": "vertical",
                                        "margin": "md",
                                        "spacing": "sm",
                                        "contents": [
                                            {
                                                "type": "text",
                                                "text": f"您輸入的手機號碼是 {text}",
                                                "weight": "bold",
                                                "size": "md",
                                                "color": "#111111",
                                                "wrap": True
                                            },
                                            {
                                                "type": "text",
                                                "text": "請問正確嗎？",
                                                "size": "sm",
                                                "color": "#555555",
                                                "wrap": True,
                                                "margin": "sm"
                                            }
                                        ]
                                    }
                                ]
                            },
                            "footer": {
                                "type": "box",
                                "layout": "horizontal",
                                "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "button",
                                        "style": "primary",
                                        "action": {
                                            "type": "postback",
                                            "label": "正確",
                                            "data": "action=confirm_phone&result=yes"
                                        }
                                    },
                                    {
                                        "type": "button",
                                        "style": "secondary",
                                        "action": {
                                            "type": "postback",
                                            "label": "重新輸入",
                                            "data": "action=confirm_phone&result=no"
                                        }
                                    }
                                ]
                            }
                        }
                    )
                    if bot_customer_api:
                        bot_customer_api.reply_message(event.reply_token, flex_message)
                    return

                # 其他任何文字：回傳歡迎的 FlexSendMessage
                flex_message = FlexSendMessage(
                    alt_text="歡迎預約",
                    contents={
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "歡迎來到伊果 SPA",
                                    "weight": "bold",
                                    "size": "lg",
                                    "color": "#1DB446",
                                    "wrap": True
                                },
                                {
                                    "type": "text",
                                    "text": "👋 很高興為您服務",
                                    "size": "sm",
                                    "color": "#555555",
                                    "wrap": True,
                                    "margin": "md"
                                }
                            ]
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "spacing": "sm",
                            "contents": [
                                {
                                    "type": "button",
                                    "style": "link",
                                    "height": "sm",
                                    "action": {
                                        "type": "message",
                                        "label": "線上預約",
                                        "text": "預約"
                                    }
                                }
                            ],
                            "flex": 0
                        }
                    }
                )
                if bot_customer_api:
                    bot_customer_api.reply_message(event.reply_token, flex_message)
                return

            except Exception:
                logging.exception("Error in customer message handling")
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                db.close()

    @handler_customer.add(PostbackEvent)
    def handle_customer_postback(event):
        # 取得 postback 的 data 與 params
        data = getattr(getattr(event, "postback", None), "data", "")
        params = getattr(getattr(event, "postback", None), "params", None) or {}

        try:
            # 預約防呆流程第二步：處理手機號碼確認
            if "action=confirm_phone" in data:
                qs = parse_qs(data)
                result = qs.get("result", [None])[0]
                
                user_id = getattr(getattr(event, "source", None), "user_id", None)
                
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.line_user_id == user_id).first()
                    if not user:
                        logging.error("User not found for phone confirmation")
                        return
                    
                    if result == "yes":
                        # 將 user.phone_temp 的值正式存入 user.phone
                        user.phone = user.phone_temp
                        user.phone_temp = None
                        db.commit()
                        
                        # 回傳「線上預約」的 datetimepicker 按鈕
                        datetime_action = DatetimePickerTemplateAction(
                            label="選擇時間",
                            data="action=select_date",
                            mode="datetime",
                        )
                        buttons = ButtonsTemplate(
                            text="感謝您！現在請選擇想預約的時間",
                            actions=[datetime_action],
                        )
                        template_message = TemplateSendMessage(alt_text="請選擇您想預約的時間", template=buttons)
                        if bot_customer_api:
                            bot_customer_api.reply_message(event.reply_token, template_message)
                    
                    elif result == "no":
                        # 將 user.phone_temp 清空設為 None 並 commit
                        user.phone_temp = None
                        db.commit()
                        
                        # 回覆文字
                        if bot_customer_api:
                            bot_customer_api.reply_message(
                                event.reply_token,
                                TextSendMessage(text="沒問題，請再次輸入您的 10 碼手機號碼：")
                            )
                
                except Exception:
                    logging.exception("Error handling phone confirmation")
                finally:
                    db.close()

            elif data == "action=select_date":
                selected_dt = params.get("datetime")
                # 回覆選擇服務方案的 ButtonsTemplate
                text = f"您選擇了 {selected_dt}，請選擇服務方案："
                actions = [
                    PostbackTemplateAction(label="90 分鐘", data=f"action=select_plan&plan=90&datetime={selected_dt}"),
                    PostbackTemplateAction(label="120 分鐘", data=f"action=select_plan&plan=120&datetime={selected_dt}"),
                ]
                buttons = ButtonsTemplate(text=text, actions=actions)
                template_message = TemplateSendMessage(alt_text="請選擇服務方案", template=buttons)

                if bot_customer_api:
                    bot_customer_api.reply_message(event.reply_token, template_message)

            # 處理選擇方案後的下一步：選擇師傅
            elif "action=select_plan" in data:
                # 解析 data 中的 plan 與 datetime
                qs = parse_qs(data)
                plan = qs.get("plan", [None])[0]
                selected_dt = qs.get("datetime", [None])[0]

                db = SessionLocal()
                try:
                    online_staff = db.query(Staff).filter(Staff.is_online == True).all()

                    if not online_staff:
                        # 沒有師傅在線上
                        if bot_customer_api:
                            bot_customer_api.reply_message(
                                event.reply_token,
                                TextSendMessage(text="目前正好沒有師傅在線上，請稍後再試或直接聯繫客服協助喔！"),
                            )
                        return

                    # 有師傅在線上，建構 carousel 型態的 Flex Message
                    bubbles = []
                    for s in online_staff:
                        bubble = {
                            "type": "bubble",
                            "body": {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {
                                        "type": "text",
                                        "text": s.name,
                                        "weight": "bold",
                                        "size": "lg",
                                        "color": "#FFFFFF",
                                        "align": "center",
                                    }
                                ],
                                "backgroundColor": "#000000",
                            },
                            "footer": {
                                "type": "box",
                                "layout": "vertical",
                                "contents": [
                                    {
                                        "type": "button",
                                        "style": "primary",
                                        "action": {
                                            "type": "postback",
                                            "label": "預約這位",
                                            "data": f"action=confirm_booking&staff_id={s.id}&plan={plan}&datetime={selected_dt}",
                                        },
                                    }
                                ],
                                "backgroundColor": "#111111",
                            },
                        }
                        bubbles.append(bubble)

                    # 加上一個「不指定師傅」的 bubble
                    none_bubble = {
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "不指定師傅",
                                    "weight": "bold",
                                    "size": "lg",
                                    "color": "#FFFFFF",
                                    "align": "center",
                                }
                            ],
                            "backgroundColor": "#000000",
                        },
                        "footer": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "button",
                                    "style": "primary",
                                    "action": {
                                        "type": "postback",
                                        "label": "預約這位",
                                        "data": f"action=confirm_booking&staff_id=none&plan={plan}&datetime={selected_dt}",
                                    },
                                }
                            ],
                            "backgroundColor": "#111111",
                        },
                    }
                    bubbles.append(none_bubble)

                    flex_contents = {"type": "carousel", "contents": bubbles}
                    flex_message = FlexSendMessage(alt_text="請選擇想預約的師傅", contents=flex_contents)

                    if bot_customer_api:
                        bot_customer_api.reply_message(event.reply_token, flex_message)

                except Exception:
                    logging.exception("Error building staff carousel")
                finally:
                    db.close()

            # 任務三：實作預約完成的動態收據
            elif "action=confirm_booking" in data:
                qs = parse_qs(data)
                staff_id = qs.get("staff_id", [None])[0]
                plan = qs.get("plan", [None])[0]
                selected_dt = qs.get("datetime", [None])[0]

                user_id = getattr(getattr(event, "source", None), "user_id", None)

                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.line_user_id == user_id).first()
                    if not user:
                        logging.error("User not found for booking confirmation")
                        return

                    # 判斷 staff_id 是否為 "none"
                    staff_obj = None
                    staff_name = "未指定"
                    if staff_id != "none":
                        staff_obj = db.query(Staff).filter(Staff.id == int(staff_id)).first()
                        if staff_obj:
                            staff_name = staff_obj.name

                    # 根據 plan 判斷定價
                    plan_int = int(plan)
                    if plan_int == 90:
                        price = 2500
                    elif plan_int == 120:
                        price = 3000
                    else:
                        price = 0

                    discount = 200
                    total = price - discount

                    # 寫入 Appointments 資料庫
                    appointment = Appointment(
                        user_id=user.id,
                        staff_id=int(staff_id) if staff_id != "none" else None,
                        duration=plan_int,
                        start_time=datetime.fromisoformat(selected_dt),
                        end_time=datetime.fromisoformat(selected_dt),
                        status="confirmed"
                    )
                    db.add(appointment)
                    db.commit()
                    db.refresh(appointment)

                    # 取得訂單 id 並格式化 PAYMENT ID
                    order_id = appointment.id
                    payment_id = f"#{datetime.utcnow().strftime('%y%m%d')}{order_id:03d}"

                    # 取得客戶 ID（VIP-{user.id:04d}）
                    customer_vip_id = f"VIP-{user.id:04d}"

                    # 透過 bot_customer_api.get_profile 取得 LINE display_name
                    customer_name = user_id
                    try:
                        profile = bot_customer_api.get_profile(user_id)
                        customer_name = profile.display_name
                    except Exception as e:
                        logging.warning(f"Unable to get customer profile: {e}")

                    # 格式化預約時間
                    try:
                        appointment_time = datetime.fromisoformat(selected_dt)
                        appointment_time_str = appointment_time.strftime("%Y年%m月%d日 %H:%M")
                    except:
                        appointment_time_str = selected_dt

                    # 動態產生預約明細 FlexSendMessage
                    flex_contents = {
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "預約確認",
                                    "weight": "bold",
                                    "color": "#1DB446",
                                    "size": "sm"
                                },
                                {
                                    "type": "text",
                                    "text": staff_name,
                                    "weight": "bold",
                                    "size": "xxl",
                                    "margin": "md"
                                },
                                {
                                    "type": "text",
                                    "text": "師傅簡介(身高體重)",
                                    "size": "xs",
                                    "color": "#aaaaaa",
                                    "wrap": True
                                },
                                {
                                    "type": "separator",
                                    "margin": "xxl"
                                },
                                {
                                    "type": "box",
                                    "layout": "vertical",
                                    "margin": "xxl",
                                    "spacing": "sm",
                                    "contents": [
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "客戶 ID",
                                                    "size": "sm",
                                                    "color": "#555555"
                                                },
                                                {
                                                    "type": "text",
                                                    "text": customer_vip_id,
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        },
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "客戶",
                                                    "size": "sm",
                                                    "color": "#555555"
                                                },
                                                {
                                                    "type": "text",
                                                    "text": customer_name,
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        },
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "時段",
                                                    "size": "sm",
                                                    "color": "#555555",
                                                    "flex": 0
                                                },
                                                {
                                                    "type": "text",
                                                    "text": appointment_time_str,
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        },
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "選擇方案",
                                                    "size": "sm",
                                                    "color": "#555555",
                                                    "flex": 0
                                                },
                                                {
                                                    "type": "text",
                                                    "text": f"{plan} 分鐘",
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        },
                                        {
                                            "type": "separator",
                                            "margin": "xxl"
                                        },
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "margin": "xxl",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "方案定價",
                                                    "size": "sm",
                                                    "color": "#555555"
                                                },
                                                {
                                                    "type": "text",
                                                    "text": f"NT$ {price:,}",
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        },
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "優惠",
                                                    "size": "sm",
                                                    "color": "#555555"
                                                },
                                                {
                                                    "type": "text",
                                                    "text": f"-NT$ {discount:,}",
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        },
                                        {
                                            "type": "box",
                                            "layout": "horizontal",
                                            "contents": [
                                                {
                                                    "type": "text",
                                                    "text": "總計",
                                                    "size": "sm",
                                                    "color": "#555555"
                                                },
                                                {
                                                    "type": "text",
                                                    "text": f"NT$ {total:,}",
                                                    "size": "sm",
                                                    "color": "#111111",
                                                    "align": "end"
                                                }
                                            ]
                                        }
                                    ]
                                },
                                {
                                    "type": "separator",
                                    "margin": "xxl"
                                },
                                {
                                    "type": "box",
                                    "layout": "horizontal",
                                    "margin": "md",
                                    "contents": [
                                        {
                                            "type": "text",
                                            "text": "PAYMENT ID",
                                            "size": "xs",
                                            "color": "#aaaaaa",
                                            "flex": 0
                                        },
                                        {
                                            "type": "text",
                                            "text": payment_id,
                                            "color": "#aaaaaa",
                                            "size": "xs",
                                            "align": "end"
                                        }
                                    ]
                                }
                            ]
                        },
                        "styles": {
                            "footer": {
                                "separator": True
                            }
                        }
                    }

                    flex_message = FlexSendMessage(alt_text="預約確認", contents=flex_contents)
                    if bot_customer_api:
                        bot_customer_api.reply_message(event.reply_token, flex_message)

                except Exception:
                    logging.exception("Error handling booking confirmation")
                finally:
                    db.close()

        except Exception:
            logging.exception("Error handling customer postback")


# --- 員工端：引導建檔與上下線邏輯 ---
if handler_staff:
    @handler_staff.add(MessageEvent, message=TextMessage)
    def handle_staff_message(event):
        user_id = getattr(getattr(event, "source", None), "user_id", None)
        text = getattr(event.message, "text", "").strip()
        reply_text = text

        if user_id:
            db = SessionLocal()
            try:
                staff = db.query(Staff).filter(Staff.line_user_id == user_id).first()
                if not staff:
                    staff = Staff(line_user_id=user_id, name="新進員工")
                    db.add(staff)
                    db.commit()

                # 判斷是否為剛加入的新師傅
                if staff.name == "新進員工":
                    if text == "我是師傅":
                        reply_text = "辛苦了！歡迎加入伊果 SPA 團隊。\\n\\n為了方便店長派單與客人辨識，請直接回覆告訴我您的「姓名」或「稱呼」喔！"
                    else:
                        # 將師傅輸入的第一句話當作姓名存起來
                        staff.name = text
                        db.commit()
                        reply_text = f"設定完成！{text} 師傅您好，您現在可以輸入「上線」來開啟接單模式囉！"
                else:
                    # 任務一：將上下線邏輯註解掉，僅保留建立檔案與普通 Echo
                    # if text == "上線":
                    #     staff.is_online = True
                    #     staff.online_start_time = datetime.utcnow()
                    #     db.commit()
                    #     reply_text = f"【狀態更新】{staff.name} 師傅，已為您切換為上線模式，隨時準備接單！"
                    # elif text == "下線":
                    #     if staff.is_online:
                    #         if staff.online_start_time:
                    #             diff = datetime.utcnow() - staff.online_start_time
                    #             if diff.total_seconds() < 7200:
                    #                 reply_text = "目前上線未滿 2 小時，為確保客人能完整預約，請稍後再切換狀態喔！"
                    #             else:
                    #                 staff.is_online = False
                    #                 staff.online_start_time = None
                    #                 db.commit()
                    #                 reply_text = f"辛苦了 {staff.name} 師傅！已為您切換為下線模式，好好休息。"
                    #         else:
                    #             staff.is_online = False
                    #             db.commit()
                    #             reply_text = f"辛苦了 {staff.name} 師傅！已為您切換為下線模式。"
                    #     else:
                    #         reply_text = "您目前已經是下線狀態囉！"
                    # else:
                    #     reply_text = f"{staff.name} 師傅您好，目前的指令有：「上線」與「下線」。\\n（未來的派單按鈕正在趕工中喔！）"
                    
                    # 普通 Echo
                    reply_text = f"{staff.name} 師傅您好，您說：{text}\\n（上下線功能暫時關閉中...）"

            except Exception:
                logging.exception("Error in staff message handling")
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                db.close()

        try:
            if bot_staff_api and text:
                bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        except Exception:
            logging.exception("Error replying to staff message")

# --- 處理 webhook 的背景工作 ---
def _process_webhook(body: bytes, signature: str, bot_api, handler):
    if not handler:
        logging.warning("No webhook handler configured; skipping processing")
        return
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        logging.warning("Invalid signature for incoming webhook")
    except Exception:
        logging.exception("Exception while handling webhook")

app = FastAPI(title="SPA 智能客服與預約系統")

# 在啟動時自動建立資料表
@app.on_event("startup")
def on_startup():
Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
try:
conn.execute(text("ALTER TABLE users ADD COLUMN phone_temp VARCHAR(50);"))
except Exception:
pass

@app.get("/")
def read_root():
    return {"message": "Hello from SPA FastAPI"}

# Customer webhook: 立即回傳 200，實際處理放到 background task 中
@app.post("/webhook/customer")
async def webhook_customer(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    background_tasks.add_task(_process_webhook, body, signature, bot_customer_api, handler_customer)
    return Response(status_code=200)

# Staff webhook: 立即回傳 200，實際處理放到 background task 中
@app.post("/webhook/staff")
async def webhook_staff(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    background_tasks.add_task(_process_webhook, body, signature, bot_staff_api, handler_staff)
    return Response(status_code=200)
