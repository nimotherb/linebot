import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import TherapistCatalog from '../components/TherapistCatalog';
import { PointerLight, SiteHeader, WingMenu } from '../components/WingMenu';

const pageMeta = {
  about: ['ABOUT', '關於伊果', '平等而細緻，讓每一種身體都能自在被理解。'],
  services: ['SERVICES', '選擇今天需要的節奏', '從六十分鐘的精準釋放，到完整兩小時的深度整理。'],
  therapists: ['THERAPISTS', '選擇適合你的師傅', '不同氣質與手法，都遵循相同的專業與界線。'],
  offers: ['OFFERS', '期間限定企劃', '優惠內容隨期間更新，預約前可由 LINE 客服確認。'],
  location: ['LOCATION', '歡迎來到西門', '台北西門町，從抵達開始放慢速度。'],
  recruit: ['RECRUIT', '與伊果一起工作', '一起建立舒服、尊重且長久的工作關係。'],
  groups: ['GROUP', '社群內容準備中', '最新社群資訊與活動整理。'],
  loyalty: ['LOYALTY', '回訪計畫準備中', '為熟悉伊果的你，準備更完整的回訪體驗。'],
  privacy: ['PRIVACY', '你的資料，我們謹慎對待', '只在提供服務所需的範圍內使用資料。'],
} as const;

const plans = [
  {
    code: 'A', name: '舒壓方案', english: 'ESSENTIAL RESET', duration: '60 MIN', price: 'NT$ 1,500',
    tags: ['不指定師傅', '指壓／油壓擇一', '10:00—24:00'],
    lead: '把選擇交給當日最適合的專業，換回一小時純粹而直接的身體釋放。',
    paragraphs: ['A 方案從「不指定師傅」開始，讓客服依照班表安排當下最合適的人選。你只需要在指壓與油壓之間選擇：前者以穩定而清晰的力道處理緊繃，後者以連續滑順的節奏把疲憊向外推開。', '六十分鐘不放入體推與機能保養，所有時間都集中在最基本、也最容易被忽略的放鬆。適合第一次到訪、臨時想休息，或已經清楚知道今天只需要一件事——讓身體鬆下來。'],
  },
  {
    code: 'B', name: '愉悅方案', english: 'SENSORY FLOW', duration: '60 MIN', price: 'NT$ 2,000',
    tags: ['可指定師傅', '指壓／油壓擇一', '體推', '機能保養'],
    lead: '從選定熟悉的氣質開始，讓短短一小時擁有更完整、更貼近個人偏好的層次。',
    paragraphs: ['B 方案讓你指定師傅，也讓溝通在服務開始前就更精準。指壓或油壓擇一作為主軸，再加入體推與機能保養；每一段接觸都不是堆疊項目，而是為下一個感受預留位置。', '這是一段緊湊但不倉促的安排。技師會依照身體回饋調整力道與停留，不浪費時間試探，也不急著收尾。適合想在有限時間內，同時獲得深度放鬆與完整互動的人。'],
  },
  {
    code: 'C', name: '享受方案', english: 'DEEP RELEASE', duration: '90 MIN', price: 'NT$ 2,500',
    tags: ['可指定師傅', '指壓', '油壓', '體推', '機能保養'],
    lead: '多出的三十分鐘，不只是延長；它讓力道、溫度與節奏終於不必彼此讓步。',
    paragraphs: ['九十分鐘讓師傅有足夠空間從指壓建立深度，再以油壓拉長放鬆的餘韻。體推與機能保養自然穿插其中，身體不需要在剛適應時就被迫進入下一階段。', '這個方案適合累積疲憊、需要更細緻照顧，或希望服務具有明確起伏的人。前段處理重量，中段打開活動感，後段把速度放慢；完整，但仍保留讓人意猶未盡的分寸。'],
  },
  {
    code: 'D', name: '極緻方案', english: 'FULL PROTOCOL', duration: '120 MIN', price: 'NT$ 3,000',
    tags: ['可指定師傅', '指壓', '油壓', '體推', '機能保養'],
    lead: '兩個小時，讓所有手法有足夠時間展開，也讓身體真正離開原本緊繃的速度。',
    paragraphs: ['D 方案把指壓、油壓、體推與機能保養編排成完整序列。師傅不需要壓縮轉場，可以先讀懂緊繃的位置，再逐步改變力道、接觸面積與速度；每個階段都有目的，也有足夠的停留。', '適合想要完整體驗、長時間工作後需要全面整理，或希望與指定師傅建立更精準默契的人。這不是把一小時複製兩次，而是一次從深到淺、從集中到延展的完整服務。'],
  },
  {
    code: 'OUT', name: '隨享外出方案', english: 'PRIVATE VISIT', duration: '100 MIN', price: 'NT$ 3,200',
    tags: ['可指定師傅', '完整手法', '3 KM 內免外出費', '預約制'],
    lead: '把熟悉的空間留給自己，讓師傅帶著完整手法抵達你選擇的地點。',
    paragraphs: ['外出方案提供一百分鐘完整服務，由你指定師傅與地點，再由客服確認交通與時段。指壓、油壓、體推與機能保養可依現場空間及需求安排，減少移動後重新整理狀態的過程。', '以獅子林大樓為中心，Google 地圖距離三公里內免收外出費；超過三公里後，每公里加收 NT$ 80。適合重視隱私、偏好熟悉空間，或希望服務結束後直接休息的人。'],
  },
] as const;

function AboutContent() {
  return <>
    <div className="manifesto"><p>EQUAL 不是口號，而是我們安排每一次服務的起點。</p><p>每個人都能自在選擇適合自己的服務，也在被理解與尊重的空間裡，重新找回身體的節奏。清楚的方案、公開的價格與可被確認的界線，讓舒服不必建立在猜測上。</p></div>
    <div className="value-grid"><article><span>01</span><h2>EQUALITY</h2><p>不預設、不評價，讓每位來訪者都能被好好接住。</p></article><article><span>02</span><h2>PRECISION</h2><p>清楚說明方案與時間，讓需求被準確理解。</p></article><article><span>03</span><h2>EASE</h2><p>像回到熟悉的地方，安靜放下今天累積的重量。</p></article></div>
  </>;
}

function ServicesContent() {
  return <>
    <div className="service-overview"><small>FIVE WAYS TO RESET</small><p>所有方案皆可於每日 10:00—24:00 洽詢預約。A、B 兩個六十分鐘方案為指壓或油壓擇一；其餘方案依內容安排完整手法。實際流程會由師傅依身體回饋微調。</p></div>
    <div className="service-journeys">{plans.map((plan, index) => <article key={plan.code} className="service-journey">
      <header><span>{String(index + 1).padStart(2, '0')}</span><i>{plan.code}</i><div><small>{plan.english}</small><h2>{plan.name}</h2></div><p>{plan.duration}</p><strong>{plan.price}</strong></header>
      <div className="service-journey-body"><h3>{plan.lead}</h3><div className="service-prose">{plan.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}</div><ul>{plan.tags.map((tag) => <li key={tag}>{tag}</li>)}</ul><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">SELECT THIS PLAN ↗</a></div>
    </article>)}</div>
    <div className="service-notes"><h2>BOOKING NOTES</h2><dl><div><dt>午夜加成</dt><dd>00:00—06:00 · NT$ 600</dd></div><div><dt>預約時加時</dt><dd>每 30 分鐘 NT$ 500</dd></div><div><dt>現場加時</dt><dd>每 30 分鐘 NT$ 700</dd></div><div><dt>外出交通</dt><dd>超過 3 公里，每公里 NT$ 80</dd></div></dl><p>客服值班時間為每日 10:00—24:00；其他時段的服務請在客服值班時間內提前完成預約。方案、師傅與優惠可能調整，最終內容以 LINE 客服確認為準。</p></div>
  </>;
}

function TherapistsContent() { return <TherapistCatalog />; }

function OffersContent() {
  const offers = [['BIRTHDAY', '生日月優惠', '在生日月替自己留一段完整的休息時間。'], ['NEW FACE', '新進師傅體驗', '認識不同手法與節奏，找到更適合自己的選擇。'], ['WEEKDAY', '平日時段精選', '避開繁忙時段，享受更安靜從容的體驗。']] as const;
  return <div className="offer-grid">{offers.map(([tag, title, copy], index) => <article key={tag}><span>0{index + 1}</span><small>{tag}</small><h2>{title}</h2><p>{copy}</p><em>填充預覽內容</em><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">向 LINE 客服確認 ↗</a></article>)}</div>;
}

function LocationContent() {
  return <div className="location-layout"><div className="location-details"><small>STUDIO INFORMATION</small><h2>伊果 SPA · 西門</h2><dl><div><dt>地址</dt><dd>台北市萬華區西寧南路 36 號</dd></div><div><dt>營業時間</dt><dd>每日 10:00—24:00</dd></div><div><dt>預約</dt><dd>LINE @017ktlhm</dd></div><div><dt>聯絡信箱</dt><dd>—</dd></div><div><dt>付款</dt><dd>現金、轉帳</dd></div></dl><a className="outline-link" href="https://www.google.com/maps/search/?api=1&query=%E5%8F%B0%E5%8C%97%E5%B8%82%E8%90%AC%E8%8F%AF%E5%8D%80%E8%A5%BF%E5%AF%A7%E5%8D%97%E8%B7%AF36%E8%99%9F" target="_blank" rel="noreferrer">OPEN IN GOOGLE MAPS ↗</a></div><div className="map-embed"><iframe src="https://www.google.com/maps/d/u/1/embed?mid=1141UqP4pbf1EG49i-Z6_c18pC2EplKQ&ehbc=2E312F&noprof=1" width="640" height="480" title="伊果 SPA Google 地圖" loading="lazy" referrerPolicy="no-referrer-when-downgrade" /></div></div>;
}

function RecruitContent() {
  return <div className="recruit-layout"><div className="manifesto"><p>WORK WITH EQUAL.</p><p>我們重視專業、誠實溝通與彼此尊重。招募資訊與聯絡信箱目前整理中；正式公開前不會顯示個人聯絡方式。</p></div><div className="recruit-card"><small>CURRENT STATUS</small><h2>內容更新中</h2><p>之後會在這裡放置職缺內容、合作方式、基本條件與聯絡管道。</p><dl><div><dt>職缺</dt><dd>—</dd></div><div><dt>聯絡信箱</dt><dd>—</dd></div></dl></div></div>;
}

function UpdatingContent({ type }: { type: 'groups' | 'loyalty' }) {
  return <div className="updating-card"><span>{type === 'groups' ? 'GROUP' : 'LOYALTY'}</span><div className="update-orbit"><i>UPDATE</i></div><h2>COMING SOON</h2><p>{type === 'groups' ? '群組入口與使用說明將在確認後公開。' : '酬賓資格、回饋方式與使用規則正在整理中。'}</p><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">先詢問 LINE 客服 ↗</a></div>;
}

function PrivacyContent() {
  return <div className="privacy-copy"><h2>DATA USE</h2><p>伊果 SPA 僅在回覆諮詢、安排預約與完成服務所需的範圍內使用顧客提供的資料。未經同意，不會把資料用於無關用途。</p><h2>LINE & BOOKING</h2><p>透過 LINE 提供的顯示名稱、聯絡方式及預約內容，可能保存於營運系統中，以便客服確認與服務追蹤。</p><h2>YOUR RIGHTS</h2><p>若需查詢、更正或刪除資料，請透過 LINE 預約客服 @017ktlhm 聯絡。</p></div>;
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

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  if (!(slug in pageMeta)) return {};
  const [english, title, intro] = pageMeta[slug as keyof typeof pageMeta];
  const pageTitle = `${english}｜${title}｜伊果 SPA`;
  return {
    title: pageTitle,
    description: intro,
    alternates: { canonical: `/${slug}` },
    openGraph: { title: pageTitle, description: intro, images: [] },
    twitter: { title: pageTitle, description: intro, images: [] },
  };
}

export default async function ContentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!(slug in pageMeta)) notFound();
  const typedSlug = slug as keyof typeof pageMeta;
  const [english, title, intro] = pageMeta[typedSlug];
  return <main className={`interior-shell page-${typedSlug}`}><PointerLight /><SiteHeader /><article className="interior-page"><header className="page-title"><p>EQUAL SPA / {String(Object.keys(pageMeta).indexOf(typedSlug) + 1).padStart(2, '0')}</p><h1>{english}</h1><div><h2>{title}</h2><span>{intro}</span></div></header><section className="page-content"><PageContent slug={typedSlug} /></section><footer className="site-footer"><div><b>伊果 SPA</b><span>EQUAL SPA · TAIPEI XIMEN</span></div><a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">LINE @017ktlhm</a><small>© {new Date().getFullYear()} EQUAL SPA</small></footer></article><WingMenu /></main>;
}
