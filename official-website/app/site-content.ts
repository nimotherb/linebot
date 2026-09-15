// official-website/app/site-content.ts

// 這是你的 Render 後端網址
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com';

/**
 * 取得正式發布的官網內容。正式網站不以舊模板或假資料作為 fallback。
 */
export async function getPublicSiteContent() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/public/site-content`, { cache: 'no-store' });
    
    if (!res.ok) {
      throw new Error(`API 請求失敗: ${res.status}`);
    }
    
    const data = await res.json();
    // data 裡面會包著 content (正式版 JSON), version (版本號), published_at (發布時間)
    return data.content || null; 
  } catch (error) {
    console.error("無法取得官網內容:", error);
    // API 失敗交由呼叫端顯示安全空狀態；不得回傳過期模板內容。
    return null; 
  }
}
