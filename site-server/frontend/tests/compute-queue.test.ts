/**
 * آزمونِ منطقِ خالصِ «صفِ پردازش» و نشانِ هدر (بدونِ مرورگر): مدتِ زمان، زمانِ نسبی، رنگِ برچسب، جایگاه، ستونِ انتظار،
 * هشدارِ سرورِ خاموش، پارامترهای درخواست، لغوِ گروهی، خلاصه و نشانِ هدر.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/compute-queue.test.ts --bundle --platform=node --format=esm --outfile=/tmp/compute-queue.test.mjs
 *   node /tmp/compute-queue.test.mjs
 */
import assert from "node:assert/strict";

import {
  KIND_OPTIONS,
  MAX_SIZE,
  PAGE_SIZE,
  TABS,
  absoluteTime,
  badgeCount,
  badgeView,
  buildQuery,
  bulkCancelConfirm,
  bulkCancelPlan,
  cancelConfirm,
  cancelNotice,
  capabilityTotals,
  defaultTab,
  emptyText,
  humanDuration,
  nodeView,
  originLabel,
  parseSummary,
  positionView,
  progressPercent,
  queueWarning,
  relativeTime,
  seenText,
  shortUid,
  statusTone,
  toFa,
  versionText,
  waitView,
  type QueueJob,
  type QueueNode,
  type QueueSummary,
} from "../src/features/tools/compute/queue/model";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const NOW = Date.parse("2026-11-07T10:00:00Z");
const ago = (s: number) => new Date(NOW - s * 1000).toISOString();

const node = (over: Partial<QueueNode> = {}): QueueNode => ({ id: 1, name: "gpu-1", online: false, enabled: true, last_seen: null, agent: null, ...over });
const summary = (over: Partial<QueueSummary> = {}): QueueSummary => ({
  waiting: 0, parked: 0, running: 0, scheduled: 0, failed_24h: 0, nodes_total: 1, nodes_online: 0,
  oldest_wait_s: null, oldest_wait_text: "", text: "صف خالی است", ...over,
});
const job = (over: Partial<QueueJob> = {}): QueueJob => ({
  uid: "0123456789abcdef0123456789abcdef", kind: "photo.edit", kind_label: "ویرایشِ عکس", title: "ویرایشِ عکس", state: "QUEUED", state_label: "در صف",
  group: "waiting", status_text: "در صف", wait_reason: "busy", position: 1, ahead: 0, waiting_s: 90, waiting_text: "۱ دقیقه", waited_s: null, run_s: null,
  created: ago(100), queued_at: ago(100), claimed: null, finished: null, node: null, node_wanted: "", attempts: 0, max_attempts: 3, lost_count: 0,
  progress: 0, message: "", error: "", origin: "panel", store: null, can_cancel: true, can_retry: false, scheduled_for: null, window: "", category: "",
  capability: "photo", parked: false, model: "", ...over,
});

// ───────────── اعداد و مدتِ زمان
check("toFa: ارقام لاتین به فارسی، بقیه دست‌نخورده", () => {
  assert.equal(toFa(1234), "۱۲۳۴");
  assert.equal(toFa("02:00-07:00"), "۰۲:۰۰-۰۷:۰۰");
  assert.equal(toFa("abc"), "abc");
});

check("humanDuration: مرزها مثلِ بک‌اند", () => {
  assert.equal(humanDuration(0), "۰ ثانیه");
  assert.equal(humanDuration(59), "۵۹ ثانیه");
  assert.equal(humanDuration(60), "۱ دقیقه");
  assert.equal(humanDuration(3599), "۵۹ دقیقه");
  assert.equal(humanDuration(3600), "۱ ساعت");
  assert.equal(humanDuration(3660), "۱ ساعت و ۱ دقیقه");
  assert.equal(humanDuration(12000), "۳ ساعت و ۲۰ دقیقه");
  assert.equal(humanDuration(47 * 3600 + 59 * 60), "۴۷ ساعت و ۵۹ دقیقه");
  assert.equal(humanDuration(48 * 3600), "۲ روز");
  assert.equal(humanDuration(5 * 86400 + 3600), "۵ روز");
});

check("humanDuration: ورودیِ خالی/نامعتبر/منفی", () => {
  assert.equal(humanDuration(null), "");
  assert.equal(humanDuration(undefined), "");
  assert.equal(humanDuration(Number.NaN), "");
  assert.equal(humanDuration(Infinity), "");
  assert.equal(humanDuration(-5), "۰ ثانیه");
  assert.equal(humanDuration(12.9), "۱۲ ثانیه");
});

// ───────────── زمانِ نسبی و مطلق
check("relativeTime: پیش / دیگر / همین الان", () => {
  assert.equal(relativeTime(ago(3), NOW), "همین الان");
  assert.equal(relativeTime(ago(30), NOW), "۳۰ ثانیه پیش");
  assert.equal(relativeTime(ago(5 * 60), NOW), "۵ دقیقه پیش");
  assert.equal(relativeTime(ago(3 * 3600 + 1200), NOW), "۳ ساعت پیش");
  assert.equal(relativeTime(ago(2 * 86400), NOW), "۲ روز پیش");
  assert.equal(relativeTime(ago(-600), NOW), "۱۰ دقیقه دیگر");
  assert.equal(relativeTime(ago(-4 * 3600), NOW), "۴ ساعت دیگر");
});

check("relativeTime: ورودیِ خالی یا خراب ⇒ خط تیره", () => {
  assert.equal(relativeTime(null, NOW), "—");
  assert.equal(relativeTime("", NOW), "—");
  assert.equal(relativeTime("not-a-date", NOW), "—");
});

check("absoluteTime: ارقامِ فارسی، خالی ⇒ خالی", () => {
  const s = absoluteTime("2026-11-07T10:00:00Z");
  assert.ok(s.length > 5 && /[۰-۹]/.test(s) && !/[0-9]/.test(s), s);
  assert.equal(absoluteTime(null), "");
  assert.equal(absoluteTime("x"), "");
});

// ───────────── سرورها و هشدار
check("versionText و seenText", () => {
  assert.equal(versionText("2.5"), "نسخهٔ ۲٫۵");
  assert.equal(versionText("v2.5.1"), "نسخهٔ ۲٫۵٫۱");
  assert.equal(versionText("2"), "نسخهٔ ۲");
  assert.equal(versionText(null), "");
  assert.equal(versionText("dev"), "");
  assert.equal(seenText(ago(180), NOW), "آخرین حضور ۳ دقیقه پیش");
  assert.equal(seenText(null, NOW), "هنوز وصل نشده");
});

check("nodeView: روشن / خاموش / غیرفعال", () => {
  assert.equal(nodeView(node({ online: true, last_seen: ago(5), agent: "2.5" }), NOW).state, "online");
  assert.equal(nodeView(node({ online: true }), NOW).label, "روشن");
  assert.equal(nodeView(node({ online: false, last_seen: ago(600) }), NOW).label, "خاموش");
  const off = nodeView(node({ enabled: false, online: true }), NOW);
  assert.equal(off.state, "disabled");
  assert.equal(off.label, "غیرفعال");
  assert.equal(nodeView(node({ agent: "2.5" }), NOW).version, "نسخهٔ ۲٫۵");
});

check("queueWarning: فقط وقتی کار منتظر است و هیچ سرورِ فعالی روشن نیست", () => {
  assert.equal(queueWarning([node()], 0), null);
  assert.equal(queueWarning([node({ online: true })], 5), null);
  assert.equal(queueWarning([node({ online: true }), node({ id: 2, online: false })], 5), null);
  const w = queueWarning([node()], 3);
  assert.ok(w);
  assert.equal(w!.title, "سرورِ پردازش خاموش است؛ ۳ کار منتظرِ روشن شدنِ آن‌اند");
  assert.deepEqual(w!.steps, ["کامپیوترِ گرافیکی را روشن کنید", "فایلِ START.bat را اجرا کنید"]);
  assert.ok(queueWarning([node()], 1)!.title.endsWith("آن است"));
});

check("queueWarning: سرورِ غیرفعال یا بی‌سرور", () => {
  const none = queueWarning([], 2)!;
  assert.ok(none.title.startsWith("هیچ سرورِ پردازشِ فعالی نیست"));
  assert.equal(none.steps.length, 3);
  const disabledOnly = queueWarning([node({ enabled: false, online: true })], 2)!;
  assert.ok(disabledOnly.title.startsWith("هیچ سرورِ پردازشِ فعالی نیست"));
});

// ───────────── تب‌ها و درخواست
check("TABS: شش تب با همان ترتیبِ خواسته", () => {
  assert.deepEqual(TABS.map((t) => t.key), ["waiting", "running", "done", "failed", "cancelled", "all"]);
  assert.deepEqual(TABS.map((t) => t.label), ["منتظر", "در حال اجرا", "تمام‌شده", "ناموفق", "لغوشده", "همه"]);
});

check("defaultTab: منتظر اگر کاری منتظر است، وگرنه همه", () => {
  assert.equal(defaultTab({ waiting: 3 }), "waiting");
  assert.equal(defaultTab({ waiting: 0 }), "all");
  assert.equal(defaultTab(null), "all");
});

check("buildQuery: هر گزینهٔ نوعِ کار", () => {
  const base = { tab: "waiting" as const, q: "", limit: 100 };
  assert.equal(buildQuery({ ...base, kindKey: "" }), "state=waiting&limit=100&offset=0");
  assert.equal(buildQuery({ ...base, kindKey: "photo" }), "state=waiting&kind=photo&limit=100&offset=0");
  assert.equal(buildQuery({ ...base, kindKey: "edit" }), "state=waiting&kind=edit&limit=100&offset=0");
  assert.equal(buildQuery({ ...base, kindKey: "comfy" }), "state=waiting&kind=comfy&limit=100&offset=0");
  assert.equal(buildQuery({ ...base, kindKey: "node" }), "state=waiting&kind=node&limit=100&offset=0");
  assert.equal(buildQuery({ ...base, kindKey: "downloads" }), "state=waiting&category=download&limit=100&offset=0");
  assert.equal(buildQuery({ ...base, kindKey: "نامعتبر" }), "state=waiting&limit=100&offset=0");
});

check("buildQuery: جستجو، سقفِ limit، offset", () => {
  assert.equal(buildQuery({ tab: "all", kindKey: "", q: "  سلام  ", limit: 100 }), "state=all&q=%D8%B3%D9%84%D8%A7%D9%85&limit=100&offset=0");
  assert.ok(buildQuery({ tab: "done", kindKey: "", q: "x".repeat(200), limit: 100 }).includes(`q=${"x".repeat(80)}&`));
  assert.ok(buildQuery({ tab: "all", kindKey: "", q: "", limit: 9999 }).includes(`limit=${MAX_SIZE}`));
  assert.ok(buildQuery({ tab: "all", kindKey: "", q: "", limit: 0 }).includes("limit=1&"));
  assert.ok(buildQuery({ tab: "all", kindKey: "", q: "", limit: 100, offset: 200 }).endsWith("offset=200"));
  assert.equal(PAGE_SIZE, 100);
});

check("KIND_OPTIONS: یکتا، و فقط «دانلودها» category دارد", () => {
  const keys = KIND_OPTIONS.map((o) => o.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.equal(KIND_OPTIONS[0].label, "همهٔ کارها");
  assert.deepEqual(KIND_OPTIONS.filter((o) => o.category).map((o) => o.key), ["downloads"]);
  for (const o of KIND_OPTIONS) assert.ok(!(o.kind && o.category), o.key);
});

check("bulkCancelPlan: بی‌فیلتر، با نوع، و بسته با جستجو یا دانلودها", () => {
  assert.deepEqual(bulkCancelPlan("", ""), { allowed: true, kind: "", hint: "" });
  assert.deepEqual(bulkCancelPlan("voice", ""), { allowed: true, kind: "voice", hint: "" });
  assert.equal(bulkCancelPlan("voice", "abc").allowed, false);
  assert.equal(bulkCancelPlan("", "  ").allowed, true);
  const dl = bulkCancelPlan("downloads", "");
  assert.equal(dl.allowed, false);
  assert.equal(dl.kind, "");
  assert.ok(dl.hint.length > 10);
});

check("متنِ تأیید و پیام‌ها", () => {
  assert.equal(bulkCancelConfirm(7, ""), "همهٔ ۷ کارِ منتظر لغو شود؟ کارهایی که الان در حال پردازش‌اند دست نمی‌خورند.");
  assert.ok(bulkCancelConfirm(2, "voice").includes("از نوعِ «صدا»"));
  assert.ok(cancelConfirm({ title: "تولیدِ تصویر", group: "running" }).includes("در گامِ بعدی متوقف می‌شود"));
  assert.equal(cancelConfirm({ title: "تولیدِ تصویر", group: "waiting" }), "«تولیدِ تصویر» از صف برداشته شود؟");
  assert.equal(cancelNotice({ group: "waiting" }), "کار لغو شد.");
  assert.ok(cancelNotice({ group: "running" }).includes("گامِ بعدی"));
});

check("emptyText: هر تب و حالتِ فیلتر", () => {
  assert.equal(emptyText("waiting", false), "صف خالی است؛ هیچ کاری منتظرِ سرورِ پردازش نیست.");
  assert.equal(emptyText("waiting", true), "کاری با این فیلتر پیدا نشد.");
  for (const t of TABS) assert.ok(emptyText(t.key, false).length > 8, t.key);
});

// ───────────── برچسبِ وضعیت و ستون‌ها
check("statusTone: همهٔ ترکیب‌ها", () => {
  const w = (wait_reason: QueueJob["wait_reason"], ahead = 0) => statusTone({ group: "waiting", wait_reason, ahead });
  assert.equal(w("no_node"), "warn");
  assert.equal(w("pinned_offline"), "warn");
  assert.equal(w("pinned_gone"), "bad");
  assert.equal(w("scheduled"), "info");
  assert.equal(w("window"), "info");
  assert.equal(w("model"), "info");
  assert.equal(w("busy", 0), "brand");
  assert.equal(w("busy", 4), "neutral");
  assert.equal(w("hold"), "neutral");
  assert.equal(w(""), "neutral");
  assert.equal(statusTone({ group: "running", wait_reason: "", ahead: 0 }), "brand");
  assert.equal(statusTone({ group: "done", wait_reason: "", ahead: 0 }), "ok");
  assert.equal(statusTone({ group: "failed", wait_reason: "", ahead: 0 }), "bad");
  assert.equal(statusTone({ group: "cancelled", wait_reason: "", ahead: 0 }), "neutral");
});

check("positionView: با و بدونِ کلِ صف، و غیرِ منتظر", () => {
  assert.deepEqual(positionView(job({ position: 1, ahead: 0 })), { main: "۱", sub: "اولِ صف" });
  assert.deepEqual(positionView(job({ position: 3, ahead: 2 })), { main: "۳", sub: "۲ کار جلوتر" });
  assert.deepEqual(positionView(job({ position: 3, ahead: 2 }), 5), { main: "۳ از ۵", sub: "۲ کار جلوتر" });
  assert.deepEqual(positionView(job({ position: 3, ahead: 2 }), 2), { main: "۳", sub: "۲ کار جلوتر" }, "کلِ کمتر از جایگاه معتبر نیست");
  assert.deepEqual(positionView(job({ group: "done", position: 0 })), { main: "—", sub: "" });
  assert.deepEqual(positionView(job({ group: "waiting", position: 0 })), { main: "—", sub: "" });
});

check("capabilityTotals: فقط منتظرها، به‌ازای هر توانایی", () => {
  const t = capabilityTotals([
    job({ capability: "photo" }), job({ capability: "photo" }), job({ capability: "voice" }),
    job({ capability: "photo", group: "done" }), job({ capability: "voice", group: "running" }),
  ]);
  assert.deepEqual(t, { photo: 2, voice: 1 });
});

check("waitView: منتظر / زمان‌بندی‌شده / در حال اجرا / پایان‌یافته", () => {
  assert.deepEqual(waitView(job({ waiting_text: "۳ ساعت", waiting_s: 10800 }), NOW), { main: "۳ ساعت", sub: "" });
  assert.deepEqual(waitView(job({ waiting_text: "", waiting_s: 125 }), NOW), { main: "۲ دقیقه", sub: "" });
  assert.deepEqual(waitView(job({ waiting_text: "", waiting_s: null }), NOW), { main: "—", sub: "" });
  assert.deepEqual(waitView(job({ wait_reason: "scheduled", waiting_text: "۱ ساعت" }), NOW), { main: "—", sub: "" });
  assert.deepEqual(waitView(job({ wait_reason: "window", waiting_text: "۱ ساعت" }), NOW), { main: "—", sub: "" });
  assert.deepEqual(waitView(job({ group: "running", claimed: ago(240), waited_s: 70 }), NOW), { main: "اجرا: ۴ دقیقه", sub: "انتظار: ۱ دقیقه" });
  assert.deepEqual(waitView(job({ group: "running", claimed: null }), NOW), { main: "—", sub: "" });
  assert.deepEqual(waitView(job({ group: "done", run_s: 330, waited_s: 7200 }), NOW), { main: "اجرا: ۵ دقیقه", sub: "انتظار: ۲ ساعت" });
  assert.deepEqual(waitView(job({ group: "failed", run_s: null, waited_s: null }), NOW), { main: "—", sub: "" });
});

check("originLabel، shortUid، progressPercent", () => {
  assert.equal(originLabel("panel"), "پنل");
  assert.equal(originLabel("voice_models"), "مدل‌های صدا");
  assert.equal(originLabel("something_new"), "something_new");
  assert.equal(originLabel(""), "");
  assert.equal(shortUid("0123456789abcdef"), "01234567");
  assert.equal(progressPercent(0.456), 46);
  assert.equal(progressPercent(2), 100);
  assert.equal(progressPercent(-1), 0);
  assert.equal(progressPercent(Number.NaN), 0);
  assert.equal(progressPercent(null), 0);
});

// ───────────── خلاصه و نشانِ هدر
check("parseSummary: پاسخ‌های خراب ⇒ null", () => {
  assert.equal(parseSummary(null), null);
  assert.equal(parseSummary("<html>"), null);
  assert.equal(parseSummary({}), null);
  assert.equal(parseSummary({ waiting: "3", running: 0 }), null);
  const s = parseSummary({ waiting: 3, running: 1, nodes_online: 1, text: "۳ کار در صف", extra: 1 });
  assert.ok(s);
  assert.equal(s!.waiting, 3);
  assert.equal(s!.parked, 0);
  assert.equal(s!.oldest_wait_s, null);
  assert.equal(parseSummary({ waiting: -4, running: 0 })!.waiting, 0);
});

check("badgeView: پنهان، زرد، خنثی", () => {
  assert.equal(badgeView(null), null);
  assert.equal(badgeView(summary()), null);
  const warn = badgeView(summary({ waiting: 4, nodes_online: 0, oldest_wait_text: "۲ ساعت", text: "۴ کار منتظرِ سرورِ پردازش" }))!;
  assert.equal(warn.tone, "warn");
  assert.equal(warn.waiting, 4);
  assert.equal(warn.title, "۴ کار منتظرِ سرورِ پردازش — قدیمی‌ترینِ آن‌ها ۲ ساعت منتظر مانده");
  const calm = badgeView(summary({ waiting: 2, nodes_online: 1, text: "۲ کار در صف" }))!;
  assert.equal(calm.tone, "neutral");
  assert.equal(calm.title, "۲ کار در صف");
  const run = badgeView(summary({ running: 2, nodes_online: 1 }))!;
  assert.equal(run.tone, "neutral");
  assert.equal(run.waiting, 0);
  assert.equal(run.title, "صف خالی است — ۲ کار در حال پردازش");
  const both = badgeView(summary({ waiting: 1, running: 1, nodes_online: 0, text: "۱ کار منتظرِ سرورِ پردازش" }))!;
  assert.equal(both.tone, "warn");
  assert.ok(both.title.endsWith("۱ کار در حال پردازش"));
});

check("badgeCount: سقفِ ۹۹+", () => {
  assert.equal(badgeCount(0), "۰");
  assert.equal(badgeCount(7), "۷");
  assert.equal(badgeCount(99), "۹۹");
  assert.equal(badgeCount(100), "۹۹+");
});

// ───────────── کیفیتِ متنِ فارسی
check("متن‌های صفحه: بدونِ واژهٔ انگلیسی جز ComfyUI و START.bat", () => {
  const texts: string[] = [
    ...TABS.map((t) => t.label), ...KIND_OPTIONS.map((o) => o.label), ...TABS.map((t) => emptyText(t.key, false)), emptyText("all", true),
    bulkCancelConfirm(3, "photo"), cancelConfirm({ title: "x", group: "running" }), cancelNotice({ group: "running" }),
    queueWarning([node()], 2)!.title, ...queueWarning([node()], 2)!.steps, ...queueWarning([], 2)!.steps,
    versionText("2.5"), seenText(null), nodeView(node()).label, bulkCancelPlan("downloads", "").hint,
  ];
  const allowed = /ComfyUI|START\.bat|x/g;
  for (const t of texts) {
    const rest = t.replace(allowed, "");
    assert.ok(!/[A-Za-z]/.test(rest), `لاتین در «${t}»`);
  }
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "OK  " : "FAIL"} ${r.name}${r.err ? " — " + r.err : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
