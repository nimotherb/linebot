'use client';

import { type CSSProperties, useEffect, useState } from 'react';

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
      <a className="line-link" href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer">
        LINE 預約 <b>@017ktlhm</b>
      </a>
    </header>
  );
}

export function WingMenu() {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    window.addEventListener('keydown', closeWithEscape);
    return () => window.removeEventListener('keydown', closeWithEscape);
  }, []);

  return (
    <div className={`menu-dock ${menuOpen ? 'is-open' : ''}`}>
      <nav id="site-menu" className="wing-menu" aria-label="主要選單" aria-hidden={!menuOpen}>
        <div className="menu-heading">
          <p>NAVIGATION · EQUAL SPA</p>
          <button type="button" onClick={() => setMenuOpen(false)} aria-label="關閉選單" tabIndex={menuOpen ? 0 : -1}>CLOSE</button>
        </div>
        <div className="menu-links">
          {menuItems.map(([label, href, english], index) => (
            <a href={href} key={href} style={{ '--item-index': index } as CSSProperties} tabIndex={menuOpen ? 0 : -1}>
              <span>0{index + 1}</span><b>{label}</b><em>{english}</em>
            </a>
          ))}
        </div>
        <a className="menu-line-cta" href="https://line.me/R/ti/p/%40017ktlhm" target="_blank" rel="noreferrer" tabIndex={menuOpen ? 0 : -1}>
          <span>LINE 預約客服</span><strong>@017ktlhm ↗</strong>
        </a>
        <div className="menu-utility">
          <a href="/privacy" tabIndex={menuOpen ? 0 : -1}>隱私權</a>
          <a href="https://equalspa-ops-preview.c83500699.chatgpt.site/" target="_blank" rel="noreferrer" tabIndex={menuOpen ? 0 : -1}>EQUAL OPERATIONS</a>
        </div>
      </nav>

      <button className="logo-trigger" type="button" aria-expanded={menuOpen} aria-controls="site-menu" onClick={() => setMenuOpen((open) => !open)}>
        <span className="trigger-line trigger-line-left" aria-hidden="true" />
        <span className="logo-tile">E</span>
        <span className="trigger-label">{menuOpen ? 'CLOSE' : 'MENU'}</span>
        <span className="trigger-line trigger-line-right" aria-hidden="true" />
      </button>
    </div>
  );
}
