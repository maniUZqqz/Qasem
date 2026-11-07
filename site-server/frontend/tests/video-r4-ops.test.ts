/**
 * آزمونِ ویرایش‌های دورِ چهارم: درج و رویه‌گذاری، سه‌نقطه‌ای، بستنِ فاصله، انتخابِ به عقب، زمان و SRT.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-r4-ops.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-r4-ops.test.mjs
 *   node /tmp/video-r4-ops.test.mjs
 */
import assert from "node:assert/strict";

import type { MediaItem } from "../src/features/content/video/api";
import { AnyClip, MediaClip, Project, clipEnd, clipLength, emptyProject, projectLength } from "../src/features/content/video/manual/model";
import {
  clipFromSource, closeGapAt, cuesOf, fitToFill, idsBefore, insertAt, makeRoom, overwriteAt, replaceSource, parseSrt, parseTime, spanOf, splitAtSourceCuts, srtTime, targetTrack, threePoint, toSrt,
} from "../src/features/content/video/manual/r4ops";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

const item = (over: Partial<MediaItem> = {}): MediaItem => ({
  ref: "video:1", title: "فیلم", kind: "video", source: "", duration: 10, has_audio: true, width: 640, height: 360, url: "/m.mp4", auth: false, proxy: "not_needed", proxy_url: null, ...over,
});
const clip = (id: string, at: number, len: number, over: Partial<MediaClip> = {}): MediaClip => ({
  id, type: "media", ref: "video:1", label: id, kind: "video", at, start: 0, end: len, src: 30, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1, fit: "cover",
  fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, ...over,
});
function proj(video: AnyClip[], audio: AnyClip[] = []): Project {
  const p = emptyProject();
  let v = false;
  let a = false;
  return {
    ...p,
    tracks: p.tracks.map((t) => {
      if (t.kind === "video" && !v) { v = true; return { ...t, clips: video }; }
      if (t.kind === "audio" && !a) { a = true; return { ...t, clips: audio }; }
      return t;
    }),
  };
}
const vt = (p: Project) => p.tracks.find((t) => t.kind === "video")!;
const at_ = (p: Project) => p.tracks.find((t) => t.kind === "audio")!;
const spans = (cs: AnyClip[]) => cs.map((c) => [Math.round(c.at * 100) / 100, Math.round(clipEnd(c) * 100) / 100]);

check("source clip uses the chosen in/out and never exceeds the file", () => {
  const c = clipFromSource(item(), 2, 5);
  assert.deepEqual([c.start, c.end], [2, 5]);
  assert.equal(clipLength(c), 3);
  const late = clipFromSource(item(), 9.99, 50);
  assert.ok(late.end <= 10 && late.end > late.start);
  const still = clipFromSource(item({ kind: "image", duration: 0 }), 0, 4);
  assert.equal(clipLength(still), 4);
});

check("insert splits the clip it lands on and pushes everything after it, on every open track", () => {
  const p = proj([clip("a", 0, 4), clip("b", 4, 4)], [clip("m", 0, 8, { kind: "audio", ref: "audio:1" })]);
  const tid = vt(p).id;
  const q = insertAt(p, tid, clipFromSource(item(), 0, 2), 2);
  assert.deepEqual(spans(vt(q).clips), [[0, 2], [2, 4], [4, 6], [6, 10]]);              // a|new|a-rest|b
  assert.deepEqual(spans(at_(q).clips), [[0, 2], [4, 10]]);                             // audio was cut and pushed too (sync)
  assert.equal(projectLength(q), projectLength(p) + 2);
  assert.equal(new Set(q.tracks.flatMap((t) => t.clips.map((c) => c.id))).size, q.tracks.flatMap((t) => t.clips).length, "ids stay unique");
});

check("insert at the very start and at the very end", () => {
  const p = proj([clip("a", 0, 4)]);
  const s = insertAt(p, vt(p).id, clipFromSource(item(), 0, 1), 0);
  assert.deepEqual(spans(vt(s).clips), [[0, 1], [1, 5]]);
  const e = insertAt(p, vt(p).id, clipFromSource(item(), 0, 1), 4);
  assert.deepEqual(spans(vt(e).clips), [[0, 4], [4, 5]]);
});

check("a locked track is neither a target nor shifted", () => {
  const base = proj([clip("a", 0, 4)], [clip("m", 0, 8, { kind: "audio", ref: "audio:1" })]);
  const p: Project = { ...base, tracks: base.tracks.map((t) => (t.kind === "audio" ? { ...t, locked: true } : t)) };
  const q = insertAt(p, vt(p).id, clipFromSource(item(), 0, 2), 1);
  assert.deepEqual(spans(at_(q).clips), [[0, 8]]);
  assert.equal(insertAt(p, at_(p).id, clipFromSource(item(), 0, 2), 1), p, "inserting into a locked track changes nothing");
  assert.equal(overwriteAt(p, at_(p).id, clipFromSource(item(), 0, 2), 1), p);
});

check("overwrite replaces only the range on the target track and shifts nothing", () => {
  const p = proj([clip("a", 0, 4), clip("b", 4, 4)], [clip("m", 0, 8, { kind: "audio", ref: "audio:1" })]);
  const q = overwriteAt(p, vt(p).id, clipFromSource(item(), 0, 3), 3);
  assert.deepEqual(spans(vt(q).clips), [[0, 3], [3, 6], [6, 8]]);                      // a(0-3) | new(3-6) | b-rest(6-8)
  assert.deepEqual(spans(at_(q).clips), [[0, 8]]);                                     // the audio track is untouched
  assert.equal(projectLength(q), 8);
});

check("overwrite swallows whole clips inside the range", () => {
  const p = proj([clip("a", 0, 2), clip("b", 2, 2), clip("c", 4, 2)]);
  const q = overwriteAt(p, vt(p).id, clipFromSource(item(), 0, 4), 1);
  assert.deepEqual(spans(vt(q).clips), [[0, 1], [1, 5], [5, 6]]);
});

check("three-point edit: the fourth point is computed", () => {
  const base = { srcDuration: 10, playhead: 7 };
  // source in+out, timeline playhead only
  assert.deepEqual(threePoint({ ...base, srcIn: 2, srcOut: 5, tlIn: null, tlOut: null }), { at: 7, srcIn: 2, srcOut: 5, length: 3, mode: "از سرِ پخش" });
  // source in+out + timeline in
  assert.equal(threePoint({ ...base, srcIn: 2, srcOut: 5, tlIn: 12, tlOut: null }).at, 12);
  // source in+out + timeline OUT: the clip ends at the out point
  const r = threePoint({ ...base, srcIn: 2, srcOut: 5, tlIn: null, tlOut: 20 });
  assert.equal(r.at, 17);
  // source in only + timeline in+out: the source out comes from the timeline length
  const t = threePoint({ ...base, srcIn: 1, srcOut: null, tlIn: 4, tlOut: 6.5 });
  assert.deepEqual([t.at, t.srcIn, t.srcOut, t.length], [4, 1, 3.5, 2.5]);
  // nothing set on the source: the whole file
  assert.equal(threePoint({ ...base, srcIn: null, srcOut: null, tlIn: null, tlOut: null }).length, 10);
  // never negative
  assert.equal(threePoint({ ...base, srcIn: 0, srcOut: 5, tlIn: null, tlOut: 2 }).at, 0);
});

check("close gap: only when the gap is common to every open track", () => {
  const p = proj([clip("a", 0, 2), clip("b", 5, 2)], [clip("m", 0, 2, { kind: "audio", ref: "audio:1" }), clip("n", 6, 2, { kind: "audio", ref: "audio:1" })]);
  const r = closeGapAt(p, 3);
  assert.ok(r.closed > 0.9 && r.closed < 4.1, String(r.closed));
  // common gap = [2, 5): audio's next clip starts at 6, video's at 5 → gap closes by 3
  assert.equal(Math.round(r.closed * 100) / 100, 3);
  assert.deepEqual(spans(vt(r.project).clips), [[0, 2], [2, 4]]);
  assert.deepEqual(spans(at_(r.project).clips), [[0, 2], [3, 5]]);               // audio shifted by the same amount: sync is kept
  assert.equal(closeGapAt(p, 1).closed, 0);                                       // inside a clip
  assert.match(closeGapAt(p, 1).reason ?? "", /روی یک قطعه/);
  assert.match(closeGapAt(proj([clip("a", 0, 2)]), 3).reason ?? "", /قطعه‌ای نیست/);
  assert.match(closeGapAt(proj([clip("a", 0, 2), clip("b", 2, 2)]), 2).reason ?? "", /فاصله‌ای نیست/);
});

check("select backward and make room", () => {
  const p = proj([clip("a", 0, 2), clip("b", 2, 2), clip("c", 5, 2)]);
  assert.deepEqual(idsBefore(p, 3).sort(), ["a", "b"]);
  const q = makeRoom(p, 3, 1.5);
  assert.deepEqual(spans(vt(q).clips), [[0, 2], [2, 3], [4.5, 5.5], [6.5, 8.5]]);
  assert.equal(makeRoom(p, 3, 0), p);
  assert.equal(spanOf([{ clip: clip("x", 2, 3) }, { clip: clip("y", 6, 1) }]), 5);
});

check("splitting at detected source cuts respects speed and the used range", () => {
  const p = proj([clip("a", 10, 6, { start: 2, end: 8, speed: 2 })]);          // plays 3 s on the timeline: [10,13], source 2..8
  const r = splitAtSourceCuts(p, "a", [6, 4, 99, 0.5]);                          // unsorted, and two cuts outside the used range
  assert.equal(r.made, 2);
  assert.deepEqual(spans(vt(r.project).clips), [[10, 11], [11, 12], [12, 13]]);
  const pieces = vt(r.project).clips as MediaClip[];
  assert.deepEqual(pieces.map((c) => [c.start, c.end]), [[2, 4], [4, 6], [6, 8]]);
  assert.equal(splitAtSourceCuts(p, "a", []).made, 0);
  assert.equal(splitAtSourceCuts(proj([clip("r", 0, 5, { reverse: true })]), "r", [2]).made, 0, "a reversed clip is left alone");
  assert.equal(splitAtSourceCuts(p, "nope", [3]).made, 0);
  const edge = splitAtSourceCuts(proj([clip("e", 0, 5)]), "e", [0.01, 4.99]);
  assert.equal(edge.made, 0, "a cut at the very edge makes no sliver");
});

check("fit to fill: speed is source length over timeline length, within 0.25-4x", () => {
  const ok = fitToFill(item(), 1, 7, 10, 13) as { clip: MediaClip; speed: number };
  assert.equal(ok.speed, 2);
  assert.equal(clipLength(ok.clip), 3);
  assert.deepEqual([ok.clip.start, ok.clip.end], [1, 7]);
  const slow = fitToFill(item(), 0, 2, 0, 4) as { speed: number };
  assert.equal(slow.speed, 0.5);
  assert.match((fitToFill(item(), 0, 10, 0, 1) as { error: string }).error, /۴ برابر|0\.25|۰٫۲۵/);
  assert.match((fitToFill(item(), 0, 0.05, 0, 3) as { error: string }).error, /کوتاه/);
  assert.match((fitToFill(item({ kind: "audio" }), 0, 2, 0, 2) as { error: string }).error, /فقط برای ویدیو/);
});

check("replace footage keeps place and settings, swaps the file, and follows its linked sound", () => {
  const v = clip("a", 5, 4, { color: { exposure: 0.3 } as MediaClip["color"], transition: { kind: "fade", duration: 0.5 } as MediaClip["transition"], link: "L1" });
  const au = clip("b", 5, 4, { kind: "audio", ref: "video:1", link: "L1" });
  const p = proj([v], [au]);
  const longer = item({ ref: "video:9", title: "تازه", duration: 20 });
  const r = replaceSource(p, "a", longer) as { project: Project; note: string };
  const nv = vt(r.project).clips[0] as MediaClip;
  assert.deepEqual([nv.ref, nv.label, nv.at, nv.start, nv.end, nv.src], ["video:9", "تازه", 5, 0, 4, 20]);
  assert.deepEqual(nv.color, { exposure: 0.3 });
  assert.equal(nv.transition?.kind, "fade");
  assert.equal((at_(r.project).clips[0] as MediaClip).ref, "video:9", "the linked sound moved to the new file too");
  assert.match(r.note, /همان‌طور ماند/);
  const shorter = item({ ref: "video:8", title: "کوتاه", duration: 2.5 });
  const s2 = replaceSource(p, "a", shorter) as { project: Project; note: string };
  const sv = vt(s2.project).clips[0] as MediaClip;
  assert.ok(sv.end <= 2.5 + 1e-6 && sv.end - sv.start > 2.4, `${sv.start}-${sv.end}`);
  assert.match(s2.note, /کوتاه شد/);
  assert.match((replaceSource(p, "a", item({ kind: "image" })) as { error: string }).error, /نوعِ رسانه/);
  assert.match((replaceSource(p, "a", item({ ref: "video:1" })) as { error: string }).error, /از قبل/);
  assert.match((replaceSource(p, "zzz", longer) as { error: string }).error, /انتخاب/);
});

check("target track: the marked one wins, else the first open track of that kind", () => {
  const base = proj([]);
  const v2 = { ...base, tracks: [...base.tracks, { ...base.tracks.find((t) => t.kind === "video")!, id: "v2", target: true }] };
  assert.equal(targetTrack(v2, "video")!.id, "v2");
  assert.equal(targetTrack(base, "video")!.id, vt(base).id);
  const locked = { ...v2, tracks: v2.tracks.map((t) => (t.id === "v2" ? { ...t, locked: true } : t)) };
  assert.equal(targetTrack(locked, "video")!.id, vt(base).id);
});

check("time parsing: Persian digits, colons, decimals", () => {
  assert.equal(parseTime("1:23"), 83);
  assert.equal(parseTime("۱:۲۳"), 83);
  assert.equal(parseTime("1:02:03"), 3723);
  assert.equal(parseTime("83٫5"), 83.5);
  assert.equal(parseTime("45"), 45);
  assert.equal(parseTime(" ۰:۰۵ "), 5);
  assert.equal(parseTime("abc"), null);
  assert.equal(parseTime("1:2:3:4"), null);
  assert.equal(parseTime(""), null);
});

check("SRT round trip keeps Persian text, times and multi-line cues", () => {
  const cues = [{ start: 0.5, end: 2.25, text: "سلام دنیا" }, { start: 3, end: 65.04, text: "خط اول\nخط دوم" }];
  const text = toSrt(cues);
  assert.match(text, /^1\r\n00:00:00,500 --> 00:00:02,250\r\nسلام دنیا\r\n/);
  assert.match(text, /00:00:03,000 --> 00:01:05,040/);
  const back = parseSrt(text);
  assert.equal(back.length, 2);
  assert.deepEqual(back.map((c) => [c.start, c.end, c.text]), [[0.5, 2.25, "سلام دنیا"], [3, 65.04, "خط اول\nخط دوم"]]);
  assert.equal(srtTime(3661.5), "01:01:01,500");
});

check("SRT parsing is forgiving: BOM, dots, tags, missing numbers, junk", () => {
  const raw = "﻿1\n00:00:01.5 --> 00:00:02.0\n<i>سلام</i>\n\n\n00:00:03,000 --> 00:00:04,000\nبدونِ شماره\n\nجمله‌ای بدونِ زمان\n\n3\n00:00:05,000 --> 00:00:04,000\nزمانِ بد\n";
  const c = parseSrt(raw);
  assert.deepEqual(c.map((x) => x.text), ["سلام", "بدونِ شماره"]);
  assert.equal(c[0].start, 1.5);
  assert.deepEqual(parseSrt(""), []);
  assert.deepEqual(parseSrt("هیچ"), []);
});

check("caption cues come from the caption track first, else from all text clips", () => {
  const p = emptyProject();
  const text = (id: string, at: number, t: string) => ({ id, type: "text", text: t, at, duration: 2 }) as unknown as AnyClip;
  const withCaps: Project = { ...p, tracks: p.tracks.map((t) => (t.kind === "text" ? { ...t, caption: true, clips: [text("c2", 4, "دوم"), text("c1", 1, "اول")] } : t)) };
  assert.deepEqual(cuesOf(withCaps).map((c) => c.text), ["اول", "دوم"]);
  assert.deepEqual(cuesOf(p), []);
  const plain: Project = { ...p, tracks: p.tracks.map((t) => (t.kind === "text" ? { ...t, clips: [text("t", 0, "عنوان"), text("e", 3, "  ")] } : t)) };
  assert.deepEqual(cuesOf(plain).map((c) => c.text), ["عنوان"]);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
