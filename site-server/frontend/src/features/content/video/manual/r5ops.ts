/**
 * ویرایش‌های دورِ پنجم (تابع‌های خالص): قفلِ همگامی، ویرایش با متنِ گفتار، مسیرِ حرکت، پوشه‌های رسانه، متنِ عمودی.
 * بدونِ React؛ آزمون: tests/video-r5-ops.test.ts.
 */
import type { MediaItem } from "../api";
import { AnyClip, Marker, MediaClip, Project, TextClip, clipEnd, clipLength, deleteClips, liftRange, updateClip, withLinked } from "./model";
import { Key, KfChannel, setKey, valueAt } from "./keyframes";
import { metaHay } from "./r6ops";

const EPS = 0.02;

// ───────────── قفلِ همگامی (Sync lock)
/** «حذفِ بی‌فاصله» که ترک‌های دارای قفلِ همگامی را هم به اندازهٔ جای خالی جلو می‌آورد تا صدا و تصویر از هم جدا نشوند */
export function rippleDeleteSync(p: Project, ids: string[]): Project {
  const all = new Set(withLinked(p, ids));
  const spans = p.tracks.flatMap((t) => t.clips.filter((c) => all.has(c.id)).map((c) => ({ tid: t.id, at: c.at, len: clipLength(c) })));
  let q = deleteClips(p, ids, true);                                         // همان ترکِ هر قطعه را خودش جلو می‌آورد
  for (const sp of spans.sort((a, b) => b.at - a.at)) {
    q = {
      ...q,
      tracks: q.tracks.map((t) => (t.id === sp.tid || !t.sync || t.locked ? t : { ...t, clips: t.clips.map((c) => (c.at >= sp.at + sp.len - EPS ? ({ ...c, at: Math.max(0, c.at - sp.len) } as AnyClip) : c)) })),
    };
  }
  return q;
}

export const syncTracks = (p: Project): number => p.tracks.filter((t) => t.sync).length;

// ───────────── ویرایش با متنِ گفتار (Text-based editing)
export type SpokenWord = { id: string; clipId: string; text: string; start: number; end: number };

/** کلمه‌های همهٔ زیرنویس‌های پروژه با زمانِ مطلق. اگر زیرنویس زمانِ کلمه نداشت، کلمه‌ها در طولِ آن به‌طور مساوی پخش می‌شوند. */
export function spokenWords(p: Project): SpokenWord[] {
  const caps = p.tracks.filter((t) => t.kind === "text" && t.caption);
  const pool = (caps.some((t) => t.clips.length) ? caps : p.tracks.filter((t) => t.kind === "text")).flatMap((t) => t.clips);
  const out: SpokenWord[] = [];
  for (const c of pool) {
    if (c.type !== "text") continue;
    const tc = c as TextClip;
    const timed = (tc.words ?? []).filter((w) => w.w.trim());
    if (tc.words) {                                  // زمانِ کلمه‌ها هست (حتی اگر برشی همهٔ کلمه‌های یک تکه را برده باشد: تکهٔ بی‌کلمه چیزی نمی‌گوید)
      timed.forEach((w, i) => out.push({ id: `${tc.id}:${i}`, clipId: tc.id, text: w.w, start: tc.at + w.s, end: tc.at + Math.max(w.s + 0.05, w.e) }));
    } else {
      const parts = tc.text.split(/\s+/).filter(Boolean);
      const step = tc.duration / Math.max(1, parts.length);
      parts.forEach((w, i) => out.push({ id: `${tc.id}:${i}`, clipId: tc.id, text: w, start: tc.at + i * step, end: tc.at + (i + 1) * step }));
    }
  }
  return out.sort((a, b) => a.start - b.start || a.end - b.end);
}

/** بازهٔ زمانیِ کلمه‌های [i..j] (شاخص در آرایهٔ مرتب) */
export function wordsRange(words: SpokenWord[], i: number, j: number): { a: number; b: number } | null {
  const lo = Math.min(i, j), hi = Math.max(i, j);
  if (lo < 0 || hi >= words.length) return null;
  const a = Math.max(0, words[lo].start - 0.03);
  const b = words[hi].end + 0.03;
  return b > a + 0.05 ? { a, b } : null;
}

/** کلمه‌های انتخاب‌شده را از ویدیو بردار (از همهٔ ترک‌های باز) و جا را ببند؛ زیرنویسِ همان بخش هم می‌رود */
export function deleteWordRange(p: Project, words: SpokenWord[], i: number, j: number, ripple = true): { project: Project; seconds: number } | null {
  const r = wordsRange(words, i, j);
  if (!r) return null;
  let q = liftRange(p, r.a, r.b, ripple);
  // تکه‌های زیرنویسِ کلمه‌زمان‌دار که بعد از برش دیگر کلمه‌ای ندارند (ته‌ماندهٔ کوتاه) هم پاک شوند
  q = { ...q, tracks: q.tracks.map((t) => (t.kind !== "text" ? t : { ...t, clips: t.clips.filter((c) => !(c.type === "text" && Array.isArray((c as TextClip).words) && (c as TextClip).words!.length === 0)) })) };
  return { project: q, seconds: r.b - r.a };
}

/** پیشنهادِ بخش‌های حذفی: مکث‌های بیش از `gap` ثانیه میانِ دو کلمهٔ پشت‌سرهم */
export function pausesBetween(words: SpokenWord[], gap = 0.8): { a: number; b: number }[] {
  const out: { a: number; b: number }[] = [];
  for (let k = 1; k < words.length; k++) {
    const d = words[k].start - words[k - 1].end;
    if (d >= gap) out.push({ a: words[k - 1].end + 0.1, b: words[k].start - 0.1 });
  }
  return out;
}

// ───────────── مسیرِ حرکت (Motion path)
export type PathPoint = { t: number; px: number; py: number; e: Key["e"] };

/** نقطه‌های مسیرِ جابه‌جاییِ قطعه: اجتماعِ زمانِ کلیدهای px و py */
export function motionPoints(c: MediaClip): PathPoint[] {
  const kx = c.kf?.px ?? [];
  const ky = c.kf?.py ?? [];
  const times = Array.from(new Set([...kx.map((k) => k.t), ...ky.map((k) => k.t)])).sort((a, b) => a - b);
  return times.map((t) => ({ t, px: valueAt(kx, t, c.px ?? 0), py: valueAt(ky, t, c.py ?? 0), e: (kx.find((k) => k.t === t) ?? ky.find((k) => k.t === t))?.e ?? "linear" }));
}

/** یک نقطهٔ مسیر را (در زمانِ t) می‌گذارد یا جابه‌جا می‌کند: هر دو کانال */
export function setMotionPoint(c: MediaClip, t: number, px: number, py: number): MediaClip["kf"] {
  const kf = { ...(c.kf ?? {}) };
  kf.px = setKey(kf.px, t, px, "px");
  kf.py = setKey(kf.py, t, py, "py");
  return kf;
}

export function removeMotionPoint(c: MediaClip, t: number): MediaClip["kf"] | undefined {
  const kf = { ...(c.kf ?? {}) };
  for (const ch of ["px", "py"] as KfChannel[]) {
    const rest = (kf[ch] ?? []).filter((k) => Math.abs(k.t - t) > EPS);
    if (rest.length) kf[ch] = rest;
    else delete kf[ch];
  }
  return Object.keys(kf).length ? kf : undefined;
}

// ───────────── پوشه‌های رسانه (Bins) و جستجو
export type BinFolder = { id: string; name: string; refs: string[] };

export function addFolder(p: Project, name: string): { project: Project; id: string } {
  const clean = name.replace(/\s+/g, " ").trim().slice(0, 40) || "پوشهٔ تازه";
  const folders = ((p as Project & { bins?: BinFolder[] }).bins ?? []);
  const base = clean;
  let n = 2;
  let nm = base;
  while (folders.some((f) => f.name === nm)) nm = `${base} ${n++}`;
  const id = `f${Date.now().toString(36)}${folders.length}`;
  return { project: { ...p, bins: [...folders, { id, name: nm, refs: [] }].slice(0, 24) } as Project, id };
}

export function foldersOf(p: Project): BinFolder[] {
  return ((p as Project & { bins?: BinFolder[] }).bins ?? []).filter((f) => f && typeof f.id === "string");
}

export function assignToFolder(p: Project, ref: string, folderId: string | null): Project {
  const bins = foldersOf(p).map((f) => ({ ...f, refs: f.refs.filter((r) => r !== ref) }));
  const next = bins.map((f) => (f.id === folderId ? { ...f, refs: [...f.refs, ref].slice(0, 400) } : f));
  return { ...p, bins: next } as Project;
}

export function renameFolder(p: Project, id: string, name: string): Project {
  const clean = name.replace(/\s+/g, " ").trim().slice(0, 40);
  if (!clean) return p;
  return { ...p, bins: foldersOf(p).map((f) => (f.id === id ? { ...f, name: clean } : f)) } as Project;
}

export function deleteFolder(p: Project, id: string): Project {
  return { ...p, bins: foldersOf(p).filter((f) => f.id !== id) } as Project;     // رسانه‌ها پاک نمی‌شوند؛ فقط از پوشه درمی‌آیند
}

const DIG: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((d, i) => (DIG[d] = String(i)));
const fold = (s: string) => String(s ?? "").toLowerCase().split("").map((c) => DIG[c] ?? (c === "ي" ? "ی" : c === "ك" ? "ک" : c)).join("").replace(/[‌\s]+/g, " ").trim();

/** جستجو در نامِ رسانه (فارسی/انگلیسی؛ «ی/ي»، «ک/ك»، نیم‌فاصله و رقم‌های فارسی را یکی می‌گیرد)، و فیلتر با پوشه */
export function filterBin(items: MediaItem[], query: string, folder: BinFolder | null, meta?: Record<string, { tags: string[]; note: string }>): MediaItem[] {
  const q = fold(query);
  return items.filter((it) => {
    if (folder && !folder.refs.includes(it.ref)) return false;
    if (!q) return true;
    const hay = fold(`${it.title} ${it.kind === "video" ? "ویدیو video فیلم" : it.kind === "audio" ? "صدا audio موسیقی music" : it.kind === "image" ? "عکس image photo تصویر" : ""} ${it.ref} ${metaHay(meta?.[it.ref])}`);
    return q.split(" ").every((w) => hay.includes(w));
  });
}

// ───────────── متنِ عمودی
export type VerticalSide = "right" | "left";
/** متنِ عمودی: چرخشِ ۹۰ درجه و قرارگرفتن کنارِ قاب (راست = خواندن از بالا به پایین، چپ = از پایین به بالا) */
export function verticalText(p: Project, id: string, side: VerticalSide): Project {
  const down = side === "right";
  return updateClip(p, id, { rotation: down ? 90 : -90, x: down ? 0.9 : 0.1, y: 0.5, align: "center" } as Partial<TextClip>);
}

export const markerKinds: Marker["kind"][] = ["marker", "chapter", "beat"];
export { clipEnd };
