import type { Metadata } from "next";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { contentFor } from "@/lib/content";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

const COPY = {
  fa: {
    eyebrow: "درباره ما",
    headline: "بازاریابی حرفه‌ای نباید امتیاز شرکت‌های بزرگ باشد",
    story: "چطور به اینجا رسیدیم",
    values: "اصولی که رعایت می‌کنیم",
    work: "با ما کار کنید",
    numerals: ["۱", "۲", "۳"],
    metaDesc: "چرا آپ‌مارکت را ساختیم و چه اصولی در محصول رعایت می‌کنیم.",
  },
  en: {
    eyebrow: "About",
    headline: "Good marketing should not be a privilege of large companies",
    story: "How we got here",
    values: "What we hold to",
    work: "Work with us",
    numerals: ["1", "2", "3"],
    metaDesc: "Why we built UpMarket, and the principles the product is held to.",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/about"),
  };
}

export default async function About({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { about } = contentFor(l);
  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/about" }], l)} />

      <section>
        <div className="wrap" style={{ maxWidth: 760, textAlign: "center" }}>
          <span className="eyebrow">{c.eyebrow}</span>
          <h1 style={{ marginTop: 18, fontSize: "clamp(1.7rem, 4vw, 2.6rem)" }}>
            {c.headline}
          </h1>
          <p className="lead" style={{ marginTop: 20 }}>
            {about.mission}
          </p>
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <SectionHead title={c.story} />
          <div className="grid g3 in-view-stagger mt-lg">
            {about.story.map((s, i) => (
              <div key={s.title} className="card">
                <span className="eyebrow">{c.numerals[i]}</span>
                <h3 className="mt">{s.title}</h3>
                <p className="muted" style={{ marginTop: 8, lineHeight: 2 }}>
                  {s.text}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <SectionHead title={c.values} />
          <div className="grid g4 in-view-stagger mt-lg">
            {about.values.map((v) => (
              <div key={v.title} className="card">
                <div className="icon-lg">{v.icon}</div>
                <h3 className="mt-sm">{v.title}</h3>
                <p className="muted mt-sm">{v.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap" style={{ textAlign: "center" }}>
          <h2>{c.work}</h2>
          <a href={`${site.panelUrl}/register`} className="btn btn-primary mt-md">
            {t.cta.startFree} →
          </a>
        </div>
      </section>
    </>
  );
}
