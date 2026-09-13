'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

type Section = 'navigation' | 'home' | 'about' | 'services' | 'therapists' | 'offers' | 'location' | 'recruit' | 'groups' | 'loyalty';
type CalculationType = 'fixed_discount' | 'percent_discount' | 'fixed_fee' | 'per_30_minutes' | 'per_km';
type PageSlug = Exclude<Section, 'navigation'>;
type ServiceDraft = { id?: number; code: string; name: string; summary: string; duration: string; price: string; visible: boolean };
type OfferDraft = { id?: number; name: string; summary: string; status: '顯示中' | '草稿'; calculationType?: CalculationType; value?: number };
export type SiteNavigationItem = { id: string; slug: PageSlug; label: string; english: string; desktopVisible: boolean; mobileVisible: boolean };
export type SitePageCard = { number: string; label: string; title: string; body: string };
export type SitePageDraft = { english: string; title: string; intro: string; body: string; cards: SitePageCard[]; cardGridEnabled: boolean; desktopVisible: boolean; mobileVisible: boolean };
export type ServiceRecord = { id: number; code: string; name: string; duration_minutes: number; price: number; description?: string | null; active: boolean };
export type PromotionRecord = { id: number; name: string; calculation_type: CalculationType; value: number; description?: string | null; active: boolean };
export type SiteDraft = {
  navigation: SiteNavigationItem[];
  pages: Record<PageSlug, SitePageDraft>;
  home: { subtitle: string; support: string; heroFontSize: number };
  booking: { lineId: string; url: string };
  services: ServiceDraft[];
  therapists: {
    intro: string;
    straightIntro: string;
    communityIntro: string;
    bisexualIntro: string;
    carouselSpeed: number;
    showMeasurements: boolean;
  };
  offers: OfferDraft[];
  store: { address: string; hours: string; payment: string; mapUrl: string };
};

export type SiteContentPayload = {
  draft?: Partial<SiteDraft>;
  draft_version: number;
  published_at?: string | null;
};

export type SiteAdminApi = {
  getAdminSiteContent: () => Promise<SiteContentPayload>;
  saveSiteDraft: (content: SiteDraft, expectedVersion: number) => Promise<SiteContentPayload>;
  publishSiteContent: (expectedVersion: number) => Promise<SiteContentPayload>;
  listServices: () => Promise<ServiceRecord[]>;
  createService: (payload: Record<string, unknown>) => Promise<ServiceRecord>;
  updateService: (id: number, payload: Record<string, unknown>) => Promise<ServiceRecord>;
  deleteService: (id: number) => Promise<{ ok: boolean }>;
  listPromotions: () => Promise<PromotionRecord[]>;
  createPromotion: (payload: Record<string, unknown>) => Promise<PromotionRecord>;
  updatePromotion: (id: number, payload: Record<string, unknown>) => Promise<PromotionRecord>;
  deletePromotion: (id: number) => Promise<{ ok: boolean }>;
};


const serviceDraftFromRecord = (record: ServiceRecord, current?: ServiceDraft): ServiceDraft => ({
  id: record.id,
  code: record.code,
  name: record.name,
  summary: current?.summary || record.description || '',
  duration: `${record.duration_minutes} MIN`,
  price: `NT$ ${record.price.toLocaleString('en-US')}`,
  visible: current?.visible ?? record.active,
});

const offerDraftFromRecord = (record: PromotionRecord, current?: OfferDraft): OfferDraft => ({
  id: record.id,
  name: record.name,
  summary: current?.summary || record.description || '',
  status: current?.status || (record.active ? '顯示中' : '草稿'),
  calculationType: record.calculation_type,
  value: record.value,
});

const numberFromLabel = (value: string, fallback: number) => {
  const parsed = Number(value.replace(/[^0-9]/g, ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
};

const initialDraft: SiteDraft = {
  navigation: [
    { id: 'home', slug: 'home', label: '首頁', english: 'HOME', desktopVisible: true, mobileVisible: true },
    { id: 'about', slug: 'about', label: '關於伊果', english: 'ABOUT', desktopVisible: true, mobileVisible: true },
    { id: 'services', slug: 'services', label: '服務項目', english: 'SERVICES', desktopVisible: true, mobileVisible: true },
    { id: 'therapists', slug: 'therapists', label: '專業師傅', english: 'THERAPISTS', desktopVisible: true, mobileVisible: true },
    { id: 'offers', slug: 'offers', label: '最新優惠', english: 'OFFERS', desktopVisible: true, mobileVisible: true },
    { id: 'location', slug: 'location', label: '交通資訊', english: 'LOCATION', desktopVisible: true, mobileVisible: true },
    { id: 'recruit', slug: 'recruit', label: '人才招募', english: 'RECRUIT', desktopVisible: true, mobileVisible: true },
    { id: 'groups', slug: 'groups', label: '群組', english: 'GROUP', desktopVisible: true, mobileVisible: true },
    { id: 'loyalty', slug: 'loyalty', label: '酬賓計畫', english: 'LOYALTY', desktopVisible: true, mobileVisible: true },
  ],
  pages: {
    home: { english: 'HOME', title: '首頁', intro: 'EQUAL SPA · MOVE · RESET', body: '', cards: [], cardGridEnabled: false, desktopVisible: true, mobileVisible: true },
    about: { english: 'ABOUT', title: '關於伊果', intro: '平等而細緻，讓每一種身體都能自在被理解。', body: '', cards: [{ number: '01', label: 'VALUE', title: 'EQUALITY', body: '不預設、不評價，讓每位來訪者都能被好好接住。' }, { number: '02', label: 'VALUE', title: 'PRECISION', body: '清楚說明方案與時間，讓需求被準確理解。' }, { number: '03', label: 'VALUE', title: 'EASE', body: '像回到熟悉的地方，安靜放下今天累積的重量。' }], cardGridEnabled: true, desktopVisible: true, mobileVisible: true },
    services: { english: 'SERVICES', title: '選擇今天需要的節奏', intro: '從六十分鐘的精準釋放，到完整兩小時的深度整理。', body: '', cards: [], cardGridEnabled: false, desktopVisible: true, mobileVisible: true },
    therapists: { english: 'THERAPISTS', title: '選擇適合你的師傅', intro: '不同氣質與手法，都遵循相同的專業與界線。', body: '', cards: [], cardGridEnabled: false, desktopVisible: true, mobileVisible: true },
    offers: { english: 'OFFERS', title: '期間限定企劃', intro: '優惠內容隨期間更新，預約前可由 LINE 客服確認。', body: '', cards: [{ number: '01', label: 'CURRENT OFFER', title: '夜間服務費', body: '服務時間落在 00:00—06:00 時，會依當期公告收取夜間服務費。' }, { number: '02', label: 'CURRENT OFFER', title: '預先加時', body: '預約時可先提出延長需求，客服會依師傅班表確認可安排的時間。' }, { number: '03', label: 'CURRENT OFFER', title: '現場加時', body: '服務進行中若仍有需要，可先與師傅確認，再由客服協助安排。' }], cardGridEnabled: true, desktopVisible: true, mobileVisible: true },
    location: { english: 'LOCATION', title: '歡迎來到西門', intro: '從抵達開始放慢速度。', body: '', cards: [], cardGridEnabled: false, desktopVisible: true, mobileVisible: true },
    recruit: { english: 'RECRUIT', title: '與伊果一起工作', intro: '一起建立舒服、尊重且長久的工作關係。', body: '', cards: [{ number: '01', label: 'CURRENT STATUS', title: '內容更新中', body: '之後會在這裡放置職缺內容、合作方式、基本條件與聯絡管道。' }], cardGridEnabled: true, desktopVisible: true, mobileVisible: true },
    groups: { english: 'GROUP', title: '社群內容準備中', intro: '最新社群資訊與活動整理。', body: '', cards: [], cardGridEnabled: false, desktopVisible: true, mobileVisible: true },
    loyalty: { english: 'LOYALTY', title: '回訪計畫準備中', intro: '為熟悉伊果的你，準備更完整的回訪體驗。', body: '', cards: [], cardGridEnabled: false, desktopVisible: true, mobileVisible: true },
  },
  home: {
    subtitle: '回到平衡，也回到更自在的自己。',
    support: '精準理解每一種身體需求，讓舒適重新回到應有的位置。',
    heroFontSize: 240,
  },
  booking: {
    lineId: '@017ktlhm',
    url: 'https://equalspa-admin.pages.dev/booking',
  },
  services: [
    { code: 'A', name: '舒壓方案', summary: '指壓或油壓擇一，簡單整理日常疲勞', duration: '60 MIN', price: 'NT$ 1,500', visible: true },
    { code: 'B', name: '愉悅方案', summary: '可指定師傅，加入體推與機能保養', duration: '60 MIN', price: 'NT$ 2,000', visible: true },
    { code: 'C', name: '享受方案', summary: '指壓與油壓完整銜接，節奏更從容', duration: '90 MIN', price: 'NT$ 2,500', visible: true },
    { code: 'D', name: '極緻方案', summary: '兩小時完整照顧，充分整理全身', duration: '120 MIN', price: 'NT$ 3,000', visible: true },
  ],
  therapists: {
    intro: '先從偏好的互動氣質開始，再於預約時確認當週班表。',
    straightIntro: '自然俐落，保留舒服距離的專業互動。',
    communityIntro: '熟悉多元需求，讓溝通更直接、更自在。',
    bisexualIntro: '開放而細膩，提供另一種柔韌平衡的節奏。',
    carouselSpeed: 45,
    showMeasurements: true,
  },
  offers: [
    { name: '生日月優惠', summary: '生日月預約可向客服確認當期內容。', status: '顯示中' },
    { name: '新進師傅體驗', summary: '認識不同手法與服務節奏。', status: '草稿' },
  ],
  store: {
    address: '台北市萬華區西寧南路 36 號',
    hours: '每日 10:00—24:00',
    payment: '現金、轉帳',
    mapUrl: 'https://www.google.com/maps/d/u/1/embed?mid=1141UqP4pbf1EG49i-Z6_c18pC2EplKQ&ehbc=2E312F&noprof=1',
  },
};

const sections: { id: Section; index: string; label: string; english: string }[] = [
  { id: 'navigation', index: '00', label: '頁籤設定', english: 'NAVIGATION' },
  { id: 'home', index: '01', label: '首頁', english: 'HOME' },
  { id: 'about', index: '02', label: '關於伊果', english: 'ABOUT' },
  { id: 'services', index: '03', label: '服務項目', english: 'SERVICES' },
  { id: 'therapists', index: '04', label: '員工目錄', english: 'THERAPISTS' },
  { id: 'offers', index: '05', label: '最新優惠', english: 'OFFERS' },
  { id: 'location', index: '06', label: '交通資訊', english: 'LOCATION' },
  { id: 'recruit', index: '07', label: '人才招募', english: 'RECRUIT' },
  { id: 'groups', index: '08', label: '群組', english: 'GROUP' },
  { id: 'loyalty', index: '09', label: '酬賓計畫', english: 'LOYALTY' },
];

function Field({ label, value, onChange, multiline = false, hint }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean; hint?: string }) {
  return <label className="studio-field"><span>{label}</span>{multiline ? <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={4} /> : <input value={value} onChange={(event) => onChange(event.target.value)} />}{hint && <small>{hint}</small>}</label>;
}

function PageSettings({ page, onChange }: { page: SitePageDraft; onChange: (patch: Partial<SitePageDraft>) => void }) {
  return <div className="studio-form-card studio-page-settings"><small>PAGE TEMPLATE</small><h3>頁面標題與副標</h3><Field label="英文頁面標題／標籤" value={page.english} onChange={(english) => onChange({ english })} /><Field label="中文頁面標題" value={page.title} onChange={(title) => onChange({ title })} /><Field label="中文副標（可換行）" value={page.intro} onChange={(intro) => onChange({ intro })} multiline /><Field label="頁面補充內容（每段空一行）" value={page.body} onChange={(body) => onChange({ body })} multiline /><div className="studio-visibility-grid"><label className="studio-check"><input type="checkbox" checked={page.desktopVisible} onChange={(event) => onChange({ desktopVisible: event.target.checked })} />桌機顯示</label><label className="studio-check"><input type="checkbox" checked={page.mobileVisible} onChange={(event) => onChange({ mobileVisible: event.target.checked })} />手機顯示</label></div></div>;
}

function PageCardsEditor({ page, onChange }: { page: SitePageDraft; onChange: (patch: Partial<SitePageDraft>) => void }) {
  const updateCard = (index: number, patch: Partial<SitePageCard>) => onChange({ cards: page.cards.map((card, cardIndex) => cardIndex === index ? { ...card, ...patch } : card) });
  const addCard = () => onChange({ cards: [...page.cards, { number: String(page.cards.length + 1).padStart(2, '0'), label: 'CARD', title: '新卡片', body: '' }] });
  const removeCard = (index: number) => onChange({ cards: page.cards.filter((_, cardIndex) => cardIndex !== index) });
  return <div className="studio-form-card studio-page-cards"><header><div><small>CARD GRID</small><h3>卡片網格版型</h3><p>卡片會依編號、標籤、標題與內文自動渲染；1 張為左右分割，3 張為三欄網格。</p></div><label className="studio-switch"><input type="checkbox" checked={page.cardGridEnabled} onChange={(event) => onChange({ cardGridEnabled: event.target.checked })} /><span />{page.cardGridEnabled ? '啟用' : '停用'}</label></header><div className="studio-page-card-list">{page.cards.map((card, index) => <article key={`${card.number}-${index}`}><b>{String(index + 1).padStart(2, '0')}</b><div><Field label="編號" value={card.number} onChange={(number) => updateCard(index, { number })} /><Field label="標籤" value={card.label} onChange={(label) => updateCard(index, { label })} /><Field label="標題" value={card.title} onChange={(title) => updateCard(index, { title })} multiline /><Field label="內文" value={card.body} onChange={(body) => updateCard(index, { body })} multiline /></div><button className="danger" type="button" onClick={() => removeCard(index)}>刪除卡片</button></article>)}</div><button className="studio-add-page" type="button" onClick={addCard}>＋ 新增卡片</button></div>;
}

export default function SiteAdminEditor({ api, notify }: { api: SiteAdminApi; notify: (msg: string) => void }) {
  const [active, setActive] = useState<Section>('home');
  const [draft, setDraft] = useState<SiteDraft>(initialDraft);
  const [notice, setNotice] = useState('讀取中...');
  const [version, setVersion] = useState(0);
  const [publishedAt, setPublishedAt] = useState<string | null>(null);
  const [showNewService, setShowNewService] = useState(false);
  const [showNewOffer, setShowNewOffer] = useState(false);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);

  // 1. 載入雲端草稿
  useEffect(() => {
    const loadContent = async () => {
      try {
        const [data, serviceRecords, promotionRecords] = await Promise.all([
          api.getAdminSiteContent(),
          api.listServices(),
          api.listPromotions(),
        ]);
        setVersion(data.draft_version || 0);
        if (data.published_at) {
          setPublishedAt(new Date(data.published_at).toLocaleString('zh-TW'));
        }
        const saved = data.draft && Object.keys(data.draft).length > 0 ? data.draft : {};
        const savedNavigation = Array.isArray(saved.navigation) ? saved.navigation.map((item, index) => ({
          ...(initialDraft.navigation[index] || initialDraft.navigation[0]),
          ...item,
        })) : initialDraft.navigation;
        const savedPages = Object.fromEntries(Object.entries(initialDraft.pages).map(([slug, page]) => [slug, { ...page, ...(saved.pages?.[slug as PageSlug] || {}) }])) as SiteDraft['pages'];
        const merged: SiteDraft = {
          ...initialDraft,
          ...saved,
          navigation: savedNavigation.length ? savedNavigation : initialDraft.navigation,
          pages: savedPages,
          home: { ...initialDraft.home, ...(saved.home || {}) },
          booking: { ...initialDraft.booking, ...(saved.booking || {}) },
          therapists: { ...initialDraft.therapists, ...(saved.therapists || {}) },
          store: { ...initialDraft.store, ...(saved.store || {}) },
          services: Array.isArray(saved.services) ? saved.services : initialDraft.services,
          offers: Array.isArray(saved.offers) ? saved.offers : initialDraft.offers,
        };
        setDraft({
          ...merged,
          services: serviceRecords.map((record) => serviceDraftFromRecord(record, merged.services.find((item) => item.id === record.id || (!item.id && item.code === record.code)))),
          offers: promotionRecords.map((record) => offerDraftFromRecord(record, merged.offers.find((item) => item.id === record.id || (!item.id && item.name === record.name)))),
        });
        setNotice('已載入雲端最新草稿');
      } catch (error) {
        setNotice('無法載入草稿，使用預設範本');
        notify(error instanceof Error ? error.message : '載入草稿失敗');
      }
    };
    loadContent();
  }, [api, notify]);

  const activeMeta = useMemo(() => sections.find((section) => section.id === active) ?? sections[0], [active]);
  const previewPath = useMemo(() => ({
    navigation: '/',
    home: '/',
    about: '/about/',
    services: '/services/',
    therapists: '/therapists/',
    offers: '/offers/',
    location: '/location/',
    recruit: '/recruit/',
    groups: '/groups/',
    loyalty: '/loyalty/',
  } satisfies Record<Section, string>)[active], [active]);
  
  const markChanged = (next: SiteDraft) => {
    setDraft(next);
    setNotice('有尚未儲存的變更');
  };

  const updatePage = (slug: PageSlug, patch: Partial<SitePageDraft>) => {
    markChanged({ ...draft, pages: { ...draft.pages, [slug]: { ...draft.pages[slug], ...patch } } });
  };

  const updateNavigationItem = (index: number, patch: Partial<SiteNavigationItem>) => {
    markChanged({ ...draft, navigation: draft.navigation.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) });
  };

  const addNavigationItem = () => {
    const usedIds = new Set(draft.navigation.map((item) => item.id));
    const id = `custom-${draft.navigation.length + 1}`;
    let uniqueId = id;
    let suffix = 2;
    while (usedIds.has(uniqueId)) uniqueId = `${id}-${suffix++}`;
    markChanged({
      ...draft,
      navigation: [...draft.navigation, { id: uniqueId, slug: 'about', label: '新頁籤', english: 'NEW PAGE', desktopVisible: true, mobileVisible: true }],
    });
  };

  const removeNavigationItem = (index: number) => {
    if (draft.navigation.length <= 1) return notify('至少保留一個官網頁籤。');
    if (!window.confirm(`確定移除「${draft.navigation[index]?.label || '這個頁籤'}」？`)) return;
    markChanged({ ...draft, navigation: draft.navigation.filter((_, itemIndex) => itemIndex !== index) });
  };

  const persistCatalog = async () => {
    await Promise.all([
      ...draft.services.filter((item) => item.id).map((item) => api.updateService(item.id!, {
        name: item.name.trim(),
        description: item.summary.trim() || null,
        duration_minutes: numberFromLabel(item.duration, 60),
        price: numberFromLabel(item.price, 0),
        active: item.visible,
      })),
      ...draft.offers.filter((item) => item.id).map((item) => api.updatePromotion(item.id!, {
        name: item.name.trim(),
        description: item.summary.trim() || null,
        calculation_type: item.calculationType || 'fixed_discount',
        value: item.value || 0,
        active: item.status === '顯示中',
      })),
    ]);
  };

  // 匯出設定檔 (備份用)
  const exportDraft = () => {
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `equalspa-site-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    notify('設定檔已成功匯出');
  };

  // 正式發布到官網
  const publish = async () => {
    if (!window.confirm('確定要將目前的草稿發布到正式官網嗎？\n發布後，一般客人就會立刻看到最新內容喔！')) return;
    try {
      setNotice('發布中...');
      // 為了安全，發布前先自動存一次最新草稿
      await persistCatalog();
      const draftRes = await api.saveSiteDraft(draft, version);
      const newVersion = draftRes.draft_version;
      
      const pubRes = await api.publishSiteContent(newVersion);
      setVersion(pubRes.draft_version);
      setPublishedAt(new Date().toLocaleString('zh-TW'));
      setNotice('官網內容已正式發布');
      setPreviewRevision(Date.now());
      notify('🚀 正式發布成功！官網內容已同步至前端。');
    } catch (error) {
      const msg = error instanceof Error ? error.message : '發布失敗';
      setNotice(`發布失敗: ${msg}`);
      notify(msg);
    }
  };

  const updateService = (index: number, patch: Partial<ServiceDraft>) => {
    const services = draft.services.map((service, serviceIndex) => serviceIndex === index ? { ...service, ...patch } : service);
    markChanged({ ...draft, services });
  };

  const createService = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCatalogBusy(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const summary = String(data.get('summary') || '').trim();
      const created = await api.createService({
        code: String(data.get('code')).trim().toUpperCase(),
        name: String(data.get('name')).trim(),
        duration_minutes: Number(data.get('duration')),
        price: Number(data.get('price')),
        description: summary || null,
        can_choose_staff: data.get('canChooseStaff') === 'on',
      });
      markChanged({ ...draft, services: [...draft.services, serviceDraftFromRecord(created, { code: created.code, name: created.name, summary, duration: '', price: '', visible: true })] });
      form.reset();
      setShowNewService(false);
      notify(`${created.name} 已新增；儲存／發布後會同步官網內容。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '新增方案失敗');
    } finally {
      setCatalogBusy(false);
    }
  };

  const deleteService = async (service: ServiceDraft) => {
    if (!window.confirm(`確定刪除「${service.name}」？\n它會從新預約與官網編輯器移除，但舊訂單仍會保留原方案紀錄。`)) return;
    setCatalogBusy(true);
    try {
      if (service.id) await api.deleteService(service.id);
      markChanged({ ...draft, services: draft.services.filter((item) => item !== service) });
      notify(`${service.name} 已從目前方案刪除，歷史訂單不受影響。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '刪除方案失敗');
    } finally {
      setCatalogBusy(false);
    }
  };

  const createOffer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCatalogBusy(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const summary = String(data.get('summary') || '').trim();
      const created = await api.createPromotion({
        name: String(data.get('name')).trim(),
        description: summary || null,
        calculation_type: String(data.get('calculationType')),
        value: Number(data.get('value')),
      });
      markChanged({ ...draft, offers: [...draft.offers, offerDraftFromRecord(created, { name: created.name, summary, status: '顯示中' })] });
      form.reset();
      setShowNewOffer(false);
      notify(`${created.name} 已新增並設為顯示中。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '新增優惠失敗');
    } finally {
      setCatalogBusy(false);
    }
  };

  const deleteOffer = async (offer: OfferDraft) => {
    if (!window.confirm(`確定刪除「${offer.name}」？\n它會停止提供給新預約，舊訂單套用的優惠仍會保留。`)) return;
    setCatalogBusy(true);
    try {
      if (offer.id) await api.deletePromotion(offer.id);
      markChanged({ ...draft, offers: draft.offers.filter((item) => item !== offer) });
      notify(`${offer.name} 已刪除，歷史訂單不受影響。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '刪除優惠失敗');
    } finally {
      setCatalogBusy(false);
    }
  };

  return <main className="site-studio-shell">
    <header className="studio-topbar">
      <a className="studio-brand" href="/"><i>E</i><span><b>SITE STUDIO</b><small>EQUAL SPA · CONTENT WORKSPACE</small></span></a>
      <div className="studio-status">
        <span className="status-dot" /> <b>{notice}</b>
      </div>
      <div className="studio-actions">
        <div style={{ marginRight: '16px', textAlign: 'right' }}>
          <span style={{ fontSize: '10px', color: '#a3afac' }}>草稿版本 v{version}</span><br/>
          <span style={{ fontSize: '10px', color: '#a3afac' }}>{publishedAt ? `上次發布: ${publishedAt}` : '尚未發布'}</span>
        </div>
        <button className="publish" type="button" onClick={publish}>發布更新</button>
      </div>
    </header>

    <div className="studio-layout">
      <aside className="studio-sidebar">
        <div><small>CONTENT MAP</small><h1>官網內容</h1><p>選擇區塊後直接修改。所有變更會先保留為草稿，點擊發布才會對外生效。</p></div>
        <nav>{sections.map((section) => <button type="button" key={section.id} className={active === section.id ? 'active' : ''} onClick={() => setActive(section.id)}><span>{section.index}</span><b>{section.label}</b><em>{section.english}</em></button>)}</nav>
      </aside>

      <section className="studio-workspace">
        <header><div><small>{activeMeta.index} / {activeMeta.english}</small><h2>{activeMeta.label}</h2></div><button type="button" onClick={exportDraft}>匯出設定 JSON</button></header>

        {active === 'navigation' && <div className="studio-navigation-editor">
          <div className="studio-form-card"><small>OFFICIAL SITE MAP</small><h3>官網頁籤同步</h3><p>這裡的順序、名稱與顯示設定會同步到官網選單。桌機為主要版型；手機只需要勾選是否顯示。</p></div>
          <div className="studio-navigation-list">{draft.navigation.map((item, index) => <article key={item.id}>
            <span className="studio-navigation-index">{String(index + 1).padStart(2, '0')}</span>
            <div className="studio-navigation-fields"><Field label="中文名稱" value={item.label} onChange={(label) => updateNavigationItem(index, { label })} /><Field label="英文標籤" value={item.english} onChange={(english) => updateNavigationItem(index, { english })} /><label className="studio-catalog-field"><span>頁面版型</span><select value={item.slug} onChange={(event) => updateNavigationItem(index, { slug: event.target.value as PageSlug })}>{sections.filter((section) => section.id !== 'navigation').map((section) => <option key={section.id} value={section.id}>{section.english} · {section.label}</option>)}</select></label><div className="studio-visibility-grid"><label className="studio-check"><input type="checkbox" checked={item.desktopVisible} onChange={(event) => updateNavigationItem(index, { desktopVisible: event.target.checked })} />桌機</label><label className="studio-check"><input type="checkbox" checked={item.mobileVisible} onChange={(event) => updateNavigationItem(index, { mobileVisible: event.target.checked })} />手機</label></div></div>
            <button className="danger" type="button" onClick={() => removeNavigationItem(index)}>移除</button>
          </article>)}</div>
          <button className="studio-add-page" type="button" onClick={addNavigationItem}>＋ 新增官網頁籤</button>
        </div>}

        {active === 'home' && <div className="studio-form-grid">
          <PageSettings page={draft.pages.home} onChange={(patch) => updatePage('home', patch)} />
          <div className="studio-form-card"><small>HERO COPY</small><h3>首頁文字</h3><Field label="主標題副標（可換行）" value={draft.home.subtitle} onChange={(subtitle) => markChanged({ ...draft, home: { ...draft.home, subtitle } })} multiline /><Field label="主視覺輔助說明（可換行）" value={draft.home.support} onChange={(support) => markChanged({ ...draft, home: { ...draft.home, support } })} multiline /><label className="studio-field"><span>主標題最大字級（px）</span><input type="number" min={96} max={480} value={draft.home.heroFontSize} onChange={(event) => markChanged({ ...draft, home: { ...draft.home, heroFontSize: Math.min(480, Math.max(96, Number(event.target.value) || 240)) } })} /><small>其他首頁文字會依主標題比例與響應式版面同步縮放。</small></label></div>
          <div className="studio-form-card"><small>BOOKING ENTRY</small><h3>預約入口</h3><Field label="LINE ID" value={draft.booking.lineId} onChange={(lineId) => markChanged({ ...draft, booking: { ...draft.booking, lineId } })} /><Field label="線上預約網址" value={draft.booking.url} onChange={(url) => markChanged({ ...draft, booking: { ...draft.booking, url } })} hint="點擊官網「立即線上預約」將會導向此網址。" /></div>
        </div>}

        {active === 'services' && <div className="studio-catalog-editor">
          <PageSettings page={draft.pages.services} onChange={(patch) => updatePage('services', patch)} />
          <header className="studio-catalog-toolbar"><div><small>MYSQL SERVICE CATALOG</small><h3>目前方案</h3><p>新增與刪除會同步預約方案。刪除只結束後續使用，舊訂單會保留當時的方案連結。</p></div><button type="button" onClick={() => setShowNewService((current) => !current)}>{showNewService ? '取消新增' : '＋ 新增方案'}</button></header>
          {showNewService && <form className="studio-new-catalog" onSubmit={createService}>
            <label><span>方案代碼</span><input name="code" required maxLength={30} placeholder="例如 F" /></label>
            <label><span>方案名稱</span><input name="name" required /></label>
            <label><span>分鐘數</span><input name="duration" type="number" min="30" max="480" step="10" defaultValue="60" required /></label>
            <label><span>價格</span><input name="price" type="number" min="0" step="100" required /></label>
            <label className="wide"><span>列表小字簡介</span><input name="summary" maxLength={500} /></label>
            <label className="studio-inline-check"><input name="canChooseStaff" type="checkbox" defaultChecked />可指定師傅</label>
            <button type="submit" disabled={catalogBusy}>建立方案</button>
          </form>}
          <div className="studio-service-editor">{draft.services.map((service, index) => <article key={service.id || service.code}>
            <header><i>{service.code}</i><div><small>SERVICE {String(index + 1).padStart(2, '0')}</small><h3>{service.name}</h3></div><div className="studio-catalog-actions"><label className="studio-switch"><input type="checkbox" checked={service.visible} onChange={(event) => updateService(index, { visible: event.target.checked })} /><span />{service.visible ? '顯示中' : '已隱藏'}</label><button className="danger" type="button" disabled={catalogBusy} onClick={() => deleteService(service)}>刪除方案</button></div></header>
            <div><Field label="方案名稱（可換行）" value={service.name} onChange={(name) => updateService(index, { name })} multiline /><Field label="列表小字簡介（可換行）" value={service.summary} onChange={(summary) => updateService(index, { summary })} multiline /><Field label="分鐘數" value={service.duration} onChange={(duration) => updateService(index, { duration })} /><Field label="價格" value={service.price} onChange={(price) => updateService(index, { price })} /></div>
          </article>)}</div>
        </div>}

        {active === 'therapists' && <div className="studio-form-grid">
          <PageSettings page={draft.pages.therapists} onChange={(patch) => updatePage('therapists', patch)} />
          <div className="studio-form-card"><small>CATALOG</small><h3>員工目錄設定</h3><Field label="目錄介紹" value={draft.therapists.intro} onChange={(intro) => markChanged({ ...draft, therapists: { ...draft.therapists, intro } })} multiline />{/* 輪播速度暫時固定於前端，保留欄位以相容既有草稿。 */}<label className="studio-check"><input type="checkbox" checked={draft.therapists.showMeasurements} onChange={(event) => markChanged({ ...draft, therapists: { ...draft.therapists, showMeasurements: event.target.checked } })} />公開顯示身高、體重與角色</label></div>
          <div className="studio-form-card studio-upload-card"><small>LIVE DIRECTORY</small><h3>公開名單</h3><div className="upload-placeholder"><b>員工資料由後台管理</b><p>公開名單、分類、照片與在職狀態會由 Back office 員工管理頁同步至官網。</p></div><p className="privacy-note">健康資訊只留在營運後台，不會出現在官網編輯器或公開頁面。</p></div>
        </div>}

        {active === 'offers' && <div className="studio-catalog-editor">
          <PageSettings page={draft.pages.offers} onChange={(patch) => updatePage('offers', patch)} />
          <PageCardsEditor page={draft.pages.offers} onChange={(patch) => updatePage('offers', patch)} />
          <header className="studio-catalog-toolbar"><div><small>MYSQL PROMOTION CATALOG</small><h3>優惠內容</h3><p>優惠可保留在草稿或設為顯示中；刪除後舊訂單仍會保存原優惠。</p></div><button type="button" onClick={() => setShowNewOffer((current) => !current)}>{showNewOffer ? '取消新增' : '＋ 新增優惠'}</button></header>
          {showNewOffer && <form className="studio-new-catalog studio-new-offer" onSubmit={createOffer}>
            <label><span>優惠名稱</span><input name="name" required /></label>
            <label><span>計算方式</span><select name="calculationType" defaultValue="fixed_discount"><option value="fixed_discount">固定折扣</option><option value="percent_discount">百分比折扣</option><option value="fixed_fee">固定加價</option><option value="per_30_minutes">每 30 分鐘</option><option value="per_km">每公里</option></select></label>
            <label><span>金額／百分比</span><input name="value" type="number" min="0" required /></label>
            <label className="wide"><span>簡短說明</span><textarea name="summary" maxLength={500} rows={4} /></label>
            <button type="submit" disabled={catalogBusy}>建立優惠</button>
          </form>}
          <div className="studio-offer-editor">{draft.offers.map((offer, index) => <article key={offer.id || `${offer.name}-${index}`}><span>0{index + 1}</span><div><Field label="優惠名稱（可換行）" value={offer.name} onChange={(name) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, name } : item) })} multiline /><Field label="簡短說明（可換行）" value={offer.summary} onChange={(summary) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, summary } : item) })} multiline /><label className="studio-catalog-field"><span>計算方式</span><select value={offer.calculationType || 'fixed_discount'} onChange={(event) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, calculationType: event.target.value as CalculationType } : item) })}><option value="fixed_discount">固定折扣</option><option value="percent_discount">百分比折扣</option><option value="fixed_fee">固定加價</option><option value="per_30_minutes">每 30 分鐘</option><option value="per_km">每公里</option></select></label><label className="studio-catalog-field"><span>金額／百分比</span><input type="number" min="0" value={offer.value || 0} onChange={(event) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, value: Number(event.target.value) } : item) })} /></label></div><div className="studio-catalog-actions"><button type="button" onClick={() => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, status: item.status === '顯示中' ? '草稿' : '顯示中' } : item) })}>{offer.status}</button><button className="danger" type="button" disabled={catalogBusy} onClick={() => deleteOffer(offer)}>刪除優惠</button></div></article>)}</div>
        </div>}

        {active === 'location' && <div className="studio-form-grid">
          <PageSettings page={draft.pages.location} onChange={(patch) => updatePage('location', patch)} />
          <div className="studio-form-card"><small>STUDIO INFORMATION</small><h3>店鋪資料</h3><Field label="地址" value={draft.store.address} onChange={(address) => markChanged({ ...draft, store: { ...draft.store, address } })} /><Field label="營業時間" value={draft.store.hours} onChange={(hours) => markChanged({ ...draft, store: { ...draft.store, hours } })} /><Field label="付款方式" value={draft.store.payment} onChange={(payment) => markChanged({ ...draft, store: { ...draft.store, payment } })} /></div>
          <div className="studio-form-card"><small>MAP</small><h3>Google 地圖</h3><Field label="嵌入網址" value={draft.store.mapUrl} onChange={(mapUrl) => markChanged({ ...draft, store: { ...draft.store, mapUrl } })} multiline /><p className="privacy-note">請貼上 Google My Maps 的 embed 網址，預覽與發布時會自動更新。</p></div>
        </div>}

        {(active === 'about' || active === 'recruit') && <div className="studio-form-grid"><PageSettings page={draft.pages[active]} onChange={(patch) => updatePage(active, patch)} /><PageCardsEditor page={draft.pages[active]} onChange={(patch) => updatePage(active, patch)} /></div>}
        {(active === 'groups' || active === 'loyalty') && <div className="studio-form-grid"><PageSettings page={draft.pages[active]} onChange={(patch) => updatePage(active, patch)} /><div className="studio-form-card"><small>CONTENT TEMPLATE</small><h3>{activeMeta.label}內容</h3><p>桌機版面以此頁設定為主；手機版只依上方勾選決定是否顯示此頁籤。</p></div></div>}
      </section>

      <aside className="studio-preview">
        <header><small>LIVE OFFICIAL SITE</small><span>正式官網現況</span></header>
        <div className="studio-preview-tools"><button type="button" onClick={() => setPreviewRevision(Date.now())}>重新整理</button><a href={previewPath} target="_blank" rel="noreferrer">另開頁面 ↗</a></div>
        <div className="studio-preview-screen">
          <iframe key={`${previewPath}-${previewRevision}`} src={`${previewPath}?studio-preview=${previewRevision}`} title={`${activeMeta.label}正式官網預覽`} />
        </div>
        <p>這裡直接載入目前正式官網，不再使用另一套模擬畫面。草稿發布後會自動重新整理。</p>
      </aside>
    </div>
  </main>;
}

