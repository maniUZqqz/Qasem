import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";
import { toolsFor } from "@/lib/tools/meta";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "ابزار رایگان",
    title: "ابزارهایی که همین حالا می‌توانی استفاده کنی",
    lead: "بدون ثبت‌نام، بدون ایمیل، بدون محدودیت.",
    metaDesc:
      "ابزارهای رایگان بازاریابی برای فروشگاه‌های آنلاین — کپشن‌ساز، بایوساز و تقویم محتوا.",
    note:
      "این ابزارها در مرورگر خودت اجرا می‌شوند. هوش مصنوعی نیستند و چیزی به سروری فرستاده نمی‌شود.",
    ctaTitle: "نسخه‌ای که محصول خودت را می‌شناسد",
    ctaLead:
      "این ابزارها روی چیزی کار می‌کنند که تو می‌نویسی. محصول اصلی، از روی عکس واقعی محصولت و کاتالوگ خودت می‌نویسد.",
  },
  en: {
    eyebrow: "Free tools",
    title: "Tools you can use right now",
    lead: "No signup, no email, no limit.",
    metaDesc:
      "Free marketing tools for online shops — caption generator, bio generator and content calendar.",
    note:
      "These run in your own browser. They are not AI and nothing is sent to a server.",
    ctaTitle: "The version that knows your product",
    ctaLead:
      "These tools work on what you type. The product itself writes from your real product photo and your own catalogue.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/tools"),
  };
}

export default async function Tools({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const t = dict(l);
  const site = await getSite(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/tools" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />
          <p className="muted center mt-sm">{c.note}</p>

          <div className="grid g3 in-view-stagger mt-md">
            {toolsFor(l).map((tool) => (
              <Link
                key={tool.slug}
                href={localePath(l, `/tools/${tool.slug}`)}
                className="card card-hover glow-edge plain"
              >
                <span className="icon-lg">{tool.icon}</span>
                <h2 className="mt-sm" style={{ fontSize: "1.1rem" }}>{tool.title}</h2>
                <p className="muted mt-sm">{tool.lead}</p>
              </Link>
            ))}
          </div>

          <div className="cta-card mt-md">
            <h3>{c.ctaTitle}</h3>
            <p className="muted mt-sm">{c.ctaLead}</p>
            <div className="row mt-sm">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/features")} className="btn btn-ghost">
                {t.cta.features}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
