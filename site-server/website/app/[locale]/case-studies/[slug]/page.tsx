import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { dict } from "@/lib/dict";
import { alternatesFor, isLocale, localePath, LOCALES, type Locale } from "@/lib/i18n";
import { getCaseStudy, getProof } from "@/lib/proof";
import { breadcrumbs } from "@/lib/seo";
import { getSite } from "@/lib/site";

type Props = { params: Promise<{ locale: string; slug: string }> };

export async function generateStaticParams() {
  const { caseStudies } = await getProof();
  return LOCALES.flatMap((locale) =>
    caseStudies.map((study) => ({ locale, slug: study.slug })),
  );
}

const COPY = {
  fa: {
    eyebrow: "مطالعه‌ی موردی",
    sections: {
      problem: "مسئله",
      before: "قبل",
      solution: "کاری که کردیم",
      process: "روند",
      outputs: "خروجی‌ها",
      results: "نتیجه",
      conclusion: "جمع‌بندی",
    },
    all: "همه‌ی مطالعات موردی",
    ctaTitle: "نوبت کسب‌وکار خودت",
    ctaLead: "فروشگاهت را ثبت کن و ببین خروجی برای محصول خودت چه شکلی است.",
    seePricing: "دیدن قیمت‌ها",
  },
  en: {
    eyebrow: "Case study",
    sections: {
      problem: "The problem",
      before: "Before",
      solution: "What we did",
      process: "The process",
      outputs: "What was produced",
      results: "The result",
      conclusion: "In short",
    },
    all: "All case studies",
    ctaTitle: "Your business next",
    ctaLead: "Add your shop and see what the output looks like for your own product.",
    seePricing: "See pricing",
  },
} as const;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isLocale(locale)) return {};
  const study = await getCaseStudy(slug);
  if (!study) return {};
  return {
    title: study.title,
    description: study.lead || study.problem.slice(0, 160),
    alternates: alternatesFor(locale, `/case-studies/${study.slug}`),
    openGraph: study.cover ? { images: [study.cover] } : undefined,
  };
}

/** §11's section order, because that order is what makes it read as a story
 *  rather than a feature list with a customer's name on top. */
export default async function CaseStudyPage({ params }: Props) {
  const { locale, slug } = await params;
  if (!isLocale(locale)) notFound();
  const l = locale as Locale;
  const c = COPY[l];
  const study = await getCaseStudy(slug);
  if (!study) notFound();

  const site = await getSite(l);
  const t = dict(l);

  const sections = [
    [c.sections.problem, study.problem],
    [c.sections.before, study.before],
    [c.sections.solution, study.solution],
    [c.sections.process, study.process],
    [c.sections.outputs, study.outputs],
    [c.sections.results, study.results],
    [c.sections.conclusion, study.conclusion],
  ].filter(([, body]) => body);

  return (
    <>
      <JsonLd
        data={breadcrumbs(
          [
            { name: c.eyebrow, path: "/case-studies" },
            { name: study.title, path: `/case-studies/${study.slug}` },
          ],
          l,
        )}
      />

      <section className="mesh">
        <div className="wrap narrow">
          <SectionHead
            as="h1"
            eyebrow={study.customer || c.eyebrow}
            title={study.title}
            lead={study.lead}
          />

          {study.cover && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              className="shot mt-lg"
              src={study.cover}
              alt={study.title}
              width={1200}
              height={630}
              loading="lazy"
            />
          )}

          <div className="stack mt-lg gap-lg">
            {sections.map(([heading, body]) => (
              <div key={heading}>
                <h2 style={{ fontSize: "1.1rem" }}>{heading}</h2>
                <p className="muted mt-sm" style={{ whiteSpace: "pre-wrap" }}>
                  {body}
                </p>
              </div>
            ))}
          </div>

          {study.testimonials.length > 0 && (
            <div className="stack mt-lg gap-md">
              {study.testimonials.map((quote) => (
                <blockquote key={quote.quote} className="card">
                  <p style={{ whiteSpace: "pre-wrap" }}>«{quote.quote}»</p>
                  <footer className="muted mt-sm">
                    {quote.name}
                    {quote.business && ` — ${quote.business}`}
                  </footer>
                </blockquote>
              ))}
            </div>
          )}

          <p className="mt-lg">
            <Link href={localePath(l, "/case-studies")} className="muted back-link">
              {c.all}
            </Link>
          </p>
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
