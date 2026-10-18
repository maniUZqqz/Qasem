import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import ToolRunner from "@/components/tools/ToolRunner";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";
import { getTool, toolSlugs, toolsFor } from "@/lib/tools/meta";

type Props = { params: Promise<{ locale: string; slug: string }> };

export function generateStaticParams() {
  return LOCALES.flatMap((locale) => toolSlugs.map((slug) => ({ locale, slug })));
}

const COPY = {
  fa: {
    crumb: "ابزار رایگان",
    eyebrow: "ابزار رایگان",
    honestyTitle: "این ابزار چیست و چه نیست",
    tips: "نکته‌هایی که به کار می‌آید",
    upsellTitle: "نسخه‌ای که محصول خودت را می‌شناسد",
    others: "ابزارهای دیگر",
    all: "← همه‌ی ابزارها",
  },
  en: {
    crumb: "Free tools",
    eyebrow: "Free tool",
    honestyTitle: "What this is, and what it is not",
    tips: "Things worth knowing",
    upsellTitle: "The version that knows your product",
    others: "Other tools",
    all: "← All tools",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const tool = getTool(slug, locale);
  if (!tool) return {};
  return {
    title: tool.title,
    description: tool.metaDesc,
    alternates: alternatesFor(locale, `/tools/${tool.slug}`),
  };
}

export default async function ToolPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const tool = getTool(slug, l);
  if (!tool) notFound();

  const c = COPY[l];
  const t = dict(l);
  const site = await getSite(l);

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.crumb, path: "/tools" },
            { name: tool.title, path: `/tools/${tool.slug}` },
          ],
          l,
        )}
      />

      <section className="mesh">
        <div className="wrap" style={{ maxWidth: 900 }}>
          <SectionHead
            as="h1"
            eyebrow={`${tool.icon} ${c.eyebrow}`}
            title={tool.title}
            lead={tool.lead}
          />

          <p className="lead mt-md">{tool.intro}</p>

          <div className="mt-md">
            <ToolRunner slug={tool.slug} locale={l} />
          </div>

          {/* Stated up front, not buried. Someone who mistakes the free tool
              for the paid product will be disappointed twice. */}
          <div className="card mt-md" style={{ borderColor: "var(--color-brand-400)" }}>
            <h2 style={{ fontSize: "1.05rem" }}>{c.honestyTitle}</h2>
            <p className="muted mt-sm">{tool.honesty}</p>
          </div>

          <div className="mt-md">
            <h2>{c.tips}</h2>
            <ul className="checks mt-sm">
              {tool.tips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </div>

          <div className="cta-card mt-md">
            <h3>{c.upsellTitle}</h3>
            <p className="muted mt-sm">{tool.upsell}</p>
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
              {toolsFor(l)
                .filter((o) => o.slug !== tool.slug)
                .map((o) => (
                  <Link key={o.slug} href={localePath(l, `/tools/${o.slug}`)} className="pill">
                    {o.icon} {o.title}
                  </Link>
                ))}
            </div>
          </div>

          <div className="mt-md">
            <Link href={localePath(l, "/tools")} className="muted back-link">
              {c.all}
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
