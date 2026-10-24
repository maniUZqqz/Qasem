import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { allComparisonSlugs, getComparison, getComparisons } from "@/lib/seoPages";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string; slug: string }> };

export async function generateStaticParams() {
  const slugs = await allComparisonSlugs();
  return LOCALES.flatMap((locale) => slugs.map((slug) => ({ locale, slug })));
}

const COPY = {
  fa: {
    crumb: "مقایسه",
    eyebrow: "مقایسه",
    table: "کنار هم",
    aspect: "موضوع",
    us: "NMarketing",
    theirWins: "کِی گزینه‌ی دیگر بهتر است",
    ourWins: "کِی NMarketing بهتر است",
    verdict: "جمع‌بندی",
    others: "مقایسه‌های دیگر",
    all: "← همه‌ی مقایسه‌ها",
  },
  en: {
    crumb: "Compare",
    eyebrow: "Comparison",
    table: "Side by side",
    aspect: "Aspect",
    us: "NMarketing",
    theirWins: "When the alternative is better",
    ourWins: "When NMarketing is better",
    verdict: "The short answer",
    others: "Other comparisons",
    all: "← All comparisons",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const cmp = await getComparison(slug, locale);
  if (!cmp) return {};
  return {
    title: cmp.title,
    description: cmp.metaDesc,
    alternates: alternatesFor(locale, `/compare/${cmp.slug}`),
  };
}

export default async function ComparePage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const all = await getComparisons(l);
  const cmp = all.find((c) => c.slug === slug);
  if (!cmp) notFound();

  const c = COPY[l];
  const t = dict(l);
  const site = await getSite(l);

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.crumb, path: "/compare" },
            { name: cmp.title, path: `/compare/${cmp.slug}` },
          ],
          l,
        )}
      />

      <section className="mesh">
        <div className="wrap">
          <SectionHead
            as="h1"
            eyebrow={`${cmp.icon} ${c.eyebrow}`}
            title={cmp.title}
            lead={cmp.lead}
          />

          <p className="lead mt-md narrow">{cmp.intro}</p>

          <div className="mt-md">
            <h2>{c.table}</h2>
            <div className="card mt-sm" style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "start", padding: "10px 8px" }}>{c.aspect}</th>
                    <th style={{ textAlign: "start", padding: "10px 8px" }}>{c.us}</th>
                    <th style={{ textAlign: "start", padding: "10px 8px" }}>{cmp.other}</th>
                  </tr>
                </thead>
                <tbody>
                  {cmp.rows.map((r) => (
                    <tr key={r.aspect} style={{ borderTop: "1px solid var(--line)" }}>
                      <td style={{ padding: "10px 8px", fontWeight: 600 }}>{r.aspect}</td>
                      <td style={{ padding: "10px 8px" }}>{r.us}</td>
                      <td style={{ padding: "10px 8px" }} className="muted">
                        {r.them}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Their side comes first on purpose. A comparison that buries the
              honest half below the sales half is not a comparison. */}
          <div className="grid g2 in-view-stagger mt-md">
            <div className="card">
              <h2 style={{ fontSize: "1.05rem" }}>{c.theirWins}</h2>
              <ul className="checks mt-sm">
                {cmp.theirWins.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
            <div className="card">
              <h2 style={{ fontSize: "1.05rem" }}>{c.ourWins}</h2>
              <ul className="checks mt-sm">
                {cmp.ourWins.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="narrow mt-md">
            <h2>{c.verdict}</h2>
            <p className="lead mt-sm">{cmp.verdict}</p>
          </div>

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
            <h3>{c.others}</h3>
            <div className="pill-row mt-sm">
              {all
                .filter((o) => o.slug !== cmp.slug)
                .map((o) => (
                  <Link
                    key={o.slug}
                    href={localePath(l, `/compare/${o.slug}`)}
                    className="pill"
                  >
                    {o.icon} {o.title}
                  </Link>
                ))}
            </div>
          </div>

          <div className="mt-md">
            <Link href={localePath(l, "/compare")} className="muted back-link">
              {c.all}
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
