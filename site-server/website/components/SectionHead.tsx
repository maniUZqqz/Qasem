/**
 * Section heading.
 *
 * `as` exists because heading level is an SEO signal, not a style choice. Every
 * page needs exactly one `h1` — the page's own subject — and each section under
 * it is an `h2`. Before this prop existed every heading on the site rendered as
 * `h2`, so most pages shipped with no `h1` at all.
 *
 * Visual size is driven by CSS on `.sec-head`, so switching the tag changes the
 * document outline without changing how the page looks.
 */
export default function SectionHead({
  eyebrow,
  title,
  lead,
  as: Tag = "h2",
}: {
  eyebrow?: string;
  title: string;
  lead?: string;
  as?: "h1" | "h2";
}) {
  return (
    <div className="sec-head">
      {eyebrow && <span className="eyebrow">{eyebrow}</span>}
      <Tag className="mt">{title}</Tag>
      {lead && <p className="lead mt">{lead}</p>}
    </div>
  );
}
