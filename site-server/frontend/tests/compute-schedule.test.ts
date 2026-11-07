/**
 * آزمونِ منطقِ خالصِ «زمان‌بندیِ دانلود» (بدونِ مرورگر): ساعت و بازه، حسابِ وقتِ تهران (UTC+3:30 ثابت)، بازهٔ نیمه‌شب،
 * فرمِ تنظیمِ کلی، انتخابگرِ زمانِ هر دانلود، برچسبِ «زمان‌بندی‌شده — شروع امروز ۰۲:۰۰» و کیفیتِ متنِ فارسی.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-schedule.test.ts --bundle --platform=node --format=esm --outfile=/tmp/compute-schedule.test.mjs
 *   node /tmp/compute-schedule.test.mjs
 */
import assert from "node:assert/strict";

import {
  DEFAULT_SETTINGS,
  DEFAULT_WHEN,
  IMMEDIATE_NOTE,
  TEHRAN_OFFSET_MS,
  WHEN_OPTIONS,
  clockLabel,
  describeSettings,
  inWindow,
  joinWindow,
  nextClockMs,
  nextWindowStartMs,
  normalizeClock,
  parseWindow,
  sameSettings,
  scheduleLabel,
  settingsBody,
  settingsError,
  settingsFromServer,
  startMoment,
  whenBody,
  whenConfirmLine,
  whenError,
  whenSummary,
  whenValid,
  windowFa,
  type DownloadSettings,
  type WhenChoice,
} from "../src/features/tools/compute/schedule";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const DAY = 86400000;
/** لحظه‌ای که ساعتِ دیواریِ تهران روزِ ۱۴۰۵/۰۸/۱۶ (۲۰۲۶-۱۱-۰۷) hh:mm را نشان می‌دهد */
const tehran = (h: number, m = 0, day = 0) => Date.UTC(2026, 10, 7, h, m) + day * DAY - TEHRAN_OFFSET_MS;
const NOW = tehran(12);

const settings = (over: Partial<DownloadSettings> = {}): DownloadSettings => ({ ...DEFAULT_SETTINGS, ...over });
const choice = (mode: WhenChoice["mode"], time = "03:30"): WhenChoice => ({ mode, time });

// ───────────── ساعت و بازه
check("ساعت: ارقامِ فارسی و عربی، یک‌رقمی، حدّها", () => {
  assert.equal(normalizeClock("۰۳:۳۰"), "03:30");
  assert.equal(normalizeClock("٣:٣٠"), "03:30");
  assert.equal(normalizeClock("3:05"), "03:05");
  assert.equal(normalizeClock(" 23:59 "), "23:59");
  assert.equal(normalizeClock("00:00"), "00:00");
  for (const bad of ["", null, undefined, "24:00", "12:60", "12", "ab:cd", "1:2", "12:345", "-1:30"]) assert.equal(normalizeClock(bad as string), null, String(bad));
});

check("بازه: خواندن و ساختن مثلِ سایت", () => {
  assert.deepEqual(parseWindow("02:00-07:00"), { start: "02:00", end: "07:00" });
  assert.deepEqual(parseWindow("۲:۳۰-۷:۰۵"), { start: "02:30", end: "07:05" });
  for (const bad of ["", null, "07:00-07:00", "25:00-07:00", "02:00", "a-b", "02:00-07:61", "1-2-3"]) assert.equal(parseWindow(bad as string), null, String(bad));
  assert.equal(joinWindow("2:00", "7:00"), "02:00-07:00");
  assert.equal(joinWindow("02:00", "02:00"), null);
  assert.equal(joinWindow("", "07:00"), null);
  assert.equal(windowFa("02:00-07:00"), "۰۲:۰۰ تا ۰۷:۰۰");
  assert.equal(windowFa("x"), "");
});

// ───────────── وقتِ تهران
check("درون/بیرونِ بازه (مرزها: شروع شامل، پایان نه)", () => {
  const w = "02:00-07:00";
  for (const [h, m, want] of [[1, 59, false], [2, 0, true], [4, 30, true], [6, 59, true], [7, 0, false], [12, 0, false], [23, 59, false]] as const)
    assert.equal(inWindow(w, tehran(h, m)), want, `${h}:${m}`);
  assert.equal(inWindow("", tehran(12)), true);
  assert.equal(inWindow("garbage", tehran(12)), true);
});

check("بازهٔ نیمه‌شب ۲۲:۰۰-۰۴:۰۰", () => {
  const w = "22:00-04:00";
  for (const [h, m, want] of [[21, 59, false], [22, 0, true], [23, 59, true], [0, 0, true], [3, 59, true], [4, 0, false], [12, 0, false]] as const)
    assert.equal(inWindow(w, tehran(h, m)), want, `${h}:${m}`);
  assert.equal(nextWindowStartMs(w, tehran(12)), tehran(22));
});

check("ساعتِ تهران ثابت است: تابستان و زمستان یکی", () => {
  const summer = Date.UTC(2026, 6, 1, 10, 0);            // ۱۰:۰۰ UTC = ۱۳:۳۰ تهران
  assert.equal(inWindow("13:00-14:00", summer), true);
  assert.equal(inWindow("14:00-15:00", summer), false);
  assert.equal(inWindow("13:00-14:00", Date.UTC(2026, 0, 1, 10, 0)), true);
});

check("نخستین ساعتِ آینده: امروز، فردا، و دقیقاً همین لحظه ⇒ فردا", () => {
  assert.equal(nextClockMs("15:30", NOW), tehran(15, 30));
  assert.equal(nextClockMs("03:30", NOW), tehran(3, 30, 1));
  assert.equal(nextClockMs("12:00", NOW), tehran(12, 0, 1));
  assert.equal(nextClockMs("۱۵:۳۰", NOW), tehran(15, 30));
  assert.equal(nextClockMs("99:99", NOW), null);
});

check("آغازِ بازهٔ بعدی", () => {
  assert.equal(nextWindowStartMs("02:00-07:00", tehran(12)), tehran(2, 0, 1));
  assert.equal(nextWindowStartMs("02:00-07:00", tehran(1, 0)), tehran(2, 0));
  assert.equal(nextWindowStartMs("02:00-07:00", tehran(3, 0)), tehran(3, 0), "داخلِ بازه ⇒ همین الان");
  assert.equal(nextWindowStartMs("", tehran(12)), tehran(12));
});

check("برچسبِ روز: امروز، فردا، چند روزِ دیگر", () => {
  assert.equal(clockLabel(tehran(15, 30), NOW), "امروز ۱۵:۳۰");
  assert.equal(clockLabel(tehran(2, 0, 1), NOW), "فردا ۰۲:۰۰");
  assert.equal(clockLabel(tehran(2, 0, 3), NOW), "۳ روزِ دیگر، ۰۲:۰۰");
  assert.equal(clockLabel(tehran(0, 5, 1), tehran(23, 50)), "فردا ۰۰:۰۵", "نیمه‌شبِ تهران، نه UTC");
});

// ───────────── «زمان‌بندی‌شده — شروع …»
check("برچسبِ کارِ زمان‌بندی‌شده از scheduled_for و window", () => {
  const iso = (ms: number) => new Date(ms).toISOString();
  assert.equal(scheduleLabel({ scheduled_for: iso(tehran(2, 0, 1)) }, NOW), "زمان‌بندی‌شده — شروع فردا ۰۲:۰۰");
  assert.equal(scheduleLabel({ scheduled_for: iso(tehran(15, 0)) }, NOW, true), "زمان‌بندی‌شده — شروع امروز ۱۵:۰۰ (به وقتِ تهران)");
  assert.equal(scheduleLabel({ window: "02:00-07:00" }, NOW), "زمان‌بندی‌شده — شروع فردا ۰۲:۰۰");
  assert.equal(scheduleLabel({ window: "02:00-07:00" }, tehran(3)), "", "بازه باز است ⇒ زمان‌بندی‌شده نیست");
  assert.equal(scheduleLabel({ scheduled_for: iso(tehran(1)) }, NOW), "", "زمانش گذشته");
  assert.equal(scheduleLabel({}, NOW), "");
  assert.equal(scheduleLabel({ scheduled_for: null, window: null }, NOW), "");
  assert.equal(scheduleLabel({ scheduled_for: "not a date" }, NOW), "");
  assert.equal(startMoment({ scheduled_for: iso(tehran(1, 0, 1)), window: "02:00-07:00" }, NOW), tehran(2, 0, 1), "هر دو شرط: دیرتر");
});

// ───────────── کارتِ تنظیمِ کلی
check("تنظیمِ کلی از پاسخِ سرور", () => {
  assert.deepEqual(settingsFromServer({ download_mode: "window", download_window: "01:30-06:00" }), { mode: "window", start: "01:30", end: "06:00" });
  assert.deepEqual(settingsFromServer({ download_mode: "now" }), DEFAULT_SETTINGS);
  assert.deepEqual(settingsFromServer(null), DEFAULT_SETTINGS);
  assert.deepEqual(settingsFromServer({ download_mode: "window", download_window: "junk" }), { mode: "window", start: "02:00", end: "07:00" });
  assert.deepEqual(settingsFromServer("x"), DEFAULT_SETTINGS);
});

check("ذخیره: بدنهٔ درخواست و خطاها", () => {
  assert.deepEqual(settingsBody(settings({ mode: "window", start: "1:30", end: "6:00" })), { download_mode: "window", download_window: "01:30-06:00" });
  assert.deepEqual(settingsBody(settings({ mode: "now" })), { download_mode: "now", download_window: "02:00-07:00" });
  assert.deepEqual(settingsBody(settings({ mode: "now", start: "", end: "" })), { download_mode: "now", download_window: "02:00-07:00" }, "با «همین الان» بازهٔ خراب جلوی ذخیره را نمی‌گیرد");
  assert.equal(settingsBody(settings({ mode: "window", start: "", end: "06:00" })), null);
  assert.equal(settingsBody(settings({ mode: "window", start: "05:00", end: "05:00" })), null);
  assert.ok(settingsError(settings({ mode: "window", start: "", end: "06:00" })).includes("کامل"));
  assert.ok(settingsError(settings({ mode: "window", start: "05:00", end: "5:00" })).includes("یکی"));
  assert.equal(settingsError(settings({ mode: "window" })), "");
  assert.equal(settingsError(settings({ mode: "now", start: "", end: "" })), "");
});

check("تغییرِ بی‌اثر دکمهٔ ذخیره را روشن نمی‌کند", () => {
  assert.equal(sameSettings(settings(), settings({ start: "5:00" })), true, "حالتِ «الان»: بازه مهم نیست");
  assert.equal(sameSettings(settings({ mode: "window" }), settings({ mode: "window", start: "2:00" })), true);
  assert.equal(sameSettings(settings({ mode: "window" }), settings({ mode: "window", end: "08:00" })), false);
  assert.equal(sameSettings(settings(), settings({ mode: "window" })), false);
});

check("جملهٔ توضیحِ تنظیم و جملهٔ «چه چیزی فوری است»", () => {
  assert.ok(describeSettings(settings()).includes("شروع می‌شوند"));
  const w = describeSettings(settings({ mode: "window" }));
  assert.ok(w.includes("۰۲:۰۰") && w.includes("۰۷:۰۰") && w.includes("به وقتِ تهران") && w.includes("بازهٔ بعدی"), w);
  assert.ok(IMMEDIATE_NOTE.includes("به‌روزرسانیِ خودِ سرورِ پردازش") && IMMEDIATE_NOTE.includes("فوری"));
});

// ───────────── انتخابگرِ زمانِ یک دانلود
check("گزینه‌ها: چهار حالت، پیش‌فرض «طبقِ تنظیمِ کلی»", () => {
  assert.deepEqual(WHEN_OPTIONS.map((o) => o.mode), ["default", "now", "at", "window"]);
  assert.equal(DEFAULT_WHEN.mode, "default");
  assert.equal(WHEN_OPTIONS[0].label, "طبقِ تنظیمِ کلی");
  assert.ok(WHEN_OPTIONS.some((o) => o.label === "الان"));
  assert.ok(WHEN_OPTIONS.some((o) => o.label.includes("در ساعتِ")));
  assert.ok(WHEN_OPTIONS.some((o) => o.label.includes("بازهٔ شبانه")));
});

check("بدنهٔ when در POST", () => {
  assert.equal(whenBody(choice("default")), undefined);
  assert.deepEqual(whenBody(choice("now")), { mode: "now" });
  assert.deepEqual(whenBody(choice("window")), { mode: "window" });
  assert.deepEqual(whenBody(choice("at", "۳:۳۰")), { mode: "at", time: "03:30" });
});

check("اعتبارِ «در ساعتِ …»", () => {
  assert.equal(whenValid(choice("at", "03:30")), true);
  assert.equal(whenValid(choice("at", "")), false);
  assert.equal(whenValid(choice("at", "25:00")), false);
  assert.equal(whenValid(choice("now", "")), true, "ساعت فقط برای «در ساعتِ» لازم است");
  assert.ok(whenError(choice("at", "x")).includes("۰۳:۳۰"));
  assert.equal(whenError(choice("window")), "");
});

check("جملهٔ «چه موقع شروع می‌شود»", () => {
  assert.equal(whenSummary(choice("now"), settings({ mode: "window" }), NOW), "همین الان شروع می‌شود.");
  assert.equal(whenSummary(choice("default"), settings(), NOW), "طبقِ تنظیمِ کلی: همین الان شروع می‌شود.");
  assert.equal(whenSummary(choice("default"), null, NOW), "طبقِ تنظیمِ کلی: همین الان شروع می‌شود.");
  assert.equal(whenSummary(choice("at", "15:30"), settings(), NOW), "در ساعتِ ۱۵:۳۰ (به وقتِ تهران) شروع می‌شود — امروز ۱۵:۳۰.");
  assert.equal(whenSummary(choice("at", "03:30"), settings(), NOW), "در ساعتِ ۰۳:۳۰ (به وقتِ تهران) شروع می‌شود — فردا ۰۳:۳۰.");
  assert.equal(whenSummary(choice("at", "oops"), settings(), NOW), "ساعت را مثل ۰۳:۳۰ بنویسید.");
  const win = settings({ mode: "window" });
  assert.equal(whenSummary(choice("default"), win, NOW), "طبقِ تنظیمِ کلی: در بازهٔ شبانه (۰۲:۰۰ تا ۰۷:۰۰، به وقتِ تهران) شروع می‌شود — فردا ۰۲:۰۰.");
  assert.equal(whenSummary(choice("window"), settings(), NOW), "در بازهٔ شبانه (۰۲:۰۰ تا ۰۷:۰۰، به وقتِ تهران) شروع می‌شود — فردا ۰۲:۰۰.", "«در بازهٔ شبانه» با تنظیمِ کلیِ «الان» هم از بازه استفاده می‌کند");
  assert.ok(whenSummary(choice("window"), win, tehran(3)).includes("همین حالا شروع می‌شود"));
  assert.equal(whenConfirmLine(choice("now"), null, NOW), "زمانِ شروع: همین الان شروع می‌شود.");
});

// ───────────── کیفیتِ متنِ فارسی
check("متن‌های کارت: بدونِ واژهٔ انگلیسی و بدونِ ارقامِ لاتین", () => {
  const texts: string[] = [
    ...WHEN_OPTIONS.map((o) => o.label), IMMEDIATE_NOTE, describeSettings(settings()), describeSettings(settings({ mode: "window" })),
    settingsError(settings({ mode: "window", start: "", end: "" })), settingsError(settings({ mode: "window", start: "5:00", end: "5:00" })),
    whenError(choice("at", "x")), whenSummary(choice("now"), null, NOW), whenSummary(choice("at", "03:30"), null, NOW),
    whenSummary(choice("window"), null, NOW), whenSummary(choice("default"), settings({ mode: "window" }), NOW),
    scheduleLabel({ window: "02:00-07:00" }, NOW, true), clockLabel(tehran(2, 0, 3), NOW), windowFa("02:00-07:00"),
  ];
  for (const t of texts) {
    assert.ok(!/[A-Za-z]/.test(t), `لاتین در «${t}»`);
    assert.ok(!/[0-9]/.test(t), `رقمِ لاتین در «${t}»`);
  }
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "OK  " : "FAIL"} ${r.name}${r.err ? " — " + r.err : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
