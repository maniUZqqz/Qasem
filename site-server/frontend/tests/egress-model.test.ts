/**
 * آزمونِ منطقِ خالصِ صفحهٔ «پراکسی و VPN» (بدونِ مرورگر): برچسب‌ها، رنگِ وضعیت، متنِ مسیر، زمان و تأخیر.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/egress-model.test.ts --bundle --platform=node --format=esm --outfile=/tmp/egress-model.test.mjs
 *   node /tmp/egress-model.test.mjs
 */
import assert from "node:assert/strict";

import { SCHEME_FA, SOURCE_FA, msText, routeText, stateText, stateTone, whenText, type ServiceRow } from "../src/features/tools/egress/model";

const base: ServiceRow = {
  key: "telegram",
  title: "تلگرام",
  group: "messaging",
  summary: "",
  used_by: [],
  hosts: [],
  probes: [],
  node: false,
  proxy_id: null,
  proxy_name: "",
  mode: "direct",
  effective: "direct",
  note: "",
  health: { state: "unknown", detail: "", checked_at: null, stale: false, targets: [] },
};

// وضعیت: رنگ و متن
assert.equal(stateTone("ok"), "ok");
assert.equal(stateTone("partial"), "warn");
assert.equal(stateTone("down"), "bad");
assert.equal(stateTone("unknown"), "neutral");
assert.equal(stateText("ok"), "سالم");
assert.equal(stateText("partial"), "بخشی در دسترس");
assert.equal(stateText("down"), "در دسترس نیست");
assert.equal(stateText("unknown"), "آزمایش نشده");

// «مستقیم» یا «از راهِ پراکسیِ X»
assert.equal(routeText(base), "مستقیم");
assert.equal(routeText({ ...base, effective: "proxy", mode: "proxy", proxy_id: 3, proxy_name: "VPN دفتر" }), "از راهِ پراکسیِ «VPN دفتر»");
// پراکسیِ خاموش: مسیر «proxy» است ولی در عمل مستقیم
assert.equal(routeText({ ...base, mode: "proxy", effective: "direct", proxy_id: 3, proxy_name: "VPN دفتر" }), "مستقیم");

// زمان و تأخیر
assert.equal(whenText(null), "");
assert.equal(whenText(""), "");
assert.equal(whenText("not a date"), "");
assert.ok(whenText("2026-11-18T10:00:00+00:00").length > 4);
assert.equal(msText(null), "—");
assert.equal(msText(undefined), "—");
assert.ok(msText(250).includes("میلی‌ثانیه"));

// نوع‌های پراکسی و منبعِ پراکسیِ سرورِ پردازش
assert.deepEqual(Object.keys(SCHEME_FA).sort(), ["http", "https", "socks5", "socks5h"]);
assert.ok(SCHEME_FA.socks5h.includes("socks5h"));
assert.ok(SOURCE_FA.site.includes("همین صفحه"));
for (const k of ["env", "file", "system", "abagram", "site"]) assert.ok(SOURCE_FA[k], k);

console.log("egress-model: همهٔ آزمون‌ها گذشت");
