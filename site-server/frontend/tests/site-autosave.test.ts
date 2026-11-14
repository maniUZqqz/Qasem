/**
 * ذخیرهٔ خودکارِ ویرایشگرِ سایت‌ساز: متنی که روی بوم تایپ می‌شود نباید گم شود، شکستِ ذخیره باید دوباره تلاش کند،
 * و بررسیِ «هنوز نمونه است» پیش از انتشار.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/site-autosave.test.ts --bundle --platform=node --format=esm --outfile=/tmp/site-autosave.test.mjs
 *   node /tmp/site-autosave.test.mjs
 */
import assert from "node:assert/strict";

import { EditSession, Timers } from "../src/features/tools/studio/builder/editSession";
import {
  Finding,
  fingerprint,
  groupFindings,
  isPlaceholderKind,
  loadConfirmed,
  needsConfirm,
  rememberConfirmed,
  splitWarnings,
} from "../src/features/tools/studio/builder/publishFindings";
import { KEEPALIVE_LIMIT, RETRY_MS, canKeepalive, chipState, chipText, hasUnsaved, retryDelay } from "../src/features/tools/studio/builder/saveSync";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

/* زمان‌سنجِ جعلی */
function fakeTimers() {
  let t = 0;
  let nextId = 1;
  const pending = new Map<number, { at: number; fn: () => void }>();
  const timers: Timers = {
    set: (fn, ms) => {
      const id = nextId++;
      pending.set(id, { at: t + ms, fn });
      return id;
    },
    clear: (id) => void pending.delete(id),
    now: () => t,
  };
  const advance = (ms: number) => {
    const end = t + ms;
    for (;;) {
      const due = [...pending.entries()].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      t = due[1].at;
      pending.delete(due[0]);
      due[1].fn();
    }
    t = end;
  };
  return { timers, advance, count: () => pending.size };
}

/* ───────── ذخیره و تلاشِ دوباره ───────── */
check("تلاشِ دوباره: ۲، ۵، ۱۵ ثانیه و بعد همان ۱۵", () => {
  assert.deepEqual([...RETRY_MS], [2000, 5000, 15000]);
  assert.deepEqual([0, 1, 2, 3, 4, 50].map(retryDelay), [2000, 5000, 15000, 15000, 15000, 15000]);
  assert.equal(retryDelay(-3), 2000);
  assert.equal(retryDelay(Number.NaN), 2000);
});

check("نشانِ ذخیره: بدترین وضعیتِ سند، نوشتن و پوسته", () => {
  const base = { save: "saved" as const, typing: false, themePending: false, themeFailed: false };
  assert.equal(chipState(base), "saved");
  assert.equal(chipState({ ...base, typing: true }), "saving", "تایپِ هنوز-نفرستاده یعنی در حالِ ذخیره");
  assert.equal(chipState({ ...base, themePending: true }), "saving");
  assert.equal(chipState({ ...base, themeFailed: true }), "error", "شکستِ پوسته/منو دیگر بی‌صدا نیست");
  assert.equal(chipState({ ...base, save: "error", typing: true }), "error");
  assert.equal(chipState({ ...base, save: "conflict", themeFailed: true }), "conflict");
  assert.equal(chipState({ ...base, save: "saving", themeFailed: true }), "error");
});

check("هشدارِ بستنِ زبانه برای هر چیزی جز «ذخیره شد»", () => {
  assert.equal(hasUnsaved("saved"), false);
  for (const s of ["saving", "error", "conflict"] as const) assert.equal(hasUnsaved(s), true, s);
});

check("متنِ نشان: فارسی و با وعدهٔ تلاشِ دوباره فقط وقتی راست است", () => {
  assert.equal(chipText("saved", true, false), "پیش‌نویس ذخیره شد");
  assert.equal(chipText("saved", false, false), "منتشر شده");
  assert.equal(chipText("saving", true, false), "در حالِ ذخیره…");
  assert.equal(chipText("error", true, false), "ذخیره نشد؛ دوباره تلاش می‌شود");
  assert.match(chipText("error", true, true), /پوسته و منو/);
  assert.equal(chipText("conflict", true, false), "جای دیگری هم باز است");
});

check("keepalive: سقفِ بایتی (فارسی دوبایتی است)", () => {
  assert.equal(canKeepalive("{}"), true);
  assert.equal(canKeepalive("x".repeat(KEEPALIVE_LIMIT)), true);
  assert.equal(canKeepalive("x".repeat(KEEPALIVE_LIMIT + 1)), false);
  assert.equal(canKeepalive("ب".repeat(KEEPALIVE_LIMIT / 2)), true);
  assert.equal(canKeepalive("ب".repeat(KEEPALIVE_LIMIT / 2 + 1)), false, "۳۰٬۰۰۱ حرفِ فارسی بیش از ۶۰ کیلوبایت است");
});

/* ───────── ذخیرهٔ حینِ نوشتن ───────── */
check("تایپ: بعد از ۶۰۰ میلی‌ثانیه مکث یک بار به سند می‌رسد", () => {
  const { timers, advance } = fakeTimers();
  let flushed = 0;
  const s = new EditSession(() => (flushed += 1), timers);
  s.input();
  advance(599);
  assert.equal(flushed, 0);
  advance(1);
  assert.equal(flushed, 1);
  advance(10000);
  assert.equal(flushed, 1, "بی‌تایپِ تازه چیزی نمی‌فرستد");
});

check("تایپِ پیوسته: هر حرف زمان‌سنج را عقب می‌برد ولی دست‌کم هر ۵ ثانیه ذخیره می‌شود", () => {
  const { timers, advance } = fakeTimers();
  let flushed = 0;
  const s = new EditSession(() => (flushed += 1), timers);
  for (let i = 0; i < 40; i += 1) {
    s.input();
    advance(200);                        // هر ۲۰۰ میلی‌ثانیه یک حرف: هرگز ۶۰۰ مکث نمی‌شود
  }
  assert.equal(flushed, 1, "۸ ثانیه تایپِ بی‌وقفه ⇒ یک بار در ۵ ثانیه (سقفِ انتظار)، نه هیچ‌وقت");
  advance(600);
  assert.equal(flushed, 2, "و بعد از مکث، باقی‌مانده");
});

check("تایپِ پیوسته: زمانِ انتظار از اولین حرفِ جلسه شمرده می‌شود و بعد از هر ذخیره از نو", () => {
  const { timers, advance } = fakeTimers();
  const at: number[] = [];
  let now = 0;
  const s = new EditSession(() => at.push(now), timers);
  for (let i = 0; i < 60; i += 1) {
    s.input();
    advance(200);
    now += 200;
  }
  assert.ok(at.length >= 2 && at[0] <= 5200, JSON.stringify(at));
});

check("flushNow و cancel", () => {
  const { timers, advance, count } = fakeTimers();
  let flushed = 0;
  const s = new EditSession(() => (flushed += 1), timers);
  s.input();
  assert.equal(s.pending, true);
  s.flushNow();
  assert.equal(flushed, 1);
  assert.equal(s.pending, false);
  assert.equal(count(), 0);
  s.input();
  s.cancel();
  advance(5000);
  assert.equal(flushed, 1, "لغوشده نمی‌فرستد");
});

/* ───────── بررسیِ پیش از انتشار ───────── */
const F = (over: Partial<Finding> = {}): Finding => ({ id: "b1", type: "hero", kind: "sample", text: "متنِ نمونه: «سلام»", target: "page", page: 3, page_title: "خانه", ...over });

check("گروه‌بندی: ترتیبِ ثابت و برچسبِ فارسی، گروهِ خالی نمی‌آید", () => {
  const g = groupFindings([F({ kind: "alt", id: "a" }), F({ kind: "link", id: "l" }), F({ kind: "sample", id: "s1" }), F({ kind: "sample", id: "s2" }), F({ kind: "contact", id: "c" })]);
  assert.deepEqual(g.map((x) => x.kind), ["sample", "contact", "link", "alt"]);
  assert.equal(g[0].items.length, 2);
  assert.equal(g[0].label, "متنِ نمونه");
  assert.deepEqual(groupFindings([]), []);
});

check("هشدارهای رندر: «هنوز نمونه است» از پیشنهادهای عمومی جدا می‌شود", () => {
  const out = splitWarnings([
    { id: "1", type: "hero", text: "الف", kind: "sample" },
    { id: "2", type: "heading", text: "ب", kind: "" },
    { id: "3", type: "image", text: "ج", kind: "media" },
    { id: "4", type: "heading", text: "د" },
  ]);
  assert.deepEqual(out.placeholders.map((w) => w.id), ["1", "3"]);
  assert.deepEqual(out.general.map((w) => w.id), ["2", "4"]);
  assert.equal(isPlaceholderKind("link"), true);
  assert.equal(isPlaceholderKind(""), false);
  assert.equal(isPlaceholderKind("whatever"), false);
});

check("اثرِ انگشتِ یافته: با بلوک، نوع و متن عوض می‌شود؛ با چیزِ دیگر نه", () => {
  const a = F();
  assert.equal(fingerprint(a), fingerprint(F()));
  assert.notEqual(fingerprint(a), fingerprint(F({ text: "متنِ نمونه: «خداحافظ»" })));
  assert.notEqual(fingerprint(a), fingerprint(F({ id: "b2" })));
  assert.notEqual(fingerprint(a), fingerprint(F({ kind: "link" })));
  assert.notEqual(fingerprint(a), fingerprint(F({ page: 4 })));
});

class MemoryStorage {
  m = new Map<string, string>();
  getItem(k: string) { return this.m.get(k) ?? null; }
  setItem(k: string, v: string) { this.m.set(k, v); }
}

check("تأییدِ پیشین: همان موردها دوباره مزاحم نمی‌شوند، موردِ تازه می‌پرسد", () => {
  (globalThis as unknown as { localStorage: unknown }).localStorage = new MemoryStorage();
  const old = [F({ id: "x" }), F({ id: "y", kind: "link", text: "دکمه" })];
  assert.equal(needsConfirm(old, loadConfirmed("shop")).length, 2, "اولین انتشار: همه را می‌پرسد");
  rememberConfirmed("shop", old);
  assert.equal(needsConfirm(old, loadConfirmed("shop")).length, 0);
  const fresh = [...old, F({ id: "z" })];
  assert.deepEqual(needsConfirm(fresh, loadConfirmed("shop")).map((f) => f.id), ["z"], "نمونهٔ تازه‌ای که برگشته دوباره می‌پرسد");
  assert.equal(needsConfirm(old, loadConfirmed("other-site")).length, 2, "تأیید مالِ همان سایت است");
});

check("حافظهٔ مرورگرِ بسته یا خراب: بی‌خطا، فقط دوباره می‌پرسد", () => {
  (globalThis as unknown as { localStorage: unknown }).localStorage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  assert.equal(loadConfirmed("s").size, 0);
  rememberConfirmed("s", [F()]);
  const mem = new MemoryStorage();
  mem.setItem("nbe-confirmed:s", "{not json");
  (globalThis as unknown as { localStorage: unknown }).localStorage = mem;
  assert.equal(loadConfirmed("s").size, 0);
  mem.setItem("nbe-confirmed:s", JSON.stringify([1, "a", null]));
  assert.deepEqual([...loadConfirmed("s")], ["a"]);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
