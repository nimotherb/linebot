import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL('https://equalspa.pages.dev'),
  title: '伊果 SPA｜台北西門按摩・LINE 預約',
  description: '伊果 SPA 位於台北西門町。服務時間 10:00–24:00，加入 LINE @017ktlhm 即可預約。',
  alternates: { canonical: '/' },
  openGraph: {
    title: '伊果 SPA｜台北西門按摩・LINE 預約',
    description: '台北西門 · 10:00–24:00 · LINE 預約 @017ktlhm',
    type: 'website',
    locale: 'zh_TW',
    url: '/',
    images: [{ url: '/og.png', width: 1730, height: 910, alt: '伊果 SPA · EQUAL SPA' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '伊果 SPA｜台北西門按摩・LINE 預約',
    description: '台北西門 · 10:00–24:00 · LINE 預約 @017ktlhm',
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
