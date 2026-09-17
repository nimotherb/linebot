import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL('https://equalspa.tw'),
  title: '伊果 SPA',
  description: '最新網站內容由 Equal SPA 後台發布。',
  alternates: { canonical: '/' },
  openGraph: {
    title: '伊果 SPA',
    description: '最新網站內容由 Equal SPA 後台發布。',
    type: 'website',
    locale: 'zh_TW',
    url: '/',
    images: [{ url: '/og.png', width: 1730, height: 910, alt: '伊果 SPA · EQUAL SPA' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '伊果 SPA',
    description: '最新網站內容由 Equal SPA 後台發布。',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-Hant">
      <body>{children}</body>
    </html>
  );
}
