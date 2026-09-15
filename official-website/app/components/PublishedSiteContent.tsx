'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');

export type PublishedService = { id?: number; code: string; name: string; summary: string; duration: string; price: string; visible: boolean };
export type PublishedOffer = { id?: number; name: string; summary: string; status: '顯示中' | '草稿' };
export type PublishedNavigationItem = { id: string; slug: string; label: string; english: string; desktopVisible?: boolean; mobileVisible?: boolean };
export type PublishedPageCard = { number?: string; label?: string; title?: string; body?: string };
export type PublishedPage = { english?: string; title?: string; intro?: string; body?: string; cards?: PublishedPageCard[]; cardGridEnabled?: boolean; desktopVisible?: boolean; mobileVisible?: boolean };
export type PublishedSiteDraft = {
  navigation?: PublishedNavigationItem[];
  pages?: Record<string, PublishedPage>;
  home?: { subtitle?: string; support?: string; heroFontSize?: number };
  booking?: { lineId?: string; url?: string };
  services?: PublishedService[];
  therapists?: {
    intro?: string;
    straightIntro?: string;
    communityIntro?: string;
    bisexualIntro?: string;
    carouselSpeed?: number;
    showMeasurements?: boolean;
  };
  offers?: PublishedOffer[];
  store?: { address?: string; hours?: string; payment?: string; mapUrl?: string };
};

export function usePublishedSiteDraft() {
  const [content, setContent] = useState<PublishedSiteDraft | undefined>();

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE_URL}/api/public/site-content`, { cache: 'no-store' })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('site content unavailable')))
      .then((payload: { content?: PublishedSiteDraft }) => {
        if (active) setContent(payload.content || {});
      })
      .catch(() => {
        // Never fall back to stale template content when the published API is unavailable.
        if (active) setContent(undefined);
      });
    return () => { active = false; };
  }, []);

  return content;
}

export function PublishedPageHeader({ slug, fallbackTitle, fallbackIntro }: { slug: string; fallbackTitle: string; fallbackIntro: string }) {
  const content = usePublishedSiteDraft();
  const page = content?.pages?.[slug];
  void fallbackTitle;
  void fallbackIntro;
  return <div><h2>{page?.title || (content ? '內容更新中' : '正在讀取官網內容')}</h2>{page?.intro && <span>{page.intro}</span>}</div>;
}

export function PublishedPageTitle({ slug, fallback }: { slug: string; fallback: string }) {
  const content = usePublishedSiteDraft();
  void fallback;
  return <h1>{content?.pages?.[slug]?.english || 'PUBLISHED CONTENT'}</h1>;
}

export function PublishedPageBody({ slug, children }: { slug: string; children: ReactNode }) {
  const content = usePublishedSiteDraft();
  const body = content?.pages?.[slug]?.body?.trim();
  void children;
  if (!content) return <div className="updating-card"><span>OFFICIAL SITE</span><h2>內容暫時無法取得</h2><p>請稍後重新整理，最新發布內容只從官方資料庫載入。</p></div>;
  if (!body) return <div className="updating-card"><span>OFFICIAL SITE</span><h2>內容更新中</h2><p>目前尚未發布此頁面的內容。</p></div>;
  return <div className="published-page-copy">{body.split(/\n\s*\n/).filter(Boolean).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</div>;
}

// Compatibility exports for existing page imports. Published content is the only source;
// these arrays intentionally contain no template or fake records.
export const fallbackAboutCards: PublishedPageCard[] = [];
export const fallbackRecruitCards: PublishedPageCard[] = [];
export const fallbackOfferCards: PublishedPageCard[] = [];

export function PublishedCardGrid({ slug, fallbackCards, onlyWhenEnabled = false }: { slug: string; fallbackCards: readonly PublishedPageCard[]; onlyWhenEnabled?: boolean }) {
  const content = usePublishedSiteDraft();
  const page = content?.pages?.[slug];
  void fallbackCards;
  if (!content) return <div className="updating-card"><span>OFFICIAL SITE</span><h2>內容暫時無法取得</h2><p>請稍後重新整理，最新發布內容只從官方資料庫載入。</p></div>;
  if (onlyWhenEnabled && page?.cardGridEnabled !== true) return null;
  if (page && page.cardGridEnabled === false) return null;
  const cards = Array.isArray(page?.cards) ? page.cards : [];
  if (!cards.length) return null;
  const count = cards.length === 1 ? 'single' : cards.length === 3 ? 'triple' : 'multiple';
  return <div className={`value-grid value-grid--${count}`} data-card-count={cards.length}>{cards.map((card, index) => <article key={`${card.number || index}-${card.title || index}`}><span>{card.number || String(index + 1).padStart(2, '0')}</span><small>{card.label || 'CARD'}</small><h2>{card.title || 'Untitled card'}</h2><p>{card.body || ''}</p></article>)}</div>;
}

type ServicePlanView = {
  code: string;
  name: string;
  english: string;
  duration: string;
  price: string;
  summary: string;
  tags: readonly string[];
  lead: string;
  paragraphs: readonly string[];
};

export function PublishedServices({ fallbackPlans, fallbackBookingUrl }: { fallbackPlans: readonly ServicePlanView[]; fallbackBookingUrl: string }) {
  const content = usePublishedSiteDraft();
  void fallbackPlans;
  void fallbackBookingUrl;
  const bookingUrl = content?.booking?.url || '';
  const plans = useMemo(() => {
    if (!content || !Array.isArray(content.services)) return [];
    return content.services.filter((item) => item.visible).map((item) => {
      return {
        code: item.code,
        name: item.name,
        english: item.code,
        duration: item.duration,
        price: item.price,
        summary: item.summary,
        tags: [] as string[],
        lead: item.summary,
        paragraphs: item.summary ? [item.summary] : [],
      };
    });
  }, [content]);

  if (!content) return <div className="updating-card"><span>SERVICES</span><h2>內容暫時無法取得</h2><p>請稍後重新整理，最新方案只從官方資料庫載入。</p></div>;

  return <>
    <div className="service-overview"><small>{plans.length} PUBLISHED SERVICES</small></div>
    <div className="service-journeys">{plans.map((plan, index) => <article key={plan.code} className="service-journey">
      <header><span className="service-index">{String(index + 1).padStart(2, '0')}</span><i>{plan.code}</i><div><small>{plan.english}</small><h2>{plan.name}</h2></div><div className="service-quick-info"><small>{plan.summary}</small><p>{plan.duration}</p></div><strong>{plan.price}</strong></header>
      <div className="service-journey-body"><h3>{plan.lead || '方案內容請洽客服確認。'}</h3><div className="service-prose">{plan.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</div>{plan.tags.length > 0 && <ul>{plan.tags.map((tag) => <li key={tag}>{tag}</li>)}</ul>}{bookingUrl && <a href={bookingUrl} target="_blank" rel="noreferrer">SELECT THIS PLAN ↗</a>}</div>
    </article>)}</div>
    {plans.length === 0 && <div className="updating-card"><span>SERVICES</span><h2>內容更新中</h2><p>方案正在整理，請先透過 LINE 客服詢問。</p></div>}
  </>;
}

export function PublishedOffers({ fallbackBookingUrl }: { fallbackBookingUrl: string }) {
  const content = usePublishedSiteDraft();
  void fallbackBookingUrl;
  const bookingUrl = content?.booking?.url || '';
  if (!content) return <div className="updating-card"><span>OFFERS</span><h2>內容暫時無法取得</h2><p>請稍後重新整理，最新優惠只從官方資料庫載入。</p></div>;
  if (content?.pages?.offers?.cardGridEnabled === true) return <PublishedCardGrid slug="offers" fallbackCards={fallbackOfferCards} onlyWhenEnabled />;
  const offers = Array.isArray(content.offers) ? content.offers.filter((item) => item.status === '顯示中') : [];

  if (offers.length === 0) return <div className="updating-card"><span>OFFERS</span><h2>內容更新中</h2><p>目前優惠正在整理，最新內容可向 LINE 客服確認。</p><a href={bookingUrl} target="_blank" rel="noreferrer">前往線上預約 ↗</a></div>;

  return <div className="offer-grid">{offers.map((offer, index) => <article key={offer.id || `${offer.name}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><small>CURRENT OFFER</small><h2>{offer.name}</h2><p>{offer.summary}</p><em>顯示中</em>{bookingUrl && <a href={bookingUrl} target="_blank" rel="noreferrer">查看可預約時段 ↗</a>}</article>)}</div>;
}

