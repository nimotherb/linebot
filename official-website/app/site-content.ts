// official-website/app/site-content.ts

// 這是你的 Render 後端網址
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com';

/**
 * 取得正式發布的官網內容
 * 搭配 Next.js 的 ISR 快取機制，每 60 秒會在背景更新一次，
 * 這樣既能保持網頁秒開，又不會頻繁消耗資料庫效能。
 */
export async function getPublicSiteContent() {
  try {
    const res = await fetch(`${API_BASE_URL}/api/public/site-content`, {
      next: { revalidate: 60 } 
    });
    
    if (!res.ok) {
      throw new Error(`API 請求失敗: ${res.status}`);
    }
    
    const data = await res.json();
    // data 裡面會包著 content (正式版 JSON), version (版本號), published_at (發布時間)
    return data.content || null; 
  } catch (error) {
    console.error("無法取得官網內容:", error);
    // 萬一後端臨時維修，可以回傳 null，讓前端顯示預設的寫死內容
    return null; 
  }
}
