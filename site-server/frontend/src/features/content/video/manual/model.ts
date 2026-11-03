import type { MediaItem } from "../api";

/**
 * مدلِ پروژهٔ تایم‌لاین — همان JSON ای که سرور (services/editing/timeline.py: from_project) می‌خواند.
 * قطعه‌ها فقط `ref` دارند، هرگز مسیرِ فایل.
 */
export type Params = Record<string, number | string | boolean>;
export type Effect = { tool: string; params: Params };

export type MediaClip = {
  id: string;
  type: "media";
  ref: string;
  label: string;
  kind: "video" | "image" | "audio";
  at: number;
  /** نقطهٔ شروع/پایانِ استفاده از «منبع» (نه تایم‌لاین)؛ برای عکس end = مدتِ نمایش */
  start: number;
  end: number;
  /** مدتِ واقعیِ منبع (برای محدود کردنِ trim) — 0 = نامحدود (عکس) */
  src: number;
  opacity: number;
  x: number;
  y: number;
  width: number;
  height: number;
  volume: number;
  speed: number;
  fit: "cover" | "contain" | "stretch";
  fade_in: number;
  fade_out: number;
  audio_on: boolean;
  has_audio: boolean;
  effects: Effect[];
  transition: { kind: "fade" | "crossfade"; duration: number } | null;
};

export type TextClip = {
  id: string;
  type: "text";
  text: string;
  at: number;
  duration: number;
  position: "top" | "middle" | "bottom";
  size: number;
  color: string;
  box: boolean;
  opacity: number;
  label: string;
};

export type AnyClip = MediaClip | TextClip;

export type Track = {
  id: string;
  kind: "video" | "audio" | "text";
  name: string;
  muted: boolean;
  locked: boolean;
  clips: AnyClip[];
};

export type ProgramOp = { id: string; tool: string; params: Params };

export type Project = {
  format: { width: number; height: number; fps: number; preset: string };
  tracks: Track[];
  global_ops: ProgramOp[];
};

export const FORMATS: { key: string; title: string; width: number; height: number }[] = [
  { key: "reel", title: "ریلز / استوری ۹:۱۶", width: 1080, height: 1920 },
  { key: "feed", title: "پستِ عمودی ۴:۵", width: 1080, height: 1350 },
  { key: "square", title: "مربع ۱:۱", width: 1080, height: 1080 },
  { key: "wide", title: "افقی ۱۶:۹", width: 1920, height: 1080 },
  { key: "reel-hd", title: "۹:۱۶ سبک (۷۲۰)", width: 720, height: 1280 },
  { key: "wide-hd", title: "۱۶:۹ سبک (۷۲۰)", width: 1280, height: 720 },
];

let counter = 0;
export const uid = (p = "c") => `${p}${Date.now().toString(36)}${(counter++).toString(36)}`;

export const emptyProject = (): Project => ({
  format: { width: 1080, height: 1920, fps: 30, preset: "reel" },
  tracks: [
    { id: uid("t"), kind: "video", name: "تصویر ۱", muted: false, locked: false, clips: [] },
    { id: uid("t"), kind: "text", name: "متن", muted: false, locked: false, clips: [] },
    { id: uid("t"), kind: "audio", name: "صدا ۱", muted: false, locked: false, clips: [] },
  ],
  global_ops: [],
});

export const clipLength = (c: AnyClip): number => (c.type === "text" ? c.duration : Math.max(0.04, (c.end - c.start) / (c.speed || 1)));
export const clipEnd = (c: AnyClip): number => c.at + clipLength(c);
export const projectLength = (p: Project): number => Math.max(0, ...p.tracks.flatMap((t) => t.clips.map(clipEnd)));
export const trackEnd = (t: Track): number => Math.max(0, ...t.clips.map(clipEnd));

export function findClip(p: Project, id: string | null): { track: Track; clip: AnyClip } | null {
  if (!id) return null;
  for (const track of p.tracks) {
    const clip = track.clips.find((c) => c.id === id);
    if (clip) return { track, clip };
  }
  return null;
}

const map = (p: Project, fn: (t: Track) => Track): Project => ({ ...p, tracks: p.tracks.map(fn) });
const sortClips = (cs: AnyClip[]) => [...cs].sort((a, b) => a.at - b.at);

export function updateClip(p: Project, id: string, patch: Partial<MediaClip> | Partial<TextClip>): Project {
  return map(p, (t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? ({ ...c, ...patch } as AnyClip) : c)) }));
}

export function updateTrack(p: Project, id: string, patch: Partial<Track>): Project {
  return map(p, (t) => (t.id === id ? { ...t, ...patch } : t));
}

/** آیا بازهٔ [at, at+len) روی این ترک با قطعه‌ای (جز `ignore`) برخورد دارد؟ */
export function overlaps(t: Track, at: number, len: number, ignore?: string): boolean {
  return t.clips.some((c) => c.id !== ignore && at < clipEnd(c) - 0.001 && at + len > c.at + 0.001);
}

/** نزدیک‌ترین جای خالی برای یک قطعهٔ `len` ثانیه‌ای نزدیکِ `at` (پیش از/پس از قطعه‌های برخوردکننده) */
export function freeSpot(t: Track, at: number, len: number, ignore?: string): number | null {
  if (!overlaps(t, Math.max(0, at), len, ignore)) return Math.max(0, at);
  const cands = [0, ...t.clips.filter((c) => c.id !== ignore).flatMap((c) => [clipEnd(c), c.at - len])]
    .filter((x) => x >= 0)
    .sort((a, b) => Math.abs(a - at) - Math.abs(b - at));
  for (const c of cands) if (!overlaps(t, c, len, ignore)) return c;
  return null;
}

export function addMedia(p: Project, trackId: string, item: MediaItem, at: number): Project {
  const dur = item.kind === "image" ? 5 : Math.max(0.5, item.duration || 5);
  const track = p.tracks.find((t) => t.id === trackId);
  if (!track) return p;
  const spot = freeSpot(track, at, dur);
  if (spot === null) return p;
  const clip: MediaClip = {
    id: uid(), type: "media", ref: item.ref, label: item.title, kind: item.kind, at: spot, start: 0, end: dur,
    src: item.kind === "image" ? 0 : item.duration, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1,
    fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: item.has_audio, effects: [], transition: null,
  };
  return map(p, (t) => (t.id === trackId ? { ...t, clips: sortClips([...t.clips, clip]) } : t));
}

export function addText(p: Project, trackId: string, text: string, at: number, duration = 2.5): Project {
  const track = p.tracks.find((t) => t.id === trackId);
  if (!track) return p;
  const spot = freeSpot(track, at, duration);
  if (spot === null) return p;
  const clip: TextClip = { id: uid(), type: "text", text, at: spot, duration, position: "bottom", size: 6, color: "#ffffff", box: true, opacity: 1, label: text.slice(0, 20) };
  return map(p, (t) => (t.id === trackId ? { ...t, clips: sortClips([...t.clips, clip]) } : t));
}

export function addTrack(p: Project, kind: Track["kind"]): Project {
  const n = p.tracks.filter((t) => t.kind === kind).length + 1;
  const name = { video: `تصویر ${n}`, audio: `صدا ${n}`, text: `متن ${n}` }[kind];
  const track: Track = { id: uid("t"), kind, name, muted: false, locked: false, clips: [] };
  // ترکِ تازهٔ تصویر رویِ ترک‌های تصویر؛ صدا در پایین
  const lastOf = p.tracks.map((t) => t.kind).lastIndexOf(kind);
  const at = lastOf >= 0 ? lastOf + 1 : p.tracks.length;
  return { ...p, tracks: [...p.tracks.slice(0, at), track, ...p.tracks.slice(at)] };
}

export function removeTrack(p: Project, id: string): Project {
  const t = p.tracks.find((x) => x.id === id);
  if (!t || p.tracks.filter((x) => x.kind === t.kind).length <= 1 && t.kind === "video") return p;
  return { ...p, tracks: p.tracks.filter((x) => x.id !== id) };
}

/** قطعه را به زمانِ تازه (و ترکِ هم‌نوعِ تازه) ببر؛ اگر جا نبود، نزدیک‌ترین جای خالی. */
export function moveClip(p: Project, id: string, at: number, toTrack?: string): Project {
  const found = findClip(p, id);
  if (!found) return p;
  const { track, clip } = found;
  const dest = p.tracks.find((t) => t.id === (toTrack ?? track.id) && t.kind === track.kind && !t.locked) ?? track;
  const len = clipLength(clip);
  const spot = freeSpot(dest, Math.max(0, at), len, id);
  if (spot === null) return p;
  const moved = { ...clip, at: spot } as AnyClip;
  return map(p, (t) => {
    if (t.id === dest.id && t.id === track.id) return { ...t, clips: sortClips(t.clips.map((c) => (c.id === id ? moved : c))) };
    if (t.id === track.id) return { ...t, clips: t.clips.filter((c) => c.id !== id) };
    if (t.id === dest.id) return { ...t, clips: sortClips([...t.clips, moved]) };
    return t;
  });
}

/** لبهٔ چپِ قطعه را به `t` ببر (برش از ابتدا): شروعِ منبع جلو می‌رود */
export function trimStart(p: Project, id: string, t: number): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  const minAt = c.type === "media" && c.kind !== "image" ? c.at - (c.start / (c.speed || 1)) : 0;
  const next = Math.max(minAt, Math.min(clipEnd(c) - 0.1, Math.max(0, t)));
  const d = next - c.at;
  if (c.type === "text") return updateClip(p, id, { at: next, duration: c.duration - d });
  if (c.kind === "image") return updateClip(p, id, { at: next, end: c.end - d });
  return updateClip(p, id, { at: next, start: c.start + d * c.speed });
}

/** لبهٔ راستِ قطعه را به `t` ببر */
export function trimEnd(p: Project, id: string, t: number): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  const minEnd = c.at + 0.1;
  const maxEnd = c.type === "media" && c.kind !== "image" && c.src ? c.at + (c.src - c.start) / (c.speed || 1) : Infinity;
  const next = Math.max(minEnd, Math.min(maxEnd, t));
  if (c.type === "text") return updateClip(p, id, { duration: next - c.at });
  if (c.kind === "image") return updateClip(p, id, { end: next - c.at });
  return updateClip(p, id, { end: c.start + (next - c.at) * c.speed });
}

/** تقسیم در زمانِ `t` (S / Ctrl+K). ⇐ پروژهٔ تازه؛ اگر `t` داخلِ قطعه نبود همان پروژه. */
export function splitAt(p: Project, id: string, t: number): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  if (t <= c.at + 0.05 || t >= clipEnd(c) - 0.05) return p;
  const right: AnyClip =
    c.type === "text"
      ? { ...c, id: uid(), at: t, duration: clipEnd(c) - t }
      : c.kind === "image"
        ? { ...c, id: uid(), at: t, end: c.end - (t - c.at), start: 0, transition: null, fade_in: 0 }
        : { ...c, id: uid(), at: t, start: c.start + (t - c.at) * c.speed, transition: null, fade_in: 0 };
  const left: AnyClip =
    c.type === "text"
      ? { ...c, duration: t - c.at }
      : c.kind === "image"
        ? { ...c, end: t - c.at, fade_out: 0 }
        : { ...c, end: c.start + (t - c.at) * c.speed, fade_out: 0 };
  return map(p, (tr) => (tr.id === f.track.id ? { ...tr, clips: sortClips(tr.clips.map((x) => (x.id === id ? left : x)).concat(right)) } : tr));
}

export function deleteClip(p: Project, id: string, ripple: boolean): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const len = clipLength(f.clip);
  const at = f.clip.at;
  return map(p, (t) => {
    if (t.id !== f.track.id) return t;
    const rest = t.clips.filter((c) => c.id !== id);
    return { ...t, clips: ripple ? rest.map((c) => (c.at >= at ? ({ ...c, at: Math.max(0, c.at - len) } as AnyClip) : c)) : rest };
  });
}

export function duplicateClip(p: Project, id: string): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const copy = { ...f.clip, id: uid() } as AnyClip;
  const spot = freeSpot(f.track, clipEnd(f.clip), clipLength(f.clip));
  if (spot === null) return p;
  copy.at = spot;
  return map(p, (t) => (t.id === f.track.id ? { ...t, clips: sortClips([...t.clips, copy]) } : t));
}

/** نقطه‌هایی که قطعه به آن‌ها می‌چسبد (snap): صفر، سرِ پخش، لبهٔ همهٔ قطعه‌ها */
export function snapPoints(p: Project, playhead: number, ignore?: string): number[] {
  const pts = [0, playhead];
  for (const t of p.tracks) for (const c of t.clips) if (c.id !== ignore) pts.push(c.at, clipEnd(c));
  return pts;
}

export function snap(value: number, points: number[], threshold: number): number {
  let best = value;
  let d = threshold;
  for (const pt of points) {
    const dd = Math.abs(pt - value);
    if (dd < d) {
      d = dd;
      best = pt;
    }
  }
  return best;
}

/** قالبِ زمان: ۰۰:۰۵.۱۲ (دقیقه:ثانیه.فریم) */
export function timecode(sec: number, fps = 30): string {
  const s = Math.max(0, sec);
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  const f = Math.floor((s - Math.floor(s)) * fps);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(m)}:${two(r)}.${two(f)}`;
}

/** برای ارسال به سرور: برنامه‌های کلِ ویدیو بی شناسه */
export function toApi(p: Project) {
  return {
    ...p,
    global_ops: p.global_ops.map((o) => ({ tool: o.tool, params: o.params })),
  };
}

export function fromApi(data: unknown): Project {
  const d = (data ?? {}) as Partial<Project>;
  const base = emptyProject();
  if (!d.tracks || !Array.isArray(d.tracks) || d.tracks.length === 0) return base;
  return {
    format: { ...base.format, ...(d.format ?? {}) },
    tracks: d.tracks.map((t) => ({
      id: t.id ?? uid("t"), kind: t.kind ?? "video", name: t.name ?? "", muted: !!t.muted, locked: !!t.locked,
      clips: (t.clips ?? []).map((c) => ({ ...c, id: c.id ?? uid() }) as AnyClip),
    })),
    global_ops: (d.global_ops ?? []).map((o) => ({ id: (o as ProgramOp).id ?? uid("g"), tool: o.tool, params: o.params ?? {} })),
  };
}
