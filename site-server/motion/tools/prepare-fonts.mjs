// Copies the fonts the styles use from the @fontsource packages (SIL Open Font License) into remotion/public/fonts
// and writes remotion/src/fonts.generated.json (key -> CSS family + files). Run by `manage.py motion_build`.
//
//   node tools/prepare-fonts.mjs
//
// Persian fonts: the "arabic" subset (Persian letters + digits verified in tests); Latin display fonts: the "latin" subset.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const modules = path.join(root, "node_modules", "@fontsource");
const outDir = path.join(root, "remotion", "public", "fonts");
const manifestPath = path.join(root, "remotion", "src", "fonts.generated.json");

// key: [CSS family, package, subsets, weights]
const AR = ["arabic", "latin"];
const FONTS = {
  // Persian-capable
  vazirmatn: ["Vazirmatn", "vazirmatn", AR, [400, 500, 700, 900]],
  lalezar: ["Lalezar", "lalezar", AR, [400]],
  kufam: ["Kufam", "kufam", AR, [500, 700, 900]],
  cairo: ["Cairo", "cairo", AR, [400, 700, 900]],
  changa: ["Changa", "changa", AR, [500, 700, 800]],
  rakkas: ["Rakkas", "rakkas", AR, [400]],
  "aref-ruqaa": ["Aref Ruqaa", "aref-ruqaa", AR, [400, 700]],
  "reem-kufi": ["Reem Kufi", "reem-kufi", AR, [500, 700]],
  harmattan: ["Harmattan", "harmattan", AR, [500, 700]],
  "markazi-text": ["Markazi Text", "markazi-text", AR, [500, 700]],
  amiri: ["Amiri", "amiri", AR, [400, 700]],
  katibeh: ["Katibeh", "katibeh", AR, [400]],
  jomhuria: ["Jomhuria", "jomhuria", AR, [400]],
  lemonada: ["Lemonada", "lemonada", AR, [500, 700]],
  "baloo-bhaijaan-2": ["Baloo Bhaijaan 2", "baloo-bhaijaan-2", AR, [500, 800]],
  mirza: ["Mirza", "mirza", AR, [500, 700]],
  blaka: ["Blaka", "blaka", ["arabic"], [400]],
  vibes: ["Vibes", "vibes", ["arabic"], [400]],
  "noto-naskh-arabic": ["Noto Naskh Arabic", "noto-naskh-arabic", ["arabic"], [500, 700]],
  "noto-kufi-arabic": ["Noto Kufi Arabic", "noto-kufi-arabic", ["arabic"], [700, 900]],
  mada: ["Mada", "mada", AR, [500, 900]],
  // Latin display / text
  "press-start-2p": ["Press Start 2P", "press-start-2p", ["latin"], [400]],
  vt323: ["VT323", "vt323", ["latin"], [400]],
  silkscreen: ["Silkscreen", "silkscreen", ["latin"], [400, 700]],
  "permanent-marker": ["Permanent Marker", "permanent-marker", ["latin"], [400]],
  bangers: ["Bangers", "bangers", ["latin"], [400]],
  fredoka: ["Fredoka", "fredoka", ["latin"], [500, 700]],
  righteous: ["Righteous", "righteous", ["latin"], [400]],
  orbitron: ["Orbitron", "orbitron", ["latin"], [700, 900]],
  monoton: ["Monoton", "monoton", ["latin"], [400]],
  "abril-fatface": ["Abril Fatface", "abril-fatface", ["latin"], [400]],
  "archivo-black": ["Archivo Black", "archivo-black", ["latin"], [400]],
  "bebas-neue": ["Bebas Neue", "bebas-neue", ["latin"], [400]],
  "special-elite": ["Special Elite", "special-elite", ["latin"], [400]],
  caveat: ["Caveat", "caveat", ["latin"], [500, 700]],
  "patrick-hand": ["Patrick Hand", "patrick-hand", ["latin"], [400]],
  "rock-salt": ["Rock Salt", "rock-salt", ["latin"], [400]],
  staatliches: ["Staatliches", "staatliches", ["latin"], [400]],
  "space-grotesk": ["Space Grotesk", "space-grotesk", ["latin"], [500, 700]],
  "dm-serif-display": ["DM Serif Display", "dm-serif-display", ["latin"], [400]],
  "playfair-display": ["Playfair Display", "playfair-display", ["latin"], [700, 900]],
  cinzel: ["Cinzel", "cinzel", ["latin"], [700, 900]],
  "major-mono-display": ["Major Mono Display", "major-mono-display", ["latin"], [400]],
  syncopate: ["Syncopate", "syncopate", ["latin"], [700]],
  limelight: ["Limelight", "limelight", ["latin"], [400]],
  bungee: ["Bungee", "bungee", ["latin"], [400]],
  "rubik-glitch": ["Rubik Glitch", "rubik-glitch", ["latin"], [400]],
  "londrina-solid": ["Londrina Solid", "londrina-solid", ["latin"], [400, 900]],
  "chelsea-market": ["Chelsea Market", "chelsea-market", ["latin"], [400]],
  "luckiest-guy": ["Luckiest Guy", "luckiest-guy", ["latin"], [400]],
  "gloria-hallelujah": ["Gloria Hallelujah", "gloria-hallelujah", ["latin"], [400]],
  "architects-daughter": ["Architects Daughter", "architects-daughter", ["latin"], [400]],
  "black-ops-one": ["Black Ops One", "black-ops-one", ["latin"], [400]],
  inter: ["Inter", "inter", ["latin"], [500, 700, 900]],
  nunito: ["Nunito", "nunito", ["latin"], [600, 800, 900]],
  "fredericka-the-great": ["Fredericka the Great", "fredericka-the-great", ["latin"], [400]],
  shrikhand: ["Shrikhand", "shrikhand", ["latin"], [400]],
  pacifico: ["Pacifico", "pacifico", ["latin"], [400]],
  lobster: ["Lobster", "lobster", ["latin"], [400]],
  "comic-neue": ["Comic Neue", "comic-neue", ["latin"], [700]],
  oswald: ["Oswald", "oswald", ["latin"], [500, 700]],
  anton: ["Anton", "anton", ["latin"], [400]],
  "bowlby-one": ["Bowlby One", "bowlby-one", ["latin"], [400]],
  unbounded: ["Unbounded", "unbounded", ["latin"], [600, 900]],
  "rubik-mono-one": ["Rubik Mono One", "rubik-mono-one", ["latin"], [400]],
  "russo-one": ["Russo One", "russo-one", ["latin"], [400]],
  audiowide: ["Audiowide", "audiowide", ["latin"], [400]],
};

function nearest(files, pkg, subset, w) {
  const have = [];
  for (const f of files) {
    const m = f.match(new RegExp(`^${pkg}-${subset}-(\\d+)-normal\\.woff2$`));
    if (m) have.push(Number(m[1]));
  }
  if (!have.length) return null;
  have.sort((a, b) => Math.abs(a - w) - Math.abs(b - w));
  return have[0];
}

fs.mkdirSync(outDir, { recursive: true });
const manifest = {};
const licenses = {};        // key -> {family, package, version, license}: written next to the manifest (the fonts table of docs/motion/README-fa.md)
const missing = [];
let bytes = 0;
for (const [key, [family, pkg, subsets, weights]] of Object.entries(FONTS)) {
  const dir = path.join(modules, pkg, "files");
  if (!fs.existsSync(dir)) {
    missing.push(key);
    continue;
  }
  const files = fs.readdirSync(dir);
  const entry = { family, files: [] };
  try {
    const meta = JSON.parse(fs.readFileSync(path.join(modules, pkg, "package.json"), "utf8"));
    licenses[key] = { family, package: `@fontsource/${pkg}`, version: meta.version, license: meta.license || "OFL-1.1" };
  } catch (e) { licenses[key] = { family, package: `@fontsource/${pkg}`, license: "see the package" }; }
  let ranges = {};
  try { ranges = JSON.parse(fs.readFileSync(path.join(modules, pkg, "unicode.json"), "utf8")); } catch (e) { /* no ranges: the face covers everything it has */ }
  for (const subset of subsets) {
    const seen = new Set();
    for (const w of weights) {
      const got = nearest(files, pkg, subset, w);
      if (got === null || seen.has(got)) continue;
      seen.add(got);
      const name = `${pkg}-${subset}-${got}-normal.woff2`;
      fs.copyFileSync(path.join(dir, name), path.join(outDir, name));
      bytes += fs.statSync(path.join(outDir, name)).size;
      entry.files.push({ w: got, url: `fonts/${name}`, subset, ur: ranges[subset] || "" });
    }
  }
  if (entry.files.length) manifest[key] = entry;
  else missing.push(key);
}
// The project's OWN Vazirmatn (backend/services/imaging/fonts: the files the caption and photo engines draw with) is bundled for the weights it
// has (400 / 700): a Persian title in the studio then looks exactly like one in the editors. The fontsource faces stay for the other weights
// (500 / 900) and as the fallback when the project files are not there.
const projectDir = path.resolve(root, "..", "backend", "services", "imaging", "fonts");
for (const [file, w] of [["Vazirmatn-Regular.ttf", 400], ["Vazirmatn-Bold.ttf", 700]]) {
  const src = path.join(projectDir, file);
  if (!fs.existsSync(src) || !manifest.vazirmatn) continue;
  const name = `vazirmatn-project-${w}-normal.ttf`;
  fs.copyFileSync(src, path.join(outDir, name));
  bytes += fs.statSync(src).size;
  // replaces the fontsource faces of the same weight (every glyph in one file, no unicode-range split)
  manifest.vazirmatn.files = manifest.vazirmatn.files.filter((f) => f.w !== w);
  manifest.vazirmatn.files.push({ w, url: `fonts/${name}`, subset: "all", ur: "", fmt: "truetype" });
}
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 1) + "\n");
for (const k of Object.keys(licenses)) if (!manifest[k]) delete licenses[k];
licenses.vazirmatn_project = { family: "Vazirmatn (the project's own copy, weights 400 / 700)", package: "backend/services/imaging/fonts", license: "OFL-1.1" };
fs.writeFileSync(path.join(root, "remotion", "src", "fonts.licenses.json"), JSON.stringify(licenses, null, 1) + "\n");
console.log(`fonts: ${Object.keys(manifest).length} families, ${(bytes / 1048576).toFixed(1)} MB -> ${outDir}`);
if (missing.length) {
  console.log("missing (skipped):", missing.join(", "));
}
