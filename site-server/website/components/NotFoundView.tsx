"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { dict } from "@/lib/dict";
import { DEFAULT_LOCALE, isLocale, localePath, type Locale } from "@/lib/i18n";

/**
 * The branded 404 body. It is a client component because a `not-found.tsx` is
 * rendered without route params: `useParams()` is the one place the locale of
 * the dead URL (/en/nope vs /nope) is still known, so an English visitor gets an
 * English page. Rendered inside `app/[locale]/layout.tsx`, so the header, the
 * footer, `lang` and `dir` are the real ones too.
 */
const COPY: Record<Locale, { title: string; body: string; home: string; pricing: string; blog: string; more: string }> = {
  fa: {
    title: "این صفحه پیدا نشد",
    body: "شاید نشانی عوض شده یا اشتباه تایپ شده باشد. از این‌ها شروع کنید:",
    home: "بازگشت به صفحه‌ی اصلی",
    pricing: "قیمت‌ها",
    blog: "وبلاگ",
    more: "بخش‌های سایت",
  },
  en: {
    title: "This page could not be found",
    body: "The address may have changed or been mistyped. Start from one of these:",
    home: "Back to the home page",
    pricing: "Pricing",
    blog: "Blog",
    more: "Sections of the site",
  },
};

export default function NotFoundView() {
  const params = useParams<{ locale?: string }>();
  const asked = params?.locale ?? "";
  const l: Locale = isLocale(asked) ? asked : DEFAULT_LOCALE;
  const t = dict(l);
  const c = COPY[l];

  return (
    <section data-testid="not-found">
      <div className="wrap narrow center">
        <div style={{ fontSize: "4rem" }} aria-hidden="true">🧭</div>
        <p className="mt" style={{ color: "var(--text-3)", fontWeight: 700, letterSpacing: ".1em" }}>
          404
        </p>
        <h1>{c.title}</h1>
        <p className="lead mt">{c.body}</p>

        <div className="row mt-md center-row">
          <Link href={localePath(l, "/")} className="btn btn-primary">
            {c.home}
          </Link>
          <Link href={localePath(l, "/pricing")} className="btn btn-ghost">
            {c.pricing}
          </Link>
          <Link href={localePath(l, "/blog")} className="btn btn-ghost">
            {c.blog}
          </Link>
        </div>

        <p className="mt-md" style={{ color: "var(--text-3)", fontSize: ".85rem" }}>{c.more}</p>
        <div className="row mt center-row">
          {t.nav.map((item) => (
            <Link key={item.href} href={localePath(l, item.href)} className="tag-link">
              {item.label}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
