'use client';

import { type CSSProperties, useEffect, useRef, useState } from 'react';

const bookingUrl = 'https://equalspa-ops-preview.c83500699.chatgpt.site/booking';

const menuItems = [
  ['首頁', '/', 'HOME'],
  ['關於伊果', '/about', 'ABOUT'],
  ['服務項目', '/services', 'SERVICES'],
  ['專業師傅', '/therapists', 'THERAPISTS'],
  ['最新優惠', '/offers', 'OFFERS'],
  ['交通資訊', '/location', 'LOCATION'],
  ['人才招募', '/recruit', 'RECRUIT'],
  ['群組', '/groups', 'GROUP'],
  ['酬賓計畫', '/loyalty', 'LOYALTY'],
] as const;

export function PointerLight() {
  useEffect(() => {
    const updateGlow = (event: PointerEvent) => {
      document.documentElement.style.setProperty('--pointer-x', `${event.clientX}px`);
      document.documentElement.style.setProperty('--pointer-y', `${event.clientY}px`);
    };
    window.addEventListener('pointermove', updateGlow, { passive: true });
    return () => window.removeEventListener('pointermove', updateGlow);
  }, []);
  return <div className="pool-light" aria-hidden="true" />;
}

export function SiteHeader() {
  return (
    <header className="home-header">
      <a className="micro-brand" href="/" aria-label="伊果 SPA 首頁">
        <span>E</span><span>伊果 SPA</span>
      </a>
      <a className="line-link" href={bookingUrl} target="_blank" rel="noreferrer">
        LINE 預約 <b>@017ktlhm</b>
      </a>
    </header>
  );
}

export function WingMenu() {
  const [menuOpen, setMenuOpen] = useState(false);
  const dockRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    const closeFromOutside = (event: PointerEvent) => {
      if (menuOpen && dockRef.current && !dockRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    window.addEventListener('keydown', closeWithEscape);
    window.addEventListener('pointerdown', closeFromOutside);
    return () => {
      window.removeEventListener('keydown', closeWithEscape);
      window.removeEventListener('pointerdown', closeFromOutside);
    };
  }, [menuOpen]);

  return (
    <div ref={dockRef} className={`menu-dock ${menuOpen ? 'is-open' : ''}`}>
      <button className="logo-trigger" type="button" aria-label={menuOpen ? '關閉網站選單' : '開啟網站選單'} aria-expanded={menuOpen} aria-controls="site-menu" onClick={() => setMenuOpen((open) => !open)}>
        <span className="logo-tile">E</span>
      </button>
      <span className="menu-thread" aria-hidden="true" />

      <nav id="site-menu" className="wing-menu" aria-label="主要選單" aria-hidden={!menuOpen}>
        <div className="menu-links">
          {menuItems.map(([label, href, english], index) => (
            <a href={href} key={href} style={{ '--item-index': index } as CSSProperties} tabIndex={menuOpen ? 0 : -1}>
              <span>0{index + 1}</span><b>{label}</b><em>{english}</em>
            </a>
          ))}
        </div>
        <a className="menu-line-cta" href={bookingUrl} target="_blank" rel="noreferrer" tabIndex={menuOpen ? 0 : -1}>
          <span>ONLINE BOOKING</span><strong>開始預約 ↗</strong>
        </a>
        <div className="menu-utility">
          <a href="/site-admin" tabIndex={menuOpen ? 0 : -1}>SITE STUDIO</a>
          <a href="/privacy" tabIndex={menuOpen ? 0 : -1}>隱私權</a>
          <a href="https://equalspa-ops-preview.c83500699.chatgpt.site/" target="_blank" rel="noreferrer" tabIndex={menuOpen ? 0 : -1}>EQUAL OPERATIONS</a>
        </div>
      </nav>
    </div>
  );
}
