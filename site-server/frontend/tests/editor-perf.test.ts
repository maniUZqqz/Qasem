/**
 * آزمونِ روانیِ ویرایشگرِ دستیِ ویدیو (۱۴۰۵/۰۸/۲۳): مقایسهٔ ساختاریِ تاریخچه (jsonEqual) باید عیناً همان JSON.stringify(a) === JSON.stringify(b) باشد،
 * و «انبارِ سرِ پخش» (playhead.ts) درست خبر بدهد.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/editor-perf.test.ts --bundle --platform=node --format=esm --outfile=/tmp/editor-perf.test.mjs
 *   node /tmp/editor-perf.test.mjs
 */
import assert from "node:assert/strict";

import { jsonEqual } from "../src/hooks/useHistory";
import { countRender } from "../src/hooks/perfCount";
import { AnyClip, MediaClip, Project, emptyProject, toApi } from "../src/features/content/video/manual/model";
import { createPlayhead } from "../src/features/content/video/manual/playhead";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

/** همان «حکمِ» قدیمی: دو رشته‌سازی */
const viaStringify = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

// ───────────── مولدِ تصادفیِ قطعی (بدون وابستگی)
let seed = 123456789;
const rnd = () => {
  seed = (seed * 1664525 + 1013904223) >>> 0;
  return seed / 4294967296;
};
const pick = <T,>(xs: T[]): T => xs[Math.floor(rnd() * xs.length)];

function scalar(): unknown {
  return pick<unknown>([
    0, -0, 1, 2, 3.5, -7, NaN, Infinity, -Infinity, "", "a", "b", "0", "null", true, false, null, undefined, () => 1, Symbol("s"),
  ]);
}
function value(depth: number): unknown {
  const r = rnd();
  if (depth <= 0 || r < 0.35) return scalar();
  if (r < 0.6) {
    const n = Math.floor(rnd() * 4);
    return Array.from({ length: n }, () => value(depth - 1));
  }
  if (r < 0.64) return new Date(1700000000000 + Math.floor(rnd() * 3) * 1000);
  if (r < 0.67) {
    const j = pick<unknown>(["x", 1, null]);   // یک بار انتخاب شود؛ toJSON باید قطعی باشد
    return { toJSON: () => j };
  }
  if (r < 0.69) return Object.assign(Object.create(null), { k: value(depth - 1) });
  const o: Record<string, unknown> = {};
  const keys = ["a", "b", "c", "d", "1", "2"];
  const n = Math.floor(rnd() * 4);
  for (let i = 0; i < n; i++) o[pick(keys)] = value(depth - 1);
  return o;
}
/** ‌کپیِ عمیق با تغییرِ احتمالیِ یک نقطه (تا جفت‌های «تقریباً برابر» هم آزموده شوند) و گاهی ترتیبِ کلیدها عوض شود */
function mutate(v: unknown, depth = 0): unknown {
  if (Array.isArray(v)) {
    const out = v.map((x) => mutate(x, depth + 1));
    if (rnd() < 0.08) out.push(scalar());
    return out;
  }
  if (v && typeof v === "object" && Object.getPrototypeOf(v) === Object.prototype) {
    let keys = Object.keys(v);
    if (rnd() < 0.1) keys = [...keys].reverse();
    const out: Record<string, unknown> = {};
    for (const k of keys) out[k] = rnd() < 0.06 ? scalar() : mutate((v as Record<string, unknown>)[k], depth + 1);
    if (rnd() < 0.05) out.zz = scalar();
    return out;
  }
  return rnd() < 0.03 ? scalar() : v;
}

check("jsonEqual ≡ JSON.stringify(a) === JSON.stringify(b): ۲۰۰۰۰ جفتِ تصادفی (برابر، تقریباً برابر، نابرابر)", () => {
  let same = 0;
  for (let i = 0; i < 20000; i++) {
    const a = value(3);
    const b = i % 3 === 0 ? value(3) : mutate(a);
    let expected: boolean;
    try {
      expected = viaStringify(a, b);
    } catch {
      continue; // نمادها/چرخه‌ها در دادهٔ پروژه نیستند
    }
    if (expected) same++;
    assert.equal(jsonEqual(a, b), expected, `i=${i} a=${safe(a)} b=${safe(b)}`);
  }
  assert.ok(same > 2000, `باید جفتِ برابرِ کافی داشته باشیم، فقط ${same}`);
});

function safe(v: unknown): string {
  try {
    return JSON.stringify(v) ?? String(v);
  } catch {
    return String(v);
  }
}

check("لبه‌ها: عدد/null/undefined/ترتیب/آرایه در برابرِ شیء", () => {
  const cases: [unknown, unknown][] = [
    [1, 1], [0, -0], [NaN, null], [NaN, Infinity], [1, "1"], ["a", "a"], [null, undefined], [undefined, undefined], [{}, []], [[], {}],
    [{ a: 1, b: 2 }, { b: 2, a: 1 }], [{ a: 1, b: undefined }, { a: 1 }], [[undefined], [null]], [[undefined], []], [{ a: () => 1 }, {}],
    [{ a: NaN }, { a: null }], [[1, [2, [3]]], [1, [2, [3]]]], [[1, [2, [3]]], [1, [2, [4]]]], [{ a: { b: { c: 1 } } }, { a: { b: { c: 1 } } }],
    [new Date(5), new Date(5)], [new Date(5), new Date(6)], [{ d: new Date(5) }, { d: "1970-01-01T00:00:00.005Z" }],
  ];
  for (const [a, b] of cases) assert.equal(jsonEqual(a, b), viaStringify(a, b), `${safe(a)} vs ${safe(b)}`);
});

// ───────────── پروژهٔ واقعی
function bigProject(clips: number): Project {
  const p = emptyProject();
  const v = p.tracks.find((t) => t.kind === "video")!;
  const list: AnyClip[] = [];
  for (let i = 0; i < clips; i++) {
    list.push({
      id: `c${i}`, type: "media", ref: "video:1", label: `c${i}`, kind: "video", at: i * 2, start: 0, end: 2, src: 30, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1,
      fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, color: { exposure: 0.1, contrast: 5 },
    } as MediaClip);
  }
  return { ...p, tracks: p.tracks.map((t) => (t.id === v.id ? { ...t, clips: list } : t)) };
}

check("پروژه: نسخهٔ بی‌تغییر (کپیِ ساختاری) برابر، تغییرِ واقعی نابرابر، جابه‌جاییِ کلید نابرابر (مثلِ رشته)", () => {
  const p = bigProject(300);
  const same = { ...p, tracks: p.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => ({ ...c })) })) };
  assert.equal(jsonEqual(p, same), true);
  assert.equal(viaStringify(p, same), true);
  const moved = { ...p, tracks: p.tracks.map((t, i) => (i === 0 ? { ...t, clips: t.clips.map((c, k) => (k === 150 ? { ...c, at: c.at + 0.04 } : c)) } : t)) };
  assert.equal(jsonEqual(p, moved), false);
  const reordered = { ...p, tracks: p.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => ({ id: c.id, ...c })) })) };
  assert.equal(jsonEqual(p, reordered), viaStringify(p, reordered));
  const undefinedKey = { ...p, extra: undefined };
  assert.equal(jsonEqual(p, undefinedKey), viaStringify(p, undefinedKey));
  assert.equal(jsonEqual(toApi(p), toApi(same)), true);
});

check("کارایی (اطلاعاتی): ۳۰۰ قطعه، یک قطعه تغییر کرده؛ مقایسهٔ ساختاری در برابرِ دو JSON.stringify", () => {
  const p = bigProject(300);
  const next = { ...p, tracks: p.tracks.map((t, i) => (i === 0 ? { ...t, clips: t.clips.map((c, k) => (k === 150 ? { ...c, at: c.at + 0.04 } : c)) } : t)) };
  const N = 400;
  let t0 = performance.now();
  for (let i = 0; i < N; i++) jsonEqual(next, p);
  const a = (performance.now() - t0) / N;
  t0 = performance.now();
  for (let i = 0; i < N; i++) viaStringify(next, p);
  const b = (performance.now() - t0) / N;
  console.log(`     jsonEqual ${(a * 1000).toFixed(1)} µs  |  دو JSON.stringify ${(b * 1000).toFixed(1)} µs  (×${(b / Math.max(a, 1e-6)).toFixed(0)})`);
  assert.ok(a < b, "مقایسهٔ ساختاری با شاخهٔ مشترک باید سریع‌تر از رشته‌سازیِ دو بارهٔ کلِ پروژه باشد");
});

// ───────────── انبارِ سرِ پخش
check("playhead: get/set/subscribe، مقدارِ برابر خبر نمی‌دهد، لغو اشتراک", () => {
  const ph = createPlayhead(1);
  assert.equal(ph.get(), 1);
  let calls = 0;
  const off = ph.subscribe(() => calls++);
  ph.set(1);
  assert.equal(calls, 0);
  ph.set(2);
  ph.set(2.5);
  assert.equal(calls, 2);
  assert.equal(ph.get(), 2.5);
  off();
  ph.set(9);
  assert.equal(calls, 2);
  assert.equal(ph.get(), 9);
  const a = ph.subscribe(() => calls++);
  const b = ph.subscribe(() => calls++);
  ph.set(10);
  assert.equal(calls, 4);
  a();
  b();
});

check("perfCount: بدونِ window.__nmPerf هیچ کاری نمی‌کند؛ با آن می‌شمارد", () => {
  const g = globalThis as unknown as { window?: { __nmPerf?: Record<string, number> } };
  const had = g.window;
  g.window = {};
  countRender("x");
  assert.equal(g.window.__nmPerf, undefined);
  g.window.__nmPerf = {};
  countRender("x");
  countRender("x", 2);
  assert.equal(g.window.__nmPerf.x, 3);
  if (had === undefined) delete g.window;
  else g.window = had;
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
