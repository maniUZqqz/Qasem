import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { allSolutionSlugs, getSolution } from "@/lib/seoPages";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string; slug: string }> };

export async function generateStaticParams() {
  const slugs = await allSolutionSlugs();
  return LOCALES.flatMap((locale) => slugs.map((slug) => ({ locale, slug })));
}

const COPY = {
  fa: {
    crumb: "راه‌حل‌ها",
    problem: "مشکل چیست",
    answer: "آپ‌مارکت چه می‌کند",
    example: "یک نمونه",
    before: "قبل",
    after: "بعد",
    workflow: "جریان کار",
    features: "قابلیت‌هایی که اینجا بیشتر به کار می‌آیند",
    ctaTitle: "دو هفته رایگان، بدون کارت بانکی",
    ctaBody: "چند محصول خودتان را وارد کنید و خروجی واقعی بگیرید.",
    seeWork: "اول نمونه‌کار را ببینم",
    all: "← همه‌ی راه‌حل‌ها",
    forWho: (n: string) => `آپ‌مارکت برای ${n}`,
  },
  en: {
    crumb: "Solutions",
    problem: "The problem",
    answer: "What UpMarket does",
    example: "An example",
    before: "Before",
    after: "After",
    workflow: "How it goes",
    features: "The features that matter most here",
    ctaTitle: "Two weeks free, no card required",
    ctaBody: "Add a few of your own products and see real output.",
    seeWork: "Show me real output first",
    all: "← All solutions",
    forWho: (n: string) => `UpMarket for ${n}`,
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const s = await getSolution(slug, locale);
  if (!s) return {};
  return {
    title: COPY[locale].forWho(s.name),
    description: `${s.tagline} — ${s.problem[0]}`,
    alternates: alternatesFor(locale, `/solutions/${s.slug}`),
  };
}

export default async function SolutionPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const s = await getSolution(slug, l);
  if (!s) notFound();

  const c = COPY[l];
  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.crumb, path: "/solutions" },
            { name: s.name, path: `/solutions/${s.slug}` },
          ],
          l,
        )}
      />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={`${s.icon} ${s.name}`} title={s.tagline} />

          <div className="narrow mt-md">
            <h2>{c.problem}</h2>
            <ul className="checks mt-sm">
              {s.problem.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </div>

          <div className="mt-md">
            <h2>{c.answer}</h2>
            <div className="grid g3 in-view-stagger mt-sm">
              {s.answer.map((a) => (
                <div key={a.title} className="card">
                  <h3>{a.title}</h3>
                  <p className="muted mt-sm">{a.desc}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-md">
            <h2>{c.example}</h2>
            <div className="vs-grid mt-sm">
              <div className="vs-card">
                <span className="pill">{c.before}</span>
                <p className="mt-sm">{s.example.before}</p>
              </div>
              <div className="vs-mid">{l === "fa" ? "←" : "→"}</div>
              <div className="vs-card">
                <span className="pill">{c.after}</span>
                <p className="mt-sm">{s.example.after}</p>
              </div>
            </div>
          </div>

          <div className="mt-md">
            <h2>{c.workflow}</h2>
            <ol className="timeline mt-sm">
              {s.workflow.map((w, i) => (
                <li key={w} className="tl-item">
                  <span className="tl-dot">{i + 1}</span>
                  <div className="tl-body">{w}</div>
                </li>
              ))}
            </ol>
          </div>

          <div className="mt-md">
            <h2>{c.features}</h2>
            <div className="pill-row mt-sm">
              {s.features.map((f) => (
                <span key={f} className="pill">
                  {f}
                </span>
              ))}
            </div>
          </div>

          <div className="cta-card mt-md">
            <h3>{c.ctaTitle}</h3>
            <p className="muted mt-sm">{c.ctaBody}</p>
            <div className="row mt-sm">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.primary}
              </a>
              <Link href={localePath(l, "/showcase")} className="btn btn-ghost">
                {c.seeWork}
              </Link>
            </div>
          </div>

          <div className="mt-md">
            <Link href={localePath(l, "/solutions")} className="muted back-link">
              {c.all}
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
