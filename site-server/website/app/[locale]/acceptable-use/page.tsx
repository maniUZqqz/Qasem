import type { Metadata } from "next";
import { notFound } from "next/navigation";

import LegalPage from "@/components/LegalPage";
import { alternatesFor, isLocale, LOCALES, type Locale } from "@/lib/i18n";
import { getLegalDoc } from "@/lib/legal";

const SLUG = "acceptable-use";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const doc = getLegalDoc(SLUG, locale);
  if (!doc) return {};
  return {
    title: doc.title,
    description: doc.description,
    alternates: alternatesFor(locale, `/${SLUG}`),
  };
}

export default async function Page({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  return <LegalPage slug={SLUG} locale={locale as Locale} />;
}
