# Cloudflare Pages 部署設定

這個 repository 內有兩個獨立的 Next.js 靜態網站。請在 Cloudflare 建立兩個 Pages 專案，兩個專案都連到 `nimotherb/linebot` 的 `main` 分支。

## 官網：`equalspa`

- Root directory：`official-website`
- Framework preset：`Next.js (Static HTML Export)`
- Build command：`npm run build`
- Build output directory：`out`
- Node.js version：`22.13.0`
- Environment variable：`NEXT_PUBLIC_API_BASE_URL=https://linebot-3r2w.onrender.com`

## 後台：`equalspa-admin`

- Root directory：`Back office`
- Framework preset：`Next.js (Static HTML Export)`
- Build command：`pnpm run build`
- Build output directory：`out`
- Node.js version：`22.13.0`
- Environment variable：`NEXT_PUBLIC_API_BASE_URL=https://linebot-3r2w.onrender.com`

`Back office/package.json` 已固定 pnpm 版本，Cloudflare 不需要使用 `--no-frozen-lockfile`。如果 lockfile 再次與套件清單不同，CI 會直接失敗並阻止部署。

## Render 後端同步

兩個 Pages 專案部署成功後，在 Render 的 Environment 更新以下值：

```dotenv
ADMIN_ALLOWED_ORIGINS=https://equalspa.pages.dev,https://equalspa-admin.pages.dev
ADMIN_DASHBOARD_URL=https://equalspa-admin.pages.dev/
STAFF_SCHEDULE_BASE_URL=https://equalspa-admin.pages.dev/?staff_token=
BOOKING_WEB_URL=https://equalspa-admin.pages.dev/booking/
```

如果已綁定正式網域，請把正式網域也加入 `ADMIN_ALLOWED_ORIGINS`，各網址之間用逗號分隔且不要加結尾斜線。其餘三個導向網址則改成正式後台網域。

## 自訂網域建議

- 官網：`www.equalspa.com`
- 後台：`ops.equalspa.com`

完成自訂網域後，重新確認 Render 的 CORS 與 LINE Bot 內的後台、排班、預約連結。
