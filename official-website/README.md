# 伊果 SPA 官方網站

此資料夾是伊果 SPA 的公開官網，與根目錄的 LINE Bot／FastAPI 後端及 `Back office/` 管理後台互相獨立。

## 頁面

- `/`：桌機動態標準字首頁；手機版循環式一頁瀏覽
- `/about`：關於伊果
- `/services`：服務與價目
- `/therapists`：師傅分類
- `/offers`：優惠預覽
- `/location`：交通與店鋪資訊
- `/recruit`：人才招募（聯絡信箱暫時留空）
- `/groups`、`/loyalty`：內容更新中
- `/privacy`：隱私權說明
- `/site-admin`：店長／Admin 使用的官網內容管理前端（本機草稿、即時預覽與 JSON 匯出）

## 官網內容管理

`/site-admin` 目前會把草稿保存在使用者自己的瀏覽器，不會直接更動所有訪客看到的正式官網。若設定 `NEXT_PUBLIC_API_URL`，發布按鈕會以營運後台登入取得的 `equalspa_admin_token` 呼叫 `PUT /api/site-content`；後端必須再次驗證店長或 Admin 權限，才可寫入正式內容。

圖片上傳尚未開放；接上後端檔案 API 前，師傅照片仍由 `public/images/therapists/` 管理。

## 待補素材

師傅頁的公開照片已依照來源 PDF 匯入 `public/images/therapists/`，並以 CSS 統一成相同的輪播與商品卡比例。日後替換照片時請沿用原檔名，建議直式 4:5，且應先確認公開使用同意。

健康資訊僅限內部後台，不可放入公開網站、公開圖片檔名或圖片替代文字。

交通頁使用店家提供的 Google My Maps 嵌入地圖。

## 本機執行

```bash
npm install
npm run dev
```

正式建置：

```bash
npm run build
```
