import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ImageResponse } from "next/og";

import { getPost, getPosts } from "@/lib/blog";
import { siteBase as site } from "@/lib/content";

export const runtime = "nodejs";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const font = (name: string) =>
  readFileSync(join(process.cwd(), "assets", name));

export async function generateStaticParams() {
  return (await getPosts()).map((p) => ({ slug: p.slug }));
}

/** Per-article card: the headline is the picture, which is what makes a
 *  shared blog link worth clicking. */
export default async function Image({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const post = await getPost(slug);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "linear-gradient(135deg, #0b1120 0%, #1e1b4b 60%, #0b1120 100%)",
          color: "#f1f5f9",
          padding: 72,
          direction: "rtl",
          fontFamily: "Vazirmatn",
        }}
      >
        <div style={{ display: "flex", fontSize: 30, color: "#a5b4fc", fontWeight: 700 }}>
          {site.name}
        </div>

        <div
          style={{
            fontSize: 62,
            fontWeight: 800,
            lineHeight: 1.35,
            display: "flex",
            maxWidth: 1000,
          }}
        >
          {post?.title ?? "وبلاگ"}
        </div>

        <div style={{ display: "flex", gap: 16, fontSize: 26, color: "#94a3b8" }}>
          {(post?.tags ?? []).slice(0, 3).map((t) => (
            <span key={t}>#{t}</span>
          ))}
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Vazirmatn", data: font("Vazirmatn-Bold.ttf"), weight: 700, style: "normal" },
        { name: "Vazirmatn", data: font("Vazirmatn-Regular.ttf"), weight: 400, style: "normal" },
      ],
    },
  );
}
