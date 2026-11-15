import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { isLocale } from "@/lib/i18n";

type Props = { params: Promise<{ locale: string; rest: string[] }> };

/**
 * Catch-all that exists only to turn every unknown URL into the branded 404.
 *
 * Without it, an unmatched URL never enters the `[locale]` segment (there is no
 * root layout above it), so Next served its own English "404: This page could
 * not be found." with no header, no footer and an empty `lang`. Every real page
 * outranks a catch-all, so nothing that exists is shadowed; the answer is still
 * HTTP 404 and `noindex`, so crawlers drop the URL as before.
 */
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  return {
    title: isLocale(locale) && locale === "en" ? "Page not found" : "صفحه پیدا نشد",
    robots: { index: false, follow: false },
  };
}

export default function Unmatched() {
  notFound();
}
