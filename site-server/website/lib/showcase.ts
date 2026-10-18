/**
 * The real outputs, from the admin — with the shipped copy as the fallback.
 *
 * **One video per work, not five.** The pipeline renders in five-second shots
 * whose last frame is the next shot's first frame, so they are one continuous
 * take that happens to arrive as five files. The site used to render them as
 * five `<video>` tags autoplaying side by side, which showed a visitor our
 * rendering architecture rather than our work — and made a twenty-five second
 * result look like five disconnected clips.
 *
 * They are stitched now: `python manage.py stitch_showcase` on the backend,
 * `node scripts/sync-showcase.mjs` for the copy in this repo. Both produce one
 * file, and this module only ever exposes `video` — singular, on purpose, so a
 * future page cannot go back to rendering a strip.
 */
import works from "@/content/showcase/works.json";

import { announce, ask } from "./api";
import type { Locale } from "./i18n";

export type Work = {
  id: string;
  category: string;
  product: string;
  image: string;
  /** The stitched video. Absent when a work has no video yet. */
  video?: string;
  /** Shown before the video is played, so the card is not a black rectangle. */
  videoPoster?: string;
  caption: string;
  /** How many five-second shots it was stitched from. `0` when unknown.
   *  Worth showing: it is the part people do not believe. */
  segmentCount: number;
  featured?: boolean;
};

type ApiWork = {
  id: string;
  category: string;
  categoryEn: string;
  product: string;
  productEn: string;
  image: string | null;
  video: string | null;
  videoPoster: string | null;
  caption: string;
  captionEn: string;
  featured: boolean;
  segmentCount: number;
};

type FileWork = {
  id: string;
  category: string;
  product: string;
  image: string;
  video?: string;
  segmentCount?: number;
  caption: string;
};

function fromApi(row: ApiWork, locale: Locale): Work {
  const en = locale === "en";
  return {
    id: row.id,
    category: (en && row.categoryEn) || row.category,
    product: (en && row.productEn) || row.product,
    image: row.image ?? "",
    video: row.video ?? undefined,
    videoPoster: row.videoPoster ?? row.image ?? undefined,
    caption: (en && row.captionEn) || row.caption,
    segmentCount: row.segmentCount ?? 0,
    featured: row.featured,
  };
}

function fromFiles(): Work[] {
  return (works as FileWork[]).map((w, i) => ({
    id: w.id,
    category: w.category,
    product: w.product,
    image: w.image,
    video: w.video,
    videoPoster: w.image,
    caption: w.caption,
    segmentCount: w.segmentCount ?? 0,
    // Whichever shipped work has a video is the one the home page can honestly
    // use for "one product, three outputs".
    featured: Boolean(w.video) || i === 0,
  }));
}

export async function getWorks(locale: Locale = "fa"): Promise<Work[]> {
  const rows = await ask<ApiWork[]>("/site/showcase/", 300, "showcase");
  if (rows && rows.length) {
    announce("showcase", true, `${rows.length} works`);
    return rows.map((r) => fromApi(r, locale));
  }
  const files = fromFiles();
  announce("showcase", false, `${files.length} works`);
  return files;
}

/** The one shown on the home page. Falls back to the first work with a video,
 *  then to the first work at all — a home page with an empty slot where the
 *  sample should be is worse than one showing a poster without a video. */
export async function getFeaturedWork(locale: Locale = "fa"): Promise<Work | null> {
  const all = await getWorks(locale);
  return (
    all.find((w) => w.featured && w.video) ??
    all.find((w) => w.video) ??
    all.find((w) => w.featured) ??
    all[0] ??
    null
  );
}
