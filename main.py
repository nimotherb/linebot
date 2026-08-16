from fastapi import FastAPI, Request, Response, Depends, BackgroundTasks
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
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

        # 如果使用者輸入「預約」，回傳 ButtonsTemplate 並使用 DatetimePicker
        if text == "預約":
            try:
                if bot_customer_api:
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
                    bot_customer_api.reply_message(event.reply_token, template_message)
            except Exception:
                logging.exception("Error replying with datetime picker")
            return

        if user_id:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.line_user_id == user_id).first()
                if not user:
                    user = User(line_user_id=user_id)
                    db.add(user)
                    db.commit()

                # 如果客人的手機號碼還是空的，啟動引導建檔模式
                if not user.phone:
                    if re.match(r"^09\\d{8}$", text):
                        user.phone = text
                        db.commit()
                        reply_text = f"太棒了！您的手機號碼 {text} 已綁定成功，隨時可以開始預約囉 🌿"
                    else:
                        reply_text = "哈囉！歡迎來到伊果 SPA 🌿 很高興為您服務。\\n\\n為了能幫您保留專屬的預約紀錄，可以先偷偷告訴我您的手機號碼嗎��[...]"
                else:
                    # 建檔完成後的預設回覆（未來可改成呼叫選單）
                    reply_text = f"收到您的訊息：{text}\\n（專屬預約選單正在努力建置中，敬請期待！）"

            except Exception:
                logging.exception("Error in customer message handling")
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                db.close()

        try:
            if bot_customer_api and text:
                bot_customer_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        except Exception:
            logging.exception("Error replying to customer message")

    @handler_customer.add(PostbackEvent)
    def handle_customer_postback(event):
        # 取得 postback 的 data 與 params
        data = getattr(getattr(event, "postback", None), "data", "")
        params = getattr(getattr(event, "postback", None), "params", None) or {}

        try:
            if data == "action=select_date":
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
                    # 已經建檔完成的師傅，進入上下線判斷模式
                    if text == "上線":
                        staff.is_online = True
                        staff.online_start_time = datetime.utcnow()
                        db.commit()
                        reply_text = f"【狀態更新】{staff.name} 師傅，已為您切換為上線模式，隨時準備接單！"
                    elif text == "下線":
                        if staff.is_online:
                            if staff.online_start_time:
                                diff = datetime.utcnow() - staff.online_start_time
                                if diff.total_seconds() < 7200:
                                    reply_text = "目前上線未滿 2 小時，為確保客人能完整預約，請稍後再切換狀態喔！"
                                else:
                                    staff.is_online = False
                                    staff.online_start_time = None
                                    db.commit()
                                    reply_text = f"辛苦了 {staff.name} 師傅！已為您切換為下線模式，好好休息。"
                            else:
                                staff.is_online = False
                                db.commit()
                                reply_text = f"辛苦了 {staff.name} 師傅！已為您切換為下線模式。"
                        else:
                            reply_text = "您目前已經是下線狀態囉！"
                    else:
                        reply_text = f"{staff.name} 師傅您好，目前的指令有：「上線」與「下線」。\\n（未來的派單按鈕正在趕工中喔！）"

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
