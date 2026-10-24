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
    eyebrow: "مطالعات موردی",
    title: "چه کسی از این استفاده کرد، و چه شد",
    lead: "هر کدام یک کسب‌وکار واقعی است، با مسئله‌ای که داشت و چیزی که تغییر کرد.",
    metaDesc:
      "مطالعات موردی واقعی NMarketing — مسئله‌ی کسب‌وکار، کاری که انجام شد و نتیجه‌ای که قابل اثبات است.",
    read: "خواندن ←",
    ctaTitle: "نوبت کسب‌وکار خودت",
    ctaLead: "فروشگاهت را ثبت کن و همین جلسه ببین خروجی برای محصول خودت چه شکلی است.",
    seePricing: "دیدن قیمت‌ها",
  },
  en: {
    eyebrow: "Case studies",
    title: "Who used this, and what happened",
    lead: "Each one is a real business, with the problem it had and what changed.",
    metaDesc:
      "Real NMarketing case studies — the business problem, the work done, and a result that can be checked.",
    read: "Read →",
    ctaTitle: "Your business next",
    ctaLead: "Add your shop and see, in this sitting, what the output looks like for your own product.",
    seePricing: "See pricing",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/case-studies"),
  };
}

/**
 * §11. Empty means this page does not exist — see `lib/proof.ts`. Shipping a
 * heading with nothing under it would be the thin page §18 warns about, and
 * inventing a customer to fill it is what §34 forbids.
 */
export default async function CaseStudies({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { caseStudies } = await getProof();
  if (caseStudies.length === 0) notFound();

  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/case-studies" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          <div className="stack mt-lg gap-lg">
            {caseStudies.map((study) => (
              <article key={study.slug} className="card">
                <div className="row-tight">
                  {study.customer && <span className="eyebrow">{study.customer}</span>}
                  <h2 style={{ fontSize: "1.15rem" }}>{study.title}</h2>
                </div>
                {study.lead && <p className="muted mt-sm">{study.lead}</p>}
                {study.results && (
                  <p className="mt-sm">
                    <strong>{study.results}</strong>
                  </p>
                )}
                <div className="mt">
                  <Link
                    href={localePath(l, `/case-studies/${study.slug}`)}
                    className="btn btn-ghost"
                  >
                    {c.read}
                  </Link>
                </div>
              </article>
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
