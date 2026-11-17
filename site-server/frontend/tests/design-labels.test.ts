/**
 * «استودیوی طراحی»: نامِ لایه‌ها هرگز «undefined» نیست، و پیوندِ «بازکردن در سایت‌ساز» به صفحه‌ای می‌رسد که واقعاً در مسیرِ p/:slug/builder/:target/:pk? هست.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/design-labels.test.ts --bundle --platform=node --format=esm --outfile=/tmp/design-labels.test.mjs
 *   node /tmp/design-labels.test.mjs
 */
import assert from "node:assert/strict";

import { nodeLabel, siteBuilderPath } from "../src/features/design/labels";

const catalog = { groups: [], blocks: [{ type: "c_hero_center_glow", label: "قهرمانِ مرکزی", group: "hero", hint: "", fields: [], defaults: {} }, { type: "section", label: "بخش", group: "layout", hint: "", fields: [], defaults: {} }] } as any;

// بلوکِ کتابخانه
assert.equal(nodeLabel({ t: "block", type: "c_hero_center_glow" }, catalog), "قهرمانِ مرکزی");
assert.equal(nodeLabel({ t: "block", type: "section" }, catalog), "بخش");
// فرزندِ «بخش»: فقط type دارد (بی t) ⇒ پیش‌تر «undefined» می‌شد
for (const n of [{ type: "image" }, { type: "text" }, { type: "button" }, { type: "totally_unknown" }, {}, { t: undefined, type: undefined }]) {
  const l = nodeLabel(n, catalog);
  assert.ok(typeof l === "string" && l.length > 0 && !/undefined|null/.test(l), JSON.stringify(n) + " ⇒ " + l);
}
assert.equal(nodeLabel({ t: "block", type: "c21" }, catalog), "قطعهٔ 21st.dev");
assert.equal(nodeLabel({ type: "c21" }, null), "قطعهٔ 21st.dev");
assert.equal(nodeLabel({ type: "image" }, catalog), "تصویر");
assert.equal(nodeLabel({ type: "image" }, null), "تصویر");
// عنصرهای ساده
assert.equal(nodeLabel({ t: "text" }, catalog), "متن");
assert.equal(nodeLabel({ t: "frame" }, catalog), "قاب Auto Layout");
assert.equal(nodeLabel({ t: "frame", name: "کارتِ من" }, catalog), "کارتِ من");
assert.equal(nodeLabel({ t: "weird" }, catalog), "لایه");

// پیوندِ سایت‌ساز: صفحهٔ اصلی + شناسه؛ بدونِ شناسه ⇒ نمای کلیِ پروژه (هرگز «…/builder/page» بی‌شناسه که ۴۰۴ می‌داد)
const site = { project_id: 19, slug: "chagher-ui-design", pages: [{ frame: "f1", title: "خانه", slug: "", blocks: 8, page_id: 49 }], url: "", style: "", published: false } as any;
assert.equal(siteBuilderPath(site), "/tools/studio/p/chagher-ui-design/builder/page/49");
assert.equal(siteBuilderPath({ ...site, pages: [{ ...site.pages[0], page_id: undefined }] }), "/tools/studio/p/chagher-ui-design");
assert.equal(siteBuilderPath({ ...site, pages: [] }), "/tools/studio/p/chagher-ui-design");
assert.ok(!siteBuilderPath(site).endsWith("/builder/page"));

console.log("design-labels: OK");
