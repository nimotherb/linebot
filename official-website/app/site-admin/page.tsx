import type { Metadata } from 'next';
import SiteAdminPortal from '../components/SiteAdminPortal';

export const metadata: Metadata = {
  title: 'SITE STUDIO｜伊果 SPA 官網管理',
  description: '伊果 SPA 官網內容管理工作區。',
  robots: { index: false, follow: false },
  openGraph: { images: [] },
  twitter: { images: [] },
};

export default function SiteAdminPage() {
  return <SiteAdminPortal />;
}
