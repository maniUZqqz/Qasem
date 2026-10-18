import { getPosts } from "@/lib/blog";
import { siteBase as site } from "@/lib/content";
import { SITE_URL, abs } from "@/lib/seo";

/** RSS. Cheap to serve, and it is still how aggregators and a fair number of
 *  readers follow a Persian tech blog. */
export async function GET() {
  const posts = await getPosts();
  const escape = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const items = posts
    .map(
      (p) => `    <item>
      <title>${escape(p.title)}</title>
      <link>${abs(`/blog/${p.slug}`)}</link>
      <guid isPermaLink="true">${abs(`/blog/${p.slug}`)}</guid>
      <description>${escape(p.description)}</description>
      <category>${escape(p.tags[0] ?? "")}</category>
    </item>`,
    )
    .join("\n");

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>${escape(site.name)} — وبلاگ</title>
    <link>${SITE_URL}/blog</link>
    <description>${escape(site.tagline)}</description>
    <language>fa-IR</language>
${items}
  </channel>
</rss>`;

  return new Response(xml, {
    headers: {
      "Content-Type": "application/rss+xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
