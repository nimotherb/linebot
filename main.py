from fastapi import FastAPI, Request, Response, Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from dotenv import load_dotenv
import os

# 讀取本地 .env（開發時會自動載入；部署到雲端時請在環境設定平台上設定 DATABASE_URL 環境變數）
load_dotenv()

# 範例 DATABASE_URL 格式（MySQL + pymysql）:
# mysql+pymysql://USERNAME:PASSWORD@HOST:PORT/DATABASE_NAME
DATABASE_URL = os.getenv("mysql://avnadmin:AVNS_3ETxOMehnck20Qjisx4@mysql-2f37be3e-nimotherb-cd46.i.aivencloud.com:13049/defaultdb?ssl-mode=REQUIRED")
if not DATABASE_URL:
    raise RuntimeError("環境變數 DATABASE_URL 未設定，請設定為 mysql+pymysql://user:pass@host:port/dbname")

# 建立 SQLAlchemy engine 與 Session 工廠
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# DB session dependency
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="FastAPI + MySQL Boilerplate")

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI"}

@app.post("/webhook")
async def line_webhook(request: Request):
    # 目前僅回傳 HTTP 200 OK 給 LINE 平台作為接收端確認
    # 若需處理訊息，可在這裡讀取 request.json() 或 request.body()
    return Response(status_code=200)
