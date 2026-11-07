/**
 * ویرایش‌های دورِ چهارم (تابع‌های خالص روی «پروژه»): درج و رویه‌گذاری از مانیتورِ منبع، ویرایشِ سه‌نقطه‌ای،
 * بستنِ فاصله، انتخابِ به عقب، چسباندنِ درج، زیرنویس SRT، و تبدیلِ زمان. بدونِ React؛ با آزمونِ خودکار (tests/video-r4-ops.test.ts).
 */
import type { MediaItem } from "../api";
import { AnyClip, MediaClip, Project, TextClip, Track, clipEnd, clipLength, deleteClips, newMediaClip, splitMany, uid } from "./model";

const EPS = 0.02;
const sorted = (cs: AnyClip[]): AnyClip[] => [...cs].sort((a, b) => a.at - b.at);
const mapTracks = (p: Project, f: (t: Track) => Track): Project => ({ ...p, tracks: p.tracks.map(f) });

/** قطعه‌هایی از ترک‌های داده‌شده که روی لحظهٔ t افتاده‌اند را در همان لحظه می‌برد */
export function cutAt(p: Project, trackIds: string[], t: number): Project {
  const ids = p.tracks.filter((tr) => trackIds.includes(tr.id)).flatMap((tr) => tr.clips.filter((c) => c.at < t - EPS && clipEnd(c) > t + EPS).map((c) => c.id));
  return ids.length ? splitMany(p, ids, t) : p;
}

const unlocked = (p: Project) => p.tracks.filter((t) => !t.locked).map((t) => t.id);

/** ترکی که ویرایش‌های «درج/رویه‌گذاری» روی آن می‌نشینند: ترکِ هدف (◎) از همان نوع، وگرنه اولین ترکِ بازِ آن نوع */
export function targetTrack(p: Project, kind: Track["kind"]): Track | undefined {
  return p.tracks.find((t) => t.kind === kind && t.target && !t.locked) ?? p.tracks.find((t) => t.kind === kind && !t.locked);
}

/** Insert: همهٔ ترک‌های باز از لحظهٔ `at` به اندازهٔ طولِ قطعه جلو می‌روند و قطعه در خالیِ ایجادشده می‌نشیند. */
export function insertAt(p: Project, trackId: string, clip: AnyClip, at: number): Project {
  const target = p.tracks.find((t) => t.id === trackId);
  if (!target || target.locked) return p;
  const len = clipLength(clip);
  const t0 = Math.max(0, at);
  const affected = unlocked(p);
  let q = cutAt(p, affected, t0);
  q = mapTracks(q, (tr) => (tr.locked ? tr : { ...tr, clips: tr.clips.map((c) => (c.at >= t0 - EPS ? ({ ...c, at: c.at + len } as AnyClip) : c)) }));
  const placed = { ...clip, id: uid(), at: t0, link: undefined } as AnyClip;
  return mapTracks(q, (tr) => (tr.id === trackId ? { ...tr, clips: sorted([...tr.clips, placed]) } : tr));
}

/** Overwrite: بازهٔ [at, at+طول) فقط روی ترکِ هدف پاک می‌شود و قطعه جایش می‌نشیند؛ بقیه جابه‌جا نمی‌شوند. */
export function overwriteAt(p: Project, trackId: string, clip: AnyClip, at: number): Project {
  const target = p.tracks.find((t) => t.id === trackId);
  if (!target || target.locked) return p;
  const len = clipLength(clip);
  const a = Math.max(0, at);
  const b = a + len;
  let q = cutAt(p, [trackId], a);
  q = cutAt(q, [trackId], b);
  const ids = q.tracks.find((t) => t.id === trackId)!.clips.filter((c) => c.at >= a - EPS && clipEnd(c) <= b + EPS).map((c) => c.id);
  q = ids.length ? deleteClips(q, ids, false) : q;
  const placed = { ...clip, id: uid(), at: a, link: undefined } as AnyClip;
  return mapTracks(q, (tr) => (tr.id === trackId ? { ...tr, clips: sorted([...tr.clips, placed]) } : tr));
}

/** قطعه‌ای از یک رسانه با بازهٔ [srcIn, srcOut] از خودِ منبع */
export function clipFromSource(item: MediaItem, srcIn: number, srcOut: number): MediaClip {
  const base = newMediaClip(item, 0);
  const dur = item.kind === "image" ? Math.max(0.5, srcOut - srcIn) : item.duration;
  if (item.kind === "image") return { ...base, start: 0, end: Math.max(0.5, srcOut - srcIn) };
  const s = Math.max(0, Math.min(srcIn, Math.max(0, dur - 0.1)));
  const e = Math.max(s + 0.1, Math.min(srcOut, dur));
  return { ...base, start: s, end: e };
}

/** Fit to fill: بازهٔ منبع [srcIn, srcOut] با تغییرِ سرعت دقیقاً بازهٔ تایم‌لاین [tlIn, tlOut] را پر می‌کند. */
export function fitToFill(item: MediaItem, srcIn: number, srcOut: number, tlIn: number, tlOut: number): { clip: MediaClip; speed: number } | { error: string } {
  const srcLen = srcOut - srcIn;
  const tlLen = tlOut - tlIn;
  if (item.kind === "audio" || item.kind === "image") return { error: "پر کردنِ بازه فقط برای ویدیو است." };
  if (srcLen < 0.1 || tlLen < 0.1) return { error: "بازهٔ منبع یا تایم‌لاین خیلی کوتاه است." };
  const speed = srcLen / tlLen;
  if (speed < 0.25 || speed > 4) return { error: `برای پر کردنِ این بازه سرعت باید ${Math.round(speed * 100) / 100} برابر شود؛ فقط ۰٫۲۵ تا ۴ برابر ممکن است. بازهٔ منبع یا تایم‌لاین را عوض کنید.` };
  return { clip: { ...clipFromSource(item, srcIn, srcOut), speed: Math.round(speed * 10000) / 10000 }, speed };
}

/**
 * جایگزینی فیلم (Replace footage): قطعه همان جا و همان تنظیم‌ها (رنگ، حرکت، افکت، گذار) را نگه می‌دارد و فقط رسانه‌اش عوض می‌شود.
 * نوعِ رسانه باید یکی باشد. صدای پیوندیِ همان فیلم هم عوض می‌شود. اگر فیلمِ تازه کوتاه‌تر باشد قطعه کوتاه می‌شود.
 */
export function replaceSource(p: Project, clipId: string, item: MediaItem): { project: Project; note: string } | { error: string } {
  const found = p.tracks.flatMap((t) => t.clips).find((c) => c.id === clipId);
  if (!found || found.type !== "media") return { error: "اول یک ویدیو، عکس یا صدا را روی تایم‌لاین انتخاب کنید." };
  if (found.kind !== item.kind) return { error: `نوعِ رسانه باید یکی باشد (این قطعه ${found.kind === "video" ? "ویدیو" : found.kind === "audio" ? "صدا" : "عکس"} است).` };
  if (found.ref === item.ref) return { error: "همین رسانه از قبل روی این قطعه است." };
  const oldRef = found.ref;
  const link = found.link;
  let shortened = false;
  const swap = (c: AnyClip): AnyClip => {
    if (c.type !== "media") return c;
    const dur = item.kind === "image" ? 0 : Math.max(0.1, item.duration || 0.1);
    let start = c.start;
    let end = c.end;
    if (item.kind !== "image") {
      if (end > dur + 0.01) {
        const len = Math.min(dur, c.end - c.start);
        start = Math.max(0, Math.min(c.start, dur - len));
        end = start + len;
        shortened = true;
      }
    }
    return { ...c, ref: item.ref, label: item.title, src: item.kind === "image" ? 0 : dur, start, end, has_audio: item.has_audio } as MediaClip;
  };
  const project = mapTracks(p, (t) => ({
    ...t,
    clips: t.clips.map((c) => (c.id === clipId || (link && c.type === "media" && c.ref === oldRef && c.link === link) ? swap(c) : c)),
  }));
  return { project, note: shortened ? "فیلمِ تازه کوتاه‌تر است؛ قطعه به اندازهٔ آن کوتاه شد." : "رسانه عوض شد؛ رنگ، حرکت، افکت و گذارِ قطعه همان‌طور ماند." };
}

export type ThreePointInput = {
  /** ورودی/خروجیِ منبع؛ null = از ابتدا / تا انتها */
  srcIn: number | null;
  srcOut: number | null;
  srcDuration: number;
  /** ورودی/خروجیِ تایم‌لاین؛ هر دو null = سرِ پخش */
  tlIn: number | null;
  tlOut: number | null;
  playhead: number;
};
export type ThreePointResult = { at: number; srcIn: number; srcOut: number; length: number; mode: string };

/** ویرایشِ سه‌نقطه‌ای: از هر سه نقطه‌ای که داده شد، نقطهٔ چهارم حساب می‌شود (طولِ منبع و تایم‌لاین یکی است). */
export function threePoint(i: ThreePointInput): ThreePointResult {
  const sIn = Math.max(0, i.srcIn ?? 0);
  const sOut = Math.max(sIn + 0.1, Math.min(i.srcOut ?? i.srcDuration, i.srcDuration || Infinity));
  if (i.tlIn !== null && i.tlOut !== null && i.tlOut > i.tlIn + 0.05) {
    // دو نقطه روی تایم‌لاین: طول از تایم‌لاین می‌آید و خروجیِ منبع حساب می‌شود
    const length = i.tlOut - i.tlIn;
    return { at: i.tlIn, srcIn: sIn, srcOut: Math.min(i.srcDuration || Infinity, sIn + length), length, mode: "ورودی و خروجیِ تایم‌لاین" };
  }
  const length = sOut - sIn;
  if (i.tlIn !== null) return { at: i.tlIn, srcIn: sIn, srcOut: sOut, length, mode: "از ورودیِ تایم‌لاین" };
  if (i.tlOut !== null) return { at: Math.max(0, i.tlOut - length), srcIn: sIn, srcOut: sOut, length, mode: "تا خروجیِ تایم‌لاین" };
  return { at: Math.max(0, i.playhead), srcIn: sIn, srcOut: sOut, length, mode: "از سرِ پخش" };
}

/** «بستنِ فاصله»: اگر لحظهٔ t در یک فاصلهٔ خالی است که روی همهٔ ترک‌های باز مشترک است، آن را می‌بندد. */
export function closeGapAt(p: Project, t: number): { project: Project; closed: number; reason?: string } {
  const open = p.tracks.filter((tr) => !tr.locked);
  let gapStart = 0;
  let gapEnd = Infinity;
  for (const tr of open) {
    if (tr.clips.some((c) => c.at < t - EPS && clipEnd(c) > t + EPS)) return { project: p, closed: 0, reason: "سرِ پخش روی یک قطعه است؛ آن را در یک فاصلهٔ خالی بگذارید." };
    const before = tr.clips.filter((c) => clipEnd(c) <= t + EPS).map(clipEnd);
    const after = tr.clips.filter((c) => c.at >= t - EPS).map((c) => c.at);
    if (before.length) gapStart = Math.max(gapStart, Math.max(...before));
    if (after.length) gapEnd = Math.min(gapEnd, Math.min(...after));
  }
  if (!Number.isFinite(gapEnd)) return { project: p, closed: 0, reason: "بعد از سرِ پخش قطعه‌ای نیست که جلو بیاید." };
  const d = gapEnd - gapStart;
  if (d < 0.03) return { project: p, closed: 0, reason: "این‌جا فاصله‌ای نیست." };
  const q = mapTracks(p, (tr) => (tr.locked ? tr : { ...tr, clips: tr.clips.map((c) => (c.at >= gapEnd - EPS ? ({ ...c, at: Math.max(0, c.at - d) } as AnyClip) : c)) }));
  return { project: q, closed: d };
}

/** همهٔ قطعه‌های ترک‌های باز که پیش از t شروع شده‌اند (انتخابِ به عقب) */
export function idsBefore(p: Project, t: number): string[] {
  return p.tracks.flatMap((tr) => (tr.locked ? [] : tr.clips.filter((c) => c.at < t - EPS).map((c) => c.id)));
}

/** پهنایِ یک دسته قطعهٔ کپی‌شده (برای «چسباندنِ درج») */
export function spanOf(clips: { clip: AnyClip }[]): number {
  if (!clips.length) return 0;
  return Math.max(...clips.map((x) => clipEnd(x.clip))) - Math.min(...clips.map((x) => x.clip.at));
}

/** جا باز کن: همهٔ ترک‌های باز از t به اندازهٔ `span` جلو بروند (بدونِ گذاشتنِ چیزی) */
export function makeRoom(p: Project, t: number, span: number): Project {
  if (span <= 0) return p;
  const q = cutAt(p, unlocked(p), t);
  return mapTracks(q, (tr) => (tr.locked ? tr : { ...tr, clips: tr.clips.map((c) => (c.at >= t - EPS ? ({ ...c, at: c.at + span } as AnyClip) : c)) }));
}

/** یک قطعهٔ رسانه‌ای را در چند «لحظهٔ منبع» (مثلاً برش‌های تشخیص‌داده‌شده) می‌برد. تکه‌های وارونه/ثابت/ramp دار را دست نمی‌زند. */
export function splitAtSourceCuts(p: Project, clipId: string, cuts: number[]): { project: Project; made: number } {
  const first = p.tracks.flatMap((t) => t.clips).find((c) => c.id === clipId);
  if (!first || first.type !== "media") return { project: p, made: 0 };
  if (first.reverse || first.freeze || (first.ramp && first.ramp.length)) return { project: p, made: 0 };
  const ref = first.ref;
  const track = p.tracks.find((t) => t.clips.some((c) => c.id === clipId))!;
  let q = p;
  let made = 0;
  for (const s of [...cuts].sort((a, b) => a - b)) {
    // the piece (of this track and file) whose used source range contains s
    const piece = q.tracks.find((t) => t.id === track.id)!.clips.find((c): c is MediaClip => c.type === "media" && c.ref === ref && c.start + 0.05 < s && s < c.end - 0.05);
    if (!piece) continue;
    const t = piece.at + (s - piece.start) / (piece.speed || 1);
    if (t <= piece.at + EPS || t >= clipEnd(piece) - EPS) continue;
    const before = q.tracks.flatMap((x) => x.clips).length;
    q = splitMany(q, [piece.id], t);
    if (q.tracks.flatMap((x) => x.clips).length > before) made++;
  }
  return { project: q, made };
}

// ───────────── زمان
const DIG: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((d, i) => (DIG[d] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((d, i) => (DIG[d] = String(i)));

/** «۱:۲۳»، «1:02:03»، «83٫5»، «45» ⇒ ثانیه؛ null اگر خوانده نشد */
export function parseTime(text: string): number | null {
  const s = String(text ?? "").split("").map((ch) => DIG[ch] ?? ch).join("").replace(/[٫,]/g, ".").replace(/[٬،\s]/g, "").replace(/：/g, ":");
  if (!s) return null;
  const parts = s.split(":");
  if (parts.length > 3 || parts.some((x) => !/^\d+(\.\d+)?$/.test(x))) return null;
  const nums = parts.map(Number);
  let sec = 0;
  for (const n of nums) sec = sec * 60 + n;
  return Number.isFinite(sec) ? Math.round(sec * 1000) / 1000 : null;
}

// ───────────── زیرنویسِ SRT
export type Cue = { start: number; end: number; text: string };

export function srtTime(sec: number): string {
  const ms = Math.max(0, Math.round(sec * 1000));
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(h)}:${p(m)}:${p(s)},${p(ms % 1000, 3)}`;
}

export function toSrt(cues: Cue[]): string {
  return cues.map((c, i) => `${i + 1}\r\n${srtTime(c.start)} --> ${srtTime(c.end)}\r\n${c.text.replace(/\r?\n+/g, "\r\n")}\r\n`).join("\r\n");
}

const SRT_T = /(\d+):(\d+):(\d+)[,.](\d{1,3})\s*-->\s*(\d+):(\d+):(\d+)[,.](\d{1,3})/;
export function parseSrt(raw: string): Cue[] {
  const text = String(raw ?? "").replace(/^﻿/, "").replace(/\r\n?/g, "\n");
  const out: Cue[] = [];
  for (const block of text.split(/\n{2,}/)) {
    const lines = block.split("\n").map((l) => l.trim()).filter((l, i, a) => l !== "" || i < a.length);
    const ti = lines.findIndex((l) => SRT_T.test(l));
    if (ti < 0) continue;
    const m = lines[ti].match(SRT_T)!;
    const ms = (x: string) => Number(x.padEnd(3, "0"));
    const start = Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + ms(m[4]) / 1000;
    const end = Number(m[5]) * 3600 + Number(m[6]) * 60 + Number(m[7]) + ms(m[8]) / 1000;
    const body = lines.slice(ti + 1).join("\n").replace(/<[^>]+>/g, "").trim();
    if (body && end > start) out.push({ start, end, text: body });
  }
  return out.sort((a, b) => a.start - b.start).slice(0, 2000);
}

/** زیرنویس‌های پروژه (ترکِ «زیرنویس»؛ اگر نبود همهٔ متن‌ها) به ترتیبِ زمان */
export function cuesOf(p: Project): Cue[] {
  const caps = p.tracks.filter((t) => t.kind === "text" && t.caption);
  const pool = (caps.length && caps.some((t) => t.clips.length) ? caps : p.tracks.filter((t) => t.kind === "text")).flatMap((t) => t.clips);
  return pool
    .filter((c): c is TextClip => c.type === "text" && !!c.text.trim())
    .map((c) => ({ start: c.at, end: c.at + c.duration, text: c.text.trim() }))
    .sort((a, b) => a.start - b.start);
}
