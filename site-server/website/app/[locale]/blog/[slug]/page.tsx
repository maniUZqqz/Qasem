import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import { getPost, getPosts } from "@/lib/blog";
import { siteBase as site } from "@/lib/content";
import { alternatesFor, DEFAULT_LOCALE } from "@/lib/i18n";
import { fa } from "@/lib/plans";
import { blogPosting, breadcrumbs } from "@/lib/seo";

type Props = { params: Promise<{ locale: string; slug: string }> };

/** Articles are written in Persian and have no English counterpart, so they
 *  exist under the Persian locale only. Generating them under /en as well
 *  would duplicate Persian text on an English URL. */
export async function generateStaticParams() {
  return (await getPosts()).map((p) => ({ locale: DEFAULT_LOCALE, slug: p.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) return { title: "پیدا نشد" };
  return {
    title: post.title,
    description: post.description,
    keywords: post.tags,
    openGraph: {
      type: "article",
      title: post.title,
      description: post.description,
      publishedTime: post.date,
      authors: [post.author],
      tags: post.tags,
    },
    alternates: alternatesFor(DEFAULT_LOCALE, `/blog/${post.slug}`, [DEFAULT_LOCALE]),
  };
}

export default async function Post({ params }: Props) {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) notFound();

  // related posts share a tag; internal links are how a blog stops being a
  // set of orphan pages and starts ranking as a topic
  const related = (await getPosts())
    .filter((p) => p.slug !== post.slug && p.tags.some((t) => post.tags.includes(t)))
    .slice(0, 3);

  return (
    <article>
      <JsonLd
        data={[
          breadcrumbs([
            { name: "وبلاگ", path: "/blog" },
            { name: post.title, path: `/blog/${post.slug}` },
          ]),
          blogPosting(post),
        ]}
      />

      <section style={{ paddingBottom: 0 }}>
        <div className="wrap narrow">
          <Link href="/blog" className="muted plain back-link">
            ← بازگشت به وبلاگ
          </Link>

          <div className="row-tight mt-md">
            {post.tags.map((t) => (
              <Link key={t} href={`/blog/tag/${encodeURIComponent(t)}`} className="eyebrow plain">
                {t}
              </Link>
            ))}
          </div>

          <h1 className="mt" style={{ fontSize: "clamp(1.7rem, 4vw, 2.6rem)" }}>
            {post.title}
          </h1>
          <p className="lead mt">{post.description}</p>

          <div
            className="muted mt-md"
            style={{ paddingBottom: 24, borderBottom: "1px solid var(--line)" }}
          >
            {post.author} · {post.date} · {fa(post.readingMinutes)} دقیقه مطالعه
          </div>
        </div>
      </section>

      <section style={{ paddingTop: 32 }}>
        <div className="wrap narrow">
          <div className="prose" dangerouslySetInnerHTML={{ __html: post.html }} />

          <div className="card cta-card mt-lg">
            <h2 style={{ fontSize: "1.3rem" }}>محتوای فروشگاه خودتان را بسازید</h2>
            <p className="muted mt-sm">دو هفته رایگان، بدون کارت بانکی.</p>
            <a href={`${site.panelUrl}/register`} className="btn btn-primary mt">
              شروع رایگان ←
            </a>
          </div>
        </div>
      </section>

      {related.length > 0 && (
        <section className="section-soft">
          <div className="wrap">
            <h2 style={{ fontSize: "1.3rem" }}>مقالات مرتبط</h2>
            <div className="grid g3 in-view-stagger mt-md">
              {related.map((p) => (
                <Link key={p.slug} href={`/blog/${p.slug}`} className="card card-hover glow-edge plain">
                  <h3 style={{ fontSize: "1rem" }}>{p.title}</h3>
                  <p className="muted mt-sm">{p.description}</p>
                  <div className="muted mt" style={{ fontSize: ".76rem" }}>
                    {fa(p.readingMinutes)} دقیقه مطالعه
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </section>
      )}
    </article>
  );
}
