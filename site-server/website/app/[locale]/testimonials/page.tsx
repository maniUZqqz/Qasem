import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { getProof } from "@/lib/proof";
import { breadcrumbs } from "@/lib/seo";
import { getSite } from "@/lib/site";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "نظر مشتریان",
    title: "حرف خودشان، نه حرف ما",
    lead: "هر نقل قول با اجازه‌ی همان شخص اینجاست.",
    metaDesc: "نظر فروشگاه‌هایی که از NMarketing استفاده می‌کنند.",
    caseStudy: "داستان کاملش ←",
    ctaTitle: "خودت امتحانش کن",
    ctaLead: "فروشگاهت را ثبت کن و ببین خروجی برای محصول خودت چه شکلی است.",
    seePricing: "دیدن قیمت‌ها",
  },
  en: {
    eyebrow: "Testimonials",
    title: "Their words, not ours",
    lead: "Every quote is here with that person's permission.",
    metaDesc: "What shops using NMarketing say about it.",
    caseStudy: "The full story →",
    ctaTitle: "Try it yourself",
    ctaLead: "Add your shop and see what the output looks like for your own product.",
    seePricing: "See pricing",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/testimonials"),
  };
}

/** §13. No `Review` structured data here on purpose: §28 says schema only
 *  where it matches the page, and review markup on a vendor's own site is the
 *  kind of self-serving review Google discounts anyway. */
export default async function Testimonials({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { testimonials } = await getProof();
  if (testimonials.length === 0) notFound();

  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/testimonials" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          <div className="grid g2 in-view-stagger mt-lg">
            {testimonials.map((quote) => (
              <blockquote key={`${quote.name}-${quote.quote.slice(0, 20)}`} className="card">
                <p style={{ whiteSpace: "pre-wrap" }}>«{quote.quote}»</p>
                {quote.outcome && (
                  <p className="mt-sm">
                    <strong>{quote.outcome}</strong>
                  </p>
                )}
                <footer className="row-tight mt">
                  {quote.photo && (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={quote.photo}
                      alt={quote.name}
                      width={40}
                      height={40}
                      loading="lazy"
                      style={{ borderRadius: "50%", objectFit: "cover" }}
                    />
                  )}
                  <span className="muted">
                    {quote.name}
                    {quote.role && ` — ${quote.role}`}
                    {quote.business && `، ${quote.business}`}
                  </span>
                </footer>
                {quote.caseStudy && (
                  <p className="mt-sm">
                    <Link
                      href={localePath(l, `/case-studies/${quote.caseStudy}`)}
                      className="muted"
                    >
                      {c.caseStudy}
                    </Link>
                  </p>
                )}
              </blockquote>
            ))}
          </div>
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <div className="cta-band">
            <h2>{c.ctaTitle}</h2>
            <p className="lead mt narrower">{c.ctaLead}</p>
            <div className="row mt-md center-row">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/pricing")} className="btn btn-ghost">
                {c.seePricing}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
