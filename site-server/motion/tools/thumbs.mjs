// Renders one still per style (the gallery thumbnails) - and, with --qa, a second one with cards (for looking at the styles).
//
//   node tools/thumbs.mjs <bundleDir> <outDir> [--browser <exe>] [--gl swangle] [--qa] [--scale 0.3] [styleId ...]
//
// One browser for all stills; a failing style is reported and skipped (the rest still render). stdout: one JSON line per style.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";

const argv = process.argv.slice(2);
const flag = (n, d) => { const i = argv.indexOf("--" + n); if (i < 0) return d; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const browser = flag("browser", null);
const gl = flag("gl", "swangle");
const scale = Number(flag("scale", "0.3"));
const qaIdx = argv.indexOf("--qa");
const qa = qaIdx >= 0;
if (qa) argv.splice(qaIdx, 1);
const [bundleDir, outDir, ...only] = argv;
if (!bundleDir || !outDir) { console.error("usage: thumbs.mjs <bundleDir> <outDir> ..."); process.exit(2); }
fs.mkdirSync(outDir, { recursive: true });

const MIME = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png", ".css": "text/css" };
const server = http.createServer((req, res) => {
  const u = decodeURIComponent((req.url || "/").split("?")[0]);
  const p = path.join(bundleDir, u === "/" ? "index.html" : u);
  if (!p.startsWith(path.resolve(bundleDir))) { res.writeHead(403); return res.end(); }
  fs.readFile(p, (e, d) => {
    if (e) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": MIME[path.extname(p)] || "application/octet-stream", "access-control-allow-origin": "*" });
    res.end(d);
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const serveUrl = `http://127.0.0.1:${server.address().port}`;

const catalog = JSON.parse(fs.readFileSync(path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "remotion", "src", "styles.generated.json"), "utf8"));
const styles = catalog.styles.filter((s) => !only.length || only.includes(s.id));

const chromiumOptions = { gl, flags: { "host-resolver-rules": "MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" } };
const instance = await openBrowser("chrome", { browserExecutable: browser, chromiumOptions, logLevel: "error" });

function specFor(st, kind) {
  const base = { style: st.id, aspect: "4:5", fps: 30, lang: "fa", brand: { use_brand_colors: false } };
  if (kind === "title") return { ...base, scenes: [{ type: "title", duration: 3, kicker: st.name_en, title: st.name_fa, subtitle: "استودیوی موشن" }] };
  return { ...base, scenes: [{ type: "list", duration: 4, title: "سه قدمِ ساده", items: ["ثبت‌نام در یک دقیقه", "خریدِ توکن", "ساختِ برنامه"], numbered: true }] };
}

let ok = 0, bad = 0;
for (const st of styles) {
  for (const kind of qa ? ["title", "list"] : ["title"]) {
    const t0 = Date.now();
    try {
      const inputProps = { spec: specFor(st, kind) };
      const composition = await selectComposition({ serveUrl, id: "Template", inputProps, puppeteerInstance: instance, chromiumOptions, logLevel: "error" });
      const out = path.join(outDir, kind === "title" ? `${st.id}.jpg` : `${st.id}.list.jpg`);
      await renderStill({ composition, serveUrl, inputProps, output: out, frame: kind === "title" ? 52 : 70, scale, imageFormat: "jpeg", jpegQuality: 82, puppeteerInstance: instance, chromiumOptions, logLevel: "error", timeoutInMilliseconds: 90000 });
      ok++;
      console.log(JSON.stringify({ ev: "still", id: st.id, kind, ms: Date.now() - t0, bytes: fs.statSync(out).size }));
    } catch (e) {
      bad++;
      console.log(JSON.stringify({ ev: "fail", id: st.id, kind, message: String(e && e.message ? e.message : e).slice(0, 400) }));
    }
  }
}
await instance.close({ silent: true }).catch(() => {});
server.close();
console.log(JSON.stringify({ ev: "end", ok, bad }));
process.exit(bad ? 1 : 0);
