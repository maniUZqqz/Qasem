import type { Metadata } from "next";
import Link from "next/link";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { notFound } from "next/navigation";

import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { num } from "@/lib/plans";
import { breadcrumbs } from "@/lib/seo";
import { getWorks } from "@/lib/showcase";
import { COPY } from "./copy";

type Props = { params: Promise<{ locale: string }> };

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  if (!isLocale(locale)) return {};
  return {
    title: COPY[locale].metaTitle,
    description: COPY[locale].metaDesc,
    alternates: alternatesFor(locale, "/showcase"),
  };
}

/**
 * Content comes from the backend (`/api/v1/site/showcase/`), where it is
 * editable in the Django admin, and falls back to
 * `content/showcase/works.json` — written by `scripts/sync-showcase.mjs` from
 * the real sample folder — when the backend cannot be reached at build time.
 *
 * Each work shows **one** video. The renderer produces five-second shots that
 * continue into each other; joining them is the backend's job, not the
 * visitor's imagination.
 */
export default async function Showcase({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const site = await getSite(l);
  const t = dict(l);
  const items = await getWorks(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/showcase" }], l)} />

      <section className="mesh">
        <div className="wrap">
          <SectionHead as="h1"
            eyebrow={c.eyebrow}
            title={c.title}
            lead={c.lead}
          />

          {items.length === 0 ? (
            <p className="muted center mt-lg">{c.empty}</p>
          ) : (
            <div className="stack mt-lg gap-lg">
              {items.map((w) => (
                <article key={w.id} className="card">
                  <div className="row-tight">
                    <span className="eyebrow">{w.category}</span>
                    <h2 style={{ fontSize: "1.15rem" }}>{w.product}</h2>
                  </div>

                  <div className="grid g2 in-view-stagger mt">
                    <div>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        className="shot"
                        src={w.image}
                        alt={c.posterAlt(w.product)}
                        width={1024}
                        height={1024}
                        loading="lazy"
                      />
                      {w.video && (
                        <div className="clip">
                          <video
                            src={w.video}
                            poster={w.videoPoster}
                            muted
                            loop
                            playsInline
                            autoPlay
                            controls
                            preload="metadata"
                            aria-label={c.videoAlt(w.product)}
                          />
                          {w.segmentCount > 1 && (
                            <div className="clip-note">
                              {c.stitchedNote(
                                num(w.segmentCount, l),
                                num(w.segmentCount * 5, l),
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>

                    <div>
<div className="muted mb-sm">{c.captionLabel}</div>
                      <div className="caption-box">{w.caption}</div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="section-soft">
        <div className="wrap">
          <SectionHead
            eyebrow={c.howEyebrow}
            title={c.howTitle}
          />
          <div className="grid g4 in-view-stagger mt-lg">
            {c.steps.map((s) => (
              <article key={s.t} className="card">
                <div className="icon-lg">{s.icon}</div>
                <h3 className="mt-sm">{s.t}</h3>
                <p className="muted mt-sm">{s.d}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section>
        <div className="wrap">
          <div className="cta-band">
            <h2>{c.ctaTitle}</h2>
            <p className="lead mt narrower">
{c.ctaLead}
            </p>
            <div className="row mt-md center-row">
              <a href={`${site.panelUrl}/register`} className="btn btn-primary">
                {t.cta.startFree}
              </a>
              <Link href={localePath(l, "/pricing")} className="btn btn-ghost">{c.seePricing}</Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
