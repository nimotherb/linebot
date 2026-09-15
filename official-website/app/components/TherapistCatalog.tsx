'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePublishedSiteDraft } from './PublishedSiteContent';

type Category = string;
type StaffCategory = { key: string; name: string; sort_order?: number };
type Therapist = { id?: number; name: string; slug: string; category: Category; categories?: string[]; height?: string | number; weight?: string | number; role?: string; bio?: string; photoUrl?: string };

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '');
const therapistOrderStorageKey = 'equalspa:therapist-order:v1';

function imagePath(therapist: Therapist) {
  if (therapist.photoUrl) return therapist.photoUrl.startsWith('/') ? `${apiBaseUrl}${therapist.photoUrl}` : therapist.photoUrl;
  return '';
}

function therapistBookingUrl(baseUrl: string, therapist: Therapist) {
  const query = new URLSearchParams({ source: 'official', staff_name: therapist.name });
  if (therapist.id) query.set('staff_id', String(therapist.id));
  const hashIndex = baseUrl.indexOf('#');
  const urlWithoutHash = hashIndex >= 0 ? baseUrl.slice(0, hashIndex) : baseUrl;
  const hash = hashIndex >= 0 ? baseUrl.slice(hashIndex) : '';
  return `${urlWithoutHash}${urlWithoutHash.includes('?') ? '&' : '?'}${query.toString()}${hash}`;
}

function shuffle<T>(items: T[]) {
  const shuffled = [...items];
  for (let index = shuffled.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
  }
  return shuffled;
}

function orderTherapists(items: Therapist[]) {
  const identified = items.filter((item) => item.id !== undefined && item.id !== null);
  if (!identified.length || typeof window === 'undefined') return items;

  const byId = new Map(identified.map((item) => [String(item.id), item]));
  const apiIds = identified.map((item) => String(item.id));
  const today = new Date().toLocaleDateString('en-CA');
  let cachedIds: string[] = [];
  try {
    const cached = JSON.parse(window.localStorage.getItem(therapistOrderStorageKey) || 'null') as { date?: string; ids?: unknown } | null;
    if (cached?.date === today && Array.isArray(cached.ids)) {
      cachedIds = cached.ids.map(String).filter((id, index, ids) => byId.has(id) && ids.indexOf(id) === index);
    }
  } catch {
    cachedIds = [];
  }

  const orderedIds = cachedIds.length ? cachedIds : shuffle(apiIds);
  const knownIds = new Set(orderedIds);
  const newIds = apiIds.filter((id) => !knownIds.has(id));
  const finalIds = [...orderedIds, ...newIds];
  try {
    window.localStorage.setItem(therapistOrderStorageKey, JSON.stringify({ date: today, ids: finalIds }));
  } catch {
    // Private browsing or storage limits should not prevent the directory from rendering.
  }

  return [...finalIds.map((id) => byId.get(id)).filter((item): item is Therapist => Boolean(item)), ...items.filter((item) => item.id === undefined || item.id === null)];
}

export default function TherapistCatalog() {
  const [category, setCategory] = useState<'all' | Category>('all');
  const [profiles, setProfiles] = useState<Therapist[]>([]);
  const [categories, setCategories] = useState<StaffCategory[]>([]);
  const [loadError, setLoadError] = useState('');
  const siteContent = usePublishedSiteDraft();
  const therapistSettings = siteContent?.therapists;
  const bookingUrl = siteContent?.booking?.url || '';
  const categoryMeta = useMemo(() => Object.fromEntries(categories.map((item) => [item.key, { label: item.name, english: item.key.toUpperCase() }])), [categories]) as Record<string, { label: string; english: string }>;
  useEffect(() => {
    Promise.all([
      fetch(`${apiBaseUrl}/api/public/therapists`).then((response) => response.ok ? response.json() : Promise.reject(new Error('therapist api unavailable'))),
      fetch(`${apiBaseUrl}/api/public/staff-categories`).then((response) => response.ok ? response.json() : Promise.reject(new Error('category api unavailable'))),
    ])
      .then(([items, categoryRows]: [Array<{ id: number; name: string; category?: string; categories?: string[]; height?: string; weight?: string; role?: string; bio?: string; photo_url?: string }>, StaffCategory[]]) => {
        const mapped = items.map((item) => ({
          id: item.id,
          name: item.name,
          slug: `staff-${item.id}`,
          category: item.category || item.categories?.[0] || '',
          categories: item.categories || (item.category ? [item.category] : []),
          height: item.height,
          weight: item.weight,
          role: item.role,
          bio: item.bio,
          photoUrl: item.photo_url,
        } as Therapist));
        setCategories(categoryRows.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0)));
        setProfiles(orderTherapists(mapped));
      })
      .catch((error) => { setProfiles([]); setCategories([]); setLoadError(error instanceof Error ? error.message : '服務團隊資料暫時無法取得'); });
  }, []);
  const visible = useMemo(() => category === 'all' ? profiles : profiles.filter((item) => (item.categories || [item.category]).includes(category)), [category, profiles]);
  const categoryText = (therapist: Therapist) => (therapist.categories || [therapist.category]).map((key) => categoryMeta[key]?.english || key).filter(Boolean).join(' · ') || 'PROFILE';

  const portrait = (therapist: Therapist, alt: string) => imagePath(therapist)
    ? <img src={imagePath(therapist)} alt={alt} loading="lazy" />
    : <span className="portrait-monogram" aria-label={alt}>{therapist.name.slice(0, 1)}</span>;

  const portraitSet = (duplicate = false) => <div className="portrait-set" aria-hidden={duplicate || undefined}>{visible.map((therapist) => <article className="portrait-product" key={`${therapist.category}-${therapist.slug}-${duplicate ? 'copy' : 'original'}`}>
    <div className="portrait-frame">{portrait(therapist, duplicate ? '' : `${therapist.name}師傅公開形象照`)}</div>
    <div><small>{categoryText(therapist)}</small><h3>{therapist.name}</h3></div>
  </article>)}</div>;

  return <>
    <section className="therapist-selector" aria-label="選擇師傅分類">
      <div className="catalog-intro"><small>SELECT YOUR MATCH</small><h2>ONE STANDARD.<br />DIFFERENT PRESENCE.</h2><p>{therapistSettings?.intro || '服務團隊內容由後台發布。'}<br />公開頁面只呈現已發布的公開資料。</p></div>
      <div className="category-tabs">
        <button className={category === 'all' ? 'active' : ''} onClick={() => setCategory('all')}><span>00</span><b>全部師傅</b><em>ALL</em></button>
        {categories.map((item, index) => <button key={item.key} className={category === item.key ? 'active' : ''} onClick={() => setCategory(item.key)}><span>{String(index + 1).padStart(2, '0')}</span><b>{item.name}</b><em>{item.key.toUpperCase()}</em></button>)}
      </div>
    </section>

    <section className="therapist-carousel" aria-label="師傅照片輪播">
      <header><div><small>PORTRAIT RAIL</small><p>{category === 'all' ? 'ALL THERAPISTS' : categoryMeta[category]?.english || category}</p></div><span>CONTINUOUS AUTOMATIC LOOP</span></header>
      <div className="portrait-rail"><div key={category} className="portrait-track">{portraitSet()}{portraitSet(true)}</div></div>
    </section>

    <section className="therapist-catalog" aria-live="polite">
      <header><small>CATALOG / {visible.length} PROFILES</small><h2>THERAPIST<br />SELECTION.</h2></header>
        {loadError && <div className="updating-card"><span>THERAPISTS</span><h2>資料暫時無法取得</h2><p>{loadError}，請稍後重新整理。</p></div>}
        {!loadError && visible.length === 0 && <div className="updating-card"><span>THERAPISTS</span><h2>內容更新中</h2><p>目前尚未發布服務團隊資料。</p></div>}
        <div className="therapist-product-grid">{visible.map((therapist) => <article key={`${therapist.category}-${therapist.slug}`}>
        <div className="therapist-product-image">{portrait(therapist, `${therapist.name}師傅`)}</div>
        <div className="therapist-product-copy"><small>{categoryText(therapist)}</small><h3>{therapist.name}</h3>{therapistSettings?.showMeasurements !== false && (therapist.height || therapist.weight || therapist.role) && <dl>{therapist.height && <div><dt>HEIGHT</dt><dd>{therapist.height} CM</dd></div>}{therapist.weight && <div><dt>WEIGHT</dt><dd>{therapist.weight} KG</dd></div>}{therapist.role && <div><dt>ROLE</dt><dd>{therapist.role}</dd></div>}</dl>}{therapist.bio && <p>{therapist.bio}</p>}{bookingUrl && <a href={therapistBookingUrl(bookingUrl, therapist)} target="_blank" rel="noreferrer">指定 {therapist.name}／送出預約通知 ↗</a>}</div>
      </article>)}</div>
    </section>
  </>;
}
