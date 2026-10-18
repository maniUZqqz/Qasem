import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { getSolutions } from "@/lib/seoPages";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "راه‌حل‌ها",
    title: "آپ‌مارکت برای چه کسب‌وکاری ساخته شده؟",
    lead: "ابزار یکسان است، ولی مشکل هر صنف فرق دارد. این صفحه‌ها بر اساس همان تفاوت نوشته شده‌اند.",
    more: "ببینید چطور →",
    ctaTitle: "صنف شما اینجا نیست؟",
    ctaBody:
      "محصول به صنف خاصی وابسته نیست — هر فروشگاهی که محصول و عکس دارد کار می‌کند. این صفحه‌ها فقط برای صنف‌هایی ساخته شده‌اند که حرف مشخصی برایشان داریم.",
    ask: "بپرسید",
    metaTitle: "آپ‌مارکت برای چه کسب‌وکارهایی",
    metaDesc:
      "فروشنده‌ی اینستاگرام، فروشگاه اینترنتی، پوشاک، دکوراسیون — هر کدام مشکل متفاوتی دارند و جریان کار متفاوتی می‌خواهند.",
  },
  en: {
    eyebrow: "Solutions",
    title: "Who is UpMarket built for?",
    lead: "The tool is the same; the problem is not. These pages are written around that difference.",
    more: "See how →",
    ctaTitle: "Your line of work not here?",
    ctaBody:
      "The product is not tied to an industry — any shop with products and photos works. These pages exist only where we have something specific to say.",
    ask: "Ask us",
    metaTitle: "Who UpMarket is built for",
    metaDesc:
      "Instagram sellers, online shops, clothing, home decor — each has a different problem and a different workflow.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const c = COPY[locale];
  return {
    title: c.metaTitle,
    description: c.metaDesc,
    alternates: alternatesFor(locale, "/solutions"),
  };
}

export default async function Solutions({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const solutions = await getSolutions(l);
  const c = COPY[l];
  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/solutions" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          <div className="grid g2 in-view-stagger mt-md">
            {solutions.map((s) => (
              <Link
                key={s.slug}
                href={localePath(l, `/solutions/${s.slug}`)}
                className="card card-hover glow-edge"
              >
                <span className="icon-lg">{s.icon}</span>
                <h3 className="mt-sm">{s.name}</h3>
                <p className="muted mt-sm">{s.tagline}</p>
                <p className="mt-sm">{s.problem[0]}</p>
                <span className="pill mt-sm">{c.more}</span>
              </Link>
            ))}
          </div>

          <div className="cta-card mt-md">
            <h3>{c.ctaTitle}</h3>
            <p className="muted mt-sm">{c.ctaBody}</p>
            <div className="row mt-sm">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/contact")} className="btn btn-ghost">
                {c.ask}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
