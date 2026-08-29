'use client';

import { FormEvent, useEffect, useMemo, useState } from 'react';

type Section = 'home' | 'services' | 'therapists' | 'offers' | 'store';
type CalculationType = 'fixed_discount' | 'percent_discount' | 'fixed_fee' | 'per_30_minutes' | 'per_km';
type ServiceDraft = { id?: number; code: string; name: string; summary: string; duration: string; price: string; visible: boolean };
type OfferDraft = { id?: number; name: string; summary: string; status: '顯示中' | '草稿'; calculationType?: CalculationType; value?: number };
export type ServiceRecord = { id: number; code: string; name: string; duration_minutes: number; price: number; description?: string | null; active: boolean };
export type PromotionRecord = { id: number; name: string; calculation_type: CalculationType; value: number; description?: string | null; active: boolean };
export type StaffProfile = {
  id: number;
  name: string;
  category: 'straight' | 'gay' | 'bisexual';
  employment_status: 'active' | 'retired';
  photo_url?: string | null;
};
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
  listServices: () => Promise<ServiceRecord[]>;
  createService: (payload: Record<string, unknown>) => Promise<ServiceRecord>;
  updateService: (id: number, payload: Record<string, unknown>) => Promise<ServiceRecord>;
  deleteService: (id: number) => Promise<{ ok: boolean; history_preserved: boolean }>;
  listPromotions: () => Promise<PromotionRecord[]>;
  createPromotion: (payload: Record<string, unknown>) => Promise<PromotionRecord>;
  updatePromotion: (id: number, payload: Record<string, unknown>) => Promise<PromotionRecord>;
  deletePromotion: (id: number) => Promise<{ ok: boolean; history_preserved: boolean }>;
  listStaff: () => Promise<StaffProfile[]>;
  createStaff: (payload: Record<string, unknown>) => Promise<StaffProfile>;
  updateStaff: (id: number, payload: Record<string, unknown>) => Promise<StaffProfile>;
  updateStaffStatus: (id: number, status: StaffProfile['employment_status'], reason: string) => Promise<StaffProfile>;
  uploadStaffPhoto: (id: number, dataUrl: string) => Promise<StaffProfile>;
  permanentlyDeleteStaff: (id: number) => Promise<{ ok: boolean }>;
};

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');
const categoryLabels: Record<StaffProfile['category'], string> = { straight: '直男師傅', gay: '圈內師傅', bisexual: '雙性師傅' };
const resolvePhotoUrl = (value?: string | null) => value?.startsWith('/') ? `${API_BASE_URL}${value}` : value || '';
const readPhoto = (file: File) => new Promise<string>((resolve, reject) => {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) return reject(new Error('只接受 JPEG、PNG 或 WebP 圖片。'));
  if (file.size > 3 * 1024 * 1024) return reject(new Error('照片大小必須小於 3 MB。'));
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result));
  reader.onerror = () => reject(new Error('照片讀取失敗。'));
  reader.readAsDataURL(file);
});

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

export default function SiteAdminEditor({ api, notify, userRole }: { api: SiteAdminApi; notify: (msg: string) => void; userRole: 'admin' | 'manager' }) {
  const [active, setActive] = useState<Section>('home');
  const [draft, setDraft] = useState<SiteDraft>(initialDraft);
  const [notice, setNotice] = useState('讀取中...');
  const [savedAt, setSavedAt] = useState('');
  const [version, setVersion] = useState(0);
  const [publishedAt, setPublishedAt] = useState<string | null>(null);
  const [staffProfiles, setStaffProfiles] = useState<StaffProfile[]>([]);
  const [showNewStaff, setShowNewStaff] = useState(false);
  const [staffBusy, setStaffBusy] = useState(false);
  const [showNewService, setShowNewService] = useState(false);
  const [showNewOffer, setShowNewOffer] = useState(false);
  const [catalogBusy, setCatalogBusy] = useState(false);

  // 1. 載入雲端草稿
  useEffect(() => {
    const loadContent = async () => {
      try {
        const [data, staff, serviceRecords, promotionRecords] = await Promise.all([
          api.getAdminSiteContent(),
          api.listStaff(),
          api.listServices(),
          api.listPromotions(),
        ]);
        setStaffProfiles(staff);
        setVersion(data.draft_version || 0);
        if (data.published_at) {
          setPublishedAt(new Date(data.published_at).toLocaleString('zh-TW'));
        }
        const saved = data.draft && Object.keys(data.draft).length > 0 ? data.draft : {};
        const merged: SiteDraft = {
          ...initialDraft,
          ...saved,
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
  
  const markChanged = (next: SiteDraft) => {
    setDraft(next);
    setNotice('有尚未儲存的變更');
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

  // 2. 儲存草稿到 MySQL
  const saveDraft = async () => {
    try {
      setNotice('儲存中...');
      await persistCatalog();
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
      await persistCatalog();
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

  const upsertStaffProfile = (profile: StaffProfile) => {
    setStaffProfiles((current) => current.some((item) => item.id === profile.id)
      ? current.map((item) => item.id === profile.id ? profile : item)
      : [...current, profile].sort((a, b) => a.name.localeCompare(b.name, 'zh-TW')));
  };

  const createStaffProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStaffBusy(true);
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      let profile = await api.createStaff({
        name: String(data.get('name')).trim(),
        category: String(data.get('category')),
        photo_url: String(data.get('photoUrl') || '').trim() || null,
      });
      const file = data.get('photoFile');
      if (file instanceof File && file.size > 0) profile = await api.uploadStaffPhoto(profile.id, await readPhoto(file));
      upsertStaffProfile(profile);
      form.reset();
      setShowNewStaff(false);
      notify(`${profile.name} 已新增到師傅資料庫。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '新增師傅失敗');
    } finally {
      setStaffBusy(false);
    }
  };

  const saveStaffProfile = async (event: FormEvent<HTMLFormElement>, profile: StaffProfile) => {
    event.preventDefault();
    setStaffBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      let updated = await api.updateStaff(profile.id, {
        name: String(data.get('name')).trim(),
        category: String(data.get('category')),
        photo_url: String(data.get('photoUrl') || '').trim() || null,
      });
      const file = data.get('photoFile');
      if (file instanceof File && file.size > 0) updated = await api.uploadStaffPhoto(profile.id, await readPhoto(file));
      upsertStaffProfile(updated);
      notify(`${updated.name} 的資料與照片已更新。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '師傅資料更新失敗');
    } finally {
      setStaffBusy(false);
    }
  };

  const toggleStaffProfile = async (profile: StaffProfile) => {
    const nextStatus = profile.employment_status === 'active' ? 'retired' : 'active';
    const reason = nextStatus === 'retired' ? '官網編輯器暫時退役' : '官網編輯器恢復在職';
    setStaffBusy(true);
    try {
      upsertStaffProfile(await api.updateStaffStatus(profile.id, nextStatus, reason));
      notify(`${profile.name} 已${nextStatus === 'retired' ? '暫時退役' : '恢復在職'}。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '師傅狀態更新失敗');
    } finally {
      setStaffBusy(false);
    }
  };

  const deleteStaffProfile = async (profile: StaffProfile) => {
    if (userRole !== 'admin') return notify('永久刪除只開放 Admin 使用。');
    if (!window.confirm(`確定永久刪除「${profile.name}」？\n此操作無法復原；已有訂單、排班或回帳紀錄時，系統會拒絕刪除。`)) return;
    setStaffBusy(true);
    try {
      await api.permanentlyDeleteStaff(profile.id);
      setStaffProfiles((current) => current.filter((item) => item.id !== profile.id));
      notify(`${profile.name} 已永久刪除。`);
    } catch (error) {
      notify(error instanceof Error ? error.message : '永久刪除失敗');
    } finally {
      setStaffBusy(false);
    }
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

        {active === 'services' && <div className="studio-catalog-editor">
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
            <div><Field label="方案名稱" value={service.name} onChange={(name) => updateService(index, { name })} /><Field label="列表小字簡介" value={service.summary} onChange={(summary) => updateService(index, { summary })} /><Field label="分鐘數" value={service.duration} onChange={(duration) => updateService(index, { duration })} /><Field label="價格" value={service.price} onChange={(price) => updateService(index, { price })} /></div>
          </article>)}</div>
        </div>}

        {active === 'therapists' && <div className="studio-form-grid">
          <div className="studio-form-card"><small>CATALOG</small><h3>師傅目錄設定</h3><Field label="目錄介紹" value={draft.therapists.intro} onChange={(intro) => markChanged({ ...draft, therapists: { ...draft.therapists, intro } })} multiline /><label className="studio-range"><span>自動輪播速度</span><input type="range" min="24" max="80" value={draft.therapists.carouselSpeed} onChange={(event) => markChanged({ ...draft, therapists: { ...draft.therapists, carouselSpeed: Number(event.target.value) } })} /><b>{draft.therapists.carouselSpeed} 秒</b></label><label className="studio-check"><input type="checkbox" checked={draft.therapists.showMeasurements} onChange={(event) => markChanged({ ...draft, therapists: { ...draft.therapists, showMeasurements: event.target.checked } })} />公開顯示身高與體重</label></div>
          <div className="studio-form-card studio-upload-card"><small>LIVE DIRECTORY</small><h3>公開名單</h3><div className="upload-placeholder"><span>{staffProfiles.filter((item) => item.employment_status === 'active').length}</span><b>位在職師傅</b><p>名單與照片直接保存到 MySQL；暫時退役會保留所有歷史資料並停止公開。</p></div><p className="privacy-note">健康資訊只留在營運後台，不會出現在官網編輯器或公開頁面。</p></div>
          <section className="studio-form-card studio-staff-manager">
            <header><div><small>THERAPIST PROFILES</small><h3>新增、照片與退役管理</h3><p>照片可貼網址或從電腦上傳。上傳檔案限 JPEG、PNG、WebP，最大 3 MB。</p></div><button type="button" onClick={() => setShowNewStaff((current) => !current)}>{showNewStaff ? '取消新增' : '＋ 新增師傅'}</button></header>
            {showNewStaff && <form className="studio-new-staff" onSubmit={createStaffProfile}><label><span>姓名／稱呼</span><input name="name" required /></label><label><span>分類</span><select name="category" defaultValue="gay"><option value="straight">直男師傅</option><option value="gay">圈內師傅</option><option value="bisexual">雙性師傅</option></select></label><label><span>照片網址</span><input name="photoUrl" type="url" placeholder="https://..." /></label><label><span>或上傳照片</span><input name="photoFile" type="file" accept="image/jpeg,image/png,image/webp" /></label><button type="submit" disabled={staffBusy}>建立師傅</button></form>}
            <div className="studio-staff-grid">{staffProfiles.map((profile) => <form className={profile.employment_status === 'retired' ? 'studio-staff-card retired' : 'studio-staff-card'} key={profile.id} onSubmit={(event) => saveStaffProfile(event, profile)}>
              <div className="studio-staff-photo">{profile.photo_url ? <img src={resolvePhotoUrl(profile.photo_url)} alt={`${profile.name}公開照片`} /> : <span>{profile.name.slice(0, 1)}</span>}<em>{profile.employment_status === 'active' ? '在職' : '暫時退役'}</em></div>
              <label><span>姓名</span><input name="name" defaultValue={profile.name} required /></label>
              <label><span>分類</span><select name="category" defaultValue={profile.category}>{Object.entries(categoryLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label className="wide"><span>照片網址</span><input name="photoUrl" type="url" defaultValue={resolvePhotoUrl(profile.photo_url)} placeholder="https://..." /></label>
              <label className="wide"><span>或上傳新照片</span><input name="photoFile" type="file" accept="image/jpeg,image/png,image/webp" /></label>
              <footer><button type="submit" disabled={staffBusy}>儲存資料</button><button type="button" disabled={staffBusy} onClick={() => toggleStaffProfile(profile)}>{profile.employment_status === 'active' ? '暫時退役' : '恢復在職'}</button>{userRole === 'admin' && <button className="danger" type="button" disabled={staffBusy} onClick={() => deleteStaffProfile(profile)}>永久刪除</button>}</footer>
            </form>)}</div>
            <p className="privacy-note">永久刪除只開放 Admin；已有預約、班表、付款或回帳紀錄時，後端會阻止刪除，請改用暫時退役。</p>
          </section>
        </div>}

        {active === 'offers' && <div className="studio-catalog-editor">
          <header className="studio-catalog-toolbar"><div><small>MYSQL PROMOTION CATALOG</small><h3>優惠內容</h3><p>優惠可保留在草稿或設為顯示中；刪除後舊訂單仍會保存原優惠。</p></div><button type="button" onClick={() => setShowNewOffer((current) => !current)}>{showNewOffer ? '取消新增' : '＋ 新增優惠'}</button></header>
          {showNewOffer && <form className="studio-new-catalog" onSubmit={createOffer}>
            <label><span>優惠名稱</span><input name="name" required /></label>
            <label><span>計算方式</span><select name="calculationType" defaultValue="fixed_discount"><option value="fixed_discount">固定折扣</option><option value="percent_discount">百分比折扣</option><option value="fixed_fee">固定加價</option><option value="per_30_minutes">每 30 分鐘</option><option value="per_km">每公里</option></select></label>
            <label><span>金額／百分比</span><input name="value" type="number" min="0" required /></label>
            <label className="wide"><span>簡短說明</span><input name="summary" maxLength={500} /></label>
            <button type="submit" disabled={catalogBusy}>建立優惠</button>
          </form>}
          <div className="studio-offer-editor">{draft.offers.map((offer, index) => <article key={offer.id || `${offer.name}-${index}`}><span>0{index + 1}</span><div><Field label="優惠名稱" value={offer.name} onChange={(name) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, name } : item) })} /><Field label="簡短說明" value={offer.summary} onChange={(summary) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, summary } : item) })} multiline /><label className="studio-catalog-field"><span>計算方式</span><select value={offer.calculationType || 'fixed_discount'} onChange={(event) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, calculationType: event.target.value as CalculationType } : item) })}><option value="fixed_discount">固定折扣</option><option value="percent_discount">百分比折扣</option><option value="fixed_fee">固定加價</option><option value="per_30_minutes">每 30 分鐘</option><option value="per_km">每公里</option></select></label><label className="studio-catalog-field"><span>金額／百分比</span><input type="number" min="0" value={offer.value || 0} onChange={(event) => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, value: Number(event.target.value) } : item) })} /></label></div><div className="studio-catalog-actions"><button type="button" onClick={() => markChanged({ ...draft, offers: draft.offers.map((item, itemIndex) => itemIndex === index ? { ...item, status: item.status === '顯示中' ? '草稿' : '顯示中' } : item) })}>{offer.status}</button><button className="danger" type="button" disabled={catalogBusy} onClick={() => deleteOffer(offer)}>刪除優惠</button></div></article>)}</div>
        </div>}

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
