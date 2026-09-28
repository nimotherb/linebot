// official-website/app/site-content.ts

// 這是你的 Render 後端網址
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com';

export type PublicSiteContentResponse<T = Record<string, unknown>> = {
  content: T;
  version: number;
  published_at?: string | null;
};

let lastPublishedResponse: PublicSiteContentResponse | undefined;

/**
 * 取得正式發布的官網內容。正式網站不以舊模板或假資料作為 fallback。
 */
export async function getPublicSiteContent(): Promise<PublicSiteContentResponse | null> {
  try {
    const res = await fetch(`${API_BASE_URL.replace(/\/$/, '')}/api/public/site-content`, { cache: 'no-store' });
    if (!res.ok) {
      throw new Error(`API 請求失敗: ${res.status}`);
    }
    const data = await res.json() as PublicSiteContentResponse;
    lastPublishedResponse = { content: data.content || {}, version: data.version || 0, published_at: data.published_at || null };
    return lastPublishedResponse;
  } catch (error) {
    void error;
    // Revalidation failures keep the last successful published response only.
    return lastPublishedResponse || null;
  }
}
