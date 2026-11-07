/**
 * آزمونِ نشانِ نسخه: اعتبارسنجیِ پاسخ، تاریخِ شمسی، راهنمای شناور، فهرستِ تغییرها.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/version-info.test.ts --bundle --platform=node --format=esm --outfile=/tmp/version-info.test.mjs
 *   node /tmp/version-info.test.mjs
 */
import assert from "node:assert/strict";

import { formatBuilt, parseChangelog, parseVersionInfo, tooltipFor } from "../src/components/versionInfo";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

check("parseVersionInfo: پاسخِ درست", () => {
  const v = parseVersionInfo({ version: "2.60", built_at: "2026-11-07T05:30:00Z", commit: "ABC1234", name: "NMarketing" });
  assert.deepEqual(v, { version: "2.60", built_at: "2026-11-07T05:30:00Z", commit: "abc1234", name: "NMarketing" });
});

check("parseVersionInfo: چیزِ نامعتبر ⇒ null (نشان کشیده نمی‌شود)", () => {
  for (const bad of [null, undefined, 5, "2.60", [], {}, { version: "" }, { version: "2.6" }, { version: "v2.60" }, { version: "<html>" }, { version: 2.6 }, { version: "2.60.1" }]) {
    assert.equal(parseVersionInfo(bad), null, JSON.stringify(bad));
  }
});

check("parseVersionInfo: فیلدهای خراب خالی می‌شوند، نسخه می‌ماند", () => {
  const v = parseVersionInfo({ version: "3.00", built_at: 5, commit: "not-a-hash", name: "" });
  assert.deepEqual(v, { version: "3.00", built_at: "", commit: "", name: "NMarketing" });
});

check("formatBuilt: شمسی، به وقتِ تهران", () => {
  assert.equal(formatBuilt("2026-11-07T05:30:00Z"), "۱۴۰۵/۰۸/۱۶");
  assert.equal(formatBuilt("2026-11-07T20:29:59Z"), "۱۴۰۵/۰۸/۱۶");
  assert.equal(formatBuilt("2026-11-07T21:00:00Z"), "۱۴۰۵/۰۸/۱۷"); // ۰۰:۳۰ بامدادِ تهران
});

check("formatBuilt: ناخوانا ⇒ ''", () => {
  assert.equal(formatBuilt(""), "");
  assert.equal(formatBuilt("yesterday"), "");
});

check("tooltipFor: تاریخ و کامیت", () => {
  const full = parseVersionInfo({ version: "2.60", built_at: "2026-11-07T05:30:00Z", commit: "abc1234" })!;
  assert.equal(tooltipFor(full), "ساخته‌شده: ۱۴۰۵/۰۸/۱۶ · commit abc1234");
  const noCommit = parseVersionInfo({ version: "2.60", built_at: "2026-11-07T05:30:00Z", commit: "" })!;
  assert.equal(tooltipFor(noCommit), "ساخته‌شده: ۱۴۰۵/۰۸/۱۶");
  const bare = parseVersionInfo({ version: "2.60" })!;
  assert.equal(tooltipFor(bare), "نسخهٔ 2.60");
});

check("parseChangelog: ورودیِ غیرِ فهرست ⇒ []", () => {
  for (const bad of [null, undefined, {}, "x", 3]) assert.deepEqual(parseChangelog(bad), []);
});

check("parseChangelog: ردیفِ خراب حذف می‌شود، درست‌ها می‌مانند", () => {
  const out = parseChangelog([
    { version: "2.60", date: "۱۴۰۵/۰۸/۱۶", summary: "", items: ["الف", "", 7, "ب"] },
    null,
    { version: "x", items: ["بی‌نسخه"] },
    { version: "2.59" },
  ]);
  assert.deepEqual(out, [
    { version: "2.60", date: "۱۴۰۵/۰۸/۱۶", summary: "", items: ["الف", "ب"] },
    { version: "2.59", date: "", summary: "", items: [] },
  ]);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
