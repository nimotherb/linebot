'use client';

import { PointerLight, SiteHeader, WingMenu } from './components/WingMenu';
import { usePublishedSiteDraft } from './components/PublishedSiteContent';

const fallbackBookingUrl = 'https://equalspa-admin.pages.dev/booking';

const fallbackServices = [
  ['A', '舒壓方案', '指壓或油壓，簡單整理日常疲勞', '60 MIN', 'NT$ 1,500'],
  ['B', '愉悅方案', '可指定師傅，加入體推與機能保養', '60 MIN', 'NT$ 2,000'],
  ['C', '享受方案', '指壓與油壓完整銜接，節奏更從容', '90 MIN', 'NT$ 2,500'],
  ['D', '極緻方案', '兩小時完整照顧，充分整理全身', '120 MIN', 'NT$ 3,000'],
] as const;

function MobileSequence({ content }: { content: ReturnType<typeof usePublishedSiteDraft> }) {
  const bookingUrl = content?.booking?.url || fallbackBookingUrl;
  const services = content && Array.isArray(content.services)
    ? content.services.filter((item) => item.visible).map((item) => [item.code, item.name, item.summary, item.duration, item.price] as const)
    : fallbackServices;
  const currentOffer = content && Array.isArray(content.offers)
    ? content.offers.find((item) => item.status === '顯示中')
    : undefined;
  const address = content?.store?.address || '台北市萬華區西寧南路 36 號';
  const hours = content?.store?.hours || '每日 10:00—24:00';
  return (
    <div className="mobile-sequence">
      <section className="mobile-panel mobile-intro">
        <p className="mobile-index">01 / EQUAL SPA</p>
        <h2 className="mobile-equal-wordmark" aria-label="EQUAL">
          <span className="mobile-equal-e">E</span>
          <span className="mobile-equal-q">Q</span>
          <span className="mobile-equal-u">U</span>
          <span className="mobile-equal-a">A</span>
          <span className="mobile-equal-l">L</span>
        </h2>
        <p>{content?.home?.subtitle || '回到平衡，也回到更自在的自己。'}</p>
        <span className="mobile-down">SCROLL ↓</span>
      </section>

      <section className="mobile-panel mobile-booking">
        <p className="mobile-index">02 / BOOKING</p>
        <div className="glass-orbit">
          <small>預約客服</small>
          <strong>{content?.booking?.lineId || '@017ktlhm'}</strong>
          <span>LINE</span>
        </div>
        <h2>BOOK<br />WITH<br />LINE.</h2>
        <p className="mobile-translation">不用等待，從 LINE 開始確認方案、師傅與時間。</p>
        <a className="mobile-primary" href={bookingUrl} target="_blank" rel="noreferrer">開啟線上預約 ↗</a>
      </section>

      <section className="mobile-panel mobile-services">
        <p className="mobile-index">03 / SERVICES</p>
        <h2>CHOOSE<br />YOUR TIME.</h2>
        <p className="mobile-translation">依照今天的身體，選擇六十到一百二十分鐘。</p>
        <div className="mobile-service-list">
          {services.map(([code, name, summary, duration, price]) => (
            <a href="/services" key={code}><i>{code}</i><span><b>{name}</b><small className="mobile-service-summary">{summary}</small><small>{duration}</small></span><strong>{price}</strong></a>
          ))}
        </div>
      </section>

      <section className="mobile-panel mobile-therapists">
        <p className="mobile-index">04 / THERAPISTS</p>
        <h2>MEET<br />YOUR MATCH.</h2>
        <p className="mobile-translation">從互動氣質開始，找到適合你的專業師傅。</p>
        <div className="category-stack">
          <a href="/therapists"><span>STRAIGHT</span><b>直男師傅</b><i>01</i></a>
          <a href="/therapists"><span>COMMUNITY</span><b>圈內師傅</b><i>02</i></a>
          <a href="/therapists"><span>BISEXUAL</span><b>雙性師傅</b><i>03</i></a>
        </div>
      </section>

      <section className="mobile-panel mobile-offer">
        <p className="mobile-index">05 / OFFERS</p>
        <div className="offer-number">01</div>
        <p className="offer-kicker">CURRENT SELECTION</p>
        <h2>CURRENT<br />OFFER.</h2>
        <p className="mobile-translation">{currentOffer?.name || '生日月，把照顧自己排進行程。'}</p>
        <p>{currentOffer?.summary || '實際適用方案與期間請洽 LINE 客服，預約時即可一併確認。'}</p>
        <a href="/offers">查看所有優惠 →</a>
      </section>

      <section className="mobile-panel mobile-location">
        <p className="mobile-index">06 / LOCATION</p>
        <div className="map-grid" aria-hidden="true"><span>西門</span><i /></div>
        <h2>TAIPEI<br />XIMEN</h2>
        <p>{address}<br />{hours}</p>
        <a href="/location">交通與店鋪資訊 →</a>
      </section>
    </div>
  );
}

export default function Home() {
  const content = usePublishedSiteDraft();
  const bookingUrl = content?.booking?.url || fallbackBookingUrl;
  return (
    <main className="home-shell">
      <PointerLight />
      <SiteHeader />

      <section className="kinetic-stage" aria-labelledby="hero-title">
        <p className="hero-eyebrow">TAIPEI · XIMEN · 10:00—24:00</p>
        <h1 id="hero-title" className="kinetic-wordmark" aria-label="EQUAL">
          <span className="letter letter-e">E</span><span className="letter letter-q">Q</span>
          <span className="letter letter-u">U</span><span className="letter letter-a">A</span>
          <span className="letter letter-l">L</span>
        </h1>
        <div className="hero-copy">
          <p>PRECISION IN<br />EVERY TOUCH.</p>
          <span>{content?.home?.support || '精準理解每一種身體需求，讓舒適重新回到應有的位置。'}</span>
          <a href={bookingUrl} target="_blank" rel="noreferrer">立即線上預約</a>
        </div>
        <p className="scroll-cue">EQUAL SPA · MOVE · RESET</p>
      </section>

      <div className="mobile-flow">
        <MobileSequence content={content} />
      </div>

      <WingMenu />
    </main>
  );
}
