import type { Metadata } from "next";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getFaq, getFaqGroups } from "@/lib/faq";
import { getSite } from "@/lib/site";
import { alternatesFor, isLocale, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs, faqPage } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "سؤالات متداول",
    title: "آنچه معمولاً پرسیده می‌شود",
    more: "سؤال دیگری دارید؟ ",
    write: "برایمان بنویسید",
    metaDesc: "پاسخ سؤالات رایج درباره‌ی نحوه‌ی کار، قیمت، امنیت داده و خروجی NMarketing.",
  },
  en: {
    eyebrow: "FAQ",
    title: "The questions we get asked",
    more: "Something else on your mind? ",
    write: "Write to us",
    metaDesc: "Common questions about how it works, pricing, data handling and output.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/faq"),
  };
}

export default async function FAQ({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  // From the admin, in the sections §14 of the site spec asks for. The
  // structured data stays flat because FAQPage has no notion of sections.
  const [groups, faq, site] = await Promise.all([
    getFaqGroups(l),
    getFaq(l),
    getSite(l),
  ]);

  return (
    <>
      <JsonLd
        data={[breadcrumbs([{ name: c.eyebrow, path: "/faq" }], l), faqPage(faq)]}
      />

      <section className="mesh">
        <div className="wrap wrap-md">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} />
          {groups.map((group) => (
            <div key={group.key} className="mt-lg">
              {group.label && (
                <h2 className="eyebrow" style={{ marginBottom: 12 }}>
                  {group.label}
                </h2>
              )}
              <div className="stack-sm">
                {group.items.map((f) => (
                  <details key={f.q} className="card qa">
                    <summary>{f.q}</summary>
                    <p>{f.a}</p>
                  </details>
                ))}
              </div>
            </div>
          ))}

          <p className="muted center mt-lg">
            {c.more}
            <a href={`mailto:${site.email}`} style={{ color: "var(--color-brand-600)" }}>
              {c.write}
            </a>
            .
          </p>
        </div>
      </section>
    </>
  );
}
