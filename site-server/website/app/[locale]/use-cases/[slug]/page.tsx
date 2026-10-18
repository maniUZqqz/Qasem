import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { allUseCaseSlugs, getUseCase } from "@/lib/seoPages";
import type { UseCase } from "@/lib/useCases";
import { abs, breadcrumbs } from "@/lib/seo";
import { LOCALE_META } from "@/lib/i18n";

type Props = { params: Promise<{ locale: string; slug: string }> };

export async function generateStaticParams() {
  const slugs = await allUseCaseSlugs();
  return LOCALES.flatMap((locale) => slugs.map((slug) => ({ locale, slug })));
}

const COPY = {
  fa: {
    crumb: "کاربردها",
    eyebrow: "کاربرد",
    why: "چرا سخت است",
    steps: "قدم به قدم",
    soonNote: "قدم‌های علامت‌خورده هنوز ساخته نشده‌اند. بقیه امروز کار می‌کنند.",
    output: "چه چیزی تحویل می‌گیرید",
    time: "زمان:",
    ctaTitle: "امتحانش کنید",
    ctaBody: "دو هفته رایگان، بدون کارت بانکی.",
    others: "کاربردهای دیگر",
  },
  en: {
    crumb: "Use cases",
    eyebrow: "Use case",
    why: "Why it is hard",
    steps: "Step by step",
    soonNote: "The marked steps are not built yet. The rest work today.",
    output: "What you end up with",
    time: "Time:",
    ctaTitle: "Try it",
    ctaBody: "Two weeks free, no card required.",
    others: "Other use cases",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const u = await getUseCase(slug, locale);
  if (!u) return {};
  return {
    title: u.title,
    description: u.pain,
    alternates: alternatesFor(locale, `/use-cases/${u.slug}`),
  };
}

/** HowTo schema, but only for the steps that actually work today. Marking a
 *  planned step as a completed instruction would be a false claim to Google
 *  and to the reader. */
function howToSchema(u: UseCase, locale: Locale) {
  const live = u.steps.filter((s) => !s.soon);
  if (live.length < 2) return null;
  return {
    "@context": "https://schema.org",
    "@type": "HowTo",
    name: u.title,
    description: u.pain,
    inLanguage: LOCALE_META[locale].htmlLang,
    url: abs(localePath(locale, `/use-cases/${u.slug}`)),
    step: live.map((s, i) => ({
      "@type": "HowToStep",
      position: i + 1,
      name: s.title,
      text: s.desc,
    })),
  };
}

export default async function UseCasePage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const u = await getUseCase(slug, l);
  if (!u) notFound();

  const c = COPY[l];
  const site = await getSite(l);
  const t = dict(l);
  const schema = howToSchema(u, l);
  const hasSoon = u.steps.some((s) => s.soon);
  const quoted = l === "fa" ? `«${u.goal}»` : `“${u.goal}”`;

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.crumb, path: "/use-cases" },
            { name: u.title, path: `/use-cases/${u.slug}` },
          ],
          l,
        )}
      />
      {schema && <JsonLd data={schema} />}

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={`${u.icon} ${c.eyebrow}`} title={u.title} lead={quoted} />

          <div className="narrow mt-md">
            <h2>{c.why}</h2>
            <p className="lead mt-sm">{u.pain}</p>
          </div>

          <div className="mt-md">
            <h2>{c.steps}</h2>
            <ol className="timeline mt-sm">
              {u.steps.map((s, i) => (
                <li key={s.title} className="tl-item">
                  <span className="tl-dot">{i + 1}</span>
                  <div className="tl-body">
                    <strong>{s.title}</strong>
                    {s.soon && <span className="pill mb-sm"> {t.common.soon}</span>}
                    <p className="muted mt-sm">{s.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
            {hasSoon && <p className="muted mt-sm">{c.soonNote}</p>}
          </div>

          <div className="mt-md">
            <h2>{c.output}</h2>
            <ul className="checks mt-sm">
              {u.output.map((o) => (
                <li key={o}>{o}</li>
              ))}
            </ul>
            <p className="muted mt-sm">
              <strong>{c.time}</strong> {u.effort}
            </p>
          </div>

          <div className="cta-card mt-md">
            <h3>{c.ctaTitle}</h3>
            <p className="muted mt-sm">{c.ctaBody}</p>
            <div className="row mt-sm">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.primary}
              </a>
              <Link href={localePath(l, "/use-cases")} className="btn btn-ghost">
                {c.others}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
