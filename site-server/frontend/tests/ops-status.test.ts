/**
 * آزمونِ منطقِ خالصِ «آخرین بکاپ» و «آزمون‌های شبانهٔ سایت» (بدونِ مرورگر).
 *
 *   cd frontend && node_modules/.bin/esbuild tests/ops-status.test.ts --bundle --platform=node --format=esm --outfile=/tmp/ops-status.test.mjs
 *   node /tmp/ops-status.test.mjs
 */
import assert from "node:assert/strict";

import { BACKUP_STALE_HOURS, OPS_TEXT, TESTS_STALE_HOURS, backupView, testsView, type BackupStatus, type SiteTests } from "../src/features/tools/compute/opsModel";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: String((e as Error)?.message ?? e) });
  }
}

const NOW = Date.parse("2026-11-14T12:00:00Z");
const okBackup: BackupStatus = {
  present: true,
  state: "ok",
  ok: true,
  at: "2026-11-14T03:50:30Z",
  size_mb: 12.4,
  databases: [
    { file: "db.sqlite3", size_mb: 10, integrity: "ok", ok: true },
    { file: "studio.sqlite3", size_mb: 0.7, integrity: "ok", ok: true },
  ],
  restore_test_ok: true,
  daily_kept: 7,
  weekly_kept: 4,
  media_kept: 2,
};

check("بکاپِ سالم: لحنِ ok، تاریخِ شمسی و «پیش»، سطرهای توضیح فارسی", () => {
  const v = backupView(okBackup, NOW);
  assert.equal(v.tone, "ok");
  assert.equal(v.badge, "سالم");
  assert.match(v.headline, /پیش/);
  assert.match(v.headline, /۱۴۰۵/);
  assert.ok(v.lines.some((l) => l.includes("۲ از ۲ دیتابیس")));
  assert.ok(v.lines.some((l) => l.includes("۷ روزانه") && l.includes("۴ هفتگی")));
  for (const l of [v.headline, ...v.lines]) assert.equal(/[0-9]/.test(l), false, `رقمِ لاتین: ${l}`);
});

check("بدونِ بکاپ و با نبودِ فایل: هشدارِ «هنوز بکاپی گرفته نشده»", () => {
  for (const b of [null, undefined, { present: false, state: "missing" } as BackupStatus]) {
    const v = backupView(b, NOW);
    assert.equal(v.tone, "warn");
    assert.equal(v.headline, OPS_TEXT.backupMissing);
  }
});

check("بکاپِ ناموفق: لحنِ bad و خطاها و آخرین بکاپِ سالم", () => {
  const v = backupView({ ...okBackup, state: "failed", ok: false, errors: ["دیتابیسِ x گرفته نشد"], last_good_at: "2026-11-13T03:50:00Z" }, NOW);
  assert.equal(v.tone, "bad");
  assert.ok(v.lines.some((l) => l.includes("دیتابیسِ x گرفته نشد")));
  assert.match(v.headline, /آخرین بکاپِ سالم/);
});

check("بکاپِ دیرکرده: هشدار", () => {
  const v = backupView({ ...okBackup, state: "stale", age_hours: BACKUP_STALE_HOURS + 5 }, NOW);
  assert.equal(v.tone, "warn");
  assert.equal(v.badge, "دیرکرد");
});

const redApp = {
  app: "customers",
  ok: false,
  tests: 40,
  failures: 1,
  errors: 2,
  skipped: 0,
  seconds: 12,
  red: [{ id: "test_a (apps.customers.tests.A.test_a)", kind: "error", message: "OperationalError: boom" }],
};
const greenApp = { app: "jobs", ok: true, tests: 20, failures: 0, errors: 0, skipped: 1, seconds: 3, red: [] };
const tests: SiteTests = {
  present: true,
  state: "red",
  running: null,
  started_at: "2026-11-13T23:30:00Z",
  finished_at: "2026-11-14T01:10:00Z",
  age_hours: 11,
  totals: { apps: 2, red_apps: 1, tests: 60, failures: 1, errors: 2, skipped: 1 },
  apps: [greenApp, redApp],
};

check("آزمون‌های شبانه: اپِ قرمز با فهرستِ آزمون‌ها و کاشی‌ها", () => {
  const v = testsView(tests, NOW);
  assert.equal(v.tone, "bad");
  assert.equal(v.red.length, 1);
  assert.equal(v.red[0].app, "customers");
  assert.equal(v.red[0].items[0].message, "OperationalError: boom");
  assert.deepEqual(v.tiles.map((t) => t.key), ["tests", "apps", "red", "redapps"]);
  assert.equal(v.tiles.find((t) => t.key === "red")?.value, "۳");
  assert.match(v.headline, /۳ آزمون قرمز/);
});

check("آزمون‌های شبانه: همه سبز", () => {
  const v = testsView({ ...tests, state: "green", totals: { apps: 2, red_apps: 0, tests: 60, failures: 0, errors: 0, skipped: 1 }, apps: [greenApp] }, NOW);
  assert.equal(v.tone, "ok");
  assert.equal(v.red.length, 0);
  assert.match(v.headline, /سبزند/);
});

check("آزمون‌های شبانه: هنوز اجرا نشده / در حالِ اجرا / قدیمی", () => {
  assert.equal(testsView({ present: false, state: "missing", running: null }, NOW).headline, OPS_TEXT.testsMissing);
  assert.equal(testsView({ present: false, state: "missing", running: { app: "jobs", since: "x" } }, NOW).badge, OPS_TEXT.testsRunning);
  const old = testsView({ ...tests, state: "stale", age_hours: TESTS_STALE_HOURS + 3 }, NOW);
  assert.equal(old.tone, "warn");
  assert.match(old.headline, /بیش از دو روز/);
});

check("اپی که نیمه‌کاره ماند یا زمانش تمام شد: یادداشتِ جدا", () => {
  const crashed = { ...redApp, crashed: true, failures: 0, errors: 0, red: [], tail: ["Traceback", "ImportError: x"] };
  const v = testsView({ ...tests, apps: [crashed] }, NOW);
  assert.match(v.red[0].note, /نیمه‌کاره/);
  assert.match(v.red[0].note, /ImportError/);
  const v2 = testsView({ ...tests, apps: [{ ...crashed, crashed: false, timeout: true }] }, NOW);
  assert.match(v2.red[0].note, /زمانِ اجرا/);
});

check("اپی که قفلِ سنگین پر بود رد شده است، نه قرمز: کاشیِ جدا و لحنِ سبز", () => {
  const skipped = { app: "compute", ok: true, tests: 0, failures: 0, errors: 0, skipped: 0, seconds: 3600, lock_timeout: true, red: [] };
  const v = testsView({ ...tests, state: "green", totals: { apps: 2, red_apps: 0, tests: 20, failures: 0, errors: 0, skipped: 1, lock_skipped: 1 }, apps: [greenApp, skipped] }, NOW);
  assert.equal(v.tone, "ok");
  assert.equal(v.red.length, 0);
  const tile = v.tiles.find((t) => t.key === "lockskipped");
  assert.equal(tile?.value, "۱");
  assert.equal(tile?.tone, "warn");
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? "\n     " + r.err : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
