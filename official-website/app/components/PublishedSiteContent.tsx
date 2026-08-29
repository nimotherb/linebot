'use client';

import { useEffect, useMemo, useState } from 'react';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');

export type PublishedService = { id?: number; code: string; name: string; summary: string; duration: string; price: string; visible: boolean };
export type PublishedOffer = { id?: number; name: string; summary: string; status: '顯示中' | '草稿' };
export type PublishedSiteDraft = {
  home?: { subtitle?: string; support?: string };
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
        if (active) setContent({});
      });
    return () => { active = false; };
  }, []);

  return content;
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
  const bookingUrl = content?.booking?.url || fallbackBookingUrl;
  const plans = useMemo(() => {
    if (!content || !Array.isArray(content.services)) return fallbackPlans;
    return content.services.filter((item) => item.visible).map((item) => {
      const detail = fallbackPlans.find((plan) => plan.code === item.code);
      return {
        code: item.code,
        name: item.name,
        english: detail?.english || 'PERSONALIZED RESET',
        duration: item.duration,
        price: item.price,
        summary: item.summary,
        tags: detail?.tags || ['預約制', '依需求安排', '客服確認'],
        lead: detail?.lead || `${item.duration} 的服務會由客服與師傅依照你的需求安排。`,
        paragraphs: detail?.paragraphs || [item.summary || '預約時可先告訴客服希望加強的部位、偏好的力道與服務節奏，現場再由師傅確認細節。'],
      };
    });
  }, [content, fallbackPlans]);

  return <>
    <div className="service-overview"><small>{plans.length} WAYS TO RESET</small><p>所有方案皆可於每日 10:00—24:00 洽詢預約。實際流程會由師傅依身體回饋微調。</p></div>
    <div className="service-journeys">{plans.map((plan, index) => <article key={plan.code} className="service-journey">
      <header><span className="service-index">{String(index + 1).padStart(2, '0')}</span><i>{plan.code}</i><div><small>{plan.english}</small><h2>{plan.name}</h2></div><div className="service-quick-info"><small>{plan.summary}</small><p>{plan.duration}</p></div><strong>{plan.price}</strong></header>
      <div className="service-journey-body"><h3>{plan.lead}</h3><div className="service-prose">{plan.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</div><ul>{plan.tags.map((tag) => <li key={tag}>{tag}</li>)}</ul><a href={bookingUrl} target="_blank" rel="noreferrer">SELECT THIS PLAN ↗</a></div>
    </article>)}</div>
    {plans.length === 0 && <div className="updating-card"><span>SERVICES</span><h2>內容更新中</h2><p>方案正在整理，請先透過 LINE 客服詢問。</p></div>}
    <div className="service-notes"><h2>BOOKING NOTES</h2><dl><div><dt>午夜加成</dt><dd>00:00—06:00 · NT$ 600</dd></div><div><dt>預約時加時</dt><dd>每 30 分鐘 NT$ 500</dd></div><div><dt>現場加時</dt><dd>每 30 分鐘 NT$ 700</dd></div><div><dt>外出交通</dt><dd>超過 3 公里，每公里 NT$ 80</dd></div></dl><p>客服值班時間為每日 10:00—24:00；其他時段的服務請在客服值班時間內提前完成預約。方案、師傅與優惠可能調整，最終內容以 LINE 客服確認為準。</p></div>
  </>;
}

const fallbackOffers: PublishedOffer[] = [
  { name: '生日月優惠', summary: '在生日月替自己留一段完整的休息時間。', status: '顯示中' },
  { name: '新進師傅體驗', summary: '認識不同手法與服務節奏，找到更適合自己的選擇。', status: '顯示中' },
  { name: '平日時段精選', summary: '避開繁忙時段，享受更安靜從容的體驗。', status: '顯示中' },
];

export function PublishedOffers({ fallbackBookingUrl }: { fallbackBookingUrl: string }) {
  const content = usePublishedSiteDraft();
  const bookingUrl = content?.booking?.url || fallbackBookingUrl;
  const offers = content && Array.isArray(content.offers) ? content.offers.filter((item) => item.status === '顯示中') : fallbackOffers;

  if (offers.length === 0) return <div className="updating-card"><span>OFFERS</span><h2>內容更新中</h2><p>目前優惠正在整理，最新內容可向 LINE 客服確認。</p><a href={bookingUrl} target="_blank" rel="noreferrer">前往線上預約 ↗</a></div>;

  return <div className="offer-grid">{offers.map((offer, index) => <article key={offer.id || `${offer.name}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><small>CURRENT OFFER</small><h2>{offer.name}</h2><p>{offer.summary}</p><em>顯示中</em><a href={bookingUrl} target="_blank" rel="noreferrer">查看可預約時段 ↗</a></article>)}</div>;
}
