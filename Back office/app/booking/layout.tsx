import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '線上預約｜伊果 SPA',
  description: '選擇伊果 SPA 方案、時段、師傅與優惠，確認後直接送出預約。',
  openGraph: {
    title: '線上預約｜伊果 SPA',
    description: '選擇方案、時段、師傅與優惠，確認後直接送出預約。',
    type: 'website',
    locale: 'zh_TW',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: '伊果 SPA 線上預約' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: '線上預約｜伊果 SPA',
    description: '選擇方案、時段、師傅與優惠，確認後直接送出預約。',
    images: ['/og.png'],
  },
};

export default function BookingLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
