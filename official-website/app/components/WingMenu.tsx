'use client';

import { type CSSProperties, useEffect, useRef, useState } from 'react';
import { usePublishedSiteDraft } from './PublishedSiteContent';

const bookingUrl = 'https://equalspa-admin.pages.dev/booking';

const defaultMenuItems = [
  { id: 'home', label: '首頁', slug: 'home', english: 'HOME', desktopVisible: true, mobileVisible: true },
  { id: 'about', label: '關於伊果', slug: 'about', english: 'ABOUT', desktopVisible: true, mobileVisible: true },
  { id: 'services', label: '服務項目', slug: 'services', english: 'SERVICES', desktopVisible: true, mobileVisible: true },
  { id: 'therapists', label: '專業師傅', slug: 'therapists', english: 'THERAPISTS', desktopVisible: true, mobileVisible: true },
  { id: 'offers', label: '最新優惠', slug: 'offers', english: 'OFFERS', desktopVisible: true, mobileVisible: true },
  { id: 'location', label: '交通資訊', slug: 'location', english: 'LOCATION', desktopVisible: true, mobileVisible: true },
  { id: 'recruit', label: '人才招募', slug: 'recruit', english: 'RECRUIT', desktopVisible: true, mobileVisible: true },
  { id: 'groups', label: '群組', slug: 'groups', english: 'GROUP', desktopVisible: true, mobileVisible: true },
  { id: 'loyalty', label: '酬賓計畫', slug: 'loyalty', english: 'LOYALTY', desktopVisible: true, mobileVisible: true },
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
  const content = usePublishedSiteDraft();
  const currentBookingUrl = content?.booking?.url || bookingUrl;
  return (
    <header className="home-header">
      <a className="micro-brand" href="/" aria-label="伊果 SPA 首頁">
        <span>E</span><span>伊果 SPA</span>
      </a>
      <a className="line-link" href={currentBookingUrl} target="_blank" rel="noreferrer">
        LINE 預約 <b>@017ktlhm</b>
      </a>
    </header>
  );
}

export function WingMenu() {
  const [menuOpen, setMenuOpen] = useState(false);
  const content = usePublishedSiteDraft();
  const dockRef = useRef<HTMLDivElement>(null);
  const menuItems = content?.navigation?.length ? content.navigation : defaultMenuItems;
  const currentBookingUrl = content?.booking?.url || bookingUrl;

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
        <span className="logo-orbit" aria-hidden="true" />
        <span className="logo-tile">E</span>
      </button>
      <span className="menu-thread" aria-hidden="true" />

      <nav id="site-menu" className="wing-menu" aria-label="主要選單" aria-hidden={!menuOpen}>
        <div className="menu-links">
          {menuItems.map((item, index) => (
            <a href={item.slug === 'home' ? '/' : `/${item.slug}`} key={`${item.id}-${item.slug}`} data-desktop-visible={item.desktopVisible !== false} data-mobile-visible={item.mobileVisible !== false} style={{ '--item-index': index } as CSSProperties} tabIndex={menuOpen ? 0 : -1}>
              <span>0{index + 1}</span><b>{item.label}</b><em>{item.english}</em>
            </a>
          ))}
        </div>
        <a className="menu-line-cta" href={currentBookingUrl} target="_blank" rel="noreferrer" tabIndex={menuOpen ? 0 : -1}>
          <span>ONLINE BOOKING</span><strong>開始預約 ↗</strong>
        </a>
        <div className="menu-utility">
          <a href="/site-admin" tabIndex={menuOpen ? 0 : -1}>SITE STUDIO</a>
          <a href="/privacy" tabIndex={menuOpen ? 0 : -1}>隱私權</a>
          <a href="https://equalspa-admin.pages.dev/" target="_blank" rel="noreferrer" tabIndex={menuOpen ? 0 : -1}>EQUAL OPERATIONS</a>
        </div>
      </nav>
    </div>
  );
}
