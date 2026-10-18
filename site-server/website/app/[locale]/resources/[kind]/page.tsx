import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { getResources, RESOURCE_KINDS } from "@/lib/proof";
import { breadcrumbs } from "@/lib/seo";
import { COPY } from "../copy";

type Props = { params: Promise<{ locale: string; kind: string }> };

/**
 * §19's four sections as their own URLs: `/resources/guides`, `/templates`,
 * `/checklists`, `/ebooks`.
 *
 * Only the sections that actually have something in them are generated. A
 * section with no rows 404s rather than rendering a heading over nothing —
 * four near-identical empty pages is exactly the pattern §34 forbids.
 */
export async function generateStaticParams() {
  const { resources } = await getResources();
  const filled = RESOURCE_KINDS.filter((k) => resources.some((r) => r.kind === k));
  return LOCALES.flatMap((locale) => filled.map((kind) => ({ locale, kind })));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, kind } = await params;
  if (!isLocale(locale) || !RESOURCE_KINDS.includes(kind)) return {};
  const label = COPY[locale].kinds[kind];
  return {
    title: label,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, `/resources/${kind}`),
  };
}

export default async function ResourceKind({ params }: Props) {
  const { locale, kind } = await params;
  if (!isLocale(locale) || !RESOURCE_KINDS.includes(kind)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { resources } = await getResources(kind);
  if (resources.length === 0) notFound();

  const label = c.kinds[kind];

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.eyebrow, path: "/resources" },
            { name: label, path: `/resources/${kind}` },
          ],
          l,
        )}
      />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={label} lead={c.lead} />

          <div className="grid g3 in-view-stagger mt-lg">
            {resources.map((item) => (
              <article key={item.slug} className="card">
                {item.icon && <div className="icon-lg">{item.icon}</div>}
                <h2 className="mt-sm" style={{ fontSize: "1rem" }}>
                  {item.title}
                </h2>
                <p className="muted mt-sm">{item.description}</p>
                {item.file && (
                  <p className="mt-sm">
                    <a href={item.file} className="btn btn-ghost" download>
                      {c.download}
                    </a>
                  </p>
                )}
                {!item.file && item.body && (
                  <p className="muted mt-sm" style={{ whiteSpace: "pre-wrap" }}>
                    {item.body}
                  </p>
                )}
              </article>
            ))}
          </div>

          <p className="mt-lg">
            <Link href={localePath(l, "/resources")} className="muted back-link">
              {c.eyebrow}
            </Link>
          </p>
        </div>
      </section>
    </>
  );
}
