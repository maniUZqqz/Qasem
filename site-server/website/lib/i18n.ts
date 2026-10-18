/**
 * Locale plumbing.
 *
 * Persian lives at the root (`/pricing`) and English under a prefix
 * (`/en/pricing`). Two reasons: the primary market is Iran, so the main
 * audience should not pay a redirect or an extra path segment for the
 * privilege; and every Persian URL that already exists keeps working.
 *
 * The trade-off is that `/` is ambiguous to a crawler until it reads the
 * hreflang set — which is exactly what `alternatesFor()` emits, with an
 * `x-default` pointing at the Persian root.
 */

export const LOCALES = ["fa", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "fa";

export const LOCALE_META: Record<
  Locale,
  { label: string; htmlLang: string; dir: "rtl" | "ltr"; ogLocale: string }
> = {
  fa: { label: "فارسی", htmlLang: "fa-IR", dir: "rtl", ogLocale: "fa_IR" },
  en: { label: "English", htmlLang: "en", dir: "ltr", ogLocale: "en_US" },
};

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

/**
 * Build a href for a path in a given locale.
 *
 * `path` is always the locale-free form (`/pricing`, `/`), so callers never
 * have to know which locale is prefixed and which is not.
 */
export function localePath(locale: Locale, path = "/"): string {
  const clean = path === "/" ? "" : path.replace(/\/+$/, "");
  return locale === DEFAULT_LOCALE ? clean || "/" : `/${locale}${clean}`;
}

/**
 * Strip the locale prefix back off — used by the language switcher so the
 * reader stays on the page they were reading.
 *
 * This must strip the *default* locale too. Persian is served from the root
 * via a middleware rewrite, so `usePathname()` reports the internal form
 * (`/fa/pricing`) rather than the visible URL (`/pricing`). Skipping `fa` here
 * produced `/en/fa/pricing` from the switcher — a 404.
 */
export function stripLocale(pathname: string): string {
  for (const locale of LOCALES) {
    if (pathname === `/${locale}`) return "/";
    if (pathname.startsWith(`/${locale}/`)) return pathname.slice(locale.length + 1);
  }
  return pathname || "/";
}

/**
 * The `alternates` block for a page, in every locale it exists in.
 *
 * `languages` is what produces the `<link rel="alternate" hreflang="...">`
 * tags. Pages that exist in only one language (Persian blog posts, for
 * instance) pass a shorter `available` list rather than advertising a URL that
 * would 404 — a broken hreflang is worse than none.
 */
export function alternatesFor(
  locale: Locale,
  path = "/",
  available: readonly Locale[] = LOCALES,
) {
  const languages: Record<string, string> = {};
  for (const l of available) {
    languages[LOCALE_META[l].htmlLang] = localePath(l, path);
  }
  if (available.includes(DEFAULT_LOCALE)) {
    languages["x-default"] = localePath(DEFAULT_LOCALE, path);
  }
  return { canonical: localePath(locale, path), languages };
}

/** Pick the right half of a `{ fa, en }` pair. */
export type Localized<T> = Record<Locale, T>;

export function pick<T>(value: Localized<T>, locale: Locale): T {
  return value[locale];
}
