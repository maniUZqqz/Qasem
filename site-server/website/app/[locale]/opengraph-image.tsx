import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ImageResponse } from "next/og";

import { siteBase as site } from "@/lib/content";

export const runtime = "nodejs";
export const alt = `${site.name} — ${site.tagline}`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * The card people see when the link is shared.
 *
 * Generated rather than a static file so the wording can never drift from
 * `lib/content.ts`. Vazirmatn is passed in explicitly: the renderer's default
 * font cannot shape Arabic script, so Persian would come out as disconnected
 * letters without it.
 */

const font = (name: string) =>
  readFileSync(join(process.cwd(), "assets", name));
export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #0b1120 0%, #1e1b4b 55%, #0b1120 100%)",
          color: "#f1f5f9",
          padding: 80,
          textAlign: "center",
          direction: "rtl",
          fontFamily: "Vazirmatn",
        }}
      >
        <div
          style={{
            fontSize: 84,
            fontWeight: 800,
            background: "linear-gradient(135deg, #818cf8, #c084fc 55%, #f472b6)",
            backgroundClip: "text",
            color: "transparent",
            marginBottom: 24,
          }}
        >
          {site.name}
        </div>
        <div style={{ fontSize: 38, color: "#cbd5e1", lineHeight: 1.5, maxWidth: 900 }}>
          {site.tagline}
        </div>
        <div
          style={{
            marginTop: 48,
            display: "flex",
            gap: 20,
            fontSize: 24,
            color: "#a5b4fc",
          }}
        >
          <span>پوستر</span>
          <span>·</span>
          <span>ویدیو</span>
          <span>·</span>
          <span>کپشن</span>
          <span>·</span>
          <span>پشتیبان فروش</span>
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
