import type { Metadata, Viewport } from "next";
import { notFound } from "next/navigation";

import "@fontsource/vazirmatn/arabic-300.css";
import "@fontsource/vazirmatn/arabic-400.css";
import "@fontsource/vazirmatn/arabic-600.css";
import "@fontsource/vazirmatn/arabic-700.css";
import "@fontsource/vazirmatn/arabic-800.css";
import "../globals.css";

import Analytics from "@/components/Analytics";
import Footer from "@/components/Footer";
import Header from "@/components/Header";
import JsonLd from "@/components/JsonLd";
import PointerGlow from "@/components/PointerGlow";
import { dict } from "@/lib/dict";
import { LOCALES, LOCALE_META, isLocale, alternatesFor } from "@/lib/i18n";
import { getSite } from "@/lib/site";
import { SITE_URL, organization, website } from "@/lib/seo";

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

/**
 * This is the root layout. There is no `app/layout.tsx` on purpose: a root
 * layout receives no params, so it cannot know the locale, and `lang`/`dir`
 * would have to be patched in from the client — after the crawler has already
 * read the wrong ones. Putting `<html>` here means the very first byte is
 * correct for the language being served.
 */
export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const s = await getSite(locale);
  const meta = LOCALE_META[locale];

  return {
    metadataBase: new URL(SITE_URL),
    title: { default: `${s.name} — ${s.tagline}`, template: `%s | ${s.name}` },
    description: s.oneLiner,
    applicationName: s.name,
    keywords: s.keywords,
    authors: [{ name: s.name, url: SITE_URL }],
    creator: s.name,
    publisher: s.name,
    openGraph: {
      type: "website",
      locale: meta.ogLocale,
      url: SITE_URL,
      siteName: s.name,
      title: `${s.name} — ${s.tagline}`,
      description: s.oneLiner,
    },
    twitter: {
      card: "summary_large_image",
      title: `${s.name} — ${s.tagline}`,
      description: s.oneLiner,
    },
    robots: {
      index: true,
      follow: true,
      googleBot: { index: true, follow: true, "max-image-preview": "large" },
    },
    alternates: {
      ...alternatesFor(locale, "/"),
      types: { "application/rss+xml": "/feed.xml" },
    },
    manifest: "/manifest.webmanifest",
    formatDetection: { telephone: false },
  };
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0b1120" },
  ],
  colorScheme: "light dark",
};

/** Applied before paint so a reader who chose dark never sees a white flash. */
const themeBoot = `
(function(){try{var t=localStorage.getItem("upmarket-theme");
if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t);
}catch(e){}})();`;

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  const meta = LOCALE_META[locale];
  const t = dict(locale);
  // From the admin, with the shipped copy as the fallback. The header is a
  // client component, so it is handed the name rather than fetching it.
  const s = await getSite(locale);

  return (
    <html lang={meta.htmlLang} dir={meta.dir} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
        <JsonLd data={[organization(locale, s), website(locale, s)]} />
      </head>
      <body>
        <a href="#main" className="skip-link">
          {t.common.skipToContent}
        </a>
        <Analytics locale={locale} />
        <PointerGlow />
        <Header locale={locale} name={s.name} />
        <main id="main">{children}</main>
        <Footer locale={locale} />
      </body>
    </html>
  );
}
