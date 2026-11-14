/**
 * آزمونِ جست‌وجوی سبک‌های موشن با نام‌هایی که مالک نوشته است.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/motion-owner-names.test.ts --bundle --platform=node --format=esm --outfile=/tmp/motion-owner-names.test.mjs
 *   node /tmp/motion-owner-names.test.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { StyleDef } from "../src/features/content/motion/api";
import { OWNER_NAMES, ownerLabel, styleMatches } from "../src/features/content/motion/ownerNames";

const mk = (id: string, name_fa: string, name_en: string, extra: Partial<StyleDef> = {}): StyleDef => ({
  id, name_fa, name_en, group: "x", group_label: "x", about: "", tags: [], palette: {}, font: { latin: "", fa: "" }, ...extra,
});

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const disney = mk("disney-inspired", "افسانهٔ شبانه (الهام از دیزنی)", "Fairy-tale Classic", { inspired: "دیزنیِ کلاسیک" });
const cn = mk("cartoon-network-inspired", "کارتونیِ تلویزیونی", "Cartoon TV Style", { inspired: "کارتونِ تلویزیونیِ مدرن", tags: ["کارتون", "شاد"] });
const cgi = mk("photoreal-cgi", "نورپردازیِ فیلمی (شبه‌واقعی)", "Photoreal-lit", { tags: ["سینمایی", "نور"] });
const lego = mk("lego-bricks", "آجرهای لگویی", "Lego-like Bricks");
const flat = mk("flat-2d", "فلتِ دوبعدی", "Flat 2D");

check("نام‌های مالک که روی کارت نیست پیدا می‌شود (حرفِ بزرگ و کوچک و فاصله فرقی ندارد)", () => {
  assert.ok(styleMatches(disney, "Disney"));
  assert.ok(styleMatches(disney, "disney"));
  assert.ok(styleMatches(cn, "Cartoon Network"));
  assert.ok(styleMatches(cn, "cartoonnetwork"));
  assert.ok(styleMatches(cgi, "Photorealistic CGI"));
  assert.ok(styleMatches(lego, "Lego Style"));
  assert.ok(styleMatches(flat, "فلت"));
});

check("جست‌وجوی خالی همه را نشان می‌دهد و نامِ نامرتبط هیچ را", () => {
  assert.ok(styleMatches(disney, ""));
  assert.ok(!styleMatches(disney, "Cyberpunk"));
  assert.ok(!styleMatches(cn, "Disney"));
});

check("نامِ مالک کنارِ کارت فقط وقتی می‌آید که در نامِ انگلیسیِ کارت نباشد", () => {
  assert.equal(ownerLabel(disney), "Disney");
  assert.equal(ownerLabel(cn), "Cartoon Network");
  assert.equal(ownerLabel(mk("pixel-art", "پیکسل", "Pixel Art")), "");
});

check("هر شناسهٔ فهرست در کاتالوگِ بک‌اند هست", () => {
  const cat = readFileSync(resolve(process.cwd(), "../backend/apps/motion/catalog.py"), "utf8");
  const ids = new Set([...cat.matchAll(/^\s*S\("([a-z0-9-]+)"/gm)].map((m) => m[1]));
  for (const id of Object.keys(OWNER_NAMES)) assert.ok(ids.has(id), `${id} در catalog.py نیست`);
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? "\n     " + r.err : ""}`);
console.log(`${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
