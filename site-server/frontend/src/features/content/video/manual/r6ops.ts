/**
 * ویرایش‌های دورِ ششم (تابع‌های خالص): برچسب و یادداشتِ رسانه، تفسیرِ فیلم، رسانهٔ گم‌شده، Replace edit، بلندیِ ترک، گذارِ پیش‌فرض،
 * هم‌اندازه‌کردنِ موسیقی، غلتشِ متن و مسیرِ متن، نویزگیر و ترکیبِ فریم‌ها. بدونِ React؛ آزمون: tests/video-r6-ops.test.ts.
 */
import type { MediaItem } from "../api";
import { AnyClip, Denoise, Interpret, MediaClip, MediaMeta, Project, TextClip, Track, clipEnd, clipLength, findClip, isMedia, updateClip } from "./model";

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(v) ? v : lo));
const EPS = 0.02;

// ───────────── برچسب و یادداشتِ رسانه
export const MAX_TAGS = 12;
export const MAX_NOTE = 300;

/** «محصول، بیرونی؛ نظرِ مشتری» ⇒ ["محصول", "بیرونی", "نظرِ مشتری"] (جداکننده: ویرگول فارسی/انگلیسی، نقطه‌ویرگول، خطِ تازه؛ بدونِ تکرار) */
export function tagsFromText(text: string): string[] {
  const out: string[] = [];
  for (const raw of String(text ?? "").split(/[,،;؛\n]+/)) {
    const t = raw.replace(/\s+/g, " ").trim().slice(0, 24);
    if (t && !out.includes(t)) out.push(t);
    if (out.length >= MAX_TAGS) break;
  }
  return out;
}

export const metaOf = (p: Project, ref: string): MediaMeta => p.media_meta?.[ref] ?? { tags: [], note: "" };

/** برچسب/یادداشتِ یک رسانه را عوض می‌کند؛ خالی شد ⇒ از پروژه حذف می‌شود */
export function setMediaMeta(p: Project, ref: string, patch: Partial<MediaMeta>): Project {
  const cur = metaOf(p, ref);
  const next: MediaMeta = {
    tags: patch.tags ? tagsFromText(patch.tags.join("،")) : cur.tags,
    note: patch.note !== undefined ? String(patch.note).slice(0, MAX_NOTE) : cur.note,
  };
  const all = { ...(p.media_meta ?? {}) };
  if (!next.tags.length && !next.note.trim()) delete all[ref];
  else all[ref] = next;
  return { ...p, media_meta: Object.keys(all).length ? all : undefined };
}

/** متنی که جستجو در رسانه‌ها روی آن می‌گردد */
export const metaHay = (m: MediaMeta | undefined): string => (m ? `${m.tags.join(" ")} ${m.note}` : "");

// ───────────── تفسیرِ فیلم
export const INTERPRET_FPS = [12, 15, 24, 25, 30, 48, 50, 60];

/** فیلمی با فریم‌بر‌ثانیهٔ `native` که «مثلِ `to` fps» خوانده شود: سرعتش = to / native (۶۰ ← ۳۰ یعنی نیمه‌سرعت) */
export const interpretSpeed = (native: number, to: number) => (native > 0 && to > 0 ? to / native : 1);

function shiftAfter(p: Project, trackId: string, from: number, delta: number, ignore: string): Project {
  if (Math.abs(delta) < 1e-4 || p.auto_ripple === false) return p;
  return { ...p, tracks: p.tracks.map((t) => (t.id !== trackId ? t : { ...t, clips: t.clips.map((c) => (c.id !== ignore && c.at >= from - EPS ? { ...c, at: Math.max(0, +(c.at + delta).toFixed(3)) } : c)) })) };
}

/** فریم‌بر‌ثانیهٔ تفسیر را روی قطعه می‌گذارد (سرعت از «سرعتِ پایه × to/native» می‌شود؛ دوباره زدن از همان پایه حساب می‌کند). → {project, speed, clamped} */
export function interpretFps(p: Project, id: string, native: number, to: number): { project: Project; speed: number; clamped: boolean } | { error: string } {
  const hit = findClip(p, id);
  if (!hit || !isMedia(hit.clip) || hit.clip.kind !== "video") return { error: "اول یک ویدیو را روی تایم‌لاین انتخاب کنید." };
  if (!(native > 0)) return { error: "فریم‌بر‌ثانیهٔ این فیلم معلوم نیست؛ دوباره بارگیری شود یا سرعت را دستی بگذارید." };
  const c = hit.clip;
  const base = c.interpret?.fps?.base ?? (c.speed || 1);
  const want = base * interpretSpeed(native, to);
  const speed = +clamp(want, 0.25, 4).toFixed(4);
  const before = clipLength(c);
  const interpret: Interpret = { ...(c.interpret ?? {}), fps: { from: native, to, base } };
  let q = updateClip(p, id, { speed, interpret } as Partial<MediaClip>);
  const after = clipLength(findClip(q, id)!.clip);
  q = shiftAfter(q, hit.track.id, clipEnd(c), after - before, id);
  return { project: q, speed, clamped: Math.abs(speed - want) > 1e-3 };
}

export function clearInterpretFps(p: Project, id: string): Project {
  const hit = findClip(p, id);
  if (!hit || !isMedia(hit.clip) || !hit.clip.interpret?.fps) return p;
  const c = hit.clip;
  const base = c.interpret!.fps!.base;
  const { fps: _gone, ...rest } = c.interpret!;
  const before = clipLength(c);
  let q = updateClip(p, id, { speed: base, interpret: Object.keys(rest).length ? rest : undefined } as Partial<MediaClip>);
  q = shiftAfter(q, hit.track.id, clipEnd(c), clipLength(findClip(q, id)!.clip) - before, id);
  return q;
}

/** نسبتِ پیکسل و خط‌های درهم (سرور: scale و yadif) */
export function setInterpret(p: Project, id: string, patch: { par?: number; deinterlace?: boolean }): Project {
  const hit = findClip(p, id);
  if (!hit || !isMedia(hit.clip)) return p;
  const cur = hit.clip.interpret ?? {};
  const next: Interpret = { ...cur };
  if (patch.par !== undefined) next.par = Math.abs(patch.par - 1) < 0.005 ? undefined : +clamp(patch.par, 0.5, 2).toFixed(4);
  if (patch.deinterlace !== undefined) next.deinterlace = patch.deinterlace || undefined;
  for (const k of Object.keys(next) as (keyof Interpret)[]) if (next[k] === undefined) delete next[k];
  return updateClip(p, id, { interpret: Object.keys(next).length ? next : undefined } as Partial<MediaClip>);
}

// ───────────── نویزگیرِ تصویر و ترکیبِ فریم‌ها
export function setDenoise(p: Project, id: string, patch: Partial<Denoise> | null): Project {
  const hit = findClip(p, id);
  if (!hit || !isMedia(hit.clip)) return p;
  if (patch === null) return updateClip(p, id, { denoise: undefined } as Partial<MediaClip>);
  const cur = hit.clip.denoise ?? { amount: 0.5, mode: "fast" as const };
  const amount = +clamp(patch.amount ?? cur.amount, 0, 1).toFixed(2);
  if (amount < 0.02) return updateClip(p, id, { denoise: undefined } as Partial<MediaClip>);
  return updateClip(p, id, { denoise: { amount, mode: (patch.mode ?? cur.mode) === "strong" ? "strong" : "fast" } } as Partial<MediaClip>);
}

export function setFrames(p: Project, id: string, mode: "blend" | "flow" | null): Project {
  const hit = findClip(p, id);
  if (!hit || !isMedia(hit.clip)) return p;
  return updateClip(p, id, { frames: mode ?? undefined } as Partial<MediaClip>);
}

/** آیا قطعه کند شده (سرعتِ کمتر از ۱ یا یک نقطهٔ کندِ منحنیِ سرعت)؟ ترکیبِ فریم‌ها فقط آن‌وقت اثر دارد */
export function isSlowed(c: MediaClip): boolean {
  if (c.freeze) return false;
  if (c.ramp?.length) return c.ramp.some((r) => r.v < 0.999);
  return (c.speed || 1) < 0.999;
}

// ───────────── رسانهٔ گم‌شده (Offline)
export type OfflineClip = { id: string; label: string; ref: string; track: string };
const NOT_A_FILE = (ref: string) => ref === "shape" || ref === "adjust" || ref.startsWith("seq:");

/** قطعه‌هایی که رسانه‌شان (ref) در رسانه‌های فروشگاه نیست؛ فقط وقتی فهرستِ رسانه‌ها بارگیری شده معنا دارد */
export function offlineClips(p: Project, known: Set<string>): OfflineClip[] {
  const out: OfflineClip[] = [];
  const walk = (tracks: Track[]) => {
    for (const t of tracks) for (const c of t.clips) if (isMedia(c) && !NOT_A_FILE(c.ref) && c.ref && !known.has(c.ref)) out.push({ id: c.id, label: c.label, ref: c.ref, track: t.name });
  };
  walk(p.tracks);
  for (const q of Object.values(p.sequences ?? {})) walk(q.tracks);
  return out;
}

// ───────────── Replace edit
/** قطعهٔ انتخاب‌شده در همان جا و با همان طول، محتوایش از `srcIn` رسانهٔ منبع می‌شود (جلوه، رنگ و جابه‌جایی‌اش می‌ماند) */
export function replaceEdit(p: Project, clipId: string, item: MediaItem, srcIn: number): { project: Project } | { error: string } {
  const hit = findClip(p, clipId);
  if (!hit || !isMedia(hit.clip)) return { error: "اول قطعه‌ای را روی تایم‌لاین انتخاب کنید که باید جایگزین شود." };
  const c = hit.clip;
  if (c.adjust || c.ref === "shape" || c.ref.startsWith("seq:")) return { error: "این قطعه را نمی‌شود با رسانه جایگزین کرد." };
  if ((item.kind === "audio") !== (c.kind === "audio")) return { error: "نوعِ رسانه با قطعه یکی نیست (صدا با صدا، تصویر با تصویر)." };
  if (item.kind === "image") {
    return { project: updateClip(p, clipId, { ref: item.ref, label: item.title, kind: "image", src: 0, has_audio: false } as Partial<MediaClip>) };
  }
  const dur = Math.max(0.2, item.duration || 0);
  const L = clipLength(c);
  const speed = c.speed || 1;
  const start = +clamp(srcIn, 0, Math.max(0, dur - 0.2)).toFixed(3);
  const end = +Math.min(dur, start + L * speed).toFixed(3);
  if (end - start < 0.2) return { error: "از این نقطه به بعد در رسانهٔ منبع چیزی نمانده؛ ورودی را عقب‌تر ببرید." };
  return { project: updateClip(p, clipId, { ref: item.ref, label: item.title, kind: item.kind, start, end, src: dur, has_audio: item.has_audio } as Partial<MediaClip>) };
}

// ───────────── بلندیِ ترک
export type TrackSize = NonNullable<Track["size"]>;
export const TRACK_ROW: Record<TrackSize, number> = { c: 24, s: 36, m: 52, l: 88 };
export const TRACK_SIZES: TrackSize[] = ["c", "s", "m", "l"];
export const trackRow = (t: Track): number => TRACK_ROW[t.size ?? "m"];

export function setTrackSize(p: Project, id: string, size: TrackSize): Project {
  return { ...p, tracks: p.tracks.map((t) => (t.id === id ? { ...t, size: size === "m" ? undefined : size } : t)) };
}
/** کوچک‌تر/بزرگ‌تر شدنِ یک پله؛ از جمع‌شده با کوچک‌تر شدن نمی‌رود پایین‌تر */
export function stepTrackSize(p: Project, id: string, dir: -1 | 1): Project {
  const t = p.tracks.find((x) => x.id === id);
  if (!t) return p;
  const i = TRACK_SIZES.indexOf(t.size ?? "m");
  return setTrackSize(p, id, TRACK_SIZES[clamp(i + dir, 0, TRACK_SIZES.length - 1)]);
}
export const setAllTrackSizes = (p: Project, size: TrackSize): Project => ({ ...p, tracks: p.tracks.map((t) => ({ ...t, size: size === "m" ? undefined : size })) });

// ───────────── گذارِ پیش‌فرض برای همهٔ برش‌ها
/** جفت‌قطعه‌های چسبیده‌ی یک ترک (فاصلهٔ کمتر از ۰٫۱۵ ثانیه) */
function joins(t: Track): [MediaClip, MediaClip][] {
  const ordered = t.clips.filter(isMedia).sort((a, b) => a.at - b.at);
  const out: [MediaClip, MediaClip][] = [];
  for (let i = 1; i < ordered.length; i++) if (Math.abs(ordered[i].at - clipEnd(ordered[i - 1])) <= 0.15 && ordered[i].kind !== "audio" && ordered[i - 1].kind !== "audio") out.push([ordered[i - 1], ordered[i]]);
  return out;
}

/** گذارِ پیش‌فرض را روی برش‌های ترک‌های تصویر (یا فقط یک ترک) می‌نشاند؛ replace=false ⇒ برش‌هایی که از قبل گذار دارند دست نمی‌خورند */
export function applyDefaultTransition(p: Project, o: { kind: string; duration: number; trackId?: string; replace?: boolean }): { project: Project; count: number } {
  const duration = +clamp(o.duration, 0.1, 2).toFixed(2);
  const ids = new Set<string>();
  for (const t of p.tracks) {
    if (t.kind !== "video" || t.locked || (o.trackId && t.id !== o.trackId)) continue;
    for (const [, later] of joins(t)) if (o.replace || !later.transition) ids.add(later.id);
  }
  if (!ids.size) return { project: { ...p, default_transition: { kind: o.kind, duration } }, count: 0 };
  return {
    project: {
      ...p, default_transition: { kind: o.kind, duration },
      tracks: p.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (ids.has(c.id) ? ({ ...c, transition: { kind: o.kind, duration } } as AnyClip) : c)) })),
    },
    count: ids.size,
  };
}

export function removeAllTransitions(p: Project): { project: Project; count: number } {
  let count = 0;
  const tracks = p.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (isMedia(c) && c.transition ? (count++, { ...c, transition: null } as AnyClip) : c)) }));
  return { project: { ...p, tracks }, count };
}

// ───────────── هم‌اندازه‌کردنِ موسیقی با ویدیو
/** پایانِ تصویر: دیرترین پایانِ قطعه‌های ترک‌های تصویر و متن */
export const pictureEnd = (p: Project): number => p.tracks.filter((t) => t.kind !== "audio").flatMap((t) => t.clips).reduce((m, c) => Math.max(m, clipEnd(c)), 0);

/** موسیقی را (با سرعتِ ۰٫۵ تا ۲ برابر، بدونِ تغییرِ زیر و بم) هم‌اندازهٔ `target` ثانیه می‌کند؛ اگر حتی با ۲ برابر بلندتر بود می‌برد (و محوِ پایانی می‌دهد) */
export function retimeToLength(p: Project, clipId: string, target: number): { project: Project; speed: number; note: string } | { error: string } {
  const hit = findClip(p, clipId);
  if (!hit || !isMedia(hit.clip) || (hit.clip.kind !== "audio" && hit.track.kind !== "audio")) return { error: "اول یک قطعهٔ صدا یا موسیقی را انتخاب کنید." };
  if (!(target > 0.5)) return { error: "ویدیو هنوز تصویری ندارد که موسیقی با آن هم‌اندازه شود." };
  const c = hit.clip;
  const span = c.end - c.start;
  const ideal = span / target;
  const speed = +clamp(ideal, 0.5, 2).toFixed(3);
  let end = c.end;
  let note = "";
  if (ideal > 2) {
    end = +(c.start + target * 2).toFixed(3);
    note = "موسیقی حتی با دو برابر سرعت بلندتر از ویدیو بود؛ انتهایش بریده شد و محوِ پایانی گرفت.";
  } else if (ideal < 0.5) {
    note = "موسیقی حتی با نصفِ سرعت از ویدیو کوتاه‌تر است؛ برای باقی‌اش موسیقیِ بلندتر یا یک قطعهٔ دیگر کنارش بگذارید.";
  }
  const q = updateClip(p, clipId, { speed, end, fade_out: Math.max(c.fade_out ?? 0, ideal > 2 ? 1.5 : 0) } as Partial<MediaClip>);
  return { project: q, speed, note };
}

// ───────────── غلتشِ متن و مسیرِ متن
export type TextMotion = "roll-up" | "roll-down" | "crawl-left" | "crawl-right" | "arc" | "wave";
export const TEXT_MOTIONS: { key: TextMotion; title: string; hint: string }[] = [
  { key: "roll-up", title: "غلتش به بالا (تیتراژ)", hint: "از پایینِ قاب شروع می‌شود و تا بالا می‌رود؛ مثلِ تیتراژِ پایانی" },
  { key: "roll-down", title: "غلتش به پایین", hint: "از بالا می‌آید و پایین می‌رود" },
  { key: "crawl-left", title: "نوارِ خبر (حرکت به چپ)", hint: "از راستِ قاب وارد و از چپ خارج می‌شود" },
  { key: "crawl-right", title: "نوارِ خبر (حرکت به راست)", hint: "از چپِ قاب وارد و از راست خارج می‌شود" },
  { key: "arc", title: "قوس (کمان)", hint: "نوشته در یک کمانِ نرم از چپ تا راست می‌رود" },
  { key: "wave", title: "موج", hint: "نوشته از چپ تا راست می‌رود و موج‌وار بالا و پایین می‌شود" },
];

/** نقطه‌های مسیر ({t، dx، dy}؛ t ثانیهٔ نسبت به شروعِ متن، dx/dy کسری از قاب) برای هر حرکت */
export function motionPath(kind: TextMotion, duration: number): { t: number; dx: number; dy: number }[] {
  const d = Math.max(0.5, duration);
  const r = (x: number) => +x.toFixed(3);
  switch (kind) {
    case "roll-up": return [{ t: 0, dx: 0, dy: 0.75 }, { t: r(d), dx: 0, dy: -0.75 }];
    case "roll-down": return [{ t: 0, dx: 0, dy: -0.75 }, { t: r(d), dx: 0, dy: 0.75 }];
    case "crawl-left": return [{ t: 0, dx: 1.1, dy: 0 }, { t: r(d), dx: -1.1, dy: 0 }];
    case "crawl-right": return [{ t: 0, dx: -1.1, dy: 0 }, { t: r(d), dx: 1.1, dy: 0 }];
    case "arc": return Array.from({ length: 9 }, (_, i) => { const u = i / 8; return { t: r(d * u), dx: r(-0.4 + 0.8 * u), dy: r(-0.18 * Math.sin(Math.PI * u)) }; });
    case "wave": return Array.from({ length: 17 }, (_, i) => { const u = i / 16; return { t: r(d * u), dx: r(-0.4 + 0.8 * u), dy: r(0.07 * Math.sin(4 * Math.PI * u)) }; });
  }
}

export function setTextMotion(p: Project, id: string, kind: TextMotion | null): Project {
  const hit = findClip(p, id);
  if (!hit || hit.clip.type !== "text") return p;
  if (kind === null) return updateClip(p, id, { path: undefined } as Partial<TextClip>);
  const c = hit.clip as TextClip;
  const lines = c.text.split("\n").length;
  const roll = kind === "roll-up" || kind === "roll-down";
  // تیتراژ: هرچه خط‌ها بیشتر، مدتِ لازم بیشتر (حدودِ ۱٫۲ ثانیه برای هر خط + ۳ ثانیه)
  const duration = roll ? Math.max(c.duration, Math.min(60, 3 + 1.2 * lines)) : c.duration;
  const patch: Partial<TextClip> = { path: motionPath(kind, duration), duration, anim_in: "none", anim_out: "none" };
  if (roll) Object.assign(patch, { position: "middle" as const, align: "center" as const, y: 0.5 });
  if (kind === "crawl-left" || kind === "crawl-right") Object.assign(patch, { position: "bottom" as const, box: true });
  return updateClip(p, id, patch);
}
