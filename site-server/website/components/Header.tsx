"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { siteFor } from "@/lib/content";
import { dict } from "@/lib/dict";
import { localePath, stripLocale, type Locale } from "@/lib/i18n";

import LocaleToggle from "./LocaleToggle";
import ThemeToggle from "./ThemeToggle";

/** `name` is passed in rather than read here: this is a client component, and
 *  the name comes from the backend, which only the server can await. Without
 *  the prop the header would be the one place on the site still showing the
 *  name that was compiled in. */
export default function Header({ locale, name }: { locale: Locale; name?: string }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const site = siteFor(locale);
  const t = dict(locale);
  // Compare against the locale-free path so the active pill highlights on
  // /en/pricing exactly as it does on /pricing.
  const bare = stripLocale(path || "/");

  // با رفتن به صفحهٔ دیگر، منوی موبایل بسته می‌شود؛ با Escape هم
  useEffect(() => {
    setOpen(false);
  }, [path]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header
      style={{
        position: "sticky", top: 0, zIndex: 50,
        background: "color-mix(in srgb, var(--bg) 88%, transparent)",
        backdropFilter: "blur(12px)",
        borderBottom: "1px solid var(--line)",
      }}
    >
      {/* چیدمان از inline به کلاس رفت تا مدیاکوئری بتواند تنگش کند —
          استایل inline بر هر کلاسی می‌چربد، پس با inline نمی‌شد در عرض کم
          فشرده‌اش کرد. */}
      <div className="wrap site-bar">
        <Link
          href={localePath(locale, "/")}
          className="gradient-text site-brand"
        >
          {name || site.name}
        </Link>

        <nav className="desktop-nav" style={{ display: "flex", gap: 4, marginInlineStart: 12 }}>
          {t.nav.map((item) => (
            <Link
              key={item.href}
              href={localePath(locale, item.href)}
              style={{
                padding: "7px 12px", borderRadius: 999, textDecoration: "none",
                fontSize: ".88rem", fontWeight: 500,
                color: bare === item.href ? "var(--color-brand-600)" : "var(--text-2)",
                background: bare === item.href ? "var(--eyebrow-bg)" : "transparent",
              }}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="site-bar-actions">
          <LocaleToggle locale={locale} />
          <ThemeToggle />
          <a href={site.panelUrl} className="btn btn-ghost desktop-only">
            {locale === "fa" ? "ورود" : "Log in"}
          </a>
          <a href={`${site.panelUrl}/register`} className="btn btn-primary">
            {t.cta.startFree}
          </a>
          <button
            className="mobile-only btn btn-ghost"
            onClick={() => setOpen((v) => !v)}
            aria-label={locale === "fa" ? "منو" : "Menu"}
            aria-expanded={open}
          >
            ☰
          </button>
        </div>
      </div>

      {/* منوی موبایل: یک پنلِ تمام‌عرض زیرِ نوار (نه ستونی که روی متنِ صفحه بیفتد)،
          با پس‌زمینهٔ مات، لینکِ ورود و بستنِ خودکار بعد از رفتن به صفحه */}
      {open && (
        <div className="mobile-menu" role="dialog" aria-label={locale === "fa" ? "منو" : "Menu"}>
          <nav className="mobile-menu-list">
            {t.nav.map((item) => (
              <Link
                key={item.href}
                href={localePath(locale, item.href)}
                onClick={() => setOpen(false)}
                className={"mobile-menu-link" + (bare === item.href ? " active" : "")}
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="mobile-menu-actions">
            <a href={site.panelUrl} className="btn btn-ghost">{locale === "fa" ? "ورود به پنل" : "Log in"}</a>
            <a href={`${site.panelUrl}/register`} className="btn btn-primary">{t.cta.startFree}</a>
          </div>
        </div>
      )}
      {open && <div className="mobile-menu-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />}

      <style>{`
        .mobile-only { display: none; }
        .mobile-menu, .mobile-menu-backdrop { display: none; }
        @media (max-width: 1020px) {
          .desktop-nav, .desktop-only { display: none !important; }
          .mobile-only { display: inline-flex; }
          .mobile-menu {
            display: block; position: absolute; inset-inline: 0; top: 100%;
            background: var(--bg); border-bottom: 1px solid var(--line);
            box-shadow: 0 18px 40px -20px rgb(0 0 0 / .35);
            padding: 10px 16px 16px; max-height: calc(100dvh - 64px); overflow-y: auto;
          }
          .mobile-menu-list { display: grid; gap: 4px; }
          .mobile-menu-link {
            display: block; padding: 12px 14px; border-radius: 12px; text-decoration: none;
            color: var(--text-2); background: var(--bg-soft); font-weight: 500;
          }
          .mobile-menu-link.active { color: var(--color-brand-600); background: var(--eyebrow-bg); }
          .mobile-menu-actions { display: flex; gap: 8px; margin-top: 12px; }
          .mobile-menu-actions .btn { flex: 1; justify-content: center; }
          .mobile-menu-backdrop { display: block; position: fixed; inset: 0; top: 64px; z-index: -1; background: rgb(0 0 0 / .25); }
        }
      `}</style>
    </header>
  );
}
