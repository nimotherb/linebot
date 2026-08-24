import type { Metadata } from 'next';
import './globals.css';
import { NavigationLoadingProvider } from './components/NavigationLoading';

export const metadata: Metadata = {
  title: '伊果 SPA｜營運管理後台',
  description: '伊果 SPA 的預約、排班、現場進度與結帳管理中心。',
  openGraph: {
    title: '伊果 SPA｜營運管理後台',
    description: '預約、排班、房間、結帳與服務方案的一站式管理中心。',
    type: 'website',
    locale: 'zh_TW',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: '伊果 SPA 營運管理後台' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '伊果 SPA｜營運管理後台',
    description: '預約、排班、房間、結帳與服務方案的一站式管理中心。',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-Hant">
      <body><NavigationLoadingProvider>{children}</NavigationLoadingProvider></body>
    </html>
  );
}
