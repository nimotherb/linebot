'use client';

import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');

export type PublishedService = {
  id?: number;
  code: string;
  name: string;
  quick_info: string;
  duration: string;
  price: string;
  visible: boolean;
};
export type PublishedOffer = { id?: number; name: string; summary?: string };
export type PublishedNavigationItem = { id: string; slug: string; label: string; english: string; desktopVisible?: boolean; mobileVisible?: boolean };
export type PublishedPageCard = { id?: string; number?: string; label?: string; title?: string; body?: string; image?: string; link?: string };
export type PublishedPageBlock = { id: string; block_type: string; sort_order: number; enabled: boolean; content: Record<string, unknown>; style?: Record<string, unknown>; responsive?: Record<string, unknown> };
export type PublishedPage = { english?: string; title?: string; intro?: string; body?: string; cards?: PublishedPageCard[]; blocks?: PublishedPageBlock[]; cardGridEnabled?: boolean; desktopVisible?: boolean; mobileVisible?: boolean };
export type PublishedSiteDraft = {
  navigation?: PublishedNavigationItem[];
  pages?: Record<string, PublishedPage>;
  home?: { subtitle?: string; support?: string; heroFontSize?: number };
  booking?: { lineId?: string; url?: string };
  services?: PublishedService[];
  therapists?: { intro?: string; straightIntro?: string; communityIntro?: string; bisexualIntro?: string; carouselSpeed?: number; showMeasurements?: boolean };
  offers?: PublishedOffer[];
  store?: { address?: string; hours?: string; payment?: string; mapUrl?: string };
};

export type PublishedSiteState = { content?: PublishedSiteDraft; syncing: boolean; hasSnapshot: boolean };

// This is the last successful published response for the current page session.
// It is not an editor draft, localStorage value, or hard-coded site template.
let lastPublishedSnapshot: PublishedSiteDraft | undefined;

export function usePublishedSiteState(): PublishedSiteState {
  const [content, setContent] = useState<PublishedSiteDraft | undefined>(lastPublishedSnapshot);
  const [syncing, setSyncing] = useState(true);
  useEffect(() => {
    let active = true;
    setSyncing(true);
    fetch(`${API_BASE_URL}/api/public/site-content`, { cache: 'no-store' })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('published content unavailable')))
      .then((payload: { content?: PublishedSiteDraft }) => {
        if (!active) return;
        const next = payload.content && typeof payload.content === 'object' ? payload.content : {};
        lastPublishedSnapshot = next;
        setContent(next);
        setSyncing(false);
      })
      .catch(() => {
        if (!active) return;
        setContent(lastPublishedSnapshot);
        setSyncing(false);
      });
    return () => { active = false; };
  }, []);
  return { content, syncing, hasSnapshot: Boolean(content) };
}

export function usePublishedSiteDraft() { return usePublishedSiteState().content; }

export function ContentSyncIndicator({ syncing }: { syncing: boolean }) {
  return syncing ? <span className="content-sync-indicator" aria-live="polite"><i className="content-sync-spinner" aria-hidden="true" />內容同步中</span> : null;
}

function EmptyPublishedContent({ syncing = false }: { syncing?: boolean }) {
  return <div className="content-empty-state" aria-label="尚無已發布內容"><ContentSyncIndicator syncing={syncing} /></div>;
}

export function PublishedPageHeader({ slug, fallbackTitle, fallbackIntro }: { slug: string; fallbackTitle: string; fallbackIntro: string }) {
  const { content, syncing } = usePublishedSiteState();
  const page = content?.pages?.[slug];
  void fallbackTitle;
  void fallbackIntro;
  if (!page) return <div><ContentSyncIndicator syncing={syncing} /></div>;
  return <div><h2>{page.title || ''}</h2>{page.intro && <span>{page.intro}</span>}<ContentSyncIndicator syncing={syncing} /></div>;
}

export function PublishedPageTitle({ slug, fallback }: { slug: string; fallback: string }) {
  const content = usePublishedSiteDraft();
  void fallback;
  return <h1>{content?.pages?.[slug]?.english || ''}</h1>;
}

export function PublishedPageBody({ slug, children }: { slug: string; children: ReactNode }) {
  const { content, syncing } = usePublishedSiteState();
  const body = content?.pages?.[slug]?.body?.trim();
  void children;
  if (!content || !body) return <EmptyPublishedContent syncing={syncing} />;
  return <div className="published-page-copy">{body.split(/\n\s*\n/).filter(Boolean).map((paragraph) => <p key={paragraph}>{paragraph}</p>)}<ContentSyncIndicator syncing={syncing} /></div>;
}

export const fallbackAboutCards: PublishedPageCard[] = [];
export const fallbackRecruitCards: PublishedPageCard[] = [];
export const fallbackOfferCards: PublishedPageCard[] = [];

function recordCards(value: unknown): PublishedPageCard[] {
  if (!Array.isArray(value)) return [];
  return value.filter((card): card is Record<string, unknown> => Boolean(card && typeof card === 'object')).map((card) => ({
    id: typeof card.id === 'string' ? card.id : undefined,
    label: typeof card.label === 'string' ? card.label : undefined,
    number: typeof card.number === 'string' ? card.number : undefined,
    title: typeof card.title === 'string' ? card.title : undefined,
    body: typeof card.body === 'string' ? card.body : undefined,
    image: typeof card.image === 'string' ? card.image : (typeof card.image_url === 'string' ? card.image_url : undefined),
    link: typeof card.link === 'string' ? card.link : undefined,
  }));
}

function cardGridBlock(page: PublishedPage | undefined): PublishedPageBlock | undefined {
  const block = page?.blocks?.filter((item) => item.block_type === 'card_grid').sort((a, b) => a.sort_order - b.sort_order).find((item) => item.enabled !== false);
  if (block) return block;
  if (page?.cardGridEnabled === true && Array.isArray(page.cards)) return { id: 'legacy-card-grid', block_type: 'card_grid', sort_order: 0, enabled: true, content: { cards: page.cards } };
  return undefined;
}

function safeUrl(value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return '';
  const candidate = value.trim();
  if (candidate.startsWith('/')) return candidate;
  try {
    const url = new URL(candidate);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : '';
  } catch { return ''; }
}

export function PublishedCardGrid({ slug, fallbackCards, onlyWhenEnabled = false }: { slug: string; fallbackCards?: readonly PublishedPageCard[]; onlyWhenEnabled?: boolean }) {
  const { content, syncing } = usePublishedSiteState();
  void fallbackCards;
  const block = cardGridBlock(content?.pages?.[slug]);
  if (onlyWhenEnabled && !block) return null;
  if (!block) return <EmptyPublishedContent syncing={syncing} />;
  const cards = recordCards(block.content.cards);
  if (!cards.length) return <EmptyPublishedContent syncing={syncing} />;
  const style = block.style || {};
  const responsive = block.responsive || {};
  const columns = Number(style.columns || responsive.desktop_columns || 3);
  const gap = Number(style.gap || responsive.gap || 20);
  const mobileColumns = Number(responsive.mobile_columns || 1);
  const wrapperStyle = { '--card-columns': String(Number.isFinite(columns) && columns > 0 ? Math.min(columns, 6) : 3), '--mobile-columns': String(Number.isFinite(mobileColumns) && mobileColumns > 0 ? Math.min(mobileColumns, 3) : 1), '--card-gap': `${Number.isFinite(gap) && gap >= 0 ? gap : 20}px` } as CSSProperties;
  const title = typeof block.content.title === 'string' ? block.content.title : '';
  const description = typeof block.content.description === 'string' ? block.content.description : '';
  return <section className="published-card-grid-module" data-desktop-visible={responsive.desktop_visible !== false} data-mobile-visible={responsive.mobile_visible !== false} style={wrapperStyle}>
    {(title || description) && <header>{title && <h2>{title}</h2>}{description && <p>{description}</p>}</header>}
    <div className="value-grid" data-card-count={cards.length}>{cards.map((card, index) => {
      const image = safeUrl(card.image);
      const href = safeUrl(card.link);
      const inner = <>{image && <img src={image} alt="" loading="lazy" />}{(card.label || card.number) && <small>{card.label || card.number}</small>}{card.title && <h2>{card.title}</h2>}{card.body && <p>{card.body}</p>}</>;
      return <article key={card.id || `${card.title || 'card'}-${index}`}>{href ? <a href={href}>{inner}</a> : inner}</article>;
    })}</div>
    <ContentSyncIndicator syncing={syncing} />
  </section>;
}

type ServicePlanView = { code: string; name: string; english: string; duration: string; price: string; quick_info: string; tags: readonly string[] };
type PublishedBlockRenderer = (block: PublishedPageBlock, context: { bookingUrl: string }) => ReactNode;

export const publishedBlockRegistry: Record<string, PublishedBlockRenderer> = {
  service_plan: (block, { bookingUrl }) => {
    const plan = block.content as unknown as ServicePlanView;
    return <article key={block.id} className="service-journey"><header><span className="service-index">{String(block.sort_order + 1).padStart(2, '0')}</span><i>{plan.code}</i><div><small>{plan.english}</small><h2>{plan.name}</h2></div><div className="service-quick-info"><small>{plan.quick_info}</small><p>{plan.duration}</p></div><strong>{plan.price}</strong></header><div className="service-journey-body">{plan.tags.length > 0 && <ul>{plan.tags.map((tag) => <li key={tag}>{tag}</li>)}</ul>}{bookingUrl && <a href={bookingUrl} target="_blank" rel="noreferrer">SELECT THIS PLAN ↗</a>}</div></article>;
  },
};

function renderPublishedBlock(block: PublishedPageBlock, context: { bookingUrl: string }) {
  if (!block.enabled) return null;
  const renderer = publishedBlockRegistry[block.block_type];
  return renderer ? renderer(block, context) : <div className="content-empty-state" data-block-type={block.block_type}><ContentSyncIndicator syncing={false} /></div>;
}

export function PublishedServices({ fallbackPlans, fallbackBookingUrl }: { fallbackPlans: readonly ServicePlanView[]; fallbackBookingUrl: string }) {
  const { content, syncing } = usePublishedSiteState();
  void fallbackPlans;
  void fallbackBookingUrl;
  const bookingUrl = content?.booking?.url || '';
  const plans = useMemo(() => (content && Array.isArray(content.services) ? content.services.filter((item) => item.visible).map((item) => ({ code: item.code, name: item.name, english: item.code, duration: item.duration, price: item.price, quick_info: item.quick_info, tags: [] as string[] })) : []), [content]);
  if (!content) return <EmptyPublishedContent syncing={syncing} />;
  return <><div className="service-journeys">{plans.map((plan, index) => renderPublishedBlock({ id: plan.code, block_type: 'service_plan', sort_order: index, enabled: true, content: plan }, { bookingUrl }))}</div>{plans.length === 0 && <EmptyPublishedContent syncing={syncing} />}<ContentSyncIndicator syncing={syncing} /></>;
}

export function PublishedOffers({ fallbackBookingUrl }: { fallbackBookingUrl: string }) {
  const { content, syncing } = usePublishedSiteState();
  void fallbackBookingUrl;
  const page = content?.pages?.offers;
  if (!content) return <EmptyPublishedContent syncing={syncing} />;
  if (cardGridBlock(page)) return <PublishedCardGrid slug="offers" />;
  const cards = Array.isArray(content.offers) ? content.offers.map((offer) => ({ id: offer.id ? String(offer.id) : undefined, title: offer.name, body: offer.summary })) : [];
  if (!cards.length) return <EmptyPublishedContent syncing={syncing} />;
  return <section className="published-card-grid-module"><div className="value-grid" data-card-count={cards.length}>{cards.map((card, index) => <article key={card.id || `${card.title}-${index}`}><h2>{card.title}</h2><p>{card.body}</p></article>)}</div><ContentSyncIndicator syncing={syncing} /></section>;
}

function validMapUrl(value: string | undefined) {
  if (!value) return '';
  try {
    const url = new URL(value);
    return (url.protocol === 'https:' || url.protocol === 'http:') && /(^|\.)google\.[^/]+|maps\./i.test(url.hostname) ? url.toString() : '';
  } catch { return ''; }
}

export function PublishedLocation() {
  const { content, syncing } = usePublishedSiteState();
  const store = content?.store;
  if (!content) return <EmptyPublishedContent syncing={syncing} />;
  const mapUrl = validMapUrl(store?.mapUrl);
  return <div className="location-layout"><section className="location-details"><small>STUDIO INFORMATION</small><h2>{content.pages?.location?.title || ''}</h2><dl>{store?.address && <div><dt>地址</dt><dd>{store.address}</dd></div>}{store?.hours && <div><dt>營業時間</dt><dd>{store.hours}</dd></div>}{store?.payment && <div><dt>付款方式</dt><dd>{store.payment}</dd></div>}</dl><ContentSyncIndicator syncing={syncing} /></section><div className={`map-embed${mapUrl ? '' : ' map-empty'}`}>{mapUrl ? <iframe src={mapUrl} title="Google 地圖" loading="lazy" referrerPolicy="no-referrer-when-downgrade" /> : <span aria-label="地圖尚未設定">地圖尚未設定</span>}</div></div>;
}
