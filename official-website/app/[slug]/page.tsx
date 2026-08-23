import { notFound } from 'next/navigation';
import { PointerLight, SiteHeader, WingMenu } from '../components/WingMenu';

const pageMeta = {
  about: ['ABOUT', '關於伊果', 'Equal care, made personal.'],
  services: ['SERVICES', '服務項目', '從一小時到完整的兩小時，依照今天的身體選擇。'],
  therapists: ['THERAPISTS', '專業師傅', '不同風格，同一份對專業與界線的重視。'],
  offers: ['OFFERS', '最新優惠', '優惠內容會隨期間更新，預約前可由 LINE 客服確認。'],
  location: ['LOCATION', '交通資訊', '台北西門町，從抵達開始放慢速度。'],
  recruit: ['RECRUIT', '人才招募', '一起建立舒服、尊重且長久的工作關係。'],
  groups: ['GROUP', '群組', '最新社群資訊與活動整理。'],
  loyalty: ['LOYALTY', '酬賓計畫', '為熟悉伊果的你，準備更完整的回訪體驗。'],
  privacy: ['PRIVACY', '隱私權', '我們只在提供服務所需的範圍內使用資料。'],
} as const;

const plans = [
  ['A', '舒壓方案', '60 分鐘', 'NT$ 1,500'],
  ['B', '愉悅方案', '60 分鐘', 'NT$ 2,000'],
  ['C', '深度方案', '90 分鐘', 'NT$ 2,500'],
  ['D', '完整方案', '120 分鐘', 'NT$ 3,000'],
  ['OUT', '外出方案', '100 分鐘', 'NT$ 3,200'],
] as const;

function AboutContent() {
  return <>
    <div className="manifesto"><p>我們相信，舒服不需要被定義成同一種樣子。</p><p>「EQUAL」代表平等——每個人都能自在選擇適合自己的服務，也在被理解與尊重的空間裡，重新找回身體的節奏。</p></div>
    <div className="value-grid"><article><span>01</span><h2>平等</h2><p>不預設、不評價，讓每位來訪者都能被好好接住。</p></article><article><span>02</span><h2>專業</h2><p>清楚說明方案與時間，尊重需求，也尊重彼此界線。</p></article><article><span>03</span><h2>自在</h2><p>像回到熟悉的地方，安靜放下今天累積的重量。</p></article></div>
  </>;
}

function ServicesContent() {
  return <>
    <div className="plan-list">{plans.map(([code, name, duration, price]) => <article key={code}><span>{code}</span><h2>{name}</h2><p>{duration}</p><strong>{price}</strong><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">選擇此方案 ↗</a></article>)}</div>
    <div className="service-notes"><h2>預約前請留意</h2><dl><div><dt>午夜加成</dt><dd>NT$ 600</dd></div><div><dt>預約前加時</dt><dd>每 30 分鐘 NT$ 500</dd></div><div><dt>現場加時</dt><dd>每 30 分鐘 NT$ 700</dd></div><div><dt>外出交通</dt><dd>超過 3 公里，每公里 NT$ 80</dd></div></dl><p>方案與優惠可能調整，最終內容以 LINE 預約客服確認為準。</p></div>
  </>;
}

function TherapistsContent() {
  const groups = [['STRAIGHT', '直男師傅', '自然、俐落的互動節奏'], ['COMMUNITY', '圈內師傅', '熟悉需求，也重視細節'], ['BISEXUAL', '雙性師傅', '開放、多元且自在的選擇']] as const;
  return <><div className="therapist-groups">{groups.map(([en, zh, copy], index) => <article key={en}>
    {/* TODO_IMAGE: 換成這個分類的師傅實拍照，建議直式 4:5；健康資訊不可放在公開圖片或文字。 */}
    <div className={`portrait-placeholder portrait-${index + 1}`}><span>{String(index + 1).padStart(2, '0')}</span><i>PHOTO<br />COMING SOON</i></div>
    <div><small>{en}</small><h2>{zh}</h2><p>{copy}</p><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">詢問本週班表 ↗</a></div>
  </article>)}</div><p className="privacy-note">師傅個人健康資訊僅供內部管理，不會顯示於公開網站。實際出勤與可預約時間請洽 LINE 客服。</p></>;
}

function OffersContent() {
  const offers = [['BIRTHDAY', '生日月優惠', '在生日月替自己留一段完整的休息時間。'], ['NEW FACE', '新進師傅體驗', '認識不同手法與節奏，找到更適合自己的選擇。'], ['WEEKDAY', '平日時段精選', '避開繁忙時段，享受更安靜從容的體驗。']] as const;
  return <div className="offer-grid">{offers.map(([tag, title, copy], index) => <article key={tag}><span>0{index + 1}</span><small>{tag}</small><h2>{title}</h2><p>{copy}</p><em>填充預覽內容</em><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">向 LINE 客服確認 ↗</a></article>)}</div>;
}

function LocationContent() {
  return <div className="location-layout"><div className="location-details"><h2>伊果 SPA · 西門</h2><dl><div><dt>地址</dt><dd>台北市萬華區西寧南路 36 號</dd></div><div><dt>營業時間</dt><dd>10:00—24:00</dd></div><div><dt>預約</dt><dd>LINE @017ktlhm</dd></div><div><dt>聯絡信箱</dt><dd>—</dd></div><div><dt>付款</dt><dd>現金、轉帳</dd></div></dl><a className="outline-link" href="https://www.google.com/maps/search/?api=1&query=%E5%8F%B0%E5%8C%97%E5%B8%82%E8%90%AC%E8%8F%AF%E5%8D%80%E8%A5%BF%E5%AF%A7%E5%8D%97%E8%B7%AF36%E8%99%9F" target="_blank" rel="noreferrer">開啟 Google Maps ↗</a></div><div className="map-card" aria-label="西門店位置示意"><div className="map-streets"/><span className="map-pin">E</span><b>西門町<br />XIMEN</b><small>TODO_MAP · 可替換成正式地圖圖片</small></div></div>;
}

function RecruitContent() {
  return <div className="recruit-layout"><div className="manifesto"><p>我們重視專業、誠實溝通與彼此尊重。</p><p>招募資訊與聯絡信箱目前整理中；正式公開前不會顯示個人聯絡方式。</p></div><div className="recruit-card"><small>CURRENT STATUS</small><h2>招募內容更新中</h2><p>之後會在這裡放置職缺內容、合作方式、基本條件與聯絡管道。</p><dl><div><dt>職缺</dt><dd>—</dd></div><div><dt>聯絡信箱</dt><dd>—</dd></div></dl></div></div>;
}

function UpdatingContent({ type }: { type: 'groups' | 'loyalty' }) {
  return <div className="updating-card"><span>{type === 'groups' ? 'GROUP' : 'LOYALTY'}</span><div className="update-orbit"><i>UPDATE</i></div><h2>內容更新中</h2><p>{type === 'groups' ? '群組入口與使用說明將在確認後公開。' : '酬賓資格、回饋方式與使用規則正在整理中。'}</p><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">先詢問 LINE 客服 ↗</a></div>;
}

function PrivacyContent() {
  return <div className="privacy-copy"><h2>資料使用原則</h2><p>伊果 SPA 僅在回覆諮詢、安排預約與完成服務所需的範圍內使用顧客提供的資料。未經同意，不會把資料用於無關用途。</p><h2>LINE 與預約紀錄</h2><p>透過 LINE 提供的顯示名稱、聯絡方式及預約內容，可能保存於營運系統中，以便客服確認與服務追蹤。</p><h2>聯絡我們</h2><p>若需查詢、更正或刪除資料，請透過 LINE 預約客服 @017ktlhm 聯絡。</p></div>;
}

function PageContent({ slug }: { slug: keyof typeof pageMeta }) {
  if (slug === 'about') return <AboutContent />;
  if (slug === 'services') return <ServicesContent />;
  if (slug === 'therapists') return <TherapistsContent />;
  if (slug === 'offers') return <OffersContent />;
  if (slug === 'location') return <LocationContent />;
  if (slug === 'recruit') return <RecruitContent />;
  if (slug === 'groups' || slug === 'loyalty') return <UpdatingContent type={slug} />;
  return <PrivacyContent />;
}

export function generateStaticParams() { return Object.keys(pageMeta).map((slug) => ({ slug })); }

export default async function ContentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!(slug in pageMeta)) notFound();
  const typedSlug = slug as keyof typeof pageMeta;
  const [english, title, intro] = pageMeta[typedSlug];
  return <main className={`interior-shell page-${typedSlug}`}><PointerLight /><SiteHeader /><article className="interior-page"><header className="page-title"><p>{english}</p><h1>{title}</h1><span>{intro}</span></header><section className="page-content"><PageContent slug={typedSlug} /></section><footer className="site-footer"><div><b>伊果 SPA</b><span>EQUAL SPA · TAIPEI XIMEN</span></div><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">LINE @017ktlhm</a><small>© {new Date().getFullYear()} EQUAL SPA</small></footer></article><WingMenu /></main>;
}
