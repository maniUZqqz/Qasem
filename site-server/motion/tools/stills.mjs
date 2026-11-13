// QA tool: renders many stills of the Template composition with ONE browser (a contact-sheet of every scene type, a style under test ...).
//
//   node tools/stills.mjs <bundleDir> <jobs.json> <outDir> [--browser <exe>] [--gl swangle] [--verbose]
//
// jobs.json: [{"name": "pixel-art-title", "spec": {...Template spec...}, "frame": 52, "scale": 0.3}, ...]
// stdout: one JSON line per still ({"ev":"still"|"fail", ...}); a failing job is reported and the rest still render.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";

const argv = process.argv.slice(2);
const flag = (n, d) => { const i = argv.indexOf("--" + n); if (i < 0) return d; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const bool = (n) => { const i = argv.indexOf("--" + n); if (i < 0) return false; argv.splice(i, 1); return true; };
const browser = flag("browser", null);
const gl = flag("gl", "swangle");
const verbose = bool("verbose");
const [bundleDir, jobsFile, outDir] = argv;
if (!bundleDir || !jobsFile || !outDir) { console.error("usage: stills.mjs <bundleDir> <jobs.json> <outDir>"); process.exit(2); }
fs.mkdirSync(outDir, { recursive: true });

const MIME = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".ttf": "font/ttf", ".png": "image/png", ".css": "text/css" };
const root = path.resolve(bundleDir);
const server = http.createServer((req, res) => {
  const u = decodeURIComponent((req.url || "/").split("?")[0]);
  const p = path.join(root, u === "/" ? "index.html" : u);
  if (!p.startsWith(root)) { res.writeHead(403); return res.end(); }
  fs.readFile(p, (e, d) => {
    if (e) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": MIME[path.extname(p)] || "application/octet-stream", "access-control-allow-origin": "*" });
    res.end(d);
  });
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const serveUrl = `http://127.0.0.1:${server.address().port}`;
const jobs = JSON.parse(fs.readFileSync(jobsFile, "utf8"));
const chromiumOptions = { gl, flags: { "host-resolver-rules": "MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" } };
const instance = await openBrowser("chrome", { browserExecutable: browser, chromiumOptions, logLevel: verbose ? "verbose" : "error" });

let ok = 0, bad = 0;
for (const j of jobs) {
  const t0 = Date.now();
  try {
    const inputProps = { spec: j.spec };
    const composition = await selectComposition({ serveUrl, id: "Template", inputProps, puppeteerInstance: instance, chromiumOptions, logLevel: verbose ? "verbose" : "error" });
    const out = path.join(outDir, `${j.name}.jpg`);
    await renderStill({ composition, serveUrl, inputProps, output: out, frame: Math.min(j.frame ?? 30, composition.durationInFrames - 1), scale: j.scale ?? 0.3, imageFormat: "jpeg", jpegQuality: 82, puppeteerInstance: instance, chromiumOptions, logLevel: verbose ? "verbose" : "error", timeoutInMilliseconds: 90000 });
    ok++;
    console.log(JSON.stringify({ ev: "still", name: j.name, ms: Date.now() - t0, bytes: fs.statSync(out).size }));
  } catch (e) {
    bad++;
    console.log(JSON.stringify({ ev: "fail", name: j.name, message: String(e && e.message ? e.message : e).slice(0, 600) }));
  }
}
await instance.close({ silent: true }).catch(() => {});
server.close();
console.log(JSON.stringify({ ev: "end", ok, bad }));
process.exit(bad ? 1 : 0);
