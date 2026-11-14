/**
 * آزمونِ متنِ «در صف بگذار» در «کیفیت و رندر»ِ ویدیوی سه‌بعدی (بدونِ مرورگر): وقتی کارگرِ GPU آنلاین نیست دکمه و پیام
 * چه می‌گویند، و توستِ بعد از ساختنِ کار.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/up3d-queue.test.ts --bundle --platform=node --format=esm --outfile=/tmp/up3d-queue.test.mjs
 *   node /tmp/up3d-queue.test.mjs
 */
import assert from "node:assert/strict";

import { estimateText, queueNote, queuedText } from "../src/features/tools/up3d/queueText";
import type { Estimate, Job } from "../src/features/tools/up3d/types";

const results: { name: string; ok: boolean; err?: string }[] = [];
function test(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? e.message : String(e) });
  }
}

const base: Estimate = { frames: 240, seconds: 0, worker: null, sec_per_frame: 0, available: false };
const node = (over: Partial<NonNullable<Estimate["gpu_nodes"]>[number]> = {}) => ({ name: "DESKTOP-EAFBTGQ", online: false, via_queue: false, install: null, ...over });
const job = (waiting: Partial<NonNullable<Job["waiting"]>> | null): Job => ({ id: 36, waiting: waiting ? { needs_gpu: true, allow_cpu: false, online: [], eligible: [], ...waiting } : null }) as unknown as Job;

test("بدونِ کارگر: تخمین می‌گوید در صف می‌ماند، نه بن‌بست", () => {
  const t = estimateText({ ...base });
  assert.equal(t.tone, "warn");
  assert.match(t.text, /در صف می‌ماند/);
});

test("کارگرِ GPU نیست ولی CPU هست: صف اول، CPU دومین راه", () => {
  const t = estimateText({ ...base, cpu_seconds: 39600 });
  assert.equal(t.tone, "warn");
  assert.match(t.text, /در صف می‌ماند/);
  assert.match(t.text, /CPU/);
});

test("کارگر آماده است: همان جملهٔ قدیمی با نامِ کارگر", () => {
  const t = estimateText({ ...base, available: true, seconds: 600, worker: "gpu-1" });
  assert.equal(t.tone, "ok");
  assert.match(t.text, /gpu-1/);
});

test("سرورِ پردازش آفلاین: می‌گوید خودش به‌روز می‌شود و Blender را نصب می‌کند و کاری از مالک لازم نیست", () => {
  const s = queueNote({ ...base, gpu_nodes: [node()] });
  assert.match(s, /DESKTOP-EAFBTGQ آفلاین است/);
  assert.match(s, /به‌روز/);
  assert.match(s, /Blender را نصب/);
  assert.match(s, /کاری از شما لازم نیست/);
});

test("سرورِ آنلاین با عاملِ قدیمی: در حالِ به‌روزرسانیِ خودکار", () => {
  assert.match(queueNote({ ...base, gpu_nodes: [node({ online: true })] }), /در حالِ به‌روزرسانیِ خودکار/);
});

test("عاملِ تازه، Blender در حالِ نصب: منتظرِ نصب", () => {
  assert.match(queueNote({ ...base, gpu_nodes: [node({ online: true, via_queue: true, install: "installing" })] }), /در حالِ نصبِ خودکار/);
  assert.match(queueNote({ ...base, gpu_nodes: [node({ online: true, via_queue: true, install: "ready" })] }), /آماده است/);
});

test("بدونِ هیچ سرورِ پردازشِ ثبت‌شده: جملهٔ عمومی", () => {
  assert.match(queueNote({ ...base }), /کارگرِ مناسب آنلاین شد خودکار اجرا می‌شود/);
  assert.match(queueNote(undefined), /صفِ ماندگار/);
});

test("توستِ کار: کارگر آماده / در صفِ سرور / منتظرِ سرورِ خاموش / منتظرِ کارگر", () => {
  assert.equal(queuedText(job(null)), "کار #۳۶ در صف گذاشته شد");
  assert.equal(queuedText(job({ eligible: ["gpu-1"] })), "کار #۳۶ در صف گذاشته شد");
  assert.match(queuedText(job({ node_queue: ["DESKTOP-EAFBTGQ"] })), /در صفِ سرورِ پردازشِ DESKTOP-EAFBTGQ است و خودکار اجرا می‌شود/);
  const off = queuedText(job({ gpu_nodes: [{ id: 5, name: "DESKTOP-EAFBTGQ", online: false } as never] }));
  assert.match(off, /روشن شد خودکار اجرا می‌شود/);
  assert.doesNotMatch(off, /ولی کارگرِ مناسبی آنلاین نیست/);
  assert.match(queuedText(job({})), /کارگری آنلاین شد خودکار اجرا می‌شود/);
});

test("درست بعد از ساخت (هنوز بی‌waiting): توست از تخمین می‌گوید منتظرِ چیست", () => {
  const t = queuedText(job(null), { ...base, gpu_nodes: [node()] });
  assert.match(t, /^کار #۳۶ در صفِ انتظار گذاشته شد؛ /);
  assert.match(t, /DESKTOP-EAFBTGQ آفلاین است/);
  assert.match(t, /کاری از شما لازم نیست/);
  assert.equal(queuedText(job(null), { ...base, available: true, worker: "gpu-1" }), "کار #۳۶ در صف گذاشته شد");
});

test("هیچ پیامی لاتینِ بی‌دلیل ندارد (فقط نامِ سرور، Blender و CPU)", () => {
  const texts = [
    estimateText({ ...base }).text,
    estimateText({ ...base, cpu_seconds: 100 }).text,
    queueNote({ ...base, gpu_nodes: [node(), node({ name: "x", online: true }), node({ name: "y", online: true, via_queue: true, install: "installing" })] }),
  ];
  const allowed = /DESKTOP-EAFBTGQ|Blender|CPU|GPU|[xy]\b/g;
  for (const t of texts) assert.ok(!/[A-Za-z]/.test(t.replace(allowed, "")), `لاتین در «${t}»`);
});

const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "OK  " : "FAIL"} ${r.name}${r.err ? " — " + r.err : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
process.exit(bad.length ? 1 : 0);
