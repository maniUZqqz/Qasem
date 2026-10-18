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
    eyebrow: "مشتری‌ها",
    title: "کسب‌وکارهایی که از آپ‌مارکت استفاده می‌کنند",
    lead: "هر کدام اجازه‌ی نمایش نامشان را داده‌اند.",
    metaDesc: "فروشگاه‌ها و کسب‌وکارهایی که از آپ‌مارکت استفاده می‌کنند.",
    caseStudy: "مطالعه‌ی موردی ←",
    ctaTitle: "به این فهرست اضافه شو",
    ctaLead: "فروشگاهت را ثبت کن و ببین خروجی برای محصول خودت چه شکلی است.",
    seePricing: "دیدن قیمت‌ها",
  },
  en: {
    eyebrow: "Customers",
    title: "Businesses using UpMarket",
    lead: "Each one agreed to be named here.",
    metaDesc: "Shops and businesses using UpMarket.",
    caseStudy: "Case study →",
    ctaTitle: "Join them",
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
    alternates: alternatesFor(locale, "/customers"),
  };
}

/** §12. Only customers who ticked «اجازه‌ی نمایش دارد» — the filter is in the
 *  API, because a logo is a public claim about somebody else's business and a
 *  front-end that forgets it publishes anyway. */
export default async function Customers({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { customers } = await getProof();
  if (customers.length === 0) notFound();

  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/customers" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          <div className="grid g3 in-view-stagger mt-lg">
            {customers.map((customer) => (
              <article key={customer.slug} className="card">
                {customer.logo && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={customer.logo}
                    alt={customer.name}
                    width={160}
                    height={80}
                    loading="lazy"
                    style={{ maxHeight: 56, width: "auto", objectFit: "contain" }}
                  />
                )}
                <h3 className="mt-sm">{customer.name}</h3>
                {customer.industry && (
                  <span className="eyebrow">{customer.industry}</span>
                )}
                {customer.description && (
                  <p className="muted mt-sm">{customer.description}</p>
                )}
                {customer.caseStudy && (
                  <p className="mt-sm">
                    <Link
                      href={localePath(l, `/case-studies/${customer.caseStudy}`)}
                      className="muted"
                    >
                      {c.caseStudy}
                    </Link>
                  </p>
                )}
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
