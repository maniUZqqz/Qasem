import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { dict } from "@/lib/dict";
import { localePath, type Locale } from "@/lib/i18n";
import { getLegalDoc } from "@/lib/legal";
import { breadcrumbs } from "@/lib/seo";

/**
 * Shared renderer for the five legal pages.
 *
 * Each page keeps its own real route file (`/privacy-policy`, `/terms`, …)
 * rather than a root-level `[slug]`, which would swallow every unmatched URL
 * and break the 404. The body lives here so the five files stay thin.
 */
export default function LegalPage({ slug, locale }: { slug: string; locale: Locale }) {
  const doc = getLegalDoc(slug, locale);
  if (!doc) notFound();

  const t = dict(locale);
  const fa = locale === "fa";

  return (
    <>
      <JsonLd data={breadcrumbs([{ name: doc.title, path: `/${doc.slug}` }], locale)} />

      <section>
        <div className="wrap">
          <SectionHead
            as="h1"
            eyebrow={fa ? "قوانین" : "Legal"}
            title={doc.title}
            lead={doc.description}
          />

          <p className="muted mt-sm">
            {fa ? "آخرین به‌روزرسانی: " : "Last updated: "}
            {doc.updated}
          </p>

          {/* Saying this out loud beats a false air of authority. Anyone
              relying on these before review deserves the warning. */}
          <div className="card mt-md" style={{ borderColor: "var(--color-brand-400)" }}>
            <strong>
              {fa
                ? "⚠️ این متن هنوز بازبینی حقوقی نشده است."
                : "⚠️ This text has not been reviewed by a lawyer yet."}
            </strong>
            <p className="muted mt-sm">
              {fa
                ? "پیش‌نویسی است بر اساس کاری که محصول واقعاً انجام می‌دهد. پیش از دریافت پرداخت واقعی باید یک وکیل بازبینی‌اش کند."
                : "It is an honest draft describing what the product actually does. A lawyer needs to review it before we take real payments."}
            </p>
          </div>

          <div className="prose narrow mt-md">
            {doc.sections.map((sec) => (
              <section key={sec.heading} className="mt-md">
                <h2>{sec.heading}</h2>
                <ul className="checks mt-sm">
                  {sec.body.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </section>
            ))}
          </div>

          <div className="mt-md">
            <h3>{fa ? "سایر قوانین" : "Other policies"}</h3>
            <div className="pill-row mt-sm">
              {t.legal
                .filter((l) => l.href !== `/${doc.slug}`)
                .map((l) => (
                  <Link key={l.href} href={localePath(locale, l.href)} className="pill">
                    {l.label}
                  </Link>
                ))}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
