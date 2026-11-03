/**
 * آزمونِ منطقِ ویرایشگر (بدونِ مرورگر): J/L-cut، پیوندِ نیمه‌های تقسیم، ریپلِ خودکار، قطعِ روی ضرب، توالیِ تودرتو، مولتی‌کم، ردیابی و پختنِ مسیر،
 * هندسهٔ جایگذاری، شکل، LUT.
 *
 *   cd frontend && node_modules/.bin/esbuild tests/video-pro2.test.ts --bundle --platform=node --format=esm --outfile=/tmp/video-pro2.test.mjs
 *   node /tmp/video-pro2.test.mjs
 */
import assert from "node:assert/strict";

import { boxToFrame, frameToBox, frameToSource, placement, sourceToFrame } from "../src/features/content/video/manual/geom";
import { MAX_KEYS, valueAt } from "../src/features/content/video/manual/keyframes";
import { applyLut, parseCube } from "../src/features/content/video/manual/lut";
import {
  AnyClip, MediaClip, Project, Track, clipEnd, clipLength, emptyProject, extractAudio, findClip, isMedia, overlaps, rateStretch, splitAt, splitMany, srcTimeAt, trimEnd, trimStart,
  uid, updateClip, withLinked,
} from "../src/features/content/video/manual/model";
import {
  autoRipple, beatFit, beatSnap, beatSplit, createMulticam, flattenForMedia, jlCut, nestClips, normalizeCuts, removeCutAt, seqLength, setAngleAt, unnestClip, viewOf, writeView,
} from "../src/features/content/video/manual/ops";
import { unitShapes } from "../src/features/content/video/manual/shapes";
import { attachTo, bakeFollowers, simplifySeries, timeOfSource, trackerFromResult } from "../src/features/content/video/manual/tracking";

const results: { name: string; ok: boolean; err?: string }[] = [];
function check(name: string, fn: () => void) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, err: e instanceof Error ? `${e.message}\n${e.stack?.split("\n").slice(1, 4).join("\n")}` : String(e) });
  }
}

// ───────────── کمکی‌ها
const media = (over: Partial<MediaClip> = {}): MediaClip => ({
  id: uid(), type: "media", ref: "video:1", label: "v", kind: "video", at: 0, start: 0, end: 4, src: 10, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1,
  fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: true, effects: [], transition: null, ...over,
});
const withTracks = (clips: MediaClip[][], kinds: Track["kind"][] = ["video", "audio"]): Project => {
  const p = emptyProject();
  p.tracks = kinds.map((k, i) => ({ id: uid("t"), kind: k, name: k + i, muted: false, locked: false, clips: (clips[i] ?? []) as AnyClip[] }));
  return p;
};
const noOverlaps = (p: Project) => p.tracks.every((t) => t.clips.every((a) => t.clips.every((b) => a === b || !(a.at < clipEnd(b) - 0.002 && b.at < clipEnd(a) - 0.002))));
const clipsOf = (p: Project) => p.tracks.flatMap((t) => t.clips).filter(isMedia);

// ───────────── تقسیم و پیوند
check("splitting a linked pair makes TWO pairs, not one group of four", () => {
  const v = media({ at: 0, start: 2, end: 6 });
  let p = withTracks([[v], []]);
  p = extractAudio(p, v.id);
  const aId = clipsOf(p).find((c) => c.kind === "audio")!.id;
  const q = splitMany(p, withLinked(p, [v.id]), 2);
  const all = clipsOf(q);
  assert.equal(all.length, 4);
  const links = new Set(all.map((c) => c.link));
  assert.equal(links.size, 2, "two link ids");
  const left = all.filter((c) => c.at < 1), right = all.filter((c) => c.at >= 1);
  assert.equal(new Set(left.map((c) => c.link)).size, 1);
  assert.equal(new Set(right.map((c) => c.link)).size, 1);
  assert.notEqual(left[0].link, right[0].link);
  assert.equal(withLinked(q, [left[0].id]).length, 2, "dragging the left half no longer drags the right half");
  assert.ok(aId);
});

check("a lone split no longer glues the halves together", () => {
  const v = media({ link: "L1" });
  const p = withTracks([[v], []]);
  const q = splitAt(p, v.id, 2);
  const links = clipsOf(q).map((c) => c.link);
  assert.deepEqual(links.sort(), ["L1", undefined].sort());
});

// ───────────── J / L
function pairAfterSplit() {
  const a = media({ at: 0, start: 1, end: 5 });          // the first shot: source 1..5 (has footage before and after)
  const b = media({ at: 4, start: 2, end: 6, ref: "video:2" });
  let p = withTracks([[a, b], []]);
  p = extractAudio(p, a.id);
  p = extractAudio(p, b.id);
  return { p, a, b };
}

check("J-cut on the second shot moves ITS sound earlier (and onto another audio track so the first shot's sound is not overlapped)", () => {
  const { p, b } = pairAfterSplit();
  const r = jlCut(p, b.id, "J", 0.5);
  assert.ok(r.ok, r.message);
  assert.ok(r.movedToTrack, "the extended sound would have overlapped the first shot's sound on the same track");
  assert.ok(noOverlaps(r.project), "no two clips overlap on one track — the server would refuse the project otherwise");
  const au = clipsOf(r.project).find((c) => c.kind === "audio" && c.ref === "video:2")!;
  assert.equal(au.at, 3.5);
  assert.equal(au.start, 1.5);
  const first = clipsOf(r.project).find((c) => c.kind === "audio" && c.ref === "video:1")!;
  assert.equal(first.at, 0, "the first shot's sound is untouched");
  assert.equal(r.project.tracks.filter((t) => t.kind === "audio").length, 2, "one audio track was added");
});

check("L-cut extends the sound after the picture; at the end of the source it says so", () => {
  const { p, a } = pairAfterSplit();
  const r = jlCut(p, a.id, "L", 0.5);
  assert.ok(r.ok, r.message);
  assert.ok(noOverlaps(r.project));
  const au = clipsOf(r.project).find((c) => c.kind === "audio" && c.ref === "video:1")!;
  assert.equal(au.end, 5.5);
  const last = media({ at: 0, start: 6, end: 10, src: 10 });
  const q = extractAudio(withTracks([[last], []]), last.id);
  const bad = jlCut(q, last.id, "L");
  assert.equal(bad.ok, false);
  assert.match(bad.message ?? "", /بعد از این نقطه/);
});

check("J-cut after a SPLIT picks the sound of the half you selected, not the other half's", () => {
  const v = media({ at: 0, start: 2, end: 8 });
  let p = extractAudio(withTracks([[v], []]), v.id);
  p = splitMany(p, withLinked(p, [v.id]), 3);
  const rightV = clipsOf(p).find((c) => c.kind === "video" && c.at >= 2.9)!;
  const r = jlCut(p, rightV.id, "J", 0.5);
  assert.ok(r.ok, r.message);
  const rightA = clipsOf(r.project).filter((c) => c.kind === "audio").sort((x, y) => x.at - y.at);
  assert.equal(rightA.length, 2);
  assert.equal(rightA[0].at, 0, "the left sound did not move");
  assert.equal(rightA[1].at, 2.5, "the right sound moved 0.5 s earlier");
  assert.ok(noOverlaps(r.project));
});

check("J-cut says why when the source has no footage before the in-point", () => {
  const v = media({ at: 2, start: 0, end: 3 });
  const p = extractAudio(withTracks([[v], []]), v.id);
  const r = jlCut(p, v.id, "J");
  assert.equal(r.ok, false);
  assert.match(r.message ?? "", /پیش از این نقطه/);
  const u = media({ at: 0, start: 1, end: 3 });
  const lone = jlCut(withTracks([[u], []]), u.id, "J");
  assert.equal(lone.ok, false);
  assert.match(lone.message ?? "", /جدا کنید/);
});

check("trimming an edge stops at the neighbour instead of overlapping it", () => {
  const a = media({ at: 0, start: 0, end: 3 }), b = media({ at: 3, start: 0, end: 3 });
  const p = withTracks([[a, b], []]);
  const longer = trimEnd(p, a.id, 5);
  assert.equal(clipEnd(findClip(longer, a.id)!.clip), 3);
  const earlier = trimStart(p, b.id, 1);
  assert.equal(findClip(earlier, b.id)!.clip.at, 3);
  const free = trimEnd(p, a.id, 5, true);
  assert.equal(clipEnd(findClip(free, a.id)!.clip), 5, "free (ripple/roll) edits are not clamped");
});

// ───────────── ریپلِ خودکار
check("slowing a clip pushes the following clips (and their linked audio) later by exactly the growth", () => {
  const a = media({ at: 0, start: 0, end: 2 }), b = media({ at: 2, start: 0, end: 4 }), c = media({ at: 6, start: 0, end: 2 });
  let p = withTracks([[a, b, c], []]);
  p = extractAudio(p, c.id);
  const audioC = clipsOf(p).find((x) => x.kind === "audio")!;
  const before = p;
  const after = updateClip(p, b.id, { speed: 0.5 });
  const q = autoRipple(before, after);
  const nb = findClip(q, b.id)!.clip as MediaClip;
  assert.equal(clipLength(nb), 8);
  assert.equal(findClip(q, c.id)!.clip.at, 10, "was 6, grew by 4");
  assert.equal(findClip(q, audioC.id)!.clip.at, 10, "the linked audio moved with it");
  assert.equal(findClip(q, a.id)!.clip.at, 0, "earlier clips are untouched");
  assert.ok(noOverlaps(q));
});

check("shortening (speeding up) pulls nothing earlier", () => {
  const a = media({ at: 0, start: 0, end: 4 }), b = media({ at: 4, start: 0, end: 2 });
  const p = withTracks([[a, b], []]);
  const q = autoRipple(p, updateClip(p, a.id, { speed: 2 }));
  assert.equal(findClip(q, b.id)!.clip.at, 4);
});

check("a speed ramp and a rate-stretch ripple too; trimming the tail does not; the toggle turns it off", () => {
  const a = media({ at: 0, start: 0, end: 2 }), b = media({ at: 2, start: 0, end: 2 });
  const p = withTracks([[a, b], []]);
  const ramped = autoRipple(p, updateClip(p, a.id, { ramp: [{ p: 0, v: 0.5 }, { p: 1, v: 0.5 }] }));
  assert.ok(findClip(ramped, b.id)!.clip.at > 3.9, "a 0.5x ramp doubles the length");
  const stretched = autoRipple(p, rateStretch(p, a.id, 5));
  assert.ok(Math.abs(findClip(stretched, b.id)!.clip.at - 5) < 0.01);
  const trimmed = autoRipple(p, trimEnd(p, a.id, 2.5, true));
  assert.equal(findClip(trimmed, b.id)!.clip.at, 2, "extending by trim is not a retime");
  const off = autoRipple(p, { ...updateClip(p, a.id, { speed: 0.5 }), auto_ripple: false });
  assert.equal(findClip(off, b.id)!.clip.at, 2);
});

check("the audio of a slowed linked clip follows its speed so they stay in sync", () => {
  const v = media({ at: 0, start: 0, end: 4 });
  let p = extractAudio(withTracks([[v], []]), v.id);
  const audio = clipsOf(p).find((c) => c.kind === "audio")!;
  const q = autoRipple(p, updateClip(p, v.id, { speed: 0.5 }));
  assert.equal((findClip(q, audio.id)!.clip as MediaClip).speed, 0.5);
  p = q;
  assert.ok(Math.abs(clipLength(findClip(p, audio.id)!.clip) - clipLength(findClip(p, v.id)!.clip)) < 0.001);
});

check("a pushed audio partner that runs into an unrelated clip moves that clip too", () => {
  const a = media({ at: 0, start: 0, end: 2 }), b = media({ at: 2, start: 0, end: 2 });
  let p = extractAudio(withTracks([[a, b], []]), b.id);
  const music = media({ at: 4.5, start: 0, end: 3, kind: "audio", ref: "audio:9", has_audio: true });
  p = { ...p, tracks: p.tracks.map((t) => (t.kind === "audio" ? { ...t, clips: [...t.clips, music] } : t)) };
  const q = autoRipple(p, updateClip(p, a.id, { speed: 0.5 }));
  assert.ok(noOverlaps(q), "no overlap anywhere after the cascade");
  assert.ok(findClip(q, music.id)!.clip.at >= 6, "the music was pushed out of the way");
});

// ───────────── ضرب‌ها
check("beat split / fit / snap", () => {
  const v = media({ at: 0, start: 0, end: 8 });
  const p = withTracks([[v], []]);
  const beats = [1, 2, 3, 4, 5, 6, 7];
  const s = beatSplit(p, [v.id], beats, 2);
  assert.equal(s.cuts, 4, "every 2nd beat: 1, 3, 5, 7");
  assert.equal(clipsOf(s.project).length, 5);
  assert.ok(noOverlaps(s.project));
  const a = media({ at: 0, start: 0, end: 3, src: 10 }), b = media({ at: 3, start: 0, end: 3, src: 10 });
  const f = beatFit(withTracks([[a, b], []]), [a.id, b.id], [0, 1, 2, 3, 4], 1);
  assert.equal(f.made, 4);
  const made = clipsOf(f.project).sort((x, y) => x.at - y.at);
  assert.deepEqual(made.map((c) => c.at), [0, 1, 2, 3]);
  assert.ok(made.every((c) => Math.abs(clipLength(c) - 1) < 1e-6), "every clip fills exactly one beat interval");
  assert.equal(made[2].start, 1, "the third interval reuses the first clip from where it stopped");
  // beats that start late (the music's first beat at 0.5 s): the first shot runs from where the clip started to the first beat
  const c0 = media({ at: 0, start: 0, end: 6, src: 10 });
  const late = beatFit(withTracks([[c0], []]), [c0.id], [0.5, 1.5, 2.5], 1);
  const lateMade = clipsOf(late.project).sort((x, y) => x.at - y.at);
  assert.deepEqual(lateMade.map((c) => [c.at, Math.round(clipLength(c) * 100) / 100]), [[0, 0.5], [0.5, 1], [1.5, 1]], "no black gap before the first beat");
  const x = media({ at: 0, start: 0, end: 2.9 }), y = media({ at: 2.9, start: 0, end: 3 });
  const sn = beatSnap(withTracks([[x, y], []]), [3.0], 0.25);
  assert.equal(sn.snapped, 1);
  assert.ok(Math.abs(clipEnd(findClip(sn.project, x.id)!.clip) - 3.0) < 1e-6);
  assert.ok(noOverlaps(sn.project));
});

// ───────────── توالیِ تودرتو
check("nest two clips, edit inside the view, the nested clip's length follows, unnest gives them back", () => {
  const a = media({ at: 1, start: 0, end: 2 }), b = media({ at: 3, start: 0, end: 2, ref: "video:2" });
  const p = withTracks([[a, b], []]);
  const r = nestClips(p, [a.id, b.id], "گروه")!;
  assert.ok(r);
  assert.equal(clipsOf(r.project).filter((c) => !c.ref.startsWith("seq:")).length, 0, "the originals left the main timeline");
  const nested = findClip(r.project, r.clipId)!.clip as MediaClip;
  assert.equal(nested.ref, `seq:${r.seqId}`);
  assert.equal(nested.at, 1);
  assert.equal(nested.end, 4);
  assert.equal(seqLength(r.project.sequences![r.seqId]), 4);
  // edit inside
  const view = viewOf(r.project, [r.seqId]);
  assert.equal(view.tracks.flatMap((t) => t.clips).length, 2);
  const inner = view.tracks.flatMap((t) => t.clips)[1] as MediaClip;
  const edited = writeView(r.project, [r.seqId], updateClip(view, inner.id, { end: 4 }));
  const nested2 = findClip(edited, r.clipId)!.clip as MediaClip;
  assert.equal(nested2.src, 6, "the nested clip's source length follows the sequence");
  assert.equal(nested2.end, 6, "…and its end, because it showed the whole sequence");
  const un = unnestClip(r.project, r.clipId);
  assert.ok(!un.message, un.message);
  assert.equal(clipsOf(un.project).filter((c) => c.ref === "video:1" || c.ref === "video:2").length, 2);
  assert.equal(un.project.sequences && Object.keys(un.project.sequences).length, 0);
  assert.ok(clipsOf(un.project).some((c) => c.ref === "video:1" && Math.abs(c.at - 1) < 1e-6), "times are back where they were");
});

check("flattenForMedia lifts the nested clips' media onto the root timeline with the right source times", () => {
  const a = media({ at: 2, start: 3, end: 7 });
  const p = withTracks([[a], []]);
  const r = nestClips(p, [a.id])!;
  let q = r.project;
  q = updateClip(q, r.clipId, { at: 10, start: 1, end: 3, speed: 2 }); // shows nested 1..3 at 2x from root 10
  const flat = flattenForMedia(q);
  const leaf = clipsOf(flat).find((c) => c.ref === "video:1")!;
  assert.ok(leaf, "the leaf is lifted");
  // nested time 1 = the leaf's source 3 + (1 - 0)*1 = 4; at root time 10 the leaf must show source 4
  assert.ok(Math.abs(leaf.at - 10) < 1e-6, `at ${leaf.at}`);
  assert.ok(Math.abs(leaf.start - 4) < 1e-6, `start ${leaf.start}`);
  assert.ok(Math.abs(leaf.speed - 2) < 1e-6, "played twice as fast");
  assert.ok(Math.abs(clipLength(leaf) - 1) < 1e-6, "2 nested seconds at 2x = 1 root second");
  assert.equal(flattenForMedia(q), flat, "memoised");
  assert.equal(flattenForMedia(p), p, "a project without nested clips is returned as is");
});

// ───────────── مولتی‌کم
check("multicam: offsets, cuts, angle switching and cuts that jump when an angle's footage ends", () => {
  const p = emptyProject();
  const angles = [
    { ref: "video:1", label: "A", duration: 10, has_audio: true },
    { ref: "video:2", label: "B", duration: 6, has_audio: true },
  ];
  const r = createMulticam(p, angles, [0, 2.5], 0, 0)!;
  assert.ok(r);
  const seq = r.project.sequences![r.seqId];
  assert.equal(seqLength(seq), 10);
  assert.equal(seq.multicam!.angles[1].offset, 2.5);
  const video = seq.tracks[0].clips as MediaClip[];
  assert.equal(video.length, 1);
  assert.equal(video[0].ref, "video:1");
  const audio = seq.tracks[1].clips as MediaClip[];
  assert.equal(audio.length, 1, "the sound of angle A plays through");
  const cut = setAngleAt(r.project, r.seqId, 4, 1);
  assert.ok(!cut.message, cut.message);
  const v2 = cut.project.sequences![r.seqId].tracks[0].clips as MediaClip[];
  assert.deepEqual(v2.map((c) => [c.ref, c.at]), [["video:1", 0], ["video:2", 4], ["video:1", 8.5]], "B ends at timeline 8.5: A takes over by itself");
  assert.equal(v2[1].start, 1.5, "angle B at timeline 4 is its second 1.5");
  assert.ok(Math.abs(v2[1].end - 6) < 1e-6, "B ends at its own 6 s = timeline 8.5; after that A takes over");
  const jump = cut.project.sequences![r.seqId].tracks[0].clips as MediaClip[];
  assert.ok(jump.length >= 2);
  const info = cut.project.sequences![r.seqId].multicam!;
  const norm = normalizeCuts(info);
  assert.ok(norm.some((c) => c.angle === 0 && c.t > 8), "when B's footage ends, the cut jumps back to A");
  const bad = setAngleAt(r.project, r.seqId, 1, 1);
  assert.match(bad.message ?? "", /فیلم ندارد/);
  const removed = removeCutAt(cut.project, r.seqId, 1);
  assert.equal((removed.sequences![r.seqId].tracks[0].clips as MediaClip[]).length, 1);
});

// ───────────── هندسه
check("box ⇄ frame mapping round-trips with scale, rotation, flips and offsets", () => {
  const c = media({ x: 0.1, y: 0.2, width: 0.5, height: 0.4, scale: 1.7, rot: 33, px: 0.05, py: -0.03, flip_h: true });
  const fa = 9 / 16;
  const pl = placement(c, 0);
  for (const [u, v] of [[0.5, 0.5], [0.1, 0.9], [0.8, 0.2], [0, 0]]) {
    const [X, Y] = boxToFrame(pl, u, v, fa);
    const [u2, v2] = frameToBox(pl, X, Y, fa);
    assert.ok(Math.abs(u - u2) < 1e-9 && Math.abs(v - v2) < 1e-9, `${u},${v} -> ${u2},${v2}`);
  }
  const [cx, cy] = boxToFrame(pl, 0.5, 0.5, fa);
  assert.ok(Math.abs(cx - (0.1 + 0.25 + 0.05)) < 1e-9 && Math.abs(cy - (0.2 + 0.2 - 0.03)) < 1e-9);
});

check("source ⇄ frame mapping honours cover / contain / stretch", () => {
  const sa = 16 / 9, fa = 9 / 16;
  const c = media({ fit: "cover" });
  const [x, y] = sourceToFrame(c, 0, 0.5, 0.5, fa, sa);
  assert.ok(Math.abs(x - 0.5) < 1e-9 && Math.abs(y - 0.5) < 1e-9);
  const [fx] = sourceToFrame(c, 0, 0.9, 0.5, fa, sa);
  assert.ok(fx > 1, "a 16:9 source covering a 9:16 frame: its right side is cropped away");
  const contain = media({ fit: "contain" });
  const [, cy] = sourceToFrame(contain, 0, 0.5, 0.0, fa, sa);
  assert.ok(cy > 0.3 && cy < 0.45, `top edge of a contained 16:9 picture: ${cy}`);
  const back = frameToSource(c, 0, ...sourceToFrame(c, 0, 0.3, 0.7, fa, sa), fa, sa);
  assert.ok(Math.abs(back[0] - 0.3) < 1e-9 && Math.abs(back[1] - 0.7) < 1e-9);
});

// ───────────── ردیابی
check("simplifySeries keeps shape within the key limit", () => {
  const pts = Array.from({ length: 200 }, (_x, i) => ({ t: i * 0.05, v: 0.5 + 0.3 * Math.sin(i / 20) }));
  const out = simplifySeries(pts, 40);
  assert.ok(out.length <= 40 && out.length > 5);
  assert.equal(out[0].t, 0);
  assert.equal(out[out.length - 1].t, pts[199].t);
  let worst = 0;
  for (const q of pts) {
    for (let i = 0; i + 1 < out.length; i++) {
      if (q.t >= out[i].t && q.t <= out[i + 1].t) {
        const u = (q.t - out[i].t) / Math.max(1e-9, out[i + 1].t - out[i].t);
        worst = Math.max(worst, Math.abs(out[i].v + (out[i + 1].v - out[i].v) * u - q.v));
      }
    }
  }
  assert.ok(worst < 0.2, `worst ${worst}`);
  assert.ok(MAX_KEYS >= 96);
});

check("timeOfSource inverts the clip's time mapping (speed, ramp, reverse)", () => {
  for (const c of [media({ at: 3, start: 1, end: 5, speed: 2 }), media({ at: 3, start: 1, end: 5, reverse: true }), media({ at: 3, start: 1, end: 5, ramp: [{ p: 0, v: 1 }, { p: 1, v: 3 }] })]) {
    for (const s of [1.5, 2.5, 4.9]) {
      const T = timeOfSource(c, s)!;
      assert.ok(T >= c.at - 1e-9 && T <= clipEnd(c) + 1e-9, `T ${T}`);
      assert.ok(Math.abs(srcTimeAt(c, T) - s) < 0.02, `source ${s} -> timeline ${T} -> source ${srcTimeAt(c, T)}`);
    }
  }
  assert.equal(timeOfSource(media({ start: 1, end: 5 }), 6), null, "outside the used range");
});

check("a sticker attached to a tracker follows the tracked point; moving the sticker changes its offset, not the path", () => {
  const tracked = media({ at: 0, start: 0, end: 4, fit: "stretch", width: 1, height: 1 });
  const sticker = media({ at: 0, start: 0, end: 4, kind: "image", ref: "sticker:fire", width: 0.2, height: 0.2, x: 0.4, y: 0.4, fit: "contain", has_audio: false });
  let p: Project = withTracks([[tracked], [sticker]], ["video", "video"]);
  const samples = Array.from({ length: 41 }, (_x, i) => ({ s: i * 0.1, x: 0.2 + i * 0.015, y: 0.5 + 0.1 * Math.sin(i / 5), scale: 1, rot: 0 }));
  const tr = trackerFromResult("ردیاب ۱", "video:1", [1280, 720], { x: 0.1, y: 0.4, w: 0.2, h: 0.2 }, { samples, lost_at: null, engine: "server", s0: 0, s1: 4 });
  p = { ...p, trackers: [tr], format: { ...p.format, width: 720, height: 1280 } };
  const aspect = () => 9 / 16;                                   // the tracked file's aspect (stretch ⇒ irrelevant)
  const at1 = attachTo(p, { clipId: sticker.id }, tr.id, 1.0, aspect);
  assert.ok(!at1.message, at1.message);
  const s1 = findClip(at1.project, sticker.id)!.clip as MediaClip;
  assert.ok(s1.follow && s1.kf?.px && s1.kf?.py, "keys were baked");
  assert.ok(s1.kf!.px!.length >= 2 && s1.kf!.px!.length <= MAX_KEYS, "x is a straight line: two keys are enough");
  assert.ok(s1.kf!.py!.length >= 4 && s1.kf!.py!.length <= MAX_KEYS, "y is a wave: more keys");
  const fa = 720 / 1280;
  // at t=2 the sticker's centre is the tracked point + the offset it had at attach time
  const pt = (t: number) => {
    const i = Math.round(t * 10);
    return [samples[i].x, samples[i].y] as const;
  };
  const centre = (t: number) => [0.4 + 0.1 + valueAt(s1.kf!.px, t, 0), 0.4 + 0.1 + valueAt(s1.kf!.py, t, 0)] as const;
  const off = [centre(1.0)[0] - pt(1.0)[0], centre(1.0)[1] - pt(1.0)[1]];
  for (const t of [0.5, 2, 3.5]) {
    const [cx, cy] = centre(t);
    assert.ok(Math.abs(cx - (pt(t)[0] + off[0])) < 0.01 && Math.abs(cy - (pt(t)[1] + off[1])) < 0.01, `t=${t}: ${cx},${cy} vs ${pt(t)}`);
  }
  void fa;
  // re-baking after moving the TRACKED clip later in time keeps the sticker on it
  const moved = updateClip(at1.project, tracked.id, { at: 1 });
  const rebaked = bakeFollowers(moved, aspect);
  const s2 = findClip(rebaked, sticker.id)!.clip as MediaClip;
  assert.notDeepEqual(s2.kf!.px, s1.kf!.px, "the baked keys changed with the tracked clip's position");
  // a mask follows too
  const masked = updateClip(p, tracked.id, { mask: { shape: "ellipse", cx: 0.2, cy: 0.5, w: 0.2, h: 0.2, feather: 0.05, invert: false } });
  const am = attachTo(masked, { clipId: tracked.id, mask: true }, tr.id, 0, aspect);
  assert.ok(!am.message, am.message);
  const mc = findClip(am.project, tracked.id)!.clip as MediaClip;
  assert.ok(mc.mask?.kx && mc.mask?.ky && mc.mask.follow);
  assert.ok(Math.abs(valueAt(mc.mask!.kx, 3, 0) - (samples[30].x - samples[0].x)) < 0.01, "the mask centre moves with the point (box fractions)");
});

// ───────────── شکل و LUT
check("shape outlines are closed polygons inside the unit box", () => {
  for (const shape of ["rect", "triangle", "star", "polygon", "heart", "arrow", "burst"] as const) {
    const [item] = unitShapes({ shape, fill: "#fff" });
    assert.equal(item.kind, "poly");
    if (item.kind === "poly") {
      assert.ok(item.pts.length >= 3);
      assert.ok(item.pts.every(([x, y]) => x >= -1e-9 && x <= 1 + 1e-9 && y >= -1e-9 && y <= 1 + 1e-9), shape);
    }
  }
  const star = unitShapes({ shape: "star", fill: "#fff", points: 6 })[0];
  assert.equal(star.kind === "poly" ? star.pts.length : 0, 12);
});

check(".cube parse + trilinear apply: identity leaves pixels, an invert LUT inverts, amount blends", () => {
  const cube = (fn: (r: number, g: number, b: number) => number[]) => {
    const n = 5;
    const rows: string[] = [`LUT_3D_SIZE ${n}`];
    for (let b = 0; b < n; b++) for (let g = 0; g < n; g++) for (let r = 0; r < n; r++) rows.push(fn(r / (n - 1), g / (n - 1), b / (n - 1)).join(" "));
    return rows.join("\n");
  };
  const id = parseCube(cube((r, g, b) => [r, g, b]));
  const inv = parseCube(cube((r, g, b) => [1 - r, 1 - g, 1 - b]));
  const px = () => ({ data: new Uint8ClampedArray([200, 32, 32, 255, 10, 250, 128, 255]) }) as unknown as ImageData;
  const a = px();
  applyLut(a, id, 1);
  assert.ok(Math.abs(a.data[0] - 200) <= 1 && Math.abs(a.data[1] - 32) <= 1);
  const b = px();
  applyLut(b, inv, 1);
  assert.ok(Math.abs(b.data[0] - 55) <= 2 && Math.abs(b.data[1] - 223) <= 2 && Math.abs(b.data[5] - 5) <= 2, `${[...b.data]}`);
  const c = px();
  applyLut(c, inv, 0.5);
  assert.ok(Math.abs(c.data[0] - 127.5) <= 2);
  assert.throws(() => parseCube("LUT_1D_SIZE 4\n0 0 0"), /یک‌بعدی/);
  assert.throws(() => parseCube(`LUT_3D_SIZE 2\n0 0 0`), /کامل نیست/);
});

check("overlaps helper agrees with what the checks above rely on", () => {
  const a = media({ at: 0, end: 2 });
  const t = withTracks([[a], []]).tracks[0];
  assert.ok(overlaps(t, 1, 2));
  assert.ok(!overlaps(t, 2, 1));
});

// ───────────── نتیجه
const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.err ? `\n     ${r.err.replace(/\n/g, "\n     ")}` : ""}`);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length) process.exit(1);
