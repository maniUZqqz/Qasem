import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { allFeatureSlugs, getFeaturePage, getFeaturePages } from "@/lib/seoPages";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string; slug: string }> };

export async function generateStaticParams() {
  const slugs = await allFeatureSlugs();
  return LOCALES.flatMap((locale) => slugs.map((slug) => ({ locale, slug })));
}

const COPY = {
  fa: {
    crumb: "قابلیت‌ها",
    eyebrow: "قابلیت",
    problem: "مشکل چیست",
    does: "چه کاری انجام می‌دهد",
    how: "چطور کار می‌کند",
    example: "یک نمونه",
    before: "قبل",
    after: "بعد",
    benefit: "چرا مهم است",
    planned: "هنوز ساخته نشده",
    plannedNote:
      "این‌ها در نقشه‌ی راه هستند و هنوز کار نمی‌کنند. اینجا نوشته شده‌اند تا بعداً غافلگیر نشوید.",
    related: "مرتبط",
    all: "← همه‌ی قابلیت‌ها",
  },
  en: {
    crumb: "Features",
    eyebrow: "Feature",
    problem: "The problem",
    does: "What it does",
    how: "How it works",
    example: "An example",
    before: "Before",
    after: "After",
    benefit: "Why it matters",
    planned: "Not built yet",
    plannedNote:
      "These are on the roadmap and do not work yet. They are listed here so nothing is a surprise later.",
    related: "Related",
    all: "← All features",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const f = await getFeaturePage(slug, locale);
  if (!f) return {};
  return {
    title: f.title,
    description: f.lead,
    alternates: alternatesFor(locale, `/features/${f.slug}`),
  };
}

export default async function FeaturePage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const pages = await getFeaturePages(l);
  const f = pages.find((p) => p.slug === slug);
  if (!f) notFound();

  const c = COPY[l];
  const t = dict(l);
  const site = await getSite(l);

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.crumb, path: "/features" },
            { name: f.title, path: `/features/${f.slug}` },
          ],
          l,
        )}
      />

      <section className="mesh">
        <div className="wrap">
          <SectionHead
            as="h1"
            eyebrow={`${f.icon} ${c.eyebrow}`}
            title={f.title}
            lead={f.lead}
          />

          <div className="narrow mt-md">
            <h2>{c.problem}</h2>
            <p className="lead mt-sm">{f.problem}</p>
          </div>

          <div className="mt-md">
            <h2>{c.does}</h2>
            <ul className="checks mt-sm">
              {f.does.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </div>

          <div className="mt-md">
            <h2>{c.how}</h2>
            <div className="grid g3 in-view-stagger mt-sm">
              {f.how.map((h) => (
                <div key={h.title} className="card">
                  <h3>{h.title}</h3>
                  <p className="muted mt-sm">{h.desc}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-md">
            <h2>{c.example}</h2>
            <div className="vs-grid mt-sm">
              <div className="vs-card">
                <span className="pill">{c.before}</span>
                <p className="mt-sm">{f.example.before}</p>
              </div>
              <div className="vs-mid">{l === "fa" ? "←" : "→"}</div>
              <div className="vs-card">
                <span className="pill">{c.after}</span>
                <p className="mt-sm">{f.example.after}</p>
              </div>
            </div>
          </div>

          <div className="narrow mt-md">
            <h2>{c.benefit}</h2>
            <p className="lead mt-sm">{f.benefit}</p>
          </div>

          {/* Planned work is kept visually separate from what ships today.
              Blending the two is how a marketing page becomes a promise the
              product cannot keep. */}
          {f.planned && f.planned.length > 0 && (
            <div className="mt-md">
              <h2>{c.planned}</h2>
              <p className="muted mt-sm">{c.plannedNote}</p>
              <ul className="checks mt-sm">
                {f.planned.map((p) => (
                  <li key={p}>
                    {p} <span className="pill">{t.common.soon}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="cta-card mt-md">
            <h3>{t.cta.noCard}</h3>
            <div className="row mt-sm">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/showcase")} className="btn btn-ghost">
                {t.cta.seeWork}
              </Link>
            </div>
          </div>

          <div className="mt-md">
            <h3>{c.related}</h3>
            <div className="pill-row mt-sm">
              {f.related.map((slug2) => {
                const r = pages.find((p) => p.slug === slug2);
                if (!r) return null;
                return (
                  <Link
                    key={slug2}
                    href={localePath(l, `/features/${slug2}`)}
                    className="pill"
                  >
                    {r.icon} {r.title}
                  </Link>
                );
              })}
            </div>
          </div>

          <div className="mt-md">
            <Link href={localePath(l, "/features")} className="muted back-link">
              {c.all}
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
