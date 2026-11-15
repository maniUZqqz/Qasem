/**
 * آزمونِ «هدرِ چسبان روی دکمه‌ها نمی‌افتد» (۱۴۰۵/۰۸/۲۴): scrollIntoView({block:"start"}) بالای قاب را به لبهٔ بالای صفحه می‌برد و
 * هدرِ چسبانِ پنل (زنگ + تم + نشانِ صف، ۵۵px) روی «حذفِ عکس / بستن» می‌افتاد (۱۴۴۰ زیرِ نشانِ صف، ۳۹۰ لبهٔ بالا پوشیده).
 * هر هدفِ اسکرول باید scroll-margin-top ِ بزرگ‌تر از ارتفاعِ هدر داشته باشد. (در مرورگرِ واقعی با elementFromPoint هم سنجیده شده.)
 *
 *   cd frontend && node_modules/.bin/esbuild tests/shell-scroll-anchor.test.ts --bundle --platform=node --format=esm --outfile=/tmp/shell-scroll-anchor.test.mjs
 *   node /tmp/shell-scroll-anchor.test.mjs   (از پوشهٔ frontend)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const HEADER_PX = 55;
const read = (p: string) => readFileSync(p, "utf8");
const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

/** مقدارِ scroll-margin-top ِ قاعده‌ای که انتخابگرش (در فهرستِ انتخابگرهای قاعده) این رشته است */
function margin(css: string, selector: string): number {
  for (const block of css.split("}")) {
    const open = block.indexOf("{");
    if (open < 0) continue;
    const head = block.slice(0, open).replace(/\/\*[\s\S]*?\*\//g, "");
    const selectors = head.split(",").map((x) => x.trim());
    if (!selectors.includes(selector)) continue;
    const v = /scroll-margin-top:\s*(\d+)px/.exec(block.slice(open));
    if (v) return Number(v[1]);
  }
  assert.fail(`scroll-margin-top برای ${selector} پیدا نشد`);
}

const photoCss = read("src/features/content/photo/photopage.css");
const editorsCss = read("src/components/editors.css");
const photoPage = read("src/features/content/photo/PhotoEditorPage.tsx");
const videoPage = read("src/features/content/VideoEditorPage.tsx");

check("کارتِ جزئیاتِ عکس (حذفِ عکس / بستن) زیرِ هدر نمی‌رود", () => {
  assert.ok(margin(photoCss, ".pe-detail-anchor") > HEADER_PX);
  assert.match(photoPage, /ref=\{detailRef\} className="[^"]*\bpe-detail-anchor\b/);
});

check("پنلِ کارِ ادیتور عکس و فضای کارِ دستی", () => {
  assert.ok(margin(photoCss, ".pe-panel-slot") > HEADER_PX);
  assert.ok(margin(photoCss, ".pe-ws-anchor") > HEADER_PX);
  assert.match(photoPage, /ref=\{panelRef\} className="pe-panel-slot"/);
});

check("هر قابِ فضای کار (عکس/ویدیو) هدفِ اسکرولِ امن است", () => {
  assert.ok(margin(editorsCss, ".ws-root") > HEADER_PX);
  assert.ok(margin(editorsCss, ".ws-anchor") > HEADER_PX);
  assert.match(videoPage, /className="[^"]*\bws-anchor\b[^"]*" ref=\{workspaceBox\}/);
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "OK  " : "FAIL"} ${r.name}${r.err ? " — " + r.err : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
