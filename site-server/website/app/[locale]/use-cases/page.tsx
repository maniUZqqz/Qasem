import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { getUseCases } from "@/lib/seoPages";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "کاربردها",
    title: "می‌خواهید چه کاری انجام دهید؟",
    lead: "به‌جای فهرست قابلیت‌ها، از کاری که در ذهن دارید شروع کنید.",
    steps: "قدم‌ها →",
    ctaTitle: "همه‌ی این‌ها در یک محصول",
    ctaBody:
      "لازم نیست برای هر کار یک ابزار جدا بخرید — داده‌ی محصول یک بار وارد می‌شود و بقیه رویش سوار می‌شوند.",
    metaTitle: "با NMarketing چه کارهایی می‌شود کرد",
    metaDesc:
      "تولید محتوای شبکه‌های اجتماعی، معرفی محصول جدید، تحلیل رقبا، ساخت ویدیوی تبلیغاتی و جواب دادن به مشتری‌ها — قدم به قدم.",
  },
  en: {
    eyebrow: "Use cases",
    title: "What are you trying to do?",
    lead: "Instead of a feature list, start from the job you have in mind.",
    steps: "Steps →",
    ctaTitle: "All of it in one product",
    ctaBody:
      "You do not need a separate tool per job — the product data goes in once and everything else builds on it.",
    metaTitle: "What you can do with NMarketing",
    metaDesc:
      "Social content, product launches, competitor analysis, promotional video and answering customers — step by step.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  const c = COPY[locale];
  return {
    title: c.metaTitle,
    description: c.metaDesc,
    alternates: alternatesFor(locale, "/use-cases"),
  };
}

export default async function UseCases({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const useCases = await getUseCases(l);
  const c = COPY[l];
  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/use-cases" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          <div className="grid g3 in-view-stagger mt-md">
            {useCases.map((u) => (
              <Link
                key={u.slug}
                href={localePath(l, `/use-cases/${u.slug}`)}
                className="card card-hover glow-edge"
              >
                <span className="icon-lg">{u.icon}</span>
                <h3 className="mt-sm">{u.title}</h3>
                <p className="muted mt-sm">{l === "fa" ? `«${u.goal}»` : `“${u.goal}”`}</p>
                <span className="pill mt-sm">{c.steps}</span>
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
