# 伊果 SPA：LINE Bot 與管理後台 API

這個 FastAPI 服務同時提供：

- 客戶與師傅 LINE webhook
- 管理後台登入、預約、排班、員工、方案、優惠、場地與結帳 API
- 公開唯讀、師傅免密碼、客服、店長與 Admin 分層權限
- 可調整的師傅回帳表、現金回帳確認與優惠 Flex 選單
- MySQL 永久資料，以及日期區間 CSV 匯出

## 本機啟動

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

請先在 `.env` 填入測試用環境變數；不要將 `.env` 或任何 Aiven／LINE 密鑰提交到 Git。

## Render 第一次部署

沿用既有的 `DATABASE_URL` 與四個 LINE 變數，再依照 [.env.example](./.env.example) 增加：

- `ADMIN_INITIAL_PIN`、`MANAGER_INITIAL_PIN`：只在第一次建立帳號時需要。登入確認後可從 Render 移除。
- `ADMIN_ALLOWED_ORIGINS`：管理後台網址與本機網址，逗號分隔。
- `ADMIN_DASHBOARD_URL`：LINE Bot 傳送的後台／排班網址。
- `STAFF_HEALTH_ENCRYPTION_KEY`：Fernet 金鑰。請另外安全備份，遺失後無法解密私密健康資料。
- `STAFF_SCHEDULE_BASE_URL`：師傅班表連結的網址前綴。
- `DATABASE_HEARTBEAT_SECONDS`：Aiven 心跳間隔；建議保留預設 720 秒（12 分鐘）。
- `CUSTOMER_SERVICE_URL`：Flex 選單失敗時顯示給客戶的真人客服連結。
- `RENDER_LOGS_URL`：管理員錯誤備援訊息中的系統紀錄連結。

Fernet 金鑰可在本機產生：

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

服務啟動時會建立缺少的資料表、兩間店內房間和初始方案。現有舊訂單若 `end_time` 沒有正確計算，也會依 `duration` 自動修復。正式部署前仍建議先在 Aiven 建立手動備份。

## 重要規則

- 預約結束時間永遠由方案分鐘數計算。
- 所有預約入口都必須至少提前 90 分鐘；09:00 最早可預約 10:30。
- 同一師傅或同一店內房間的時段不可重疊；相鄰時段可以。
- 師傅班表最少 2 小時。
- 距離開班 90 分鐘內（含剛好 90 分鐘），師傅不能自行新增或撤銷；店長／Admin 可填原因強制處理。
- `師傅在線` 已停用，是否能安排服務由正式班表與預約決定。
- 健康資料只允許 Admin 讀寫，並在 MySQL 中以加密內容保存。
- 刪除師傅採「暫時退役」，不會破壞歷史訂單。
- LINE 管理員必須先輸入 `root`，再輸入對應後台 PIN 才會綁定；管理選單可登出並解除綁定。
- LINE 客戶先看簡易確認 Flex，按下確認才寫入訂單；正式建立後再回傳完整訂單 Flex。
- 客戶名稱與 `VIP-xxxx` 流水分開；手機號碼是可編輯的客戶 ID，同一客戶可保存多支手機。
- 公開 API 會遮罩客戶、電話、備註、付款、回帳與營收；師傅工作階段只回傳自己的班表與訂單。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

目前測試包含登入權限、兩間房初始化、預約結束時間、師傅／房間撞期、店長新增帳號限制，以及 2 小時／90 分鐘排班規則。

API 文件在服務啟動後可由 `/docs` 查看；例如本機為 `http://127.0.0.1:8000/docs`。
