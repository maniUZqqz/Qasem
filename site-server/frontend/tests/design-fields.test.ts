/**
 * «استودیوی طراحی»: هر نوعِ صفحهٔ کاتالوگ و هر نوعِ اسلایدِ بک‌اند فرمِ ویرایش دارد و فیلدها شکلِ درستی دارند.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/design-fields.test.ts --bundle --platform=node --format=esm --outfile=/tmp/design-fields.test.mjs
 *   node /tmp/design-fields.test.mjs
 */
import assert from "node:assert/strict";

import { CATALOG_FIELDS, DECK_FIELDS, NOTES } from "../src/features/design/fields";

const PAGE_TYPES = ["cover", "toc", "text", "grid", "hero", "price_list", "lookbook", "steps", "divider", "back"];
const SLIDE_TYPES = ["title", "agenda", "text", "product", "comparison", "stats", "timeline", "team", "cta", "section", "image"];
const KINDS = new Set(["text", "textarea", "number", "image", "imagelist", "products", "product", "lines", "objs", "select", "check"]);

assert.deepEqual(Object.keys(CATALOG_FIELDS).sort(), [...PAGE_TYPES].sort(), "catalog page types");
assert.deepEqual(Object.keys(DECK_FIELDS).sort(), [...SLIDE_TYPES].sort(), "deck slide types");
for (const [name, table] of [["catalog", CATALOG_FIELDS], ["deck", DECK_FIELDS]] as const) {
  for (const [type, defs] of Object.entries(table)) {
    assert.ok(defs.length > 0, `${name}.${type}: بدونِ فیلد`);
    const keys = defs.map((d) => d.k);
    assert.equal(new Set(keys).size, keys.length, `${name}.${type}: کلیدِ تکراری`);
    for (const d of defs) {
      assert.ok(KINDS.has(d.t), `${name}.${type}.${d.k}: نوعِ فیلدِ ناشناخته ${d.t}`);
      assert.ok(d.l.length > 1, `${name}.${type}.${d.k}: برچسب`);
      if (d.t === "objs") assert.ok((d.sub ?? []).length > 0, `${name}.${type}.${d.k}: objs بدونِ زیرفیلد`);
      if (d.t === "select") assert.ok((d.opts ?? []).length > 0, `${name}.${type}.${d.k}: select بدونِ گزینه`);
    }
  }
}
assert.equal(NOTES().k, "notes");
// آمارِ واقعی: منبعِ هر عدد جزوِ فرم است
assert.deepEqual(DECK_FIELDS.stats[1].sub!.map((s) => s.k), ["value", "label", "source"]);
console.log("design-fields: ok");
