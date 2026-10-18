import type { MetadataRoute } from "next";

import { siteBase as site } from "@/lib/content";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${site.name} — ${site.tagline}`,
    short_name: site.name,
    description: site.oneLiner,
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#6366f1",
    lang: "fa-IR",
    dir: "rtl",
    icons: [
      { src: "/icon", sizes: "512x512", type: "image/png" },
    ],
  };
}
