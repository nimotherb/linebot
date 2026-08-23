'use client';

import { useEffect } from 'react';
import { PointerLight, SiteHeader, WingMenu } from './components/WingMenu';

const services = [
  ['A', '舒壓方案', '60 MIN', 'NT$ 1,500'],
  ['B', '愉悅方案', '60 MIN', 'NT$ 2,000'],
  ['C', '深度方案', '90 MIN', 'NT$ 2,500'],
  ['D', '完整方案', '120 MIN', 'NT$ 3,000'],
] as const;

function MobileSequence({ duplicate = false }: { duplicate?: boolean }) {
  return (
    <div className="mobile-sequence" aria-hidden={duplicate || undefined}>
      <section className="mobile-panel mobile-intro">
        <p className="mobile-index">00 / EQUAL SPA</p>
        <h2>讓身體<br />回到平衡。</h2>
        <p>台北西門町，給自己一段安靜而完整的休息時間。</p>
        <span className="mobile-down">SCROLL ↓</span>
      </section>

      <section className="mobile-panel mobile-booking">
        <p className="mobile-index">01 / BOOKING</p>
        <div className="glass-orbit">
          <small>預約客服</small>
          <strong>@017ktlhm</strong>
          <span>LINE</span>
        </div>
        <h2>不用等待，<br />從 LINE 開始。</h2>
        <a className="mobile-primary" href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">加入好友並預約 ↗</a>
      </section>

      <section className="mobile-panel mobile-services">
        <p className="mobile-index">02 / SERVICES</p>
        <h2>你的時間，<br />你的節奏。</h2>
        <div className="mobile-service-list">
          {services.map(([code, name, duration, price]) => (
            <a href="/services" key={code}><i>{code}</i><span><b>{name}</b><small>{duration}</small></span><strong>{price}</strong></a>
          ))}
        </div>
      </section>

      <section className="mobile-panel mobile-therapists">
        <p className="mobile-index">03 / THERAPISTS</p>
        <h2>找到適合你的<br />專業師傅。</h2>
        <div className="category-stack">
          <a href="/therapists"><span>STRAIGHT</span><b>直男師傅</b><i>01</i></a>
          <a href="/therapists"><span>COMMUNITY</span><b>圈內師傅</b><i>02</i></a>
          <a href="/therapists"><span>BISEXUAL</span><b>雙性師傅</b><i>03</i></a>
        </div>
      </section>

      <section className="mobile-panel mobile-offer">
        <p className="mobile-index">04 / OFFERS</p>
        <div className="offer-number">01</div>
        <p className="offer-kicker">CURRENT SELECTION</p>
        <h2>生日月，<br />把照顧自己<br />排進行程。</h2>
        <p>實際適用方案與期間請洽 LINE 客服，預約時即可一併確認。</p>
        <a href="/offers">查看所有優惠 →</a>
      </section>

      <section className="mobile-panel mobile-location">
        <p className="mobile-index">05 / LOCATION</p>
        <div className="map-grid" aria-hidden="true"><span>西門</span><i /></div>
        <h2>TAIPEI<br />XIMEN</h2>
        <p>台北市萬華區西寧南路 36 號<br />營業時間 10:00—24:00</p>
        <a href="/location">交通與店鋪資訊 →</a>
        <small>KEEP SCROLLING · BACK TO EQUAL</small>
      </section>
    </div>
  );
}

export default function Home() {
  useEffect(() => {
    let ticking = false;
    const loopMobilePage = () => {
      if (ticking || window.innerWidth > 760 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      ticking = true;
      window.requestAnimationFrame(() => {
        const sequence = document.querySelector<HTMLElement>('.mobile-sequence');
        if (sequence && window.scrollY >= sequence.offsetHeight) {
          window.scrollTo({ top: window.scrollY - sequence.offsetHeight, behavior: 'instant' as ScrollBehavior });
        }
        ticking = false;
      });
    };
    window.addEventListener('scroll', loopMobilePage, { passive: true });
    return () => window.removeEventListener('scroll', loopMobilePage);
  }, []);

  return (
    <main className="home-shell">
      <PointerLight />
      <SiteHeader />

      <section className="kinetic-stage" aria-labelledby="hero-title">
        <p className="hero-eyebrow">TAIPEI · XIMEN · 10:00—24:00</p>
        <h1 id="hero-title" className="kinetic-wordmark" aria-label="EQUAL SPA">
          <span className="letter letter-e">E</span><span className="letter letter-q">Q</span>
          <span className="letter letter-u">U</span><span className="letter letter-a">A</span>
          <span className="letter letter-l">L</span><span className="letter letter-s">S</span>
          <span className="letter letter-p">P</span><span className="letter letter-a2">A</span>
        </h1>
        <div className="hero-copy">
          <p>讓每一次抵達，都是身體重新歸零的開始。</p>
          <a href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">立即使用 LINE 預約</a>
        </div>
        <p className="scroll-cue">MOVE · BREATHE · RESET</p>
      </section>

      <div className="mobile-flow">
        <MobileSequence />
        <MobileSequence duplicate />
      </div>

      <WingMenu />
    </main>
  );
}
