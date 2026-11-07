import { getVersion, versionTitle } from "@/lib/version";

/**
 * «v2.60» in the corner of the footer, linking to the panel's "what's new" page.
 *
 * Absolutely positioned inside the footer (which is `position: relative`), 10px
 * from the bottom: the footer's content block ends 48px above the bottom edge,
 * so the badge never touches the legal links or the contact address.
 *
 * Renders nothing when the version is unknown (see lib/version.ts).
 */
export default async function VersionBadge({ locale, panelUrl }: { locale: "fa" | "en"; panelUrl: string }) {
  const v = await getVersion();
  if (!v) return null;
  return (
    <a
      className="ver-badge"
      href={`${panelUrl}/changelog`}
      title={versionTitle(v, locale)}
      aria-label={locale === "fa" ? `نسخهٔ ${v.version} — چه چیزی تازه است` : `Version ${v.version} — what's new`}
      style={{
        position: "absolute",
        insetBlockEnd: 10,
        insetInlineEnd: 14,
        padding: "1px 9px",
        border: "1px solid var(--line)",
        borderRadius: 999,
        color: "var(--text-3)",
        fontSize: ".72rem",
        lineHeight: 1.6,
        opacity: 0.8,
        textDecoration: "none",
        // no `direction` here: logical insets resolve against the element's own direction
        unicodeBidi: "isolate",
      }}
    >
      v{v.version}
    </a>
  );
}
