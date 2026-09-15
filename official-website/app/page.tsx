'use client';

import { PointerLight, SiteHeader, WingMenu } from './components/WingMenu';
import { usePublishedSiteDraft } from './components/PublishedSiteContent';

function MobileSequence({ content }: { content: ReturnType<typeof usePublishedSiteDraft> }) {
  const bookingUrl = content?.booking?.url || '';
  const homePage = content?.pages?.home;
  const services = content && Array.isArray(content.services)
    ? content.services.filter((item) => item.visible).map((item) => [item.code, item.name, item.summary, item.duration, item.price] as const)
    : [];
  const currentOffer = content && Array.isArray(content.offers)
    ? content.offers.find((item) => item.status === '顯示中')
    : undefined;
  const address = content?.store?.address || '—';
  const hours = content?.store?.hours || '—';
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
        <p>{content?.home?.subtitle || homePage?.intro || '內容更新中'}</p>
        <span className="mobile-down">SCROLL ↓</span>
      </section>

      <section className="mobile-panel mobile-booking">
        <p className="mobile-index">02 / BOOKING</p>
        <div className="glass-orbit">
          <small>預約客服</small>
          <strong>{content?.booking?.lineId || '—'}</strong>
          <span>LINE</span>
        </div>
        <h2>BOOK<br />WITH<br />LINE.</h2>
        <p className="mobile-translation">不用等待，從 LINE 開始確認方案、師傅與時間。</p>
        {bookingUrl && <a className="mobile-primary" href={bookingUrl} target="_blank" rel="noreferrer">開啟線上預約 ↗</a>}
      </section>

      <section className="mobile-panel mobile-services">
        <p className="mobile-index">03 / SERVICES</p>
        <h2>CHOOSE<br />YOUR TIME.</h2>
        <p className="mobile-translation">依照今天的身體，選擇六十到一百二十分鐘。</p>
        <div className="mobile-service-list">
          {services.map(([code, name, summary, duration, price]) => (
            <a href="/services" key={code}><i>{code}</i><span><b>{name}</b><small className="mobile-service-summary">{summary}</small><small>{duration}</small></span><strong>{price}</strong></a>
          ))}
          {services.length === 0 && <p className="updating-card">目前尚未發布服務方案。</p>}
        </div>
      </section>

      <section className="mobile-panel mobile-therapists">
        <p className="mobile-index">04 / THERAPISTS</p>
        <h2>MEET<br />YOUR MATCH.</h2>
        <p className="mobile-translation">從互動氣質開始，找到適合你的專業師傅。</p>
        <div className="category-stack"><a href="/therapists"><span>THERAPISTS</span><b>查看服務團隊</b><i>↗</i></a></div>
      </section>

      <section className="mobile-panel mobile-offer">
        <p className="mobile-index">05 / OFFERS</p>
        <div className="offer-number">01</div>
        <p className="offer-kicker">CURRENT SELECTION</p>
        <h2>CURRENT<br />OFFER.</h2>
        <p className="mobile-translation">{currentOffer?.name || '內容更新中'}</p>
        <p>{currentOffer?.summary || '最新內容將由後台發布。'}</p>
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
  const bookingUrl = content?.booking?.url || '';
  const homePage = content?.pages?.home;
  if (!content) return <main className="home-shell"><PointerLight /><SiteHeader /><section className="kinetic-stage"><div className="updating-card"><span>OFFICIAL SITE</span><h2>內容暫時無法取得</h2><p>請稍後重新整理，最新發布內容只從官方資料庫載入。</p></div></section><WingMenu /></main>;
  return (
    <main className="home-shell">
      <PointerLight />
      <SiteHeader />

      <section className="kinetic-stage" aria-labelledby="hero-title">
          <p className="hero-eyebrow">{homePage?.english || 'HOME'}</p>
        <h1 id="hero-title" className="kinetic-wordmark" aria-label="EQUAL" style={{ fontSize: `clamp(8rem, 22vw, ${content?.home?.heroFontSize || 240}px)` }}>
          <span className="letter letter-e">E</span><span className="letter letter-q">Q</span>
          <span className="letter letter-u">U</span><span className="letter letter-a">A</span>
          <span className="letter letter-l">L</span>
        </h1>
        <div className="hero-copy">
          <p>{homePage?.title || content?.home?.subtitle || '內容更新中'}</p>
          <span>{homePage?.body || content?.home?.support || '官方內容更新中。'}</span>
          {bookingUrl && <a href={bookingUrl} target="_blank" rel="noreferrer">立即線上預約</a>}
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
