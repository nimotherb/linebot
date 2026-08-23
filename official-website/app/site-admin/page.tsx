import type { Metadata } from 'next';
// Site admin temporarily disabled — route renamed to site-admin-disabled to avoid exposure.
// To re-enable, restore from git history and remove the renamed file.

export const metadata: Metadata = {
  title: 'SITE STUDIO (disabled)',
  description: 'This route has been disabled.',
  robots: { index: false, follow: false },
  openGraph: { images: [] },
  twitter: { images: [] },
};

export default function SiteAdminPage() {
  return <div style={{ padding: 40 }}>This route is temporarily disabled.</div>;
}
