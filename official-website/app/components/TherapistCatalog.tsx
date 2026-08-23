'use client';

import { type CSSProperties, useMemo, useState } from 'react';

type Category = 'straight' | 'community' | 'bisexual';
type Therapist = { name: string; slug: string; category: Category; height: number; weight: number };

const categoryMeta: Record<Category, { label: string; english: string; note: string }> = {
  straight: { label: '直男師傅', english: 'STRAIGHT', note: '自然俐落，保留舒服距離的專業互動。' },
  community: { label: '圈內師傅', english: 'COMMUNITY', note: '熟悉多元需求，讓溝通更直接、更自在。' },
  bisexual: { label: '雙性師傅', english: 'BISEXUAL', note: '開放而細膩，提供另一種柔韌平衡的節奏。' },
};

const bookingUrl = 'https://equalspa-ops-preview.c83500699.chatgpt.site/booking';

const therapists: Therapist[] = [
  { name: 'Eason', slug: 'eason', category: 'straight', height: 180, weight: 72 },
  { name: 'Show', slug: 'show', category: 'straight', height: 187, weight: 82 },
  { name: '霍爾', slug: 'hol', category: 'straight', height: 174, weight: 63 },
  { name: '小六', slug: 'xiaoliu', category: 'straight', height: 170, weight: 60 },
  { name: '吳樂', slug: 'wule', category: 'straight', height: 173, weight: 75 },
  { name: '小馬', slug: 'xiaoma', category: 'straight', height: 180, weight: 75 },
  { name: 'Frank', slug: 'frank', category: 'straight', height: 178, weight: 70 },
  { name: '捷程', slug: 'jiecheng', category: 'straight', height: 175, weight: 82 },
  { name: 'Jun', slug: 'jun', category: 'straight', height: 176, weight: 76 },
  { name: '小猴', slug: 'xiaohou', category: 'straight', height: 175, weight: 69 },
  { name: '小虎', slug: 'xiaohu', category: 'straight', height: 182, weight: 79 },
  { name: '白羊', slug: 'baiyang', category: 'straight', height: 170, weight: 52 },
  { name: '佐恩', slug: 'zuoen', category: 'straight', height: 178, weight: 60 },
  { name: '宇森', slug: 'yusen', category: 'straight', height: 180, weight: 84 },
  { name: 'Harry', slug: 'harry', category: 'community', height: 170, weight: 56 },
  { name: '士羽', slug: 'shiyu', category: 'community', height: 172, weight: 73 },
  { name: '瑞奇', slug: 'ricky', category: 'community', height: 172, weight: 56 },
  { name: '朗', slug: 'lang', category: 'community', height: 185, weight: 81 },
  { name: 'Jack', slug: 'jack', category: 'community', height: 167, weight: 58 },
  { name: 'Max', slug: 'max', category: 'community', height: 176, weight: 70 },
  { name: '泠', slug: 'ling', category: 'community', height: 173, weight: 65 },
  { name: '阿焰', slug: 'ayan', category: 'community', height: 177, weight: 65 },
  { name: 'Jacob', slug: 'jacob', category: 'community', height: 185, weight: 80 },
  { name: '華', slug: 'hua', category: 'community', height: 177, weight: 68 },
  { name: '武', slug: 'wu', category: 'community', height: 174, weight: 72 },
  { name: 'Seven', slug: 'seven', category: 'community', height: 177, weight: 67 },
  { name: '小柏', slug: 'xiaobai', category: 'community', height: 175, weight: 78 },
  { name: 'Wilson', slug: 'wilson', category: 'community', height: 177, weight: 77 },
  { name: 'Wayne', slug: 'wayne', category: 'community', height: 178, weight: 70 },
  { name: '路卡', slug: 'luka', category: 'community', height: 157, weight: 56 },
  { name: 'Erik', slug: 'erik', category: 'community', height: 163, weight: 53 },
  { name: 'Mars', slug: 'mars', category: 'community', height: 175, weight: 80 },
  { name: 'ED', slug: 'ed', category: 'community', height: 178, weight: 71 },
  { name: '萊伊', slug: 'lai', category: 'community', height: 185, weight: 75 },
  { name: 'Alex', slug: 'alex', category: 'community', height: 180, weight: 74 },
  { name: 'Fali', slug: 'fali', category: 'community', height: 180, weight: 64 },
  { name: '伊恩', slug: 'ian', category: 'community', height: 169, weight: 58 },
  { name: 'Zane', slug: 'zane', category: 'community', height: 174, weight: 70 },
  { name: 'Eden', slug: 'eden', category: 'community', height: 173, weight: 70 },
  { name: '沐恩', slug: 'muen', category: 'bisexual', height: 172, weight: 66 },
  { name: '阿玄', slug: 'axuan', category: 'bisexual', height: 175, weight: 59 },
  { name: '尼爾', slug: 'neil', category: 'bisexual', height: 178, weight: 75 },
  { name: '彥', slug: 'yan', category: 'bisexual', height: 175, weight: 79 },
  { name: '承承', slug: 'chengcheng', category: 'bisexual', height: 170, weight: 55 },
  { name: '小安', slug: 'xiaoan', category: 'bisexual', height: 173, weight: 58 },
  { name: '小羅', slug: 'xiaoluo', category: 'bisexual', height: 183, weight: 68 },
  { name: '可樂', slug: 'kele', category: 'bisexual', height: 170, weight: 60 },
];

function imagePath(therapist: Therapist) {
  return `/images/therapists/${therapist.category}/${therapist.slug}.png`;
}

export default function TherapistCatalog() {
  const [category, setCategory] = useState<'all' | Category>('all');
  const visible = useMemo(() => category === 'all' ? therapists : therapists.filter((item) => item.category === category), [category]);

  const portraitSet = (duplicate = false) => <div className="portrait-set" aria-hidden={duplicate || undefined}>{visible.map((therapist, index) => <article className="portrait-product" key={`${therapist.category}-${therapist.slug}-${duplicate ? 'copy' : 'original'}`}>
    <div className="portrait-frame"><img src={imagePath(therapist)} alt={duplicate ? '' : `${therapist.name}師傅公開形象照`} loading={duplicate || index >= 5 ? 'lazy' : 'eager'} /></div>
    <span>{String(index + 1).padStart(2, '0')}</span><div><small>{categoryMeta[therapist.category].english}</small><h3>{therapist.name}</h3></div>
  </article>)}</div>;

  return <>
    <section className="therapist-selector" aria-label="選擇師傅分類">
      <div className="catalog-intro"><small>SELECT YOUR MATCH</small><h2>ONE STANDARD.<br />DIFFERENT PRESENCE.</h2><p>先從偏好的互動氣質開始，再於預約時確認當週班表。公開頁面只呈現姓名、身高體重與照片；健康資訊保留在內部管理系統。</p></div>
      <div className="category-tabs">
        <button className={category === 'all' ? 'active' : ''} onClick={() => setCategory('all')}><span>00</span><b>全部師傅</b><em>ALL</em></button>
        {(Object.keys(categoryMeta) as Category[]).map((key, index) => <button key={key} className={category === key ? 'active' : ''} onClick={() => setCategory(key)}><span>0{index + 1}</span><b>{categoryMeta[key].label}</b><em>{categoryMeta[key].english}</em></button>)}
      </div>
    </section>

    <section className="therapist-carousel" aria-label="師傅照片輪播">
      <header><div><small>PORTRAIT RAIL</small><p>{category === 'all' ? 'ALL THERAPISTS' : categoryMeta[category].english}</p></div><span>AUTOMATIC LOOP · PAUSE ON HOVER</span></header>
      <div className="portrait-rail"><div key={category} className="portrait-track" style={{ '--rail-duration': `${Math.max(34, visible.length * 2.8)}s` } as CSSProperties}>{portraitSet()}{portraitSet(true)}</div></div>
    </section>

    <section className="therapist-catalog" aria-live="polite">
      <header><small>CATALOG / {visible.length} PROFILES</small><h2>THERAPIST<br />SELECTION.</h2></header>
      <div className="therapist-product-grid">{visible.map((therapist, index) => <article key={`${therapist.category}-${therapist.slug}`}>
        <div className="therapist-product-image"><img src={imagePath(therapist)} alt={`${therapist.name}師傅`} loading="lazy"/><span>{String(index + 1).padStart(2, '0')}</span></div>
        <div className="therapist-product-copy"><small>{categoryMeta[therapist.category].english}</small><h3>{therapist.name}</h3><dl><div><dt>HEIGHT</dt><dd>{therapist.height} CM</dd></div><div><dt>WEIGHT</dt><dd>{therapist.weight} KG</dd></div></dl><p>{categoryMeta[therapist.category].note}</p><a href={bookingUrl} target="_blank" rel="noreferrer">詢問班表／指定預約 ↗</a></div>
      </article>)}</div>
    </section>
  </>;
}
