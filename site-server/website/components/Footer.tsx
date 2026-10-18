import Link from "next/link";

import { getSite } from "@/lib/site";
import { dict } from "@/lib/dict";
import { localePath, type Locale } from "@/lib/i18n";
import { getProof, getResources } from "@/lib/proof";

/* These links were 22px tall — the height of the text and nothing else.
   On a phone that is half of what a thumb reliably hits, and the footer is
   where somebody goes when they are already looking for something.

   The height comes from padding rather than line-height so the text keeps
   its own rhythm, and the list gap drops to 0 because the padding is now
   doing the spacing. Same visual density, a target you can actually land on. */
const linkStyle = {
  display: "block",
  paddingBlock: 11,
  color: "var(--text-2)",
  textDecoration: "none",
  fontSize: ".88rem",
} as const;

const colTitle = { fontSize: ".9rem", marginBottom: 12 } as const;
const list = { listStyle: "none", padding: 0, display: "grid", gap: 0 } as const;

export default async function Footer({ locale }: { locale: Locale }) {
  const site = await getSite(locale);
  const t = dict(locale);

  // §11–§13 and §19 pages 404 until somebody writes something, so their links
  // appear the moment there is content and not before. A footer link to a 404
  // on every page of the site is worse than no link.
  const [{ caseStudies, customers, testimonials }, { resources }] =
    await Promise.all([getProof(), getResources()]);

  // Keyed by column index rather than by title: `t.footer` is a list, and
  // matching on the heading text would put these in the wrong column the day
  // somebody renames one.
  const extra: Record<number, { href: string; label: string }[]> = {
    1: resources.length
      ? [{ href: "/resources", label: locale === "fa" ? "منابع" : "Guides & templates" }]
      : [],
    2: [
      caseStudies.length && {
        href: "/case-studies",
        label: locale === "fa" ? "مطالعات موردی" : "Case studies",
      },
      customers.length && {
        href: "/customers",
        label: locale === "fa" ? "مشتری‌ها" : "Customers",
      },
      testimonials.length && {
        href: "/testimonials",
        label: locale === "fa" ? "نظر مشتریان" : "Testimonials",
      },
    ].filter(Boolean) as { href: string; label: string }[],
  };

  return (
    <footer style={{ borderTop: "1px solid var(--line)", background: "var(--bg-soft)" }}>
      <div className="wrap" style={{ paddingBlock: 48 }}>
        <div className="grid g4">
          <div>
            <div className="gradient-text" style={{ fontWeight: 800, fontSize: "1.3rem" }}>
              {site.name}
            </div>
            <p className="muted" style={{ marginTop: 8, lineHeight: 1.9 }}>
              {site.tagline}
            </p>
            <a
              href={`${site.panelUrl}/register`}
              className="btn btn-primary"
              style={{ marginTop: 16 }}
            >
              {t.cta.free}
            </a>
          </div>

          {t.footer.map((col, column) => (
            <div key={col.title}>
              <h3 style={colTitle}>{col.title}</h3>
              <ul style={list}>
                {[...col.links, ...(extra[column] ?? [])].map((i) => (
                  <li key={i.href}>
                    <Link href={localePath(locale, i.href)} style={linkStyle}>
                      {i.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div
          style={{
            marginTop: 40,
            paddingTop: 24,
            borderTop: "1px solid var(--line)",
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span className="muted">
            © {new Date().getFullYear()} {site.name} — {t.common.rights}
          </span>

          {/* Legal links belong in the footer on every page — that is where
              people look for them, and where a reviewer expects them. */}
          <nav style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
            {t.legal.map((i) => (
              <Link key={i.href} href={localePath(locale, i.href)} style={linkStyle}>
                {i.label}
              </Link>
            ))}
          </nav>

          <a
            href={`mailto:${site.email}`}
            className="muted"
            /* The one link in the footer people actually mean to press, and it
               was 24px tall. The negative margin keeps it optically aligned
               with the row while the padding gives the thumb something. */
            style={{ textDecoration: "none", display: "inline-block", padding: "10px 0", margin: "-10px 0" }}
          >
            {site.email}
          </a>
        </div>
      </div>
    </footer>
  );
}
