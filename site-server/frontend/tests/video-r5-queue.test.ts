/**
 * آزمونِ صفِ چندخروجی و «رندر و جایگزینی».
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-queue.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-queue.test.mjs
 *   node /tmp/video-r5-queue.test.mjs
 */
import assert from "node:assert/strict";

import { MediaClip, Project, clipEnd, emptyProject } from "../src/features/content/video/manual/model";
import { FORMAT_CHOICES, MAX_WAITS, choicesFrom, groupChoices, makeQueue, queueSummary, runQueue } from "../src/features/content/video/manual/r5queue";
import { applyReplace, pollJob, replaceSpec } from "../src/features/content/video/manual/r5replace";

const results: { name: string; ok: boolean; err?: string }[] = [];
const pending: Promise<void>[] = [];
function check(name: string, fn: () => void | Promise<void>) {
  const done = (ok: boolean, err?: unknown) => results.push({ name, ok, err: err ? (err instanceof Error ? `${err.message}\n${err.stack?.split("\n").slice(1, 4).join("\n")}` : String(err)) : undefined });
  try {
    const r = fn();
    if (r && typeof (r as Promise<void>).then === "function") pending.push((r as Promise<void>).then(() => done(true), (e) => done(false, e)));
    else done(true);
  } catch (e) {
    done(false, e);
  }
}

const presets = [
  { key: "reels", title: "ریلز", group: "شبکه‌های اجتماعی" }, { key: "youtube", title: "یوتیوب", group: "شبکه‌های اجتماعی" }, { key: "telegram", title: "تلگرام", group: "پیام‌رسان" },
];
const choices = choicesFrom(presets);
const noWait = () => Promise.resolve();

// ───────────── صفِ چندخروجی
check("گزینه‌ها: پریست‌ها + سه خروجیِ ویژه، گروه‌بندی‌شده", () => {
  assert.equal(choices.length, presets.length + FORMAT_CHOICES.length);
  const g = groupChoices(choices);
  assert.deepEqual(g.map((x) => x.group), ["شبکه‌های اجتماعی", "پیام‌رسان", "خروجی‌های ویژه"]);
  assert.equal(g[0].items.length, 2);
});
check("ساختنِ صف: ترتیبِ انتخاب، گزینهٔ ناشناخته نادیده، فریمِ سرِ پخش در عکس", () => {
  const q = makeQueue(choices, ["preset:telegram", "nope", "fmt:frame", "preset:reels"], 3.456);
  assert.deepEqual(q.map((i) => i.key), ["preset:telegram", "fmt:frame", "preset:reels"]);
  assert.deepEqual(q[0].override, { preset: "telegram", format: "mp4" });
  assert.deepEqual(q[1].override, { format: "frame", frame_t: 3.46 });
  assert.ok(q.every((i) => i.state === "wait"));
});
check("همه با موفقیت فرستاده می‌شوند و به ترتیب", async () => {
  const sent: string[] = [];
  const out = await runQueue(makeQueue(choices, ["preset:reels", "fmt:gif", "fmt:audio"]), async (o) => { sent.push(String(o.preset ?? o.format)); return { ok: true }; }, { wait: noWait });
  assert.deepEqual(sent, ["reels", "gif", "audio"]);
  assert.ok(out.every((i) => i.state === "sent"));
  assert.equal(queueSummary(out), "3 فرستاده شد");
});
check("صفِ پرِ سرور: صبر می‌کند و دوباره تلاش می‌کند، بدونِ از دست دادنِ ترتیب", async () => {
  let calls = 0;
  const waits: number[] = [];
  const out = await runQueue(makeQueue(choices, ["preset:reels", "preset:youtube"]), async () => (++calls <= 2 ? { ok: false, full: true, message: "پر" } : { ok: true }), { wait: async (ms) => { waits.push(ms); } });
  assert.deepEqual(out.map((i) => i.state), ["sent", "sent"]);
  assert.equal(waits.length, 2);
  assert.equal(calls, 4, "دو بار پر، بعد دو موفقیت");
});
check("خطای یک خروجی بقیه را نمی‌ایستاند و دلیلش ثبت می‌شود", async () => {
  const out = await runQueue(makeQueue(choices, ["preset:reels", "preset:youtube", "fmt:gif"]),
    async (o) => (o.preset === "youtube" ? { ok: false, message: "پروژه خالی است" } : { ok: true }), { wait: noWait });
  assert.deepEqual(out.map((i) => i.state), ["sent", "failed", "sent"]);
  assert.equal(out[1].message, "پروژه خالی است");
  assert.match(queueSummary(out), /2 فرستاده شد · 1 ناموفق/);
});
check("استثنا هم به خطای فارسی/متنی تبدیل می‌شود و صف ادامه دارد", async () => {
  const out = await runQueue(makeQueue(choices, ["preset:reels", "fmt:gif"]), async (o) => { if (o.preset) throw new Error("قطع شد"); return { ok: true }; }, { wait: noWait });
  assert.deepEqual(out.map((i) => i.state), ["failed", "sent"]);
  assert.equal(out[0].message, "قطع شد");
});
check("اگر صف همیشه پر بماند بعد از سقفِ انتظار ناموفق می‌شود و بعدی‌ها هنوز تلاش می‌کنند", async () => {
  let n = 0;
  const out = await runQueue(makeQueue(choices, ["preset:reels", "fmt:gif"]), async (o) => (o.preset ? (n++, { ok: false, full: true, message: "پر" }) : { ok: true }), { wait: noWait });
  assert.equal(out[0].state, "failed");
  assert.match(out[0].message ?? "", /مدتِ زیادی پر ماند/);
  assert.equal(n, MAX_WAITS + 1);
  assert.equal(out[1].state, "sent");
});
check("لغو: آنچه فرستاده شده می‌ماند و بقیه «لغو شد» می‌شوند", async () => {
  let stop = false;
  const out = await runQueue(makeQueue(choices, ["preset:reels", "preset:youtube", "fmt:gif"]), async () => { stop = true; return { ok: true }; }, { wait: noWait, cancelled: () => stop });
  assert.deepEqual(out.map((i) => i.state), ["sent", "cancelled", "cancelled"]);
});
check("onChange هر تغییر را گزارش می‌کند و کپیِ جدا می‌دهد", async () => {
  const seen: string[] = [];
  const q = makeQueue(choices, ["fmt:gif"]);
  await runQueue(q, async () => ({ ok: true }), { wait: noWait, onChange: (items) => seen.push(items[0].state) });
  assert.ok(seen.includes("sending") && seen[seen.length - 1] === "sent");
  assert.equal(q[0].state, "wait", "ورودی دست نخورده");
});

// ───────────── رندر و جایگزینی
const clip = (id: string, at: number, len: number, over: Partial<MediaClip> = {}): MediaClip => ({
  id, type: "media", ref: "video:1", label: id, kind: "video", at, start: 0, end: len, src: 30, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1, fit: "cover",
  fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, ...over,
});
function proj(video: MediaClip[], audio: MediaClip[] = []): Project {
  const p = emptyProject();
  let v = false, a = false;
  return { ...p, tracks: p.tracks.map((t) => (t.kind === "video" && !v ? ((v = true), { ...t, clips: video }) : t.kind === "audio" && !a ? ((a = true), { ...t, clips: audio }) : t)) };
}
check("replaceSpec: بازه، پروژهٔ فقط‌انتخاب‌ها و in/out", () => {
  const p = proj([clip("a", 2, 3), clip("b", 5, 4), clip("c", 12, 2)]);
  const s = replaceSpec(p, ["a", "b"]);
  assert.ok(s.ok);
  if (!s.ok) return;
  assert.equal(s.at, 2);
  assert.equal(s.end, 9);
  assert.deepEqual(s.data.inout, { in: 2, out: 9 });
  assert.deepEqual(s.data.tracks.flatMap((t) => t.clips.map((c) => c.id)).sort(), ["a", "b"]);
  assert.ok(s.data.tracks.every((t) => t.clips.length > 0), "ترکِ خالی نمی‌رود");
});
check("replaceSpec: قطعهٔ پیوندی (صدای هم‌راه) هم می‌آید", () => {
  const p = proj([clip("v", 0, 4, { link: "L1" })], [clip("au", 0, 4, { link: "L1", kind: "audio", ref: "video:1" })]);
  const s = replaceSpec(p, ["v"]);
  assert.ok(s.ok);
  if (s.ok) assert.deepEqual(s.ids.sort(), ["au", "v"]);
});
check("replaceSpec: خطاهای فارسیِ روشن", () => {
  const p = proj([clip("a", 0, 4), clip("adj", 0, 4, { adjust: true, ref: "adjust", kind: "image" }), clip("n", 5, 3, { ref: "seq:abc" })]);
  const none = replaceSpec(p, []);
  assert.ok(!none.ok && /انتخاب/.test(none.error));
  const adj = replaceSpec(p, ["a", "adj"]);
  assert.ok(!adj.ok && /لایهٔ تنظیم/.test(adj.error));
  const nested = replaceSpec(p, ["n"]);
  assert.ok(!nested.ok && /توالیِ تودرتو/.test(nested.error));
  const tiny = replaceSpec(proj([clip("t", 0, 0.1)]), ["t"]);
  assert.ok(!tiny.ok && /کوتاه/.test(tiny.error));
});
check("applyReplace: اصل‌ها پاک و فایلِ تازه همان‌جا؛ بقیه دست نخورده", () => {
  const p = proj([clip("a", 2, 3), clip("b", 5, 4), clip("c", 12, 2)]);
  const s = replaceSpec(p, ["a", "b"]);
  assert.ok(s.ok);
  if (!s.ok) return;
  const q = applyReplace(p, s, { ref: "video:99", seconds: 7, has_audio: true })!;
  const all = q.tracks.flatMap((t) => t.clips);
  assert.ok(!all.some((c) => c.id === "a" || c.id === "b"));
  const n = all.find((c) => c.type === "media" && c.ref === "video:99") as MediaClip;
  assert.equal(n.at, 2);
  assert.equal(clipEnd(n), 9);
  assert.equal(n.start, 0);
  assert.equal(n.has_audio, true);
  assert.ok(all.some((c) => c.id === "c"));
});
check("applyReplace: اگر در این فاصله قطعه‌ها عوض شده‌اند چیزی را خراب نمی‌کند", () => {
  const p = proj([clip("a", 2, 3)]);
  const s = replaceSpec(p, ["a"]);
  assert.ok(s.ok);
  if (!s.ok) return;
  assert.equal(applyReplace(proj([clip("other", 2, 3)]), s, { ref: "video:9", seconds: 3, has_audio: true }), null);
});
check("applyReplace: جای ترکِ اصلی پر شد ⇒ ترکِ تصویرِ تازه", () => {
  const p = proj([clip("a", 2, 3)]);
  const s = replaceSpec(p, ["a"]);
  assert.ok(s.ok);
  if (!s.ok) return;
  const withBlocker = proj([clip("a", 2, 3), clip("x", 1, 1.5)]);                   // هم‌پوشانیِ بعد از پاک‌شدنِ a با x و ترکِ ۱ (ثانیهٔ ۱ تا ۲٫۵)
  const spec2 = { ...s, ids: ["a"] };
  const q = applyReplace(withBlocker, spec2, { ref: "video:9", seconds: 3, has_audio: false })!;
  const vids = q.tracks.filter((t) => t.kind === "video");
  const home = vids.find((t) => t.clips.some((c) => c.id === "x"))!;
  assert.ok(!home.clips.some((c) => c.type === "media" && c.ref === "video:9"), "روی ترکِ اشغال نه");
  assert.ok(vids.some((t) => t.clips.some((c) => c.type === "media" && c.ref === "video:9")));
});
check("pollJob: در انتظار، خطا، لغو، تمام‌شده با و بدونِ فایل", () => {
  const job = (state: string, over = {}) => ({ id: 5, state, error: "", label: "x", percent: 40, active: true, ...over });
  assert.deepEqual(pollJob([], {}, 5), { phase: "wait", percent: 0, label: "" });
  assert.deepEqual(pollJob([job("RUNNING")], {}, 5), { phase: "wait", percent: 40, label: "x" });
  assert.deepEqual(pollJob([job("FAILED", { error: "ffmpeg مرد" })], {}, 5), { phase: "failed", message: "ffmpeg مرد" });
  assert.deepEqual(pollJob([job("CANCELLED")], {}, 5), { phase: "failed", message: "رندر لغو شد." });
  const rendered = { ref: "video:7", seconds: 3, has_audio: true };
  assert.deepEqual(pollJob([job("COMPLETED")], { "5": rendered }, 5), { phase: "done", rendered });
  const missing = pollJob([job("COMPLETED")], {}, 5);
  assert.equal(missing.phase, "failed");
});

await Promise.all(pending);
const bad = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "✓" : "✗"} ${r.name}${r.err ? `\n    ${r.err}` : ""}`);
console.log(`\n${results.length - bad.length}/${results.length} passed`);
if (bad.length) process.exit(1);
