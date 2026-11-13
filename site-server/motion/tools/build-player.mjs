// Builds the in-panel player (Remotion Player + the engine + sucrase) into one script with esbuild.
//
//   node tools/build-player.mjs <outDir>      -> <outDir>/player.js
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const out = path.resolve(process.argv[2] || path.join(root, "build", "player"));
fs.mkdirSync(out, { recursive: true });
const t0 = Date.now();
const res = await esbuild.build({
  entryPoints: [path.join(root, "remotion", "src", "player", "main.tsx")],
  outfile: path.join(out, "player.js"),
  bundle: true,
  minify: true,
  target: "es2020",
  format: "iife",
  jsx: "automatic",
  loader: { ".json": "json", ".woff2": "file" },
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "none",
  logLevel: "error",
  metafile: true,
});
const size = fs.statSync(path.join(out, "player.js")).size;
console.log(JSON.stringify({ ev: "built", out, kb: Math.round(size / 1024), seconds: +((Date.now() - t0) / 1000).toFixed(1), inputs: Object.keys(res.metafile.inputs).length }));
