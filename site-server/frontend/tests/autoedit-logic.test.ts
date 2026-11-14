/**
 * آزمونِ منطقِ «تدوینِ خودکار»: پاسخ به پرسشِ مکث‌ها، پنجرهٔ شنیدن، شمارش‌ها، و اینکه صدای «قبل/بعد» هرگز روی هم نمی‌افتد.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/autoedit-logic.test.ts --bundle --platform=node --format=esm --outfile=/tmp/autoedit-logic.test.mjs
 *   node /tmp/autoedit-logic.test.mjs
 */
import assert from "node:assert/strict";

import { clock, countsLine, momentLabel, mutedFor, openCount, previewWindow, quickMoments, seedChoices, toAnswers, toggleKey, type SilenceRow } from "../src/features/content/video/autoedit/logic";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

const q = (id: string, start: number, end: number, suggest: SilenceRow["suggest"], extra: Partial<SilenceRow> = {}): SilenceRow => ({
  id, start, end, len: end - start, kind: "dramatic", suggest, reason: "x", before: "", after: "", ...extra,
});

check("پاسخِ آغازینِ هر پرسش پیشنهادِ خودِ سیستم است (یک لمس کافی است)", () => {
  const qs = [q("s1", 5, 6.6, "keep"), q("s2", 12, 13.5, "shorten")];
  assert.deepEqual(seedChoices(qs), { s1: "keep", s2: "shorten" });
  assert.deepEqual(seedChoices(qs, { s1: "cut" }), { s1: "cut", s2: "shorten" });
});

check("بدنهٔ ذخیره فقط جای مکث و تصمیم را می‌فرستد", () => {
  const qs = [q("s1", 5, 6.6, "keep"), q("s2", 12, 13.5, "shorten")];
  assert.deepEqual(toAnswers(qs, { s1: "keep", s2: "cut" }), [{ start: 5, end: 6.6, action: "keep" }, { start: 12, end: 13.5, action: "cut" }]);
  assert.deepEqual(toAnswers(qs, { s1: "keep" }), [{ start: 5, end: 6.6, action: "keep" }]);
});

check("پنجرهٔ شنیدن کمی پیش و پس از مکث است و از ویدیو بیرون نمی‌زند", () => {
  assert.deepEqual(previewWindow({ start: 10, end: 11.5 }, 60), { from: 8.4, to: 13.1 });
  const early = previewWindow({ start: 0.5, end: 1.5 }, 60);
  assert.equal(early.from, 0);
  const late = previewWindow({ start: 58, end: 59.5 }, 60);
  assert.equal(late.to, 60);
  assert.ok(previewWindow({ start: 59.9, end: 60 }, 60).to > previewWindow({ start: 59.9, end: 60 }, 60).from);
});

check("ساعت: دقیقه:ثانیه با یک رقمِ اعشار", () => {
  assert.equal(clock(65.44), "1:05.4");
  assert.equal(clock(5), "0:05.0");
  assert.equal(clock(-3), "0:00.0");
});

check("پرسش‌های بی‌پاسخ شمرده می‌شود", () => {
  assert.equal(openCount([q("a", 1, 2, "keep"), q("b", 3, 4, "cut", { answered: true })]), 1);
});

check("جمع‌بندیِ شمارش‌ها", () => {
  const f = (n: number | string) => String(n);
  assert.equal(countsLine({ cut: 2, shorten: 3, keep: 4 }, 6.54, f), "2 مکثِ بی‌دلیل بریده، 3 مکث کوتاه، 4 مکث دست‌نخورده — جمعاً 6.5 ثانیه کم می‌شود");
  assert.equal(countsLine({ keep: 1 }, 0, f), "1 مکث دست‌نخورده");
});

check("صدا فقط از یکی از دو ویدیوی قبل/بعد پخش می‌شود", () => {
  for (const listen of ["before", "after"] as const) {
    const audible = (["before", "after"] as const).filter((side) => !mutedFor(listen, side));
    assert.deepEqual(audible, [listen], `listen=${listen}: exactly one side may be audible`);
  }
});

check("انتخابِ اندازه‌ها", () => {
  assert.deepEqual(toggleKey(["a"], "b"), ["a", "b"]);
  assert.deepEqual(toggleKey(["a", "b"], "a"), ["b"]);
});

check("برچسبِ لحظهٔ ویدیو برای اسلایدرِ قبل/بعد (دقیقه:ثانیه)", () => {
  assert.equal(momentLabel(0), "0:00");
  assert.equal(momentLabel(12.4), "0:12");
  assert.equal(momentLabel(84), "1:24");
  assert.equal(momentLabel(-5), "0:00");
});

check("لحظه‌های پیشنهادیِ نگاه به نور: پنج لحظه، دور از لبه‌ها، روی نیم‌ثانیه", () => {
  const m = quickMoments(97.7);
  assert.deepEqual(m.map((x) => x.label), ["اول", "یک‌چهارم", "وسط", "سه‌چهارم", "آخر"]);
  for (const x of m) {
    assert.ok(x.t >= 0.2 && x.t <= 97.7 - 0.4, `${x.label} ${x.t} must stay inside the video`);
    assert.equal(x.t * 2, Math.round(x.t * 2), `${x.label} ${x.t} is on a half second`);
  }
  assert.deepEqual(m.map((x) => x.t), [...m.map((x) => x.t)].sort((a, b) => a - b), "in order");
  assert.equal(m[2].t, 49);
  assert.deepEqual(quickMoments(0.5), [], "a clip shorter than a second has nothing to choose between");
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
