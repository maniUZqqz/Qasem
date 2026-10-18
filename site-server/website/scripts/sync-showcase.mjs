/**
 * Copies the real sample output into the site, and stitches the video.
 *
 * The showcase is the strongest thing this site has, and it must not depend on
 * a sibling folder existing at deploy time. So the media and captions are
 * copied in once, here, and the pages read only from inside the project.
 *
 * **The five-second segments are joined into one file.** The pipeline renders
 * in five-second shots whose last frame is the next shot's first frame — one
 * continuous take, delivered as five files. Showing them as five players is a
 * picture of our rendering architecture, not of our work. ffmpeg joins them
 * here; if ffmpeg is missing, an already-stitched file from a previous run is
 * kept and the work keeps its video.
 *
 * This writes the **fallback** copy. The live site reads the same content from
 * the backend (`/api/v1/site/showcase/`), where it is editable in the admin.
 *
 *     node scripts/sync-showcase.mjs
 */
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const upmarket = join(root, "..");
const data = join(upmarket, "..", "..", "دیتا");

const SAMPLES = join(data, "3-نمونه‌کار");
const MEDIA = join(data, "2-ارائه", "static", "portfolio");
const DEST = join(root, "public", "showcase");

const WORKS = [
  { id: "apparel", category: "پوشاک", product: "کت اورسایز کرم",
    dir: "01-پوشاک", image: "apparel.png" },
  { id: "accessory", category: "اکسسوری", product: "گردنبند مینیمال",
    dir: "02-اکسسوری", image: "accessory.png" },
  { id: "decor", category: "دکوراسیون", product: "آباژور مینیمال",
    dir: "03-دکوراسیون", image: "decor.png",
    segments: [1, 2, 3, 4, 5].map((n) => `decor-seg${n}.mp4`) },
];

/** The launcher downloads ffmpeg here; `ffmpeg` on PATH is the other chance. */
function ffmpegBin() {
  const bundled = join(upmarket, "ffmpeg", "bin", "ffmpeg.exe");
  return existsSync(bundled) ? bundled : "ffmpeg";
}

/**
 * Join segments into one mp4. Lossless when the segments share a codec, which
 * they do — they come out of one render — and a re-encode when they do not.
 * Returns false rather than throwing: a build that cannot stitch should ship
 * the previous stitched file, not fail.
 */
function stitch(segments, out) {
  const list = join(DEST, ".concat.txt");
  writeFileSync(list, segments.map((s) => `file '${join(DEST, s).replace(/\\/g, "/")}'`).join("\n"), "utf8");
  const args = ["-y", "-f", "concat", "-safe", "0", "-i", list];
  try {
    execFileSync(ffmpegBin(), [...args, "-c", "copy", out], { stdio: "ignore" });
    return true;
  } catch {
    try {
      execFileSync(
        ffmpegBin(),
        [...args, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out],
        { stdio: "ignore" },
      );
      return true;
    } catch {
      return false;
    }
  } finally {
    rmSync(list, { force: true });
  }
}

if (!existsSync(SAMPLES)) {
  console.log("  samples folder not found - keeping existing copy");
  process.exit(0);
}

// Media first: the stitch below reads the segments out of public/showcase.
//
// copied one file at a time: cpSync crashes the process on Windows when the
// source path contains non-ASCII segments, and it does so *after* the copy,
// which turns a working prebuild step into a failed build
mkdirSync(DEST, { recursive: true });
if (existsSync(MEDIA)) {
  for (const name of readdirSync(MEDIA)) {
    const from = join(MEDIA, name);
    if (!statSync(from).isFile()) continue;
    const to = join(DEST, name);
    if (existsSync(to) && statSync(to).size === statSync(from).size) continue;
    copyFileSync(from, to);
  }
}

const out = [];
for (const w of WORKS) {
  const captionFile = join(SAMPLES, w.dir, "caption.txt");
  if (!existsSync(captionFile)) {
    console.log(`  ! caption missing for ${w.id}`);
    continue;
  }

  const segments = (w.segments ?? []).filter((s) => existsSync(join(DEST, s)));
  const videoName = `${w.id}.mp4`;
  const videoPath = join(DEST, videoName);
  let hasVideo = existsSync(videoPath);

  if (segments.length > 1) {
    if (stitch(segments, videoPath)) {
      hasVideo = true;
      console.log(`  ${w.id}: ${segments.length} segments -> ${videoName}`);
    } else if (hasVideo) {
      console.log(`  ${w.id}: ffmpeg unavailable - keeping existing ${videoName}`);
    } else {
      console.log(`  ! ${w.id}: ffmpeg unavailable and no stitched video yet`);
    }
  }

  out.push({
    id: w.id,
    category: w.category,
    product: w.product,
    image: `/showcase/${w.image}`,
    ...(hasVideo ? { video: `/showcase/${videoName}` } : {}),
    segmentCount: segments.length,
    caption: readFileSync(captionFile, "utf8").trim(),
  });
}

mkdirSync(join(root, "content", "showcase"), { recursive: true });
writeFileSync(
  join(root, "content", "showcase", "works.json"),
  JSON.stringify(out, null, 2),
  "utf8",
);

console.log(`  showcase synced: ${out.length} works`);
