import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ImageResponse } from "next/og";

export const runtime = "nodejs";
export const size = { width: 512, height: 512 };
export const contentType = "image/png";

const font = (name: string) =>
  readFileSync(join(process.cwd(), "assets", name));

/** Generated so the mark stays in step with the site palette. */
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #4f46e5, #c084fc 60%, #f472b6)",
          color: "#fff",
          fontSize: 300,
          fontWeight: 800,
          fontFamily: "Vazirmatn",
        }}
      >
        N
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
