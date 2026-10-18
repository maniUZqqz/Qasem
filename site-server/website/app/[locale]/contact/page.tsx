import type { Metadata } from "next";
import { notFound } from "next/navigation";

import ContactForm from "@/components/ContactForm";
import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, LOCALES, type Locale } from "@/lib/i18n";
import { breadcrumbs } from "@/lib/seo";
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
    alternates: alternatesFor(locale, "/contact"),
  };
}

export default async function Contact({ params }: Props) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const site = await getSite(l);
  const t = dict(l);

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: c.eyebrow, path: "/contact" }], l)} />

      <section>
        <div className="wrap" style={{ maxWidth: 860 }}>
          <SectionHead as="h1" eyebrow={c.eyebrow} title={c.title} lead={c.lead} />

          <div className="mt-md">
            <ContactForm locale={l} />
          </div>

          <div className="grid g3 in-view-stagger mt-md">
            <a href={`mailto:${site.email}`} className="card card-hover glow-edge plain">
              <div className="icon-lg">✉️</div>
              <h3 className="mt-sm">{c.email}</h3>
              <p className="muted mt-sm" dir="ltr">
                {site.email}
              </p>
            </a>

            <a
              href={site.instagram}
              target="_blank"
              rel="noopener noreferrer"
              className="card card-hover glow-edge plain"
            >
              <div className="icon-lg">📷</div>
              <h3 className="mt-sm">{c.instagram}</h3>
              <p className="muted mt-sm">{c.instagramNote}</p>
            </a>

            <div className="card">
              <div className="icon-lg">⚡</div>
              <h3 className="mt-sm">{c.fastest}</h3>
              <p className="muted mt-sm">{c.fastestNote}</p>
              <a
                href={`${site.panelUrl}/register`}
                className="btn btn-primary"
                style={{ marginTop: 12 }}
              >
                {t.cta.startFree}
              </a>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
