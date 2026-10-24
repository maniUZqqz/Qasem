import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getPosts, getTags } from "@/lib/blog";
import { fa } from "@/lib/plans";
import { breadcrumbs } from "@/lib/seo";
import { alternatesFor, DEFAULT_LOCALE } from "@/lib/i18n";

type Props = { params: Promise<{ locale: string; tag: string }> };

/** Tag pages list Persian articles, so like the articles themselves they
 *  exist under the Persian locale only. */
export async function generateStaticParams() {
  return (await getTags()).map((tag) => ({
    locale: DEFAULT_LOCALE,
    tag: encodeURIComponent(tag),
  }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { tag } = await params;
  const name = decodeURIComponent(tag);
  return {
    title: `مقالات ${name}`,
    description: `همه‌ی مقالات NMarketing درباره‌ی ${name}.`,
    alternates: alternatesFor(DEFAULT_LOCALE, `/blog/tag/${tag}`, [DEFAULT_LOCALE]),
  };
}

export default async function TagPage({ params }: Props) {
  const { tag } = await params;
  const name = decodeURIComponent(tag);
  const posts = (await getPosts()).filter((p) => p.tags.includes(name));
  const tags = await getTags();
  if (posts.length === 0) notFound();

  return (
    <section>
      <div className="wrap">
        <SectionHead as="h1"
          eyebrow="وبلاگ"
          title={`مقالات ${name}`}
          lead={`${fa(posts.length)} مقاله`}
        />

        <div className="row center-x mt-md center-row">
          <Link href="/blog" className="tag-link">همه</Link>
          {tags.map((t) => (
            <Link
              key={t}
              href={`/blog/tag/${encodeURIComponent(t)}`}
              className={`tag-link ${t === name ? "on" : ""}`}
            >
              {t}
            </Link>
          ))}
        </div>

        <div className="grid g3 in-view-stagger mt-lg">
          {posts.map((post) => (
            <Link key={post.slug} href={`/blog/${post.slug}`} className="card card-hover glow-edge plain">
              <h3>{post.title}</h3>
              <p className="muted mt-sm">{post.description}</p>
              <div className="muted mt" style={{ fontSize: ".76rem" }}>
                {post.date} · {fa(post.readingMinutes)} دقیقه
              </div>
            </Link>
          ))}
        </div>
      </div>

      <JsonLd
        data={breadcrumbs([
          { name: "وبلاگ", path: "/blog" },
          { name, path: `/blog/tag/${tag}` },
        ])}
      />
    </section>
  );
}
