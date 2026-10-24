import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getComparisons } from "@/lib/seoPages";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "مقایسه",
    title: "NMarketing در برابر گزینه‌های دیگر",
    lead: "منصفانه — با مواردی که گزینه‌ی دیگر بهتر است.",
    metaDesc: "مقایسه‌ی منصفانه‌ی NMarketing با آژانس، فریلنسر و انجام دادن خودتان.",
    note:
      "هر صفحه مواردی را می‌گوید که گزینه‌ی دیگر واقعاً بهتر است. اگر جایی چنین موردی نداشتیم، آن صفحه را نمی‌ساختیم.",
  },
  en: {
    eyebrow: "Compare",
    title: "NMarketing against the alternatives",
    lead: "Fairly — including where the alternative is the better answer.",
    metaDesc:
      "A fair comparison of NMarketing with agencies, freelancers and doing it yourself.",
    note:
      "Every page names cases where the other option genuinely wins. If we could not name any, we would not have built the page.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/compare"),
  };
}

export default async function Compare({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const comparisons = await getComparisons(l);
  const c = COPY[l];

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/compare" }], l)} />
      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />
          <p className="muted center mt-sm">{c.note}</p>
          <div className="grid g3 in-view-stagger mt-md">
            {comparisons.map((cmp) => (
              <Link
                key={cmp.slug}
                href={localePath(l, `/compare/${cmp.slug}`)}
                className="card card-hover glow-edge plain"
              >
                <span className="icon-lg">{cmp.icon}</span>
                <h2 className="mt-sm" style={{ fontSize: "1.05rem" }}>
                  {cmp.title}
                </h2>
                <p className="muted mt-sm">{cmp.lead}</p>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
