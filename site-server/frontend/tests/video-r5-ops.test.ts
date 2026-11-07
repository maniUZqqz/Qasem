/**
 * آزمونِ ویرایش‌های دورِ پنجم: قفلِ همگامی، ویرایش با متنِ گفتار، مسیرِ حرکت، پوشه‌ها و جستجوی رسانه، متنِ عمودی.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r5-ops.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r5-ops.test.mjs
 *   node /tmp/video-r5-ops.test.mjs
 */
import assert from "node:assert/strict";

import type { MediaItem } from "../src/features/content/video/api";
import { AnyClip, MediaClip, Project, TextClip, clipEnd, emptyProject, projectLength } from "../src/features/content/video/manual/model";
import {
  addFolder, assignToFolder, deleteFolder, deleteWordRange, filterBin, foldersOf, motionPoints, pausesBetween, removeMotionPoint, renameFolder,
  rippleDeleteSync, setMotionPoint, spokenWords, syncTracks, verticalText, wordsRange,
} from "../src/features/content/video/manual/r5ops";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

const clip = (id: string, at: number, len: number, over: Partial<MediaClip> = {}): MediaClip => ({
  id, type: "media", ref: "video:1", label: id, kind: "video", at, start: 0, end: len, src: 30, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1, fit: "cover",
  fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, ...over,
});
const text = (id: string, at: number, duration: number, t: string, over: Partial<TextClip> = {}): TextClip => ({ id, type: "text", text: t, at, duration, position: "bottom", size: 6, color: "#fff", box: true, opacity: 1, label: t, ...over });
function proj(video: AnyClip[], audio: AnyClip[] = [], texts: AnyClip[] = [], caption = true): Project {
  const p = emptyProject();
  let v = false, a = false, tx = false;
  return {
    ...p,
    tracks: p.tracks.map((t) => {
      if (t.kind === "video" && !v) { v = true; return { ...t, clips: video }; }
      if (t.kind === "audio" && !a) { a = true; return { ...t, clips: audio }; }
      if (t.kind === "text" && !tx) { tx = true; return { ...t, caption, clips: texts }; }
      return t;
    }),
  };
}
const kind = (p: Project, k: string) => p.tracks.find((t) => t.kind === k)!;
const spans = (cs: AnyClip[]) => cs.map((c) => [Math.round(c.at * 100) / 100, Math.round(clipEnd(c) * 100) / 100]);

check("sync lock: ripple delete moves the locked tracks too, but not unlocked ones", () => {
  const base = proj([clip("a", 0, 2), clip("b", 2, 2), clip("c", 4, 2)], [clip("m", 0, 6, { kind: "audio", ref: "audio:1" }), clip("n", 6, 2, { kind: "audio", ref: "audio:1" })]);
  const locked: Project = { ...base, tracks: base.tracks.map((t) => (t.kind === "audio" ? { ...t, sync: true } : t)) };
  assert.equal(syncTracks(locked), 2);                                                         // the two sound tracks of a new project
  const out = rippleDeleteSync(locked, ["b"]);
  assert.deepEqual(spans(kind(out, "video").clips), [[0, 2], [2, 4]]);                       // the same track closes up as before
  assert.deepEqual(spans(kind(out, "audio").clips), [[0, 6], [4, 6]]);                        // m (0-6) starts before the gap: stays; n (6-8) after it: moves 2 s
  const free = rippleDeleteSync(base, ["b"]);                                                  // nothing locked: audio untouched
  assert.deepEqual(spans(kind(free, "audio").clips), [[0, 6], [6, 8]]);
  assert.equal(projectLength(out), 6);
});

check("sync lock: several deleted clips shift by the sum, a locked track that is also 'locked' (editing lock) is left alone", () => {
  const base = proj([clip("a", 0, 1), clip("b", 1, 1), clip("c", 2, 1), clip("d", 3, 1)], [clip("n", 4, 1, { kind: "audio", ref: "audio:1" })]);
  const both: Project = { ...base, tracks: base.tracks.map((t) => (t.kind === "audio" ? { ...t, sync: true } : t)) };
  const out = rippleDeleteSync(both, ["b", "c"]);
  assert.deepEqual(spans(kind(out, "video").clips), [[0, 1], [1, 2]]);
  assert.deepEqual(spans(kind(out, "audio").clips), [[2, 3]]);
  const frozen: Project = { ...both, tracks: both.tracks.map((t) => (t.kind === "audio" ? { ...t, locked: true } : t)) };
  assert.deepEqual(spans(kind(rippleDeleteSync(frozen, ["b"]), "audio").clips), [[4, 5]]);
});

const caps = () => proj([clip("v", 0, 20)], [], [
  text("t1", 1, 2, "سلام به همه", { words: [{ w: "سلام", s: 0, e: 0.6 }, { w: "به", s: 0.7, e: 1.0 }, { w: "همه", s: 1.1, e: 1.9 }] }),
  text("t2", 6, 2, "این یک نمونه است"),                                                         // no word times: spread evenly
]);

check("spoken words: absolute times from timed captions, even spread for untimed ones, sorted", () => {
  const w = spokenWords(caps());
  assert.deepEqual(w.map((x) => x.text), ["سلام", "به", "همه", "این", "یک", "نمونه", "است"]);
  assert.equal(w[0].start, 1);
  assert.ok(Math.abs(w[2].end - 2.9) < 1e-9);
  assert.ok(Math.abs(w[3].start - 6) < 1e-9 && Math.abs(w[3].end - 6.5) < 1e-9 && Math.abs(w[6].end - 8) < 1e-9);
  assert.equal(spokenWords(proj([clip("v", 0, 5)])).length, 0);
});

check("deleting a word range cuts that stretch from every track and closes the gap, captions included", () => {
  const p = proj([clip("v", 0, 20)], [clip("m", 0, 20, { kind: "audio", ref: "audio:1" })], caps().tracks.find((t) => t.kind === "text")!.clips);
  const w = spokenWords(p);
  const r = deleteWordRange(p, w, 1, 2, true)!;                                                // "به همه": 1.7 .. 2.93
  const len = projectLength(r.project);
  assert.ok(Math.abs(len - (20 - r.seconds)) < 0.3, `${len} vs ${20 - r.seconds}`);
  assert.ok(r.seconds > 1 && r.seconds < 1.5);
  assert.ok(kind(r.project, "video").clips.length >= 2, "the video was split around the cut");
  assert.ok(kind(r.project, "audio").clips.length >= 2, "and so was the sound");
  const left = spokenWords(r.project).map((x) => x.text);
  assert.ok(!left.includes("همه"), `the deleted caption words are gone: ${left}`);
  assert.equal(deleteWordRange(p, w, 0, 99, true), null);
});

check("a range is the span of its first and last word (either click order); empty/oob ranges are refused", () => {
  const w = spokenWords(caps());
  const a = wordsRange(w, 0, 2)!;
  const b = wordsRange(w, 2, 0)!;
  assert.deepEqual(a, b);
  assert.ok(a.a < 1 && a.b > 2.8);
  assert.equal(wordsRange(w, -1, 2), null);
});

check("long pauses between words are found", () => {
  const w = spokenWords(caps());
  const pauses = pausesBetween(w, 0.8);
  assert.equal(pauses.length, 1);
  assert.ok(pauses[0].a > 2.9 && pauses[0].b < 6, JSON.stringify(pauses));
  assert.equal(pausesBetween(w, 99).length, 0);
});

check("motion path: points from px/py keys, set, move and remove", () => {
  let c = clip("a", 0, 6);
  assert.deepEqual(motionPoints(c), []);
  c = { ...c, kf: setMotionPoint(c, 0, 0, 0) };
  c = { ...c, kf: setMotionPoint(c, 3, 0.2, -0.1) };
  c = { ...c, kf: setMotionPoint(c, 5, -0.3, 0.2) };
  const pts = motionPoints(c);
  assert.deepEqual(pts.map((p) => [p.t, p.px, p.py]), [[0, 0, 0], [3, 0.2, -0.1], [5, -0.3, 0.2]]);
  c = { ...c, kf: setMotionPoint(c, 3, 0.4, 0.4) };                                           // moving an existing point replaces it
  assert.equal(motionPoints(c).length, 3);
  assert.deepEqual(motionPoints(c)[1], { t: 3, px: 0.4, py: 0.4, e: "linear" });
  const kf = removeMotionPoint(c, 3)!;
  assert.deepEqual(motionPoints({ ...c, kf }).map((p) => p.t), [0, 5]);
  assert.equal(removeMotionPoint({ ...c, kf: { px: [{ t: 1, v: 0.1, e: "linear" }], py: [{ t: 1, v: 0.1, e: "linear" }] } }, 1), undefined);
});

check("motion path: keys outside the allowed range are clamped by the key setter", () => {
  const c = clip("a", 0, 6);
  const kf = setMotionPoint(c, 1, 9, -9)!;
  assert.equal(kf.px![0].v, 2);
  assert.equal(kf.py![0].v, -2);
});

const items: MediaItem[] = [
  { ref: "video:1", title: "معرفیِ چای سبز", kind: "video", source: "", duration: 10, has_audio: true, width: 1, height: 1, url: "", auth: false, proxy: "not_needed", proxy_url: null },
  { ref: "video:2", title: "كيف چرم (ي و ك عربی)", kind: "video", source: "", duration: 10, has_audio: true, width: 1, height: 1, url: "", auth: false, proxy: "not_needed", proxy_url: null },
  { ref: "audio:3", title: "موسیقیِ شاد", kind: "audio", source: "", duration: 30, has_audio: true, width: 0, height: 0, url: "", auth: true, proxy: "not_needed", proxy_url: null },
];

check("bins: create (unique names), assign, move, rename, delete (media are never deleted)", () => {
  let p = emptyProject();
  const a = addFolder(p, "  پروژهٔ   چای ");
  p = a.project;
  const b = addFolder(p, "پروژهٔ چای");
  p = b.project;
  assert.deepEqual(foldersOf(p).map((f) => f.name), ["پروژهٔ چای", "پروژهٔ چای ۲".replace("۲", "2")]);
  assert.equal(addFolder(p, "").project.bins!.length, 3);
  p = assignToFolder(p, "video:1", a.id);
  p = assignToFolder(p, "video:2", a.id);
  p = assignToFolder(p, "video:1", b.id);                                                      // moving removes it from the first one
  assert.deepEqual(foldersOf(p).map((f) => f.refs), [["video:2"], ["video:1"]]);
  p = assignToFolder(p, "video:1", null);                                                      // «—» = out of every folder
  assert.deepEqual(foldersOf(p).map((f) => f.refs), [["video:2"], []]);
  p = renameFolder(p, a.id, "کارهای مشتری");
  assert.equal(foldersOf(p)[0].name, "کارهای مشتری");
  assert.equal(renameFolder(p, a.id, "   "), p);
  const gone = deleteFolder(p, a.id);
  assert.equal(foldersOf(gone).length, 1);
  assert.equal(items.length, 3);
});

check("media search: Persian/English, Arabic letters, digits, kinds, and folder filter", () => {
  assert.deepEqual(filterBin(items, "چای", null).map((i) => i.ref), ["video:1"]);
  assert.deepEqual(filterBin(items, "کیف", null).map((i) => i.ref), ["video:2"]);                  // Arabic ي/ك in the title still match
  assert.deepEqual(filterBin(items, "موسیقی", null).map((i) => i.ref), ["audio:3"]);
  assert.deepEqual(filterBin(items, "music", null).map((i) => i.ref), ["audio:3"]);
  assert.deepEqual(filterBin(items, "ویدیو", null).map((i) => i.ref), ["video:1", "video:2"]);
  assert.deepEqual(filterBin(items, "  ", null).length, 3);
  assert.equal(filterBin(items, "چای سبز", null).length, 1);
  assert.equal(filterBin(items, "چای چرم", null).length, 0, "every word must match");
  assert.deepEqual(filterBin(items, "", { id: "f", name: "x", refs: ["video:2"] }).map((i) => i.ref), ["video:2"]);
  assert.deepEqual(filterBin(items, "چای", { id: "f", name: "x", refs: ["video:2"] }), []);
});

check("vertical text rotates 90 degrees to the right/left edge and keeps the rest", () => {
  const p = proj([clip("v", 0, 5)], [], [text("t", 0, 3, "برچسب")], false);
  const down = verticalText(p, "t", "right");
  const t1 = kind(down, "text").clips[0] as TextClip;
  assert.deepEqual([t1.rotation, t1.x, t1.y, t1.text], [90, 0.9, 0.5, "برچسب"]);
  const up = kind(verticalText(p, "t", "left"), "text").clips[0] as TextClip;
  assert.deepEqual([up.rotation, up.x], [-90, 0.1]);
  assert.equal(verticalText(p, "nope", "right").tracks.length, p.tracks.length);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
