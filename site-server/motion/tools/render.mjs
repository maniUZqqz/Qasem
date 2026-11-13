// The renderer. ONE script for the site's server render, the GPU node (Windows) and the thumbnails.
//
//   node render.mjs <job.json>
//
// job.json:
//   serve        folder of the bundle (output of build-shell.mjs)                                   (required)
//   composition  "Template" (default) | "User"
//   props        input props ({"spec": {...}} for Template). Strings "@file:<name>" are replaced by a data: URI of
//                <assets_dir>/<name> (images the site attached to the job).
//   assets_dir   folder with the job's input files
//   user_js      path of the compiled user code (composition "User"): copied into a private copy of the bundle, with a
//                Content-Security-Policy that allows nothing but the page's own origin and data: images
//   out          output .mp4 (or .png for a still: set "still": <frame number>)
//   scale        output scale (0.5 = 540p of a 1080 composition)          crf (default 18)     concurrency (default 1)
//   pixel_format (yuv420p)   video_image_format (jpeg | png: how frames travel from the browser)   jpeg_quality (92)   color_space (bt709 = standard TV-range yuv420p, the default | default = Remotion's own)
//   browser      path of a Chrome headless shell / Edge (null = Remotion's own)    chrome_mode  headless-shell | chrome-for-testing
//   gl           ANGLE backend: "swangle" (software; servers) | "angle" (GPU; Windows) | "egl" ...
//   max_seconds  hard cap on the length (code mode)        timeout_ms   per-frame timeout
//   offline      block every network request but localhost (default true)
//
// stdout: one JSON object per line: {"ev":"start"|"progress"|"done"|"error", ...}. Exit code 0 = ok.
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const emit = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const fail = (message, extra = {}) => {
  emit({ ev: "error", message: String(message).slice(0, 2000), ...extra });
  try { cleanup(); } catch (e) { /* not started yet */ }
  process.exit(1);
};

const jobFile = process.argv[2];
if (!jobFile) fail("usage: node render.mjs <job.json>");
const job = JSON.parse(fs.readFileSync(jobFile, "utf8"));
const t0 = Date.now();

const MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml" };
function dataUri(file) {
  const ext = path.extname(file).toLowerCase();
  const mime = MIME[ext];
  if (!mime) throw new Error(`asset type not allowed: ${path.basename(file)}`);
  const buf = fs.readFileSync(file);
  if (buf.length > 6 * 1024 * 1024) throw new Error(`asset too large: ${path.basename(file)}`);
  return `data:${mime};base64,${buf.toString("base64")}`;
}
function resolveFiles(v) {
  if (typeof v === "string" && v.startsWith("@file:")) {
    const name = path.basename(v.slice(6));
    return dataUri(path.join(job.assets_dir || ".", name));
  }
  if (Array.isArray(v)) return v.map(resolveFiles);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, resolveFiles(x)]));
  return v;
}

const CSP =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; " +
  "media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' data: blob:; frame-src 'none'; object-src 'none'; " +
  "base-uri 'none'; form-action 'none'";

// The bundle is served by OUR OWN tiny HTTP server (127.0.0.1), not by Remotion from a folder path: when the page raises an error Remotion
// tries to read the bundle's source map; from a folder that is a fatal ENOENT that hides the real message, over HTTP it is a quiet miss.
// Any "*.map" gets an empty valid source map, so the page's real error text always reaches the job result.
const STATIC_MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".ttf": "font/ttf", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml", ".css": "text/css", ".ico": "image/x-icon" };
function serveDir(dir) {
  const root = path.resolve(dir);
  const server = http.createServer((req, res) => {
    const u = decodeURIComponent((req.url || "/").split("?")[0]);
    if (u.endsWith(".map")) {
      res.writeHead(200, { "content-type": "application/json" });
      return res.end('{"version":3,"sources":[],"names":[],"mappings":""}');
    }
    const p = path.join(root, u === "/" ? "index.html" : u);
    if (p !== root && !p.startsWith(root + path.sep)) { res.writeHead(403); return res.end(); }
    fs.readFile(p, (e, d) => {
      if (e) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "content-type": STATIC_MIME[path.extname(p).toLowerCase()] || "application/octet-stream", "access-control-allow-origin": "*", "cache-control": "no-store" });
      res.end(d);
    });
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ url: `http://127.0.0.1:${server.address().port}`, close: () => server.close() })));
}

const browserLogs = [];
const onBrowserLog = (l) => {
  if (!l) return;
  const t = String(l.type || "");
  if (t === "error" || t === "pageerror" || t === "exception") browserLogs.push(`${t}: ${String(l.text || "").slice(0, 300)}`);
  if (process.env.NM_MOTION_DEBUG) console.error(`[browser ${t}] ${String(l.text || "").slice(0, 400)}`);
};

let tmp = null;
let closeServer = null;
function cleanup() {
  if (closeServer) closeServer();
  if (tmp) fs.rmSync(tmp, { recursive: true, force: true });
}
function prepareUserBundle(serve, userJs, maxSeconds) {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "nm-motion-user-"));
  fs.cpSync(serve, tmp, { recursive: true });
  const code = fs.readFileSync(userJs, "utf8");
  fs.writeFileSync(path.join(tmp, "nm-user.js"), `window.__NM_MAX_SECONDS=${Number(maxSeconds) || 60};\n${code}`);
  const idx = path.join(tmp, "index.html");
  let html = fs.readFileSync(idx, "utf8");
  const tag = `<meta http-equiv="Content-Security-Policy" content="${CSP}"><script src="nm-user.js"></script>`;
  html = html.includes("<head>") ? html.replace("<head>", "<head>" + tag) : tag + html;
  fs.writeFileSync(idx, html);
  return tmp;
}

// Remotion refuses a scaled size that is not a whole number ("height must be an integer: 1080 x 0.3333 = 359.964"). The site already sends an exact
// scale (runner.exact_scale); this is the safety net for any other caller: the nearest double (or a dyadic scale) whose products are exact.
function exactScale(w, h, s) {
  const ok = (x) => Number.isInteger(w * x) && Number.isInteger(h * x);
  if (ok(s)) return s;
  const ulp = Number.EPSILON * s;
  for (let i = 1; i <= 256; i++) for (const x of [s + i * ulp, s - i * ulp]) if (ok(x)) return x;
  for (const x of [1, 0.5, 0.25]) if (x <= Math.max(s, 0.25) && ok(x)) return x;
  return 1;
}
// the size of the file: Remotion makes H.264 sizes even (1350 x 0.5 = 675 -> the composition is trimmed to 1348)
function outputDims(w, h, s) {
  let hh = h, ww = w;
  while (Math.round(hh * s) % 2 !== 0) hh--;
  while (Math.round(ww * s) % 2 !== 0) ww--;
  return { width: Math.round(ww * s), height: Math.round(hh * s) };
}

async function main() {
  const compId = job.composition || "Template";
  const serveSrc = path.resolve(job.serve);
  if (!fs.existsSync(path.join(serveSrc, "index.html"))) fail(`no bundle in ${serveSrc}`);
  const served = await serveDir(compId === "User" ? prepareUserBundle(serveSrc, job.user_js, job.max_seconds) : serveSrc);
  closeServer = served.close;
  const serveUrl = served.url;
  const inputProps = resolveFiles(job.props || {});
  const flags = { "disable-background-networking": true };
  if (job.offline !== false) flags["host-resolver-rules"] = "MAP * ~NOTFOUND , EXCLUDE localhost , EXCLUDE 127.0.0.1";
  const common = {
    serveUrl,
    inputProps,
    browserExecutable: job.browser || null,
    chromeMode: job.chrome_mode || undefined,
    chromiumOptions: { gl: job.gl === undefined ? "swangle" : job.gl, flags, ...(job.chrome_mode === "chrome-for-testing" ? { headless: true } : {}) },
    logLevel: job.log_level || "error",
    onBrowserLog,
    timeoutInMilliseconds: Number(job.timeout_ms) || 90000,
  };
  const composition = await selectComposition({ ...common, id: compId });
  const scale = exactScale(composition.width, composition.height, Number(job.scale) || 1);
  const maxS = Number(job.max_seconds) || 0;
  if (maxS && composition.durationInFrames / composition.fps > maxS + 0.01) {
    fail(`the video is longer than the allowed ${maxS} seconds`, { code: "too_long" });
  }
  const out = path.resolve(job.out);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const dims = outputDims(composition.width, composition.height, scale);
  emit({ ev: "start", width: dims.width, height: dims.height, fps: composition.fps, frames: composition.durationInFrames, scale });

  if (job.still !== undefined && job.still !== null) {
    await renderStill({ ...common, composition, output: out, frame: Math.min(Number(job.still) || 0, composition.durationInFrames - 1), scale, imageFormat: job.image_format || (out.endsWith(".png") ? "png" : "jpeg"), jpegQuality: job.jpeg_quality || 85 });
    emit({ ev: "done", out, ms: Date.now() - t0, still: true });
    return;
  }
  let last = -1;
  await renderMedia({
    ...common,
    composition,
    codec: job.codec || "h264",
    outputLocation: out,
    scale,
    crf: job.crf ?? 18,
    pixelFormat: job.pixel_format || "yuv420p",
    imageFormat: job.video_image_format || "jpeg",
    jpegQuality: job.jpeg_quality || 92,
    ...((job.color_space || "bt709") !== "default" ? { colorSpace: job.color_space || "bt709" } : {}),
    concurrency: Number(job.concurrency) || 1,
    muted: true,
    overwrite: true,
    hardwareAcceleration: job.hw || "if-possible",
    onProgress: ({ progress, renderedFrames, encodedFrames, stitchStage }) => {
      const p = Math.round(progress * 100);
      if (p !== last) {
        last = p;
        emit({ ev: "progress", progress, rendered: renderedFrames, encoded: encodedFrames, stage: stitchStage, total: composition.durationInFrames });
      }
    },
  });
  const size = fs.statSync(out).size;
  emit({ ev: "done", out, bytes: size, ms: Date.now() - t0, width: dims.width, height: dims.height, fps: composition.fps, frames: composition.durationInFrames });
}

main()
  .catch((e) => {
    const base = e && e.message ? e.message : String(e);
    fail(browserLogs.length && !base.includes(browserLogs[browserLogs.length - 1].slice(0, 40)) ? `${base} | ${browserLogs.slice(-3).join(" | ")}` : base);
  })
  .finally(() => cleanup());
