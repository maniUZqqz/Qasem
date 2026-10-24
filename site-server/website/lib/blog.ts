/**
 * Blog posts, from the backend — with the Markdown files as a fallback.
 *
 * Files were right for seven articles: versioned with the code, reviewable in a
 * pull request, no admin needed. They stop being right at an article every
 * other day, because then publishing means a deploy, and a deploy at eleven at
 * night is one nobody does — so the post waits and the cadence quietly dies.
 *
 * **The files stay as the fallback, and that is not hedging.** The public blog
 * is SEO surface. If the backend is down or slow during a build, falling back
 * to whatever is on disk means the site still has articles; throwing would mean
 * deploying a blog with nothing in it, which is worse than a slightly stale one.
 *
 * Everything the site renders goes through the same `Post` shape regardless of
 * where it came from, so nothing downstream has to know which it was.
 */
import fs from "node:fs";
import path from "node:path";

import matter from "gray-matter";
import { remark } from "remark";
import html from "remark-html";

import { ask } from "./api";

const DIR = path.join(process.cwd(), "content", "blog");

export type Post = {
  slug: string;
  title: string;
  description: string;
  date: string;
  author: string;
  /** The one shelf this post sits on. A post has many tags and exactly one
   *  category — that difference is what makes a category page a navigable
   *  section of the blog rather than a second tag list. */
  category: string;
  tags: string[];
  readingMinutes: number;
  cover?: string;
};

export type FullPost = Post & { html: string };

/** A blog category. `description` only ever comes from the backend — it is
 *  editorial text, not something derivable from the posts in it. */
export type Category = { name: string; count: number; slug?: string; description?: string };

type ApiPost = Post & { body?: string; category_slug?: string };

// --------------------------------------------------------------- backend
//
// `ask` lives in lib/api.ts: a dead backend during a build is a reason to use
// the files, not a reason to ship a blog with no articles in it — and that
// rule is the same for every part of the site, so it is written once.

function normalise(row: ApiPost): Post {
  return {
    slug: row.slug,
    title: row.title,
    description: row.description ?? "",
    date: row.date ?? "",
    author: row.author ?? "تیم NMarketing",
    category: row.category ?? "عمومی",
    tags: Array.isArray(row.tags) ? row.tags : [],
    readingMinutes: row.readingMinutes ?? 1,
    cover: row.cover ?? undefined,
  };
}

// ----------------------------------------------------------------- files

function readAll(): { slug: string; raw: string }[] {
  if (!fs.existsSync(DIR)) return [];
  return fs
    .readdirSync(DIR)
    .filter((f) => f.endsWith(".md"))
    .map((f) => ({
      slug: f.replace(/\.md$/, ""),
      raw: fs.readFileSync(path.join(DIR, f), "utf8"),
    }));
}

function meta(slug: string, raw: string): { post: Post; body: string } {
  const { data, content } = matter(raw);
  const words = content.trim().split(/\s+/).length;
  return {
    post: {
      slug,
      title: data.title ?? slug,
      description: data.description ?? "",
      date: data.date ?? "",
      author: data.author ?? "تیم NMarketing",
      category: data.category ?? "عمومی",
      tags: data.tags ?? [],
      cover: data.cover,
      // Persian reads slower than English in most measurements; 200 wpm is a
      // reasonable middle and only ever shown as a rough hint
      readingMinutes: Math.max(1, Math.round(words / 200)),
    },
    body: content,
  };
}

function postsFromFiles(): Post[] {
  return readAll()
    .map(({ slug, raw }) => meta(slug, raw).post)
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}

// ------------------------------------------------------------------- api

/** Said once per build, not per page.

    A build that fell back to the files is not an error — it is the design —
    but it does mean the blog is as fresh as the last `export_articles` run,
    and whoever deployed it should be able to see that in the log rather than
    discover it from a reader. */
let announced = false;

function announce(live: boolean, count: number) {
  if (announced) return;
  announced = true;
  if (live) {
    console.log(`[blog] ${count} articles from the API`);
  } else {
    console.warn(
      `[blog] backend unreachable — falling back to ${count} Markdown files ` +
      `on disk. They are only as current as the last ` +
      `\`python manage.py export_articles\`.`,
    );
  }
}

export async function getPosts(): Promise<Post[]> {
  const rows = await ask<ApiPost[]>("/blog/articles/", 120, "articles");
  if (rows && rows.length) {
    announce(true, rows.length);
    return rows.map(normalise);
  }
  const files = postsFromFiles();
  announce(false, files.length);
  return files;
}

/**
 * A Persian slug reaches a page from the router still percent-encoded
 * (`%DA%A9%D9%BE...`). A caller that passes it straight through looks up an
 * article whose slug is literally that escape sequence — which exists in
 * neither the database nor `content/blog`, so the article 404s while the index
 * that linked to it works perfectly. That is exactly what happened.
 *
 * Decoding here rather than in each page means the next dynamic route cannot
 * forget. Input that is already decoded passes through unchanged, and a
 * malformed escape returns the original rather than throwing — a bad URL
 * should 404, not crash the render.
 */
export function decodeSlug(slug: string): string {
  try {
    return decodeURIComponent(slug);
  } catch {
    return slug;
  }
}

export async function getPost(slug: string): Promise<FullPost | null> {
  const name = decodeSlug(slug);
  const row = await ask<ApiPost>(
    `/blog/articles/${encodeURIComponent(name)}/`,
    120,
    "articles",
  );
  if (row?.body) {
    const processed = await remark().use(html).process(row.body);
    return { ...normalise(row), html: processed.toString() };
  }

  const file = path.join(DIR, `${name}.md`);
  if (!fs.existsSync(file)) return null;
  const { post, body } = meta(name, fs.readFileSync(file, "utf8"));
  const processed = await remark().use(html).process(body);
  return { ...post, html: processed.toString() };
}

export async function getTags(): Promise<string[]> {
  const all = (await getPosts()).flatMap((p) => p.tags);
  return Array.from(new Set(all));
}

/** Categories that actually have posts, most-used first.

    Read from the backend when it answers, because the row carries a
    `description` that no amount of counting posts can reconstruct — a category
    page whose only content is a list of links has nothing to rank on.

    The fallback still derives them from the posts themselves, so a dead
    backend gives a category page without a blurb rather than no page at all.
    A hand-kept list was never an option: it goes stale the moment somebody
    adds a post, and an empty category page in the sitemap is a 404 Google has
    already indexed. */
export async function getCategories(): Promise<Category[]> {
  const rows = await ask<Category[]>("/blog/categories/", 120, "categories");
  if (rows && rows.length) {
    return rows
      .filter((c) => c.count > 0)
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "fa"));
  }

  const counts = new Map<string, number>();
  for (const post of await getPosts()) {
    counts.set(post.category, (counts.get(post.category) ?? 0) + 1);
  }
  return Array.from(counts, ([name, count]) => ({ name, count, slug: "", description: "" })).sort(
    (a, b) => b.count - a.count || a.name.localeCompare(b.name, "fa"),
  );
}

export async function getPostsInCategory(name: string): Promise<Post[]> {
  return (await getPosts()).filter((p) => p.category === name);
}

/** Old article URLs that must keep working.

    Changing a slug 404s every link anyone ever shared — including the results
    Google indexed, which is the traffic the article was written for. */
export async function getRedirects(): Promise<{ from: string; to: string }[]> {
  return (
    (await ask<{ from: string; to: string }[]>("/blog/redirects/", 120, "articles")) ?? []
  );
}
