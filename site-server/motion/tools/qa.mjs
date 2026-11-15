// QA tool: renders key frames of a plan with the page in QA mode (spec.qa) and collects, per frame, the GEOMETRY of every text block / box that the page
// reports on its console ("NMQA:{json}", see remotion/src/qa.tsx) next to a JPEG of the same frame. The backend (apps/motion/qa.py) judges them.
// ONE script for the site and the GPU node (processing/motion_jobs.py `motion.qa`).
//
//   node qa.mjs <job.json>
//
// job.json: serve (bundle), props ({"spec": ...}; strings "@file:<name>" become data: URIs of <assets_dir>/<name>), assets_dir, frames [{name, frame}],
//           out_dir, scale (0.5), browser, chrome_mode, gl, offline (true), timeout_ms, quality (jpeg 1-100)
// stdout: JSON lines {"ev":"progress"|"done"|"error"}; "done" has {results: <out_dir>/results.json}. results.json = [{name, frame, image, geometry}].
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";

const emit = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml" };
function dataUri(file) {
  const mime = MIME[path.extname(file).toLowerCase()];
  if (!mime) throw new Error(`asset type not allowed: ${path.basename(file)}`);
  const buf = fs.readFileSync(file);
  if (buf.length > 6 * 1024 * 1024) throw new Error(`asset too large: ${path.basename(file)}`);
  return `data:${mime};base64,${buf.toString("base64")}`;
}
function resolveFiles(v) {
  if (typeof v === "string" && v.startsWith("@file:")) return dataUri(path.join(job.assets_dir || ".", path.basename(v.slice(6))));
  if (Array.isArray(v)) return v.map(resolveFiles);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, resolveFiles(x)]));
  return v;
}
const STATIC_MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".ttf": "font/ttf", ".png": "image/png", ".css": "text/css" };
function serveDir(dir) {
  const root = path.resolve(dir);
  const server = http.createServer((req, res) => {
    const u = decodeURIComponent((req.url || "/").split("?")[0]);
    if (u.endsWith(".map")) { res.writeHead(200, { "content-type": "application/json" }); return res.end('{"version":3,"sources":[],"names":[],"mappings":""}'); }
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

let served = null, instance = null;
try {
  fs.mkdirSync(job.out_dir, { recursive: true });
  served = await serveDir(job.serve);
  const props = resolveFiles(job.props || {});
  if (props.spec) props.spec.qa = true;
  const flags = { "disable-background-networking": true };
  if (job.offline !== false) flags["host-resolver-rules"] = "MAP * ~NOTFOUND , EXCLUDE localhost , EXCLUDE 127.0.0.1";
  const chromiumOptions = { gl: job.gl === undefined ? "swangle" : job.gl, flags, ...(job.chrome_mode === "chrome-for-testing" ? { headless: true } : {}) };
  instance = await openBrowser("chrome", { browserExecutable: job.browser || null, chromeMode: job.chrome_mode || undefined, chromiumOptions, logLevel: "error" });
  const composition = await selectComposition({ serveUrl: served.url, id: "Template", inputProps: props, puppeteerInstance: instance, chromiumOptions, logLevel: "error", timeoutInMilliseconds: Number(job.timeout_ms) || 90000 });
  const results = [];
  const frames = job.frames || [];
  for (let k = 0; k < frames.length; k++) {
    const f = frames[k];
    let geometry = null;
    const logs = [];
    const out = path.join(job.out_dir, `${f.name}.jpg`);
    await renderStill({
      composition, serveUrl: served.url, inputProps: props, output: out, frame: Math.max(0, Math.min(Number(f.frame) || 0, composition.durationInFrames - 1)),
      scale: Number(job.scale) || 0.5, imageFormat: "jpeg", jpegQuality: Number(job.quality) || 88, puppeteerInstance: instance, chromiumOptions, logLevel: "error",
      timeoutInMilliseconds: Number(job.timeout_ms) || 90000,
      onBrowserLog: (l) => { const t = String((l && l.text) || ""); if (t.startsWith("NMQA:")) logs.push(t.slice(5)); },
    });
    for (let i = logs.length - 1; i >= 0 && !geometry; i--) { try { geometry = JSON.parse(logs[i]); } catch (e) { /* next */ } }
    results.push({ name: f.name, frame: f.frame, image: out, geometry });
    emit({ ev: "progress", progress: (k + 1) / frames.length, stage: "qa", rendered: k + 1, total: frames.length });
  }
  const resFile = path.join(job.out_dir, "results.json");
  fs.writeFileSync(resFile, JSON.stringify({ width: composition.width, height: composition.height, fps: composition.fps, frames: composition.durationInFrames, shots: results }));
  emit({ ev: "done", results: resFile, count: results.length });
} catch (e) {
  emit({ ev: "error", message: String(e && e.message ? e.message : e).slice(0, 1500) });
  process.exitCode = 1;
} finally {
  try { if (instance) await instance.close({ silent: true }); } catch (e) { /* ignore */ }
  try { if (served) served.close(); } catch (e) { /* ignore */ }
}
process.exit(process.exitCode || 0);
