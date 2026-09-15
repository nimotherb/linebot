import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import TherapistCatalog from '../components/TherapistCatalog';
import { PublishedOffers, PublishedPageBody, PublishedPageHeader, PublishedPageTitle, PublishedServices } from '../components/PublishedSiteContent';
import { PointerLight, SiteHeader, WingMenu } from '../components/WingMenu';

const pageMeta = {
  about: 'ABOUT',
  services: 'SERVICES',
  therapists: 'THERAPISTS',
  offers: 'OFFERS',
  location: 'LOCATION',
  recruit: 'RECRUIT',
  groups: 'GROUP',
  loyalty: 'LOYALTY',
  privacy: 'PRIVACY',
} as const;

const bookingUrl = '';
const plans: never[] = [];

function AboutContent() {
  return <PublishedPageBody slug="about"><div /></PublishedPageBody>;
}

function ServicesContent() {
  return <PublishedServices fallbackPlans={plans} fallbackBookingUrl={bookingUrl} />;
}

function TherapistsContent() { return <TherapistCatalog />; }

function OffersContent() {
  return <PublishedOffers fallbackBookingUrl={bookingUrl} />;
}

function LocationContent() {
  return <PublishedPageBody slug="location"><div /></PublishedPageBody>;
}

function RecruitContent() {
  return <PublishedPageBody slug="recruit"><div /></PublishedPageBody>;
}

function UpdatingContent({ type }: { type: 'groups' | 'loyalty' }) {
  return <PublishedPageBody slug={type}><div /></PublishedPageBody>;
}

function PrivacyContent() {
  return <PublishedPageBody slug="privacy"><div className="privacy-copy" /></PublishedPageBody>;
}

function PageContent({ slug }: { slug: keyof typeof pageMeta }) {
  if (slug === 'about') return <AboutContent />;
  if (slug === 'services') return <ServicesContent />;
  if (slug === 'therapists') return <TherapistsContent />;
  if (slug === 'offers') return <OffersContent />;
  if (slug === 'location') return <LocationContent />;
  if (slug === 'recruit') return <RecruitContent />;
  if (slug === 'groups' || slug === 'loyalty') return <UpdatingContent type={slug} />;
  return <PrivacyContent />;
}

export function generateStaticParams() { return Object.keys(pageMeta).map((slug) => ({ slug })); }

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  if (!(slug in pageMeta)) return {};
  const english = pageMeta[slug as keyof typeof pageMeta];
  let title = '';
  let intro = '';
  try {
    const response = await fetch(`${(process.env.NEXT_PUBLIC_API_BASE_URL || 'https://linebot-3r2w.onrender.com').replace(/\/$/, '')}/api/public/site-content`, { cache: 'no-store' });
    if (response.ok) {
      const payload = await response.json() as { content?: { pages?: Record<string, { title?: string; intro?: string }> } };
      title = payload.content?.pages?.[slug]?.title || '';
      intro = payload.content?.pages?.[slug]?.intro || '';
    }
  } catch {
    // Metadata remains generic when the published API is unavailable.
  }
  const pageTitle = title ? `${english}｜${title}｜伊果 SPA` : `${english}｜伊果 SPA`;
  return {
    title: pageTitle,
    ...(intro ? { description: intro } : {}),
    alternates: { canonical: `/${slug}` },
    openGraph: { title: pageTitle, ...(intro ? { description: intro } : {}), images: [] },
    twitter: { title: pageTitle, ...(intro ? { description: intro } : {}), images: [] },
  };
}

export default async function ContentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!(slug in pageMeta)) notFound();
  const typedSlug = slug as keyof typeof pageMeta;
  const english = pageMeta[typedSlug];
  return <main className={`interior-shell page-${typedSlug}`}><PointerLight /><SiteHeader /><article className="interior-page"><header className="page-title"><p>EQUAL SPA / {String(Object.keys(pageMeta).indexOf(typedSlug) + 1).padStart(2, '0')}</p><PublishedPageTitle slug={typedSlug} fallback={english} /><PublishedPageHeader slug={typedSlug} fallbackTitle="" fallbackIntro="" /></header><section className="page-content"><PageContent slug={typedSlug} /></section><footer className="site-footer"><div><b>伊果 SPA</b><span>EQUAL SPA · TAIPEI XIMEN</span></div>{bookingUrl && <a href={bookingUrl} target="_blank" rel="noreferrer">ONLINE BOOKING</a>}<small>© {new Date().getFullYear()} EQUAL SPA</small></footer></article><WingMenu /></main>;
}

