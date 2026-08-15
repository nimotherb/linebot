from fastapi import FastAPI, Request, Response, Depends, BackgroundTasks
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from dotenv import load_dotenv
import os
import logging
from datetime import datetime

# LINE SDK
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 讀取本地 .env（開發時會自動載入；部署到雲端時請在環境設定平台上設定 DATABASE_URL 環境變數）
load_dotenv()

# 範例 DATABASE_URL 格式（MySQL + pymysql）:
# mysql+pymysql://USERNAME:PASSWORD@HOST:PORT/DATABASE_NAME
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

    # relationship to appointments
    appointments = relationship("Appointment", back_populates="user", cascade="all, delete-orphan")


class Staff(Base):
    __tablename__ = "staffs"

    id = Column(Integer, primary_key=True, index=True)
    line_user_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    is_online = Column(Boolean, default=False, nullable=False)
    online_start_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # relationship to appointments
    appointments = relationship("Appointment", back_populates="staff", cascade="all, delete-orphan")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    staff_id = Column(Integer, ForeignKey("staffs.id"), nullable=True)
    duration = Column(Integer, nullable=False)  # 存放 90 或 120（分鐘）
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

# 讀取 LINE 相關環境變數（請在部署平台或 .env 中設定）
LINE_SECRET_CUSTOMER = os.getenv("LINE_SECRET_CUSTOMER")
LINE_TOKEN_CUSTOMER = os.getenv("LINE_TOKEN_CUSTOMER")
LINE_SECRET_STAFF = os.getenv("LINE_SECRET_STAFF")
LINE_TOKEN_STAFF = os.getenv("LINE_TOKEN_STAFF")

# 建立 LineBotApi / WebhookHandler 實例（若未設定會是 None）
bot_customer_api = LineBotApi(LINE_TOKEN_CUSTOMER) if LINE_TOKEN_CUSTOMER else None
handler_customer = WebhookHandler(LINE_SECRET_CUSTOMER) if LINE_SECRET_CUSTOMER else None

bot_staff_api = LineBotApi(LINE_TOKEN_STAFF) if LINE_TOKEN_STAFF else None
handler_staff = WebhookHandler(LINE_SECRET_STAFF) if LINE_SECRET_STAFF else None

# 設定基本 logging
logging.basicConfig(level=logging.INFO)

# 為每個 handler 註冊一個簡單的文字 echo 回覆
if handler_customer:
    @handler_customer.add(MessageEvent, message=TextMessage)
    def handle_customer_message(event):
        try:
            if bot_customer_api and hasattr(event.message, "text"):
                text = event.message.text
                bot_customer_api.reply_message(event.reply_token, TextSendMessage(text=text))
        except Exception:
            logging.exception("Error replying to customer message")

if handler_staff:
    @handler_staff.add(MessageEvent, message=TextMessage)
    def handle_staff_message(event):
        try:
            if bot_staff_api and hasattr(event.message, "text"):
                text = event.message.text
                bot_staff_api.reply_message(event.reply_token, TextSendMessage(text=text))
        except Exception:
            logging.exception("Error replying to staff message")

# 處理 webhook 的背景工作：驗證簽章並交由 handler 處理（若簽章錯誤則紀錄）
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

app = FastAPI(title="FastAPI + MySQL Boilerplate with LINE Webhook")

# 在啟動時自動建立資料表
@app.on_event("startup")
def on_startup():
    # 這會使用上面定義的 Base 與 engine，在 MySQL 中建立 tables（若已存在則不會覆蓋）
    Base.metadata.create_all(bind=engine)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI"}

# 保留原本的 /webhook 路由（僅回傳 200）
@app.post("/webhook")
async def line_webhook(request: Request):
    # 目前僅回傳 HTTP 200 OK 給 LINE 平台作為接收端確認
    # 若需處理訊息，可在這裡讀取 request.json() 或 request.body()
    return Response(status_code=200)

# Customer webhook: 立即回傳 200，實際處理放到 background task 中
@app.post("/webhook/customer")
async def webhook_customer(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    # 立刻回傳 200，並在背景處理簽章驗證與回覆
    background_tasks.add_task(_process_webhook, body, signature, bot_customer_api, handler_customer)
    return Response(status_code=200)

# Staff webhook: 同上，使用 staff 的 token/secret
@app.post("/webhook/staff")
async def webhook_staff(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    background_tasks.add_task(_process_webhook, body, signature, bot_staff_api, handler_staff)
    return Response(status_code=200)
