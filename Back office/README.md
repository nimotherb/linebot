# 伊果 SPA Back Office

獨立的後台管理網頁專案，放在 `linebot` repository 的 `Back office/` 目錄。

## 功能

- 管理帳號登入與角色權限
- 預約、師傅與兩間店內房間撞期檢查
- 本週／下週排班與師傅免登入專屬連結
- 服務方案、優惠、員工、客戶與結帳管理
- 日期區間 CSV 匯出
- FastAPI 管理 API 上線前自動使用安全示範資料

## 開發

```bash
pnpm install
pnpm dev
```

後端預設位置為 `https://linebot-3r2w.onrender.com`，可使用 `NEXT_PUBLIC_API_BASE_URL` 指向其他 FastAPI 服務。

> 不要把 PIN、LINE token、Aiven 密碼或 `.env` 提交到 GitHub。
