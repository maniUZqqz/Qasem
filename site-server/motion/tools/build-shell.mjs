// Bundles the Remotion project (motion/remotion) with @remotion/bundler into a static folder: the "shell" that the site
// and the GPU node render. Run by `manage.py motion_build`.
//
//   node tools/build-shell.mjs <outDir>
//
// The bundle holds the engine + the style catalog + the fonts; what changes per render (the spec, or the user's compiled code)
// is passed at render time, so the same folder serves every job.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const out = path.resolve(process.argv[2] || path.join(root, "build", "bundle"));

function sourceHash() {
  const h = crypto.createHash("sha256");
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir).sort()) {
      const p = path.join(dir, name);
      const st = fs.statSync(p);
      if (st.isDirectory()) walk(p);
      else if (/\.(tsx?|json|woff2)$/.test(name)) {
        h.update(path.relative(root, p));
        h.update(fs.readFileSync(p));
      }
    }
  };
  walk(path.join(root, "remotion", "src"));
  walk(path.join(root, "remotion", "public"));
  return h.digest("hex").slice(0, 16);
}

const t0 = Date.now();
fs.rmSync(out, { recursive: true, force: true });
const got = await bundle({
  entryPoint: path.join(root, "remotion", "src", "index.tsx"),
  publicDir: path.join(root, "remotion", "public"),
  outDir: out,
  enableCaching: false,         // the webpack cache is ~250 MB: not worth keeping on the server
  onProgress: () => {},
});
// no source maps in the shipped bundle (smaller, and nothing to leak)
for (const f of fs.readdirSync(got)) if (f.endsWith(".map")) fs.rmSync(path.join(got, f));
const version = { hash: sourceHash(), remotion: "4.0.543", built_at: new Date().toISOString() };
fs.writeFileSync(path.join(got, "nm-motion-version.json"), JSON.stringify(version));
let bytes = 0;
const sum = (d) => fs.readdirSync(d, { withFileTypes: true }).forEach((e) => (e.isDirectory() ? sum(path.join(d, e.name)) : (bytes += fs.statSync(path.join(d, e.name)).size)));
sum(got);
console.log(JSON.stringify({ ev: "built", out: got, hash: version.hash, mb: +(bytes / 1048576).toFixed(1), seconds: +((Date.now() - t0) / 1000).toFixed(1) }));
