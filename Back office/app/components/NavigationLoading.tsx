'use client';

import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';

type NavigationLoadingContextValue = {
  isNavigating: boolean;
  startNavigation: (message?: string) => void;
  stopNavigation: () => void;
  runNavigation: (action: () => void, message?: string) => void;
};

const DISPLAY_DELAY_MS = 10_000;
const MINIMUM_VISIBLE_MS = 280;
const FAILSAFE_MS = 60_000;

const NavigationLoadingContext = createContext<NavigationLoadingContextValue | null>(null);

export function NavigationLoadingProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [isNavigating, setIsNavigating] = useState(false);
  const [message, setMessage] = useState('正在載入頁面…');
  const startedAt = useRef(0);
  const visible = useRef(false);
  const showTimer = useRef<number | null>(null);
  const hideTimer = useRef<number | null>(null);
  const failsafeTimer = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    if (showTimer.current !== null) window.clearTimeout(showTimer.current);
    if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    if (failsafeTimer.current !== null) window.clearTimeout(failsafeTimer.current);
    showTimer.current = null;
    hideTimer.current = null;
    failsafeTimer.current = null;
  }, []);

  const stopNavigation = useCallback(() => {
    if (!visible.current) {
      clearTimers();
      setIsNavigating(false);
      return;
    }

    const elapsed = performance.now() - startedAt.current;
    const remaining = Math.max(0, MINIMUM_VISIBLE_MS - elapsed);
    if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      visible.current = false;
      setIsNavigating(false);
      clearTimers();
    }, remaining);
  }, [clearTimers]);

  const startNavigation = useCallback((nextMessage = '正在載入頁面…') => {
    clearTimers();
    visible.current = false;
    setIsNavigating(false);
    setMessage(nextMessage);
    showTimer.current = window.setTimeout(() => {
      showTimer.current = null;
      startedAt.current = performance.now();
      visible.current = true;
      setIsNavigating(true);
      failsafeTimer.current = window.setTimeout(() => {
        visible.current = false;
        setIsNavigating(false);
        clearTimers();
      }, FAILSAFE_MS);
    }, DISPLAY_DELAY_MS);
  }, [clearTimers]);

  const runNavigation = useCallback((action: () => void, nextMessage?: string) => {
    startNavigation(nextMessage);
    window.requestAnimationFrame(() => {
      action();
      stopNavigation();
    });
  }, [startNavigation, stopNavigation]);

  useEffect(() => {
    stopNavigation();
  }, [pathname, stopNavigation]);

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const element = event.target instanceof Element ? event.target : null;
      const anchor = element?.closest<HTMLAnchorElement>('a[href]');
      if (!anchor || anchor.download || (anchor.target && anchor.target !== '_self')) return;

      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) return;

      const destination = new URL(anchor.href, window.location.href);
      if (destination.origin !== window.location.origin) return;
      if (destination.pathname === window.location.pathname && destination.search === window.location.search && destination.hash) return;
      startNavigation('正在前往頁面…');
    };

    const onHistoryNavigation = () => startNavigation('正在載入上一頁…');
    const onPageShow = () => stopNavigation();
    document.addEventListener('click', onDocumentClick, true);
    window.addEventListener('popstate', onHistoryNavigation);
    window.addEventListener('pageshow', onPageShow);
    return () => {
      document.removeEventListener('click', onDocumentClick, true);
      window.removeEventListener('popstate', onHistoryNavigation);
      window.removeEventListener('pageshow', onPageShow);
      clearTimers();
    };
  }, [clearTimers, startNavigation, stopNavigation]);

  return (
    <NavigationLoadingContext.Provider value={{ isNavigating, startNavigation, stopNavigation, runNavigation }}>
      {children}
      {isNavigating && (
        <div className="navigation-loading-overlay" role="status" aria-live="polite" aria-label={message}>
          <div className="navigation-loading-card">
            <span className="navigation-loading-spinner" aria-hidden="true" />
            <strong>{message}</strong>
          </div>
        </div>
      )}
    </NavigationLoadingContext.Provider>
  );
}

export function useNavigationLoading() {
  const context = useContext(NavigationLoadingContext);
  if (!context) throw new Error('useNavigationLoading must be used inside NavigationLoadingProvider');
  return context;
}
