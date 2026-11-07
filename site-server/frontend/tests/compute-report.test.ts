/**
 * آزمونِ منطقِ خالصِ «گزارشِ سرورهای پردازش» (بدونِ مرورگر): قالبِ اعداد و اندازه، تاریخِ شمسی و بازهٔ زمانی، نشانیِ درخواست و CSV،
 * کاهشِ نقاطِ نمودار و مسیرِ SVG، نوارِ روشن/خاموش، وضعیتِ سرور و منابع، کاشی‌های خلاصه، دانلود و متن‌های فارسی.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-report.test.ts --bundle --platform=node --format=esm --outfile=/tmp/compute-report.test.mjs
 *   node /tmp/compute-report.test.mjs
 */
import assert from "node:assert/strict";

import {
  CHARTS,
  CSV_LABELS,
  DEFAULT_RANGE,
  LEVEL_OPTIONS,
  MAX_DAYS,
  PAGE_SIZE,
  POLL_MS,
  PRESETS,
  SERVICE_LABELS,
  agentVersionView,
  allStaticTexts,
  axisLabel,
  buildLinePaths,
  chartValue,
  clockText,
  csvPath,
  downloadProgressText,
  downloadStateTone,
  errorSourceLabel,
  errorTextFromBody,
  fmtBytes,
  fmtGb,
  fmtMb,
  fmtNum,
  fmtPct,
  fmtSpeed,
  fmtTemp,
  gapLimit,
  isoDaysBetween,
  jalaliDate,
  jalaliDateTime,
  lastSeenText,
  levelLabel,
  levelTone,
  logsQuery,
  logsTruncatedNote,
  meterTone,
  niceMax,
  nodeState,
  pageInfo,
  parseJalaliDate,
  parseRetention,
  rangeParams,
  rangeText,
  reportQuery,
  resourceRows,
  runDuration,
  scheduleText,
  segmentBars,
  seriesStats,
  serviceChips,
  shiftIsoDate,
  shouldPoll,
  sortNodes,
  successRateText,
  successTone,
  summaryTiles,
  tehranIsoDate,
  thinPoints,
  toFa,
  toGregorian,
  toJalali,
  uptimeNote,
  uptimeText,
  validateCustomRange,
  type JobStat,
  type Point,
  type ReportNode,
  type Uptime,
} from "../src/features/tools/compute/report/model";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const NOW = Date.parse("2026-11-07T10:51:00Z"); // ۱۴:۲۱ تهران، ۱۴۰۵/۰۸/۱۶
const TODAY = "2026-11-07";

const stat = (over: Partial<JobStat> = {}): JobStat => ({
  count: 0, success: 0, failed: 0, cancelled: 0, running: 0, waiting: 0, avg_run_s: null, avg_wait_s: null, success_rate: null, ...over,
});
const uptime = (over: Partial<Uptime> = {}): Uptime => ({
  range_s: 86400, online_s: 43200, pct: 50, longest_gap_s: 7200, sessions: 3, since: null, partial: false, ...over,
});
const node = (over: Partial<ReportNode> = {}): ReportNode => ({
  id: 1, name: "gpu-1", enabled: true, online: true, last_seen: new Date(NOW - 30_000).toISOString(), created: "2026-10-01T00:00:00Z",
  agent: "2.5", agent_latest: "2.6", update_waiting: false, hostname: "PC1", gpu: "RTX 3060", services: { comfyui: true, ollama: false },
  models: { ollama: [], ollama_stale: false, comfy: {}, comfy_count: 0, audio: {}, voice_clone: false, packages: [], download_running: false, download_error: "" },
  resources: {
    ram_free_mb: 4096, ram_total_mb: 16384, vram_used_mb: 6144, vram_total_mb: 12288, disk_free_gb: 120.5, disk_total_gb: 500,
    gpu_util_pct: 35, gpu_temp_c: 61, ram_used_pct: 75, vram_used_pct: 50, disk_used_pct: 75.9,
  },
  resources_known: { ram: true, vram: true, disk: true, gpu_util: true, gpu_temp: true },
  jobs: stat(), jobs_by_kind: [], logs: { count: 0, kept_max: 500, truncated: false }, uptime: uptime(), segments: [], sessions: [], sessions_truncated: false,
  series: { ram_used_pct: [], vram_used_pct: [], disk_free_gb: [], gpu_util_pct: [], gpu_temp_c: [] }, ...over,
});

// ───────────── اعداد و اندازه
check("fmtNum: ممیزِ فارسی، جداکنندهٔ هزارگان، نامعتبر ⇒ «—»", () => {
  assert.equal(fmtNum(1234.5, 1), "۱٬۲۳۴٫۵");
  assert.equal(fmtNum(7, 1), "۷");
  assert.equal(fmtNum(0.04, 1), "۰");
  assert.equal(fmtNum(null), "—");
  assert.equal(fmtNum(Number.NaN), "—");
  assert.equal(fmtNum(Infinity), "—");
  assert.equal(fmtNum(undefined), "—");
});

check("fmtBytes / fmtMb / fmtGb / fmtSpeed", () => {
  assert.equal(fmtBytes(500), "۵۰۰ بایت");
  assert.equal(fmtBytes(2048), "۲ کیلوبایت");
  assert.equal(fmtBytes(450 * 1024 ** 2), "۴۵۰ مگابایت");
  assert.equal(fmtBytes(2.5 * 1024 ** 2), "۲٫۵ مگابایت");
  assert.equal(fmtBytes(1.2 * 1024 ** 3), "۱٫۲ گیگابایت");
  assert.equal(fmtBytes(-1), "—");
  assert.equal(fmtBytes(null), "—");
  assert.equal(fmtMb(4096), "۴ گیگابایت");
  assert.equal(fmtMb(null), "—");
  assert.equal(fmtGb(120.5), "۱۲۱ گیگابایت");
  assert.equal(fmtGb(3.25), "۳٫۳ گیگابایت");
  assert.equal(fmtSpeed(2 * 1024 ** 2), "۲ مگابایت بر ثانیه");
  assert.equal(fmtSpeed(0), "");
  assert.equal(fmtSpeed(null), "");
});

check("fmtPct / fmtTemp / chartValue", () => {
  assert.equal(fmtPct(75), "۷۵٪");
  assert.equal(fmtPct(33.33, 1), "۳۳٫۳٪");
  assert.equal(fmtPct(null), "—");
  assert.equal(fmtTemp(61.4), "۶۱ درجه");
  assert.equal(fmtTemp(undefined), "—");
  assert.equal(chartValue("pct", 50), "۵۰٪");
  assert.equal(chartValue("gb", 120), "۱۲۰ گیگابایت");
  assert.equal(chartValue("c", 70), "۷۰ درجه");
  assert.equal(chartValue("c", null), "—");
});

check("runDuration: ثانیه و دقیقه، نامعتبر ⇒ «—»", () => {
  assert.equal(runDuration(0), "۰ ثانیه");
  assert.equal(runDuration(45.4), "۴۵ ثانیه");
  assert.equal(runDuration(492), "۸ دقیقه و ۱۲ ثانیه");
  assert.equal(runDuration(600), "۱۰ دقیقه");
  assert.equal(runDuration(3 * 3600 + 20 * 60), "۳ ساعت و ۲۰ دقیقه");
  assert.equal(runDuration(null), "—");
  assert.equal(runDuration(Number.NaN), "—");
});

// ───────────── تاریخِ شمسی
check("toJalali / toGregorian: تاریخ‌های شناخته‌شده", () => {
  assert.deepEqual(toJalali(2026, 11, 7), [1405, 8, 16]);
  assert.deepEqual(toGregorian(1405, 8, 16), [2026, 11, 7]);
  assert.deepEqual(toJalali(2026, 3, 21), [1405, 1, 1]);
  assert.deepEqual(toJalali(2025, 3, 20), [1403, 12, 30]); // ۱۴۰۳ کبیسه است
  assert.deepEqual(toJalali(2025, 3, 21), [1404, 1, 1]);
  assert.deepEqual(toJalali(2024, 3, 20), [1403, 1, 1]);
  assert.deepEqual(toGregorian(1403, 12, 30), [2025, 3, 20]);
});

check("رفت‌وبرگشتِ شمسی ⇄ میلادی برای ۱۰ سال، هر ۳۷ روز", () => {
  const start = Date.UTC(2020, 0, 1);
  for (let i = 0; i < 100; i += 1) {
    const d = new Date(start + i * 37 * 86_400_000);
    const [jy, jm, jd] = toJalali(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
    assert.deepEqual(toGregorian(jy, jm, jd), [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate()]);
    assert.ok(jm >= 1 && jm <= 12 && jd >= 1 && jd <= 31);
  }
});

check("parseJalaliDate: ارقامِ فارسی/عربی/لاتین و جداکننده‌ها", () => {
  assert.equal(parseJalaliDate("۱۴۰۵/۰۸/۱۶"), "2026-11-07");
  assert.equal(parseJalaliDate("1405-8-16"), "2026-11-07");
  assert.equal(parseJalaliDate("١٤٠٥.٠٨.١٦"), "2026-11-07");
  assert.equal(parseJalaliDate("  ۱۴۰۵ / ۰۸ / ۱۶ "), "2026-11-07");
  assert.equal(parseJalaliDate("۱۴۰۳/۱۲/۳۰"), "2025-03-20");
});

check("parseJalaliDate: روزِ ناموجود و ورودیِ بد ⇒ null", () => {
  for (const bad of ["", "abc", "۱۴۰۵/۱۳/۰۱", "۱۴۰۵/۰۰/۱۰", "۱۴۰۵/۰۷/۳۱", "۱۴۰۴/۱۲/۳۰", "۱۴۰۵/۰۸", "۱۲۰/۰۱/۰۱", "۱۴۰۵/۰۱/۳۲", "2026-11-07"]) {
    assert.equal(parseJalaliDate(bad), null, bad);
  }
});

check("tehranIsoDate / shiftIsoDate / isoDaysBetween", () => {
  assert.equal(tehranIsoDate(NOW), "2026-11-07");
  assert.equal(tehranIsoDate(Date.parse("2026-11-07T21:00:00Z")), "2026-11-08"); // ۰۰:۳۰ تهرانِ فردا
  assert.equal(tehranIsoDate(Date.parse("2026-11-07T20:29:00Z")), "2026-11-07");
  assert.equal(shiftIsoDate("2026-11-01", -1), "2026-10-31");
  assert.equal(shiftIsoDate("2026-12-31", 1), "2027-01-01");
  assert.equal(shiftIsoDate("2028-02-28", 1), "2028-02-29");
  assert.equal(isoDaysBetween("2026-11-01", "2026-11-07"), 6);
  assert.equal(isoDaysBetween("2026-10-31", "2026-11-01"), 1);
});

check("jalaliDate / jalaliDateTime / clockText (وقتِ تهران)", () => {
  assert.equal(jalaliDate("2026-11-07"), "۱۴۰۵/۰۸/۱۶");
  assert.equal(jalaliDate(""), "");
  assert.equal(jalaliDate("نادرست"), "");
  assert.equal(jalaliDateTime("2026-11-07T10:51:00Z"), "۱۴۰۵/۰۸/۱۶ ۱۴:۲۱");
  assert.equal(jalaliDateTime("2026-11-07T21:30:00Z"), "۱۴۰۵/۰۸/۱۷ ۰۱:۰۰");
  assert.equal(jalaliDateTime(Date.parse("2026-11-07T10:51:00Z") / 1000), "۱۴۰۵/۰۸/۱۶ ۱۴:۲۱");
  assert.equal(jalaliDateTime(null), "—");
  assert.equal(jalaliDateTime("x"), "—");
  assert.equal(clockText("2026-11-07T10:51:00Z"), "۱۴:۲۱");
  assert.equal(clockText("x"), "—");
});

// ───────────── بازهٔ زمانی
check("rangeParams: پیش‌تنظیم‌ها و بازهٔ دلخواه", () => {
  assert.deepEqual(rangeParams({ preset: "today" }), { days: "1" });
  assert.deepEqual(rangeParams({ preset: "7d" }), { days: "7" });
  assert.deepEqual(rangeParams({ preset: "30d" }), { days: "30" });
  assert.deepEqual(rangeParams({ preset: "custom", from: "2026-11-01", to: "2026-11-07" }), { from: "2026-11-01", to: "2026-11-07" });
  assert.deepEqual(rangeParams({ preset: "custom" }), { days: "7" });
  assert.deepEqual(rangeParams(DEFAULT_RANGE), { days: "7" });
  assert.deepEqual(PRESETS.map((p) => p.key), ["today", "7d", "30d", "custom"]);
});

check("validateCustomRange: بازهٔ درست", () => {
  const ok = validateCustomRange("۱۴۰۵/۰۸/۱۰", "۱۴۰۵/۰۸/۱۶", TODAY);
  assert.deepEqual(ok, { ok: true, from: "2026-11-01", to: "2026-11-07", days: 7 });
  const blankTo = validateCustomRange("۱۴۰۵/۰۸/۱۰", "  ", TODAY);
  assert.deepEqual(blankTo, { ok: true, from: "2026-11-01", to: TODAY, days: 7 });
  const future = validateCustomRange("۱۴۰۵/۰۸/۱۰", "۱۴۰۵/۰۹/۲۰", TODAY);
  assert.equal(future.ok && future.to, TODAY); // «تا»ی آینده به امروز می‌رسد
  const one = validateCustomRange("۱۴۰۵/۰۸/۱۶", "۱۴۰۵/۰۸/۱۶", TODAY);
  assert.equal(one.ok && one.days, 1);
});

check("validateCustomRange: خطاها فارسی‌اند", () => {
  const cases: [string, string][] = [
    ["", ""],
    ["abc", ""],
    ["۱۴۰۵/۰۸/۱۰", "xyz"],
    ["۱۴۰۵/۰۸/۱۷", ""], // آینده
    ["۱۴۰۵/۰۸/۱۶", "۱۴۰۵/۰۸/۱۰"], // برعکس
    ["۱۴۰۵/۰۱/۰۱", "۱۴۰۵/۰۸/۱۶"], // بیش از ۹۰ روز
  ];
  for (const [from, to] of cases) {
    const r = validateCustomRange(from, to, TODAY);
    assert.equal(r.ok, false, `${from}|${to}`);
    if (!r.ok) assert.match(r.error, /[؀-ۿ]/);
  }
  const long = validateCustomRange("۱۴۰۵/۰۱/۰۱", "۱۴۰۵/۰۸/۱۶", TODAY);
  assert.ok(!long.ok && long.error.includes(toFa(MAX_DAYS)));
});

check("rangeText: بازهٔ پاسخ به شمسی", () => {
  assert.equal(rangeText({ from: "2026-11-01", to: "2026-11-07", days: 7 }), "۱۴۰۵/۰۸/۱۰ تا ۱۴۰۵/۰۸/۱۶ (۷ روز)");
  assert.equal(rangeText({ from: "2026-11-07", to: "2026-11-07", days: 1 }), "۱۴۰۵/۰۸/۱۶ (یک روز)");
});

// ───────────── نشانی‌ها
check("reportQuery / logsQuery: ترتیبِ ثابت و فقط پارامترِ لازم", () => {
  assert.equal(reportQuery({ preset: "7d" }, null), "days=7");
  assert.equal(reportQuery({ preset: "today" }, 3), "days=1&node=3");
  assert.equal(reportQuery({ preset: "custom", from: "2026-11-01", to: "2026-11-07" }, null), "from=2026-11-01&to=2026-11-07");
  assert.equal(logsQuery({ sel: { preset: "30d" }, nodeId: null, level: "all", q: "", offset: 0 }), "days=30&limit=100&offset=0");
  assert.equal(
    logsQuery({ sel: { preset: "7d" }, nodeId: 2, level: "error", q: "  CUDA out  ", offset: 200, limit: 50 }),
    "days=7&node=2&level=error&q=CUDA+out&limit=50&offset=200",
  );
  const clamp = logsQuery({ sel: { preset: "7d" }, nodeId: null, level: "all", q: "x".repeat(300), offset: -5, limit: 99999 });
  assert.match(clamp, /limit=500&offset=0/);
  assert.equal(new URLSearchParams(clamp).get("q")!.length, 100);
  assert.equal(PAGE_SIZE, 100);
});

check("csvPath: بخش، بازه، سرور؛ فیلترِ لاگ فقط برای لاگ‌ها", () => {
  assert.equal(csvPath("jobs", { preset: "7d" }, 3), "/compute/report/export.csv?section=jobs&days=7&node=3");
  assert.equal(csvPath("sessions", { preset: "today" }, null), "/compute/report/export.csv?section=sessions&days=1");
  assert.equal(
    csvPath("logs", { preset: "custom", from: "2026-11-01", to: "2026-11-07" }, null, { level: "error", q: " CUDA mem " }),
    "/compute/report/export.csv?section=logs&from=2026-11-01&to=2026-11-07&level=error&q=CUDA+mem",
  );
  assert.equal(csvPath("errors", { preset: "30d" }, null, { level: "error", q: "x" }), "/compute/report/export.csv?section=errors&days=30");
  assert.equal(csvPath("logs", { preset: "7d" }, null, { level: "all", q: "" }), "/compute/report/export.csv?section=logs&days=7");
  assert.deepEqual(Object.keys(CSV_LABELS).sort(), ["downloads", "errors", "jobs", "logs", "samples", "sessions"]);
});

check("errorTextFromBody / parseRetention", () => {
  assert.equal(errorTextFromBody('{"days":["تعدادِ روز باید عدد باشد."]}'), "تعدادِ روز باید عدد باشد.");
  assert.equal(errorTextFromBody('{"from":"تاریخِ شروع در آینده است."}'), "تاریخِ شروع در آینده است.");
  assert.equal(errorTextFromBody('{"detail":{"x":["پیام"]}}'), "پیام");
  assert.equal(errorTextFromBody("<html>"), "خروجی ساخته نشد.");
  assert.equal(errorTextFromBody("{}"), "خروجی ساخته نشد.");
  assert.deepEqual(parseRetention("۳۰"), { ok: true, days: 30 });
  assert.deepEqual(parseRetention(" 365 "), { ok: true, days: 365 });
  assert.deepEqual(parseRetention("1"), { ok: true, days: 1 });
  for (const bad of ["", "0", "366", "-3", "۳.۵", "abc", "۱۰۰۰"]) assert.equal(parseRetention(bad).ok, false, bad);
});

// ───────────── نمودار
check("seriesStats", () => {
  assert.equal(seriesStats([]), null);
  const s = seriesStats([[1, 10], [2, 30], [3, 20]])!;
  assert.deepEqual([s.min, s.max, s.avg, s.last], [10, 30, 20, 20]);
});

check("thinPoints: سقف، میانگینِ سطل، ترتیب و حذفِ ورودیِ خراب", () => {
  const pts: Point[] = Array.from({ length: 1000 }, (_, i) => [i, i % 10]);
  const out = thinPoints(pts, 100);
  assert.ok(out.length <= 100 && out.length >= 90);
  for (let i = 1; i < out.length; i += 1) assert.ok(out[i][0] > out[i - 1][0]);
  assert.ok(out.every((p) => p[1] >= 0 && p[1] <= 9));
  assert.equal(thinPoints(pts.slice(0, 50), 100).length, 50);
  const shuffled: Point[] = [[5, 1], [1, 1], [3, 1]];
  assert.deepEqual(thinPoints(shuffled, 10).map((p) => p[0]), [1, 3, 5]);
  const junk: Point[] = [[1, Number.NaN], [Number.POSITIVE_INFINITY, 2], [2, 3]];
  assert.deepEqual(thinPoints(junk, 10), [[2, 3]]);
  assert.deepEqual(thinPoints([], 10), []);
  // میانگین: دو نقطه در یک سطل
  assert.deepEqual(thinPoints([[0, 10], [10, 30], [20, 50], [30, 70]], 2), [[5, 20], [25, 60]]);
});

check("niceMax", () => {
  assert.equal(niceMax([10, 50], 100), 100);
  assert.equal(niceMax([]), 1);
  assert.equal(niceMax([0]), 1);
  const m = niceMax([120.5, 80]);
  assert.ok(m >= 120.5 && m <= 200);
  assert.ok(niceMax([61]) >= 61 && niceMax([61]) <= 100);
});

check("buildLinePaths: وقفه خط را می‌شکند، نقطهٔ تنها دایره می‌شود، بیرونِ بازه نمی‌آید", () => {
  const pts: Point[] = [[0, 10], [60, 20], [120, 30], [1000, 40], [1060, 50]];
  const r = buildLinePaths(pts, 0, 2000, 200, 100, 100, 300);
  assert.equal(r.lines.length, 2);
  assert.equal(r.lines[0], "M0 90 L6 80 L12 70");
  assert.equal(r.lines[1], "M100 60 L106 50");
  assert.equal(r.areas.length, 2);
  assert.ok(r.areas[0].endsWith(" Z") && r.areas[0].includes("L12 100 L0 100"));
  assert.deepEqual(r.dots, []);
  const lone = buildLinePaths([[0, 10], [100, 20], [5000, 30], [9000, 40]], 0, 10000, 100, 50, 100, 500);
  assert.equal(lone.lines.length, 1); // ۰ و ۱۰۰ فاصلهٔ کم دارند ⇒ یک خط
  assert.equal(lone.dots.length, 2); // ۵۰۰۰ و ۹۰۰۰ هرکدام تنها ⇒ دایره
  const out = buildLinePaths([[-50, 1], [50, 2], [20_000, 3]], 0, 100, 100, 100, 10, 1000);
  assert.equal(out.dots.length, 1);
  assert.deepEqual(buildLinePaths([], 0, 10, 10, 10, 10, 5), { lines: [], areas: [], dots: [] });
  assert.deepEqual(buildLinePaths(pts, 5, 5, 10, 10, 10, 5).lines, []);
  assert.deepEqual(buildLinePaths(pts, 0, 10, 10, 10, 0, 5).lines, []);
  // مقدارِ بیشتر از سقف روی لبهٔ بالا می‌ماند
  assert.equal(buildLinePaths([[0, 500], [10, 500]], 0, 10, 10, 100, 100, 50).lines[0], "M0 0 L10 0");
});

check("gapLimit: حداقل ۱۵۰ ثانیه و متناسب با گامِ نمونه", () => {
  assert.equal(gapLimit(3600), 150);
  assert.equal(gapLimit(86400), 900);
  assert.ok(gapLimit(30 * 86400) > gapLimit(86400));
});

check("segmentBars: درصدِ چپ و پهنا، کمینهٔ پهنا، برش به بازه", () => {
  const bars = segmentBars([[0, 50], [75, 100]], 0, 100);
  assert.deepEqual(bars, [{ left: 0, width: 50 }, { left: 75, width: 25 }]);
  const tiny = segmentBars([[10, 10.01]], 0, 1000);
  assert.equal(tiny[0].width, 0.4);
  const clipped = segmentBars([[-50, 20], [90, 500]], 0, 100);
  assert.deepEqual(clipped, [{ left: 0, width: 20 }, { left: 90, width: 10 }]);
  assert.deepEqual(segmentBars([[0, 5]], 10, 10), []);
  assert.deepEqual(segmentBars([], 0, 10), []);
});

check("axisLabel: بازهٔ کوتاه ساعت، بلند تاریخِ شمسی", () => {
  const t = Date.parse("2026-11-07T10:51:00Z") / 1000;
  assert.equal(axisLabel(t, 3600), "۱۴:۲۱");
  assert.equal(axisLabel(t, 7 * 86400), "۰۸/۱۶");
});

// ───────────── سرور
check("nodeState / lastSeenText", () => {
  assert.deepEqual(nodeState({ enabled: true, online: true }), { state: "online", label: "روشن", tone: "ok" });
  assert.deepEqual(nodeState({ enabled: true, online: false }), { state: "offline", label: "خاموش", tone: "bad" });
  assert.deepEqual(nodeState({ enabled: false, online: true }), { state: "disabled", label: "غیرفعال", tone: "neutral" });
  assert.equal(lastSeenText(null), "هنوز وصل نشده");
  assert.equal(lastSeenText(new Date(NOW - 3 * 60_000).toISOString(), NOW), "۳ دقیقه پیش (۱۴۰۵/۰۸/۱۶ ۱۴:۱۸)");
});

check("agentVersionView: به‌روز، نسخهٔ تازه‌تر، نامعلوم", () => {
  assert.deepEqual(agentVersionView({ agent: "2.6", agent_latest: "2.6", update_waiting: false }), { text: "نسخهٔ ۲٫۶", tone: "ok", note: "به‌روز است" });
  const old = agentVersionView({ agent: "2.5", agent_latest: "2.6", update_waiting: true });
  assert.equal(old.tone, "warn");
  assert.ok(old.note.includes("نسخهٔ ۲٫۶") && old.note.includes("به‌روز کنید"));
  assert.equal(agentVersionView({ agent: "2.5", agent_latest: null, update_waiting: true }).tone, "warn");
  assert.deepEqual(agentVersionView({ agent: null, agent_latest: "2.6", update_waiting: false }), { text: "نسخه نامعلوم", tone: "neutral", note: "" });
});

check("sortNodes: روشن، خاموش، غیرفعال؛ بعد نام", () => {
  const list = [
    node({ id: 1, name: "b-off", online: false }),
    node({ id: 2, name: "z-on" }),
    node({ id: 3, name: "a-off", online: false }),
    node({ id: 4, name: "a-dis", enabled: false, online: false }),
    node({ id: 5, name: "a-on" }),
  ];
  assert.deepEqual(sortNodes(list).map((n) => n.name), ["a-on", "z-on", "a-off", "b-off", "a-dis"]);
  assert.deepEqual(list.map((n) => n.id), [1, 2, 3, 4, 5]); // ورودی دست نمی‌خورد
  assert.deepEqual(sortNodes([]), []);
});

check("meterTone: ۷۰ و ۹۰ مرزِ رنگ", () => {
  assert.equal(meterTone(0), "ok");
  assert.equal(meterTone(69.9), "ok");
  assert.equal(meterTone(70), "warn");
  assert.equal(meterTone(90), "bad");
  assert.equal(meterTone(null), "neutral");
  assert.equal(meterTone(Number.NaN), "neutral");
});

check("resourceRows: مقدارِ شناخته‌شده و «نامعلوم» برای عاملِ قدیمی", () => {
  const rows = resourceRows(node());
  assert.deepEqual(rows.map((r) => r.key), ["ram", "vram", "gpu", "disk", "temp"]);
  assert.equal(rows[0].value, "۱۲ گیگابایت از ۱۶ گیگابایت");
  assert.equal(rows[0].pct, 75);
  assert.equal(rows[0].tone, "warn");
  assert.equal(rows[1].value, "۶ گیگابایت از ۱۲ گیگابایت");
  assert.equal(rows[3].value, "۱۲۱ گیگابایت آزاد از ۵۰۰ گیگابایت");
  assert.equal(rows[4].value, "۶۱ درجه");
  assert.equal(rows[4].tone, "ok");
  const old = resourceRows(
    node({
      resources: { ...node().resources, disk_free_gb: null, disk_total_gb: null, gpu_util_pct: null, gpu_temp_c: null, disk_used_pct: null },
      resources_known: { ram: true, vram: true, disk: false, gpu_util: false, gpu_temp: false },
    }),
  );
  for (const k of ["gpu", "disk", "temp"]) assert.equal(old.find((r) => r.key === k)!.value, "نامعلوم");
  assert.equal(old.find((r) => r.key === "disk")!.pct, null);
  const hot = resourceRows(node({ resources: { ...node().resources, gpu_temp_c: 88 } }));
  assert.equal(hot[4].tone, "bad");
});

check("serviceChips / uptimeText / uptimeNote", () => {
  const chips = serviceChips({ comfyui: true, ollama: false });
  assert.equal(chips.find((c) => c.key === "comfyui")!.on, true);
  assert.equal(chips.find((c) => c.key === "ollama")!.on, false);
  assert.equal(chips.find((c) => c.key === "photo")!.on, false);
  assert.equal(chips.length, Object.keys(SERVICE_LABELS).length);
  assert.equal(uptimeText(uptime({ pct: 50, longest_gap_s: 7200 })), "۵۰٪ روشن · طولانی‌ترین خاموشی ۲ ساعت");
  assert.equal(uptimeText(uptime({ pct: 99.96, longest_gap_s: 0 })), "۱۰۰٪ روشن");
  assert.equal(uptimeText(uptime({ pct: 87.34, longest_gap_s: 30 })), "۸۷٫۳٪ روشن");
  assert.equal(uptimeText(uptime({ pct: null, range_s: 0 })), "هنوز آماری ثبت نشده");
  assert.equal(uptimeNote(uptime()), "");
  assert.ok(uptimeNote(uptime({ partial: true, since: "2026-11-07T10:51:00Z" })).includes("۱۴۰۵/۰۸/۱۶ ۱۴:۲۱"));
});

// ───────────── آمارِ کارها
check("successRateText / successTone", () => {
  assert.equal(successRateText({ success_rate: null, success: 0, failed: 0 }), "—");
  assert.equal(successRateText({ success_rate: 66.7, success: 2, failed: 1 }), "۶۷٪ موفق");
  assert.equal(successTone({ success_rate: 100 }), "ok");
  assert.equal(successTone({ success_rate: 90 }), "warn");
  assert.equal(successTone({ success_rate: 50 }), "bad");
  assert.equal(successTone({ success_rate: null }), "neutral");
});

check("summaryTiles", () => {
  const base = {
    nodes: [node(), node({ id: 2, name: "gpu-2", online: false }), node({ id: 3, name: "old", enabled: false, online: false })],
    jobs: { per_kind: [], totals: stat({ count: 10, success: 8, failed: 2, avg_run_s: 125, avg_wait_s: 8, success_rate: 80 }) },
    errors: [],
    queue_now: { waiting: 2, running: 1, oldest_wait_s: 30, oldest_wait_text: "۳۰ ثانیه" },
  };
  const t = Object.fromEntries(summaryTiles(base as never).map((x) => [x.key, x]));
  assert.equal(t.nodes.value, "۱ از ۲");
  assert.equal(t.nodes.tone, "warn");
  assert.equal(t.jobs.value, "۱۰");
  assert.equal(t.jobs.hint, "۸۰٪ موفق");
  assert.equal(t.jobs.tone, "warn");
  assert.equal(t.run.value, "۲ دقیقه و ۵ ثانیه");
  assert.equal(t.wait.value, "۸ ثانیه");
  assert.equal(t.wait.hint, "الان ۲ کار منتظر است");
  assert.equal(t.errors.value, "۰");
  assert.equal(t.errors.tone, "ok");
  const empty = Object.fromEntries(
    summaryTiles({ nodes: [], jobs: { per_kind: [], totals: stat() }, errors: [], queue_now: { waiting: 0, running: 0, oldest_wait_s: null, oldest_wait_text: "" } }).map((x) => [x.key, x]),
  );
  assert.equal(empty.nodes.value, "۰ از ۰");
  assert.equal(empty.nodes.hint, "هنوز سروری ثبت نشده");
  assert.equal(empty.run.value, "—");
  assert.equal(empty.jobs.tone, "neutral");
  const down = summaryTiles({ ...base, nodes: [node({ online: false })] } as never).find((x) => x.key === "nodes")!;
  assert.equal(down.tone, "bad");
});

// ───────────── خطا، لاگ، دانلود
check("levelLabel / levelTone / errorSourceLabel / pageInfo", () => {
  assert.equal(levelLabel("ERROR"), "خطا");
  assert.equal(levelLabel("critical"), "خطا");
  assert.equal(levelLabel("WARNING"), "هشدار");
  assert.equal(levelLabel("INFO"), "اطلاع");
  assert.equal(levelLabel("DEBUG"), "جزئیات");
  assert.equal(levelTone("ERROR"), "bad");
  assert.equal(levelTone("warn"), "warn");
  assert.equal(levelTone("INFO"), "neutral");
  assert.equal(errorSourceLabel("job"), "کارِ ناموفق");
  assert.equal(errorSourceLabel("log"), "لاگِ سرور");
  assert.equal(pageInfo(340, 100, 100), "۱۰۱ تا ۲۰۰ از ۳۴۰");
  assert.equal(pageInfo(0, 0, 0), "موردی نیست");
  assert.equal(logsTruncatedNote(500), "از هر سرور فقط ۵۰۰ خطِ آخر در سایت نگه داشته می‌شود.");
  assert.deepEqual(LEVEL_OPTIONS.map((o) => o.key), ["all", "error", "warning", "info"]);
});

check("downloadProgressText / downloadStateTone / scheduleText", () => {
  assert.equal(
    downloadProgressText({ percent: 25, bytes_done: 100 * 1024 ** 2, bytes_total: 400 * 1024 ** 2, speed_bps: 2 * 1024 ** 2, eta_s: 150, items_done: null, items_total: null }),
    "۲۵٪ · ۱۰۰ مگابایت از ۴۰۰ مگابایت · ۲ مگابایت بر ثانیه · حدودِ ۲ دقیقه مانده",
  );
  assert.equal(
    downloadProgressText({ percent: 25, bytes_done: 500, bytes_total: 2000, speed_bps: null, eta_s: null, items_done: 1, items_total: 4 }),
    "۲۵٪ · ۵۰۰ بایت از ۲ کیلوبایت · ۱ از ۴ فایل",
  );
  assert.equal(downloadProgressText({ percent: null, bytes_done: null, bytes_total: null, speed_bps: null, eta_s: null }), "در حالِ آماده‌سازی…");
  assert.equal(downloadStateTone("COMPLETED"), "ok");
  assert.equal(downloadStateTone("FAILED"), "bad");
  assert.equal(downloadStateTone("CANCELLED"), "neutral");
  assert.equal(downloadStateTone("RUNNING"), "brand");
  assert.equal(scheduleText({ scheduled_for: null, window: "" }), "");
  assert.equal(scheduleText({ scheduled_for: null, window: "02:00-07:00" }), "فقط در بازهٔ ۰۲:۰۰-۰۷:۰۰ (وقتِ تهران)");
  assert.equal(
    scheduleText({ scheduled_for: "2026-11-07T22:30:00Z", window: "02:00-07:00" }),
    "شروعِ زمان‌بندی‌شده ۱۴۰۵/۰۸/۱۷ ۰۲:۰۰ · فقط در بازهٔ ۰۲:۰۰-۰۷:۰۰ (وقتِ تهران)",
  );
});

check("به‌روزرسانی: هر ۳۰ ثانیه و فقط وقتی زبانه دیده می‌شود", () => {
  assert.equal(POLL_MS, 30_000);
  assert.equal(shouldPoll(false, false), true);
  assert.equal(shouldPoll(true, false), false);
  assert.equal(shouldPoll(false, true), false);
});

// ───────────── متن‌های فارسی
const TECH = /\b(?:ComfyUI|START|bat|Ollama|GPU|RAM|VRAM|CSV|MOSS|Excel|Update|AI)\b/g;

check("متن‌های ثابتِ صفحه فارسی‌اند و جز نامِ فنی انگلیسیِ سرگردان ندارند", () => {
  const texts = allStaticTexts();
  assert.ok(texts.length > 80);
  for (const t of texts) {
    assert.ok(t.length > 0);
    const stripped = t.replace(TECH, "");
    assert.equal(/[A-Za-z]/.test(stripped), false, `انگلیسیِ سرگردان: ${t}`);
    if (!/^[\s\d۰-۹.\-/:]*$/.test(t)) assert.match(t, /[؀-ۿ]|^(?:ComfyUI|Ollama|RAM|VRAM|GPU)/, t);
  }
});

check("خروجیِ قالب‌بندها جز واحدِ فنی انگلیسی ندارد و رقم‌ها فارسی‌اند", () => {
  const outs = [
    fmtNum(1234.5), fmtBytes(5 * 1024 ** 3), fmtMb(900), fmtGb(55), fmtSpeed(3_000_000), fmtPct(42), fmtTemp(70), runDuration(125),
    jalaliDateTime("2026-11-07T10:51:00Z"), rangeText({ from: "2026-11-01", to: "2026-11-07", days: 7 }), pageInfo(10, 0, 10),
    uptimeText(uptime()), lastSeenText(new Date(NOW - 5000).toISOString(), NOW), agentVersionView({ agent: "2.5", agent_latest: "2.6", update_waiting: true }).note,
    ...summaryTiles({ nodes: [node()], jobs: { per_kind: [], totals: stat({ count: 3, avg_run_s: 5, success_rate: 100 }) }, errors: [], queue_now: { waiting: 0, running: 0, oldest_wait_s: null, oldest_wait_text: "" } } as never).flatMap((t) => [t.label, t.value, t.hint]),
    ...resourceRows(node()).map((r) => r.value),
  ];
  for (const o of outs) {
    assert.equal(/[0-9]/.test(o), false, `رقمِ لاتین: ${o}`);
    assert.equal(/[A-Za-z]/.test(o.replace(TECH, "")), false, `انگلیسی: ${o}`);
  }
});

check("نمودارها: همهٔ سری‌های API پوشش داده شده و برچسبِ فارسی دارند", () => {
  assert.deepEqual(CHARTS.map((c) => c.key), ["ram_used_pct", "vram_used_pct", "gpu_util_pct", "disk_free_gb", "gpu_temp_c"]);
  for (const c of CHARTS.filter((x) => x.unit === "pct")) assert.equal(c.max, 100);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? "\n     " + r.err : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
