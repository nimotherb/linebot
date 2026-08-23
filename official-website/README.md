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

## 待補素材

師傅頁目前使用刻意設計的抽象佔位圖。請在取得公開使用同意後，將照片放入 `public/images/therapists/`，建議使用直式 4:5 圖片，再搜尋程式碼中的 `TODO_IMAGE` 進行替換。

健康資訊僅限內部後台，不可放入公開網站、公開圖片檔名或圖片替代文字。

地圖目前使用圖像化示意；搜尋 `TODO_MAP` 可找到日後替換位置。

## 本機執行

```bash
npm install
npm run dev
```

正式建置：

```bash
npm run build
```
