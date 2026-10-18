import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import JsonLd from "@/components/JsonLd";
import SectionHead from "@/components/SectionHead";
import { getCategories, getPostsInCategory } from "@/lib/blog";
import { fa } from "@/lib/plans";
import { breadcrumbs } from "@/lib/seo";
import { alternatesFor, DEFAULT_LOCALE } from "@/lib/i18n";

type Props = { params: Promise<{ locale: string; slug: string }> };

/** Like the articles themselves, category pages exist under the Persian
 *  locale only. */
export async function generateStaticParams() {
  return (await getCategories()).map(({ name }) => ({
    locale: DEFAULT_LOCALE,
    slug: encodeURIComponent(name),
  }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const name = decodeURIComponent(slug);
  return {
    title: `${name} — مقالات آپ‌مارکت`,
    description: `همه‌ی مقالات آپ‌مارکت در دسته‌ی ${name}.`,
    alternates: alternatesFor(DEFAULT_LOCALE, `/blog/category/${slug}`, [DEFAULT_LOCALE]),
  };
}

export default async function CategoryPage({ params }: Props) {
  const { slug } = await params;
  const name = decodeURIComponent(slug);
  const posts = await getPostsInCategory(name);
  const about = (await getCategories()).find((c) => c.name === name)?.description ?? "";
  // 404 rather than an empty page: a category with nothing in it is a URL
  // somebody mistyped or one we renamed, and an empty page that returns 200
  // gets indexed and then keeps getting visited.
  if (posts.length === 0) notFound();
  const categories = await getCategories();

  return (
    <section>
      <div className="wrap">
        <SectionHead
          as="h1"
          eyebrow="وبلاگ"
          title={name}
          lead={about || `${fa(posts.length)} مقاله در این دسته`}
        />

        <div className="row center-x mt-md center-row">
          <Link href="/blog" className="tag-link">همه</Link>
          {categories.map((category) => (
            <Link
              key={category.name}
              href={`/blog/category/${encodeURIComponent(category.name)}`}
              className={`tag-link ${category.name === name ? "on" : ""}`}
            >
              {category.name} ({fa(category.count)})
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
          { name, path: `/blog/category/${slug}` },
        ])}
      />
    </section>
  );
}
