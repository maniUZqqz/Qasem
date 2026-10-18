"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LOCALES, LOCALE_META, localePath, stripLocale, type Locale } from "@/lib/i18n";

/**
 * Language switcher.
 *
 * It keeps the reader on the page they were reading rather than dumping them
 * on the home page — the single most annoying thing a language switcher can
 * do. `stripLocale` turns the current URL back into a locale-free path, and
 * `localePath` re-prefixes it for the other language.
 *
 * Rendered as real links, not buttons, so the alternate language is
 * crawlable and can be opened in a new tab.
 */
export default function LocaleToggle({ locale }: { locale: Locale }) {
  const pathname = usePathname() || "/";
  const bare = stripLocale(pathname);

  return (
    <div
      role="group"
      aria-label={locale === "fa" ? "تغییر زبان" : "Change language"}
      style={{
        display: "inline-flex",
        border: "1px solid var(--line)",
        borderRadius: 999,
        overflow: "hidden",
      }}
    >
      {LOCALES.map((l) => {
        const active = l === locale;
        return (
          <Link
            key={l}
            href={localePath(l, bare)}
            hrefLang={LOCALE_META[l].htmlLang}
            aria-current={active ? "true" : undefined}
            style={{
              /* «فا» is two letters wide, which made this a 31x35 target
                 sitting between two other small ones in the header. The
                 minimums below are the floor a thumb needs; the flex centring
                 keeps the label where it was. */
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minWidth: 44,
              minHeight: 44,
              padding: "0 12px",
              fontSize: ".8rem",
              fontWeight: 600,
              textDecoration: "none",
              color: active ? "#fff" : "var(--text-2)",
              background: active ? "var(--color-brand-600)" : "transparent",
            }}
          >
            {l === "fa" ? "فا" : "EN"}
          </Link>
        );
      })}
    </div>
  );
}
