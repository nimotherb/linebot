'use client';

import { useEffect, useMemo, useState } from 'react';

type Section = 'home' | 'services' | 'therapists' | 'offers' | 'store';
type ServiceDraft = { code: string; name: string; summary: string; duration: string; price: string; visible: boolean };
type OfferDraft = { name: string; summary: string; status: '顯示中' | '草稿' };
export type SiteDraft = {
  home: { subtitle: string; support: string };
  booking: { lineId: string; url: string };
  services: ServiceDraft[];
  therapists: { intro: string; carouselSpeed: number; showMeasurements: boolean };
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
};

const initialDraft: SiteDraft = {
  home: {
    subtitle: '回到平衡，也回到更自在的自己。',
    support: '精準理解每一種身體需求，讓舒適重新回到應有的位置。',
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
  { id: 'home', index: '01', label: '首頁文字', english: 'HOME' },
  { id: 'services', index: '02', label: '服務方案', english: 'SERVICES' },
  { id: 'therapists', index: '03', label: '師傅目錄', english: 'THERAPISTS' },
  { id: 'offers', index: '04', label: '優惠內容', english: 'OFFERS' },
  { id: 'store', index: '05', label: '店鋪資訊', english: 'STORE' },
];

function Field({ label, value, onChange, multiline = false, hint }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean; hint?: string }) {
  return <label className="studio-field"><span>{label}</span>{multiline ? <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={3} /> : <input value={value} onChange={(event) => onChange(event.target.value)} />}{hint && <small>{hint}</small>}</label>;
}

export default function SiteAdminEditor({ api, notify }: { api: SiteAdminApi; notify: (msg: string) => void }) {
  const [active, setActive] = useState<Section>('home');
  const [draft, setDraft] = useState<SiteDraft>(initialDraft);
  const [notice, setNotice] = useState('讀取中...');
  const [savedAt, setSavedAt] = useState('');
  const [version, setVersion] = useState(0);
  const [publishedAt, setPublishedAt] = useState<string | null>(null);

  // 1. 載入雲端草稿
  useEffect(() => {
    const loadContent = async () => {
      try {
        const data = await api.getAdminSiteContent();
        setVersion(data.draft_version || 0);
        if (data.published_at) {
          setPublishedAt(new Date(data.published_at).toLocaleString('zh-TW'));
        }
        if (data.draft && Object.keys(data.draft).length > 0) {
          // 將雲端草稿與預設內容合併，避免新增欄位遺失。
          setDraft({ ...initialDraft, ...data.draft });
        }
        setNotice('已載入雲端最新草稿');
      } catch (error) {
        setNotice('無法載入草稿，使用預設範本');
        notify(error instanceof Error ? error.message : '載入草稿失敗');
      }
    };
    loadContent();
  }, [api, notify]);

  const activeMeta = useMemo(() => sections.find((section) => section.id === active) ?? sections[0], [active]);
  
  const markChanged = (next: SiteDraft) => {
    setDraft(next);
    setNotice('有尚未儲存的變更');
  };

  // 2. 儲存草稿到 MySQL
  const saveDraft = async () => {
    try {
      setNotice('儲存中...');
      const res = await api.saveSiteDraft(draft, version);
      setVersion(res.draft_version);
      const timestamp = new Intl.DateTimeFormat('zh-TW', { hour: '2-digit', minute: '2-digit' }).format(new Date());
      setSavedAt(timestamp);
      setNotice('草稿已安全儲存至 MySQL');
      notify(`💾 草稿已儲存，版本更新至 v${res.draft_version}`);
    } catch (error) {
      const msg = error instanceof Error ? error.message : '儲存失敗';
      setNotice(`儲存失敗: ${msg}`);
      notify(msg);
    }
  };

  // 3. 匯出設定檔 (備份用)
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

  // 4. 正式發布到官網
  const publish = async () => {
    if (!window.confirm('確定要將目前的草稿發布到正式官網嗎？\n發布後，一般客人就會立刻看到最新內容喔！')) return;
    try {
      setNotice('發布中...');
      // 為了安全，發布前先自動存一次最新草稿
      const draftRes = await api.saveSiteDraft(draft, version);
      const newVersion = draftRes.draft_version;
      
      const pubRes = await api.publishSiteContent(newVersion);
      setVersion(pubRes.draft_version);
      setPublishedAt(new Date().toLocaleString('zh-TW'));
      setNotice('官網內容已正式發布');
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

  return <main className="site-studio-shell">
    <header className="studio-topbar">
      <a className="studio-brand" href="/"><i>E</i><span><b>SITE STUDIO</b><small>EQUAL SPA · CONTENT WORKSPACE</small></span></a>
      <div className="studio-status">
        <span className="status-dot" /> <b>{notice}</b>
        {savedAt && <small>最後儲存 {savedAt}</small>}
      </div>
      <div className="studio-actions">
        <div style={{ marginRight: '16px', textAlign: 'right' }}>
          <span style={{ fontSize: '10px', color: '#a3afac' }}>草稿版本 v{version}</span><br/>
          <span style={{ fontSize: '10px', color: '#a3afac' }}>{publishedAt ? `上次發布: ${publishedAt}` : '尚未發布'}</span>
        </div>
        <button type="button" onClick={saveDraft}>儲存草稿</button>
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

        {active === 'home' && <div className="studio-form-grid">
          <div className="studio-form-card"><small>HERO COPY</small><h3>首頁文字</h3><Field label="單行中文副標" value={draft.home.subtitle} onChange={(subtitle) => markChanged({ ...draft, home: { ...draft.home, subtitle } })} hint="建議 22 個中文字以內，只保留一行。" /><Field label="主視覺輔助說明" value={draft.home.support} onChange={(support) => markChanged({ ...draft, home: { ...draft.home, support } })} multiline /></div>
          <div className="studio-form-card"><small>BOOKING ENTRY</small><h3>預約入口</h3><Field label="LINE ID" value={draft.booking.lineId} onChange={(lineId) => markChanged({ ...draft, booking: { ...draft.booking, lineId } })} /><Field label="線上預約網址" value={draft.booking.url} onChange={(url) => markChanged({ ...draft, booking: { ...draft.booking, url } })} hint="點擊官網「立即線上預約」將會導向此網址。" /></div>
        </div>}

        {active === 'services' && <div className="studio-service-editor">{draft.services.map((service, index) => <article key={service.code}>
          <header><i>{service.code}</i><div><small>SERVICE {String(index + 1).padStart(2, '0')}</small><h3>{service.name}</h3></div><label className="studio-switch"><input type="checkbox" checked={service.visible} onChange={(event) => updateService(index, { visible: event.target.checked })} /><span />{service.visible ? '顯示中' : '已隱藏'}</label></header>
          <div><Field label="方案名稱" value={service.name} onChange={(name) => updateService(index, { name })} /><Field label="列表小字簡介" value={service.summary} onChange={(summary) => updateService(index, { summary })} /><Field label="分鐘數" value={service.duration} onChange={(duration) => updateService(index, { duration })} /><Field label="價格" value={service.price} onChange={(price) => updateService(index, { price })} /></div>
        </article>)}</div>}

        {active === 'therapists' && <div className="studio-form-grid">
          <div className="studio-form-card"><small>CATALOG</small><h3>師傅目錄設定</h3><Field label="目錄介紹" value={draft.therapists.intro} onChange={(intro) => markChanged({ ...draft, therapists: { ...draft.therapists, intro } })} multiline /><label className="studio-range"><span>自動輪播速度</span><input type="range" min="24" max="80" value={draft.therapists.carouselSpeed} onChange={(event) => markChanged({ ...draft, therapists: { ...draft.therapists, carouselSpeed: Number(event.target.value) } })} /><b>{draft.therapists.carouselSpeed} 秒</b></label><label className="studio-check"><input type="checkbox" checked={draft.therapists.showMeasurements} onChange={(event) => markChanged({ ...draft, therapists: { ...draft.therapists, showMeasurements: event.target.checked } })} />公開顯示身高與體重</label></div>
          <div className="studio-form-card studio-upload-card"><small>PUBLIC PHOTOS</small><h3>公開照片</h3><div className="upload-placeholder"><span>47</span><b>張公開形象照</b><p>目前沿用官網既有圖片。真實師傅名單由後台「員工管理」自動帶入。</p></div><p className="privacy-note">健康資訊只留在營運後台，絕對不會出現在官網。</p></div>
        </div>}

        {active === 'offers' && <div className="studio-offer-editor">{draft.offers.map((offer, index) => <article key={`${offer.name}-${index}`}><span>0{index + 1}</span><div><Field label="優惠名稱" value={offer.name} onChange={(name) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, name } : item) })} /><Field label="簡短說明" value={offer.summary} onChange={(summary) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, summary } : item) })} multiline /></div><button type="button" onClick={() => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, status: item.status === '顯示中' ? '草稿' : '顯示中' } : item) })}>{offer.status}</button></article>)}</div>}

        {active === 'store' && <div className="studio-form-grid">
          <div className="studio-form-card"><small>STUDIO INFORMATION</small><h3>店鋪資料</h3><Field label="地址" value={draft.store.address} onChange={(address) => markChanged({ ...draft, store: { ...draft.store, address } })} /><Field label="營業時間" value={draft.store.hours} onChange={(hours) => markChanged({ ...draft, store: { ...draft.store, hours } })} /><Field label="付款方式" value={draft.store.payment} onChange={(payment) => markChanged({ ...draft, store: { ...draft.store, payment } })} /></div>
          <div className="studio-form-card"><small>MAP</small><h3>Google 地圖</h3><Field label="嵌入網址" value={draft.store.mapUrl} onChange={(mapUrl) => markChanged({ ...draft, store: { ...draft.store, mapUrl } })} multiline /><p className="privacy-note">請貼上 Google My Maps 的 embed 網址，預覽與發布時會自動更新。</p></div>
        </div>}
      </section>

      <aside className="studio-preview">
        <header><small>LIVE CONTENT PREVIEW</small><span>即時預覽</span></header>
        <div className="studio-preview-screen">
          <span className="preview-logo">E</span>
          {active === 'home' && <><small>EQUAL SPA</small><h2>RETURN TO<br />EQUAL.</h2><p>{draft.home.subtitle}</p><a>{draft.booking.lineId}</a></>}
          {active === 'services' && <><small>SELECT A SERVICE</small>{draft.services.filter((service) => service.visible).map((service) => <div className="preview-service" key={service.code}><i>{service.code}</i><span><b>{service.name}</b><small>{service.summary}</small><em>{service.duration}</em></span><strong>{service.price}</strong></div>)}</>}
          {active === 'therapists' && <><small>THERAPISTS</small><h2>ONE STANDARD.<br />DIFFERENT PRESENCE.</h2><p>{draft.therapists.intro}</p><div className="preview-portraits"><i /><i /><i /></div></>}
          {active === 'offers' && <><small>CURRENT OFFERS</small>{draft.offers.filter((offer) => offer.status === '顯示中').map((offer) => <div className="preview-offer" key={offer.name}><b>{offer.name}</b><p>{offer.summary}</p></div>)}</>}
          {active === 'store' && <><small>STUDIO</small><h2>TAIPEI<br />XIMEN</h2><p>{draft.store.address}<br />{draft.store.hours}<br />{draft.store.payment}</p></>}
        </div>
        <p>此畫面為快速預覽文字層級用。發布後將套用至響應式對外官網。</p>
      </aside>
    </div>
  </main>;
}
