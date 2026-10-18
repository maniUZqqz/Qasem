import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { getResources, RESOURCE_KINDS } from "@/lib/proof";
import { breadcrumbs } from "@/lib/seo";
import { getSite } from "@/lib/site";
import { COPY } from "./copy";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].eyebrow,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/resources"),
  };
}

/** §19. 404s while the library is empty — a resources page with no resources
 *  is a page built for Google, which §34 lists by name. */
export default async function Resources({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const { resources } = await getResources();
  if (resources.length === 0) notFound();

  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/resources" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          {RESOURCE_KINDS.map((kind) => {
            const rows = resources.filter((r) => r.kind === kind);
            if (rows.length === 0) return null;
            return (
              <div key={kind} className="mt-lg">
                <div className="row-tight">
                  <h2 style={{ fontSize: "1.1rem" }}>{c.kinds[kind]}</h2>
                  <Link href={localePath(l, `/resources/${kind}`)} className="muted back-link">
                    ←
                  </Link>
                </div>
                <div className="grid g3 in-view-stagger mt">
                  {rows.map((item) => (
                    <article key={item.slug} className="card">
                      {item.icon && <div className="icon-lg">{item.icon}</div>}
                      <h3 className="mt-sm">{item.title}</h3>
                      <p className="muted mt-sm">{item.description}</p>
                      {item.file && (
                        <p className="mt-sm">
                          <a href={item.file} className="btn btn-ghost" download>
                            {c.download}
                          </a>
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <div className="cta-band">
            <h2>{c.ctaTitle}</h2>
            <p className="lead mt narrower">{c.ctaLead}</p>
            <div className="row mt-md center-row">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/pricing")} className="btn btn-ghost">
                {c.seePricing}
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
