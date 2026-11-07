/**
 * ابزارهای قطعهٔ دورِ پنجم (تابع‌های خالص): لایهٔ تنظیم، کلیدِ روشنایی، اصلاحِ لنز، نقطهٔ لنگر.
 * آزمون: tests/video-r5-fx.test.ts. سرور همین فیلدها را در services/editing/timeline.py می‌خواند و می‌بُرد.
 */
import { Anchor, Lens, Luma, MediaClip, Project, Track, TrackMatte, addTrack, clipEnd, findClip, overlaps, uid, updateClip } from "./model";

export const ADJUST_REF = "adjust";
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(v) ? v : 0));

export const isAdjust = (c: unknown): boolean => !!c && (c as MediaClip).type === "media" && (c as MediaClip).adjust === true;

/** قطعهٔ «لایهٔ تنظیم»؛ مثلِ یک عکس است (بی‌منبع): start همیشه ۰ و end = مدت */
export function newAdjustment(at: number, duration: number, id = uid()): MediaClip {
  return {
    id, type: "media", ref: ADJUST_REF, label: "لایهٔ تنظیم", kind: "image", at: Math.max(0, at), start: 0, end: Math.max(0.2, duration), src: 0, opacity: 1,
    x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1, fit: "stretch", fade_in: 0, fade_out: 0, audio_on: false, has_audio: false, effects: [], transition: null,
    adjust: true, color: undefined,
  };
}

/** لایهٔ تنظیم را روی یک ترکِ تصویرِ تازهٔ بالای همه می‌گذارد (تا روی همهٔ ترک‌های پایین اثر کند). برمی‌گرداند {project, id} */
export function addAdjustment(p: Project, at: number, duration: number, id = uid()): { project: Project; id: string } {
  const clip = newAdjustment(at, duration, id);
  const top = [...p.tracks].reverse().find((t) => t.kind === "video" && !t.locked);
  const lastVideo = p.tracks.map((t, i) => (t.kind === "video" ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
  let q = p;
  let tid = top && p.tracks.indexOf(top) === lastVideo && !overlaps(top, clip.at, duration) ? top.id : "";
  if (!tid) {
    q = addTrack(q, "video");
    const made = q.tracks.filter((t) => t.kind === "video").slice(-1)[0] as Track;
    tid = made.id;
  }
  return { project: { ...q, tracks: q.tracks.map((t) => (t.id === tid ? { ...t, clips: [...t.clips, clip].sort((a, b) => a.at - b.at) } : t)) }, id: clip.id };
}

/** مدتِ پیش‌فرضِ لایهٔ تنظیم: تا انتهای قطعه‌ای که زیرِ سرِ پخش است (یا ۵ ثانیه)، و همیشه داخلِ پروژه */
export function adjustmentSpan(p: Project, time: number): number {
  let end = 0;
  for (const t of p.tracks) if (t.kind === "video") for (const c of t.clips) if (c.type === "media" && !isAdjust(c) && c.at <= time + 1e-6 && clipEnd(c) > time) end = Math.max(end, clipEnd(c));
  return end > time + 0.2 ? end - time : 5;
}

// ───────────── کلیدِ روشنایی
export const DEFAULT_LUMA: Luma = { on: true, mode: "dark", tolerance: 0.1, softness: 0.05 };
export function setLuma(p: Project, id: string, patch: Partial<Luma> | null): Project {
  const hit = findClip(p, id);
  if (!hit || hit.clip.type !== "media") return p;
  if (patch === null) return updateClip(p, id, { luma: undefined });
  const cur = (hit.clip as MediaClip).luma ?? DEFAULT_LUMA;
  const next: Luma = { ...cur, ...patch };
  next.tolerance = clamp(next.tolerance, 0, 1);
  next.softness = clamp(next.softness, 0, 1);
  next.mode = next.mode === "bright" ? "bright" : "dark";
  return updateClip(p, id, { luma: next });
}

// ───────────── اصلاحِ لنز
export const lensIsFlat = (l: Lens | undefined) => !l || (Math.abs(l.k1) < 0.005 && Math.abs(l.k2) < 0.005);
export function setLens(p: Project, id: string, patch: Partial<Lens> | null): Project {
  const hit = findClip(p, id);
  if (!hit || hit.clip.type !== "media") return p;
  if (patch === null) return updateClip(p, id, { lens: undefined });
  const cur = (hit.clip as MediaClip).lens ?? { k1: 0, k2: 0 };
  const next = { k1: clamp(patch.k1 ?? cur.k1, -1, 1), k2: clamp(patch.k2 ?? cur.k2, -1, 1) };
  return updateClip(p, id, { lens: lensIsFlat(next) ? undefined : next });
}

// ───────────── نقطهٔ لنگر
export const anchorIsCentre = (a: Anchor | undefined) => !a || (Math.abs(a.x) < 0.002 && Math.abs(a.y) < 0.002);
export function setAnchor(p: Project, id: string, a: Anchor | null): Project {
  const hit = findClip(p, id);
  if (!hit || hit.clip.type !== "media") return p;
  if (a === null) return updateClip(p, id, { anchor: undefined });
  const next = { x: clamp(a.x, -1, 1), y: clamp(a.y, -1, 1) };
  return updateClip(p, id, { anchor: anchorIsCentre(next) ? undefined : next });
}
/** نُه نقطهٔ آماده: گوشه‌ها، میانهٔ لبه‌ها و مرکز (کسری از جعبه، از مرکز) */
export const ANCHOR_PRESETS: { key: string; title: string; x: number; y: number }[] = [
  { key: "tr", title: "بالا راست", x: 0.5, y: -0.5 }, { key: "tc", title: "بالا میانه", x: 0, y: -0.5 }, { key: "tl", title: "بالا چپ", x: -0.5, y: -0.5 },
  { key: "mr", title: "راست میانه", x: 0.5, y: 0 }, { key: "mc", title: "مرکز", x: 0, y: 0 }, { key: "ml", title: "چپ میانه", x: -0.5, y: 0 },
  { key: "br", title: "پایین راست", x: 0.5, y: 0.5 }, { key: "bc", title: "پایین میانه", x: 0, y: 0.5 }, { key: "bl", title: "پایین چپ", x: -0.5, y: 0.5 },
];

// ───────────── Track matte
const usable = (c: unknown): c is MediaClip => !!c && (c as MediaClip).type === "media" && (c as MediaClip).kind !== "audio" && !(c as MediaClip).adjust;

/** قطعه‌ای که ماتِ این قطعه است: روی ترکِ تصویرِ بعدیِ بالاتر، بیشترین هم‌پوشانیِ زمانی (بیش از ۰٫۰۵ ثانیه) */
export function matteSourceFor(p: Project, id: string): MediaClip | null {
  const videos = p.tracks.filter((t) => t.kind === "video" && !t.hidden);
  const hit = findClip(p, id);
  if (!hit || !usable(hit.clip)) return null;
  const i = videos.findIndex((t) => t.id === hit.track.id);
  const upper = i >= 0 ? videos[i + 1] : undefined;
  if (!upper) return null;
  const a = hit.clip as MediaClip;
  let best: MediaClip | null = null;
  let over = 0.05;
  for (const m of upper.clips) {
    if (!usable(m)) continue;
    const o = Math.min(clipEnd(a), clipEnd(m)) - Math.max(a.at, m.at);
    if (o > over) { best = m; over = o; }
  }
  return best;
}

/** برای پیش‌نمایش: {قطعه ⇒ ماتش} و مجموعهٔ قطعه‌هایی که فقط مات‌اند (مثلِ سرور: هر مات فقط برای یک قطعه) */
export function planMattes(p: Project): { of: Map<string, MediaClip>; src: Set<string> } {
  const of = new Map<string, MediaClip>();
  const src = new Set<string>();
  const videos = p.tracks.filter((t) => t.kind === "video" && !t.hidden);
  videos.forEach((lower, i) => {
    const upper = videos[i + 1];
    if (!upper) return;
    for (const a of lower.clips) {
      if (!usable(a) || !a.track_matte) continue;
      let best: MediaClip | null = null;
      let over = 0.05;
      for (const m of upper.clips) {
        if (!usable(m) || src.has(m.id)) continue;
        const o = Math.min(clipEnd(a), clipEnd(m)) - Math.max(a.at, m.at);
        if (o > over) { best = m; over = o; }
      }
      if (best) { of.set(a.id, best); src.add(best.id); }
    }
  });
  return { of, src };
}

export const DEFAULT_MATTE: TrackMatte = { mode: "luma", invert: false };
export function setTrackMatte(p: Project, id: string, patch: Partial<TrackMatte> | null): Project {
  const hit = findClip(p, id);
  if (!hit || hit.clip.type !== "media") return p;
  if (patch === null) return updateClip(p, id, { track_matte: undefined });
  const cur = (hit.clip as MediaClip).track_matte ?? DEFAULT_MATTE;
  return updateClip(p, id, { track_matte: { mode: (patch.mode ?? cur.mode) === "alpha" ? "alpha" : "luma", invert: (patch.invert ?? cur.invert) === true } });
}
