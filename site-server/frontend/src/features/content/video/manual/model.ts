import type { MediaItem } from "../api";
import {
  Kf, KfChannel, Key, RAMP_STEPS, RampKey, rampSpeeds, sliceKeys, sliceRamp, shiftKeys, valueAt,
} from "./keyframes";

export type { Kf, KfChannel, Key, RampKey };
export type { Easing } from "./keyframes";

/**
 * مدلِ پروژهٔ تایم‌لاین — همان JSON ای که سرور (services/editing/timeline.py: from_project) می‌خواند.
 * قطعه‌ها فقط `ref` دارند، هرگز مسیرِ فایل. همهٔ فیلدهای «حرفه‌ای» اختیاری‌اند (پروژه‌های قدیمی همان‌طور کار می‌کنند).
 */
export type Params = Record<string, number | string | boolean>;
export type Effect = { tool: string; params: Params };

export type Blend = "normal" | "multiply" | "screen" | "overlay" | "add" | "softlight" | "lighten" | "darken" | "difference";
export type Crop = { l?: number; r?: number; t?: number; b?: number };
/** نقطهٔ ماسکِ آزاد: لنگر (x,y) و دو دستگیره (ورودی ix,iy / خروجی ox,oy) به‌صورتِ جابه‌جایی از لنگر؛ همه کسری از جعبهٔ قطعه */
export type BezierPt = { x: number; y: number; ix: number; iy: number; ox: number; oy: number };
export type Mask = {
  shape: "none" | "rect" | "ellipse" | "bezier"; cx: number; cy: number; w: number; h: number; feather: number; invert: boolean;
  /** ماسکِ آزاد (bezier) */
  points?: BezierPt[];
  /** جابه‌جاییِ مرکزِ ماسک (کسری از جعبه) در زمانِ قطعه — از ردیابیِ حرکت پخته می‌شود */
  kx?: Key[]; ky?: Key[];
  /** وصل به ردیاب (برای ماسک: مرکزِ ماسک همیشه به اندازهٔ bx,by از نقطهٔ ردیابی‌شده می‌ماند) */
  follow?: Follow;
};
export type ShapeKind = "rect" | "rounded" | "ellipse" | "triangle" | "star" | "polygon" | "heart" | "arrow" | "burst";
export type ShapeSpec = {
  shape: ShapeKind; fill: string; fill2?: string; angle?: number; fill_opacity?: number; stroke?: string; stroke_w?: number;
  radius?: number; points?: number; inner?: number;
};
/** وصل‌بودن به یک ردیاب: همیشه به اندازهٔ (bx,by) (کسری از قاب) از نقطهٔ ردیابی‌شده فاصله دارد؛ کلیدها از مسیر پخته می‌شوند */
export type Follow = { tracker: string; bx: number; by: number };
export type Chroma = { on: boolean; color: string; similarity: number; blend: number; spill: number };
export type ClipAudio = {
  pan?: number; eq?: string; comp?: number; enhance?: boolean; denoise?: boolean; normalize?: boolean; denoise_ai?: boolean;
  /** EQ پارامتریک: فرکانس (Hz)، بهره (dB)، پهنا (Q) — تا ۵ باند */
  bands?: { f: number; g: number; q: number }[];
  /** کمپرسورِ دقیق: آستانه dB، نسبت، حمله و رهایی ms، جبرانِ بلندی dB */
  cdetail?: { on: boolean; thr: number; ratio: number; attack: number; release: number; makeup: number };
  /** زیر و بمی بر حسبِ نیم‌پرده (−۱۲..۱۲) */
  pitch?: number;
  echo?: { on: boolean; delay: number; decay: number };
 };
/**
 * بازتنظیمِ قاب (Reframe): پنجره‌ای در «خودِ منبع» که پیش از جا دادن (fit) بریده می‌شود؛ بنابراین کیفیت از فایلِ اصلی است.
 * w,h = اندازهٔ پنجره (کسری از پهنا/ارتفاعِ منبع)؛ cx,cy = مرکزِ پنجره (کسری از منبع). kx,ky = کلیدفریمِ مرکز در زمانِ قطعه
 * (t از شروعِ قطعه روی تایم‌لاین، v کسری ۰..۱ از منبع). اگر نباشند cx,cy ثابت‌اند. همان ریاضیِ سرور (compose.py) و Compositor.
 */
export type Reframe = { w: number; h: number; cx: number; cy: number; kx?: Key[]; ky?: Key[] };
export type TransitionSpec = { kind: string; duration: number };

export type Rgb = [number, number, number];
export type HslKey = "red" | "yellow" | "green" | "cyan" | "blue" | "magenta";
export type ColorParams = {
  exposure?: number; contrast?: number; highlights?: number; shadows?: number; whites?: number; blacks?: number;
  temperature?: number; tint?: number; saturation?: number; vibrance?: number;
  wheels?: { shadows?: Rgb; mids?: Rgb; highs?: Rgb };
  curves?: { m?: [number, number][]; r?: [number, number][]; g?: [number, number][]; b?: [number, number][] };
  hsl?: Partial<Record<HslKey, { h: number; s: number; l: number }>>;
  look?: string; look_amount?: number;
  sharpen?: number; denoise?: number; vignette?: number; grain?: number; blur?: number;
};

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
  transition: TransitionSpec | null;
  // ---- حرفه‌ای
  rot?: number; scale?: number; px?: number; py?: number; flip_h?: boolean; flip_v?: boolean;
  blend?: Blend; crop?: Crop; mask?: Mask; kf?: Kf; chroma?: Chroma; color?: ColorParams;
  ramp?: RampKey[]; reverse?: boolean; freeze?: boolean; link?: string; audio?: ClipAudio;
  /** بازتنظیمِ قاب: پنجرهٔ بُرشِ منبع (برای ۹:۱۶ و دنبال‌کردنِ سوژه). نبودن = کلِ منبع */
  reframe?: Reframe;
  /** شکل (تصویرِ کشیده‌شده): ref = "shape" و سرور PNG می‌سازد */
  shape?: ShapeSpec;
  /** LUT ِ .cube از کتابخانهٔ فروشگاه */
  lut?: { key: string; amount: number };
  /** ماتِ حذفِ پس‌زمینه (ویدیوی خاکستریِ ساخته‌شده روی سرورِ پردازش) */
  matte?: { key: string };
  follow?: Follow;
  /** «لایهٔ تنظیم»: قطعه‌ای بی‌تصویر که رنگ و افکتش روی همهٔ ترک‌های زیرش اعمال می‌شود (ref = "adjust") */
  adjust?: boolean;
  /** «کلیدِ روشنایی»: تاریک‌ها یا روشن‌ها شفاف شوند */
  luma?: Luma;
  /** «اصلاحِ لنز»: k1 < 0 اعوجاجِ بشکه‌ای را صاف می‌کند، k1 > 0 بالشتکی را */
  lens?: Lens;
  /** «نقطهٔ لنگر»: مرکزِ چرخش و بزرگ‌نمایی؛ کسری از جعبهٔ قطعه، از مرکز (۰ و ۰ = مرکز) */
  anchor?: Anchor;
  /** «Track matte»: این قطعه فقط از پشتِ قطعهٔ هم‌زمانِ ترکِ تصویرِ بالاتر دیده می‌شود (آن قطعه خودش نمایش داده نمی‌شود) */
  track_matte?: TrackMatte;
};

export type Luma = { on: boolean; mode: "dark" | "bright"; tolerance: number; softness: number };
export type Lens = { k1: number; k2: number };
export type Anchor = { x: number; y: number };
export type TrackMatte = { mode: "luma" | "alpha"; invert: boolean };

export type TextAnimIn = "none" | "fade" | "slide_up" | "slide_down" | "slide_left" | "slide_right" | "pop" | "zoom" | "typewriter" | "blur";
export type TextWord = { w: string; s: number; e: number };

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
  // ---- عنوان‌های حرفه‌ای (titles.clean)
  text2?: string; template?: string; font?: string; bold?: boolean; italic?: boolean;
  stroke_color?: string; stroke?: number; shadow?: number; shadow_color?: string;
  box_color?: string; box_opacity?: number; box_pad?: number; align?: "right" | "center" | "left";
  x?: number; y?: number; rotation?: number; scale?: number;
  anim_in?: TextAnimIn; anim_out?: TextAnimIn; anim_dur?: number;
  words?: TextWord[]; hl_color?: string; hl_mode?: "color" | "scale" | "box"; caption?: boolean; accent?: string;
  /** مسیرِ ردیابی: جابه‌جاییِ لنگر (کسری از قاب) در زمانِ متن — از ردیاب پخته می‌شود */
  path?: { t: number; dx: number; dy: number }[];
  follow?: Follow;
};

export type AnyClip = MediaClip | TextClip;

export type TrackRole = "" | "speech" | "music" | "sfx";

export type Track = {
  id: string;
  kind: "video" | "audio" | "text";
  name: string;
  muted: boolean;
  locked: boolean;
  hidden?: boolean;
  solo?: boolean;
  gain_db?: number;
  pan?: number;
  role?: TrackRole;
  caption?: boolean;
  /** «هدف» (◎): ویرایش‌های درج و رویه‌گذاری از مانیتورِ منبع روی این ترک می‌نشینند */
  target?: boolean;
  /** قفلِ همگامی: با «حذفِ بی‌فاصله» روی ترکی دیگر، این ترک هم به اندازهٔ جای خالی جلو می‌آید */
  sync?: boolean;
  clips: AnyClip[];
};

export type ProgramOp = { id: string; tool: string; params: Params };
export type Marker = { id: string; t: number; label: string; color: string; kind: "marker" | "beat" | "chapter" };
export type Ducking = { on: boolean; amount_db: number; threshold: number; attack_ms: number; release_ms: number };
/** بلندیِ نهاییِ خروجی برای شبکه‌های اجتماعی: loudnorm روی مستر (target = LUFS، tp = سقفِ اوج به dB) */
export type Loudness = { on: boolean; target: number; tp: number };
export type Master = { gain_db: number; limiter: boolean; loudness?: Loudness };
export type ExportBlock = { preset?: string; codec?: "h264" | "h265"; fps?: number | null; height?: number | null; quality?: "high" | "medium" | "small"; audio_kbps?: number; where?: "auto" | "server"; target_mb?: number | null };

export type ExportWhere = "auto" | "server";
export type MulticamInfo = {
  angles: { ref: string; label: string; offset: number; duration: number; has_audio: boolean }[];
  cuts: { t: number; angle: number }[];
  /** زاویه‌ای که صدایش پخش می‌شود (-1 = بی‌صدا) */
  audio: number;
};
/** توالیِ تودرتو: همان ترک‌های یک پروژه؛ یک قطعه با ref = "seq:<id>" آن را مثلِ یک ویدیو پخش می‌کند */
export type Sequence = { name: string; tracks: Track[]; format?: { width: number; height: number; fps: number; preset: string }; multicam?: MulticamInfo };
export type TrackerSample = { s: number; x: number; y: number; scale: number; rot: number };
/** ردیابِ حرکت: مسیرِ یک نقطه/ناحیه در یک ویدیو (ثانیهٔ «منبع»، مرکز به‌صورتِ کسری از قابِ منبع) */
export type Tracker = {
  id: string; name: string; ref: string; size: [number, number]; region: { x: number; y: number; w: number; h: number };
  s0: number; s1: number; lost_at: number | null; engine: string; samples: TrackerSample[];
};

export type Project = {
  format: { width: number; height: number; fps: number; preset: string };
  tracks: Track[];
  global_ops: ProgramOp[];
  markers?: Marker[];
  inout?: { in: number; out: number } | null;
  master?: Master;
  ducking?: Ducking;
  export?: ExportBlock;
  sequences?: Record<string, Sequence>;
  trackers?: Tracker[];
  /** false ⇒ درازترشدنِ یک قطعه (کندکردن، تغییرِ سرعت، منحنیِ سرعت) قطعه‌های بعدی را جلو نمی‌برد؛ نبودن = روشن */
  auto_ripple?: boolean;
};

export const DEFAULT_DUCKING: Ducking = { on: false, amount_db: 12, threshold: 0.04, attack_ms: 40, release_ms: 500 };
export const DEFAULT_MASTER: Master = { gain_db: 0, limiter: true };
export const SOCIAL_LOUDNESS: Loudness = { on: true, target: -14, tp: -1 };

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
  // ترتیبِ آرایه = ترتیبِ لایه‌ها از پایین به بالا (سرور: اندیسِ بزرگ‌تر رویِ کوچک‌تر)؛ تایم‌لاین ترک‌های تصویر/متن را وارونه نشان می‌دهد.
  tracks: [
    { id: uid("t"), kind: "video", name: "تصویر ۱", muted: false, locked: false, clips: [] },
    { id: uid("t"), kind: "video", name: "تصویر ۲", muted: false, locked: false, clips: [] },
    { id: uid("t"), kind: "text", name: "متن", muted: false, locked: false, clips: [] },
    { id: uid("t"), kind: "audio", name: "صدا ۱", muted: false, locked: false, role: "speech", clips: [] },
    { id: uid("t"), kind: "audio", name: "موسیقی", muted: false, locked: false, role: "music", clips: [] },
  ],
  global_ops: [],
  markers: [],
  inout: null,
});

// ───────────── زمان‌بندیِ قطعه (همان timeline.py: Clip.length / segments)
/** سرعتِ هر تکه برای قطعه‌ای با منحنیِ سرعت؛ وگرنه یک عدد */
export function clipSpeeds(c: MediaClip): number[] {
  return c.ramp && c.ramp.length >= 2 && c.kind !== "image" && !c.freeze ? rampSpeeds(c.ramp) : [c.speed || 1];
}

export function clipLength(c: AnyClip): number {
  if (c.type === "text") return c.duration;
  if (c.freeze || c.kind === "image") return Math.max(0.04, c.end - c.start);
  const sp = clipSpeeds(c);
  const span = c.end - c.start;
  if (sp.length === 1) return Math.max(0.04, span / sp[0]);
  const step = span / sp.length;
  return Math.max(0.04, sp.reduce((s, v) => s + step / v, 0));
}
export const clipEnd = (c: AnyClip): number => c.at + clipLength(c);
export const projectLength = (p: Project): number => Math.max(0, ...p.tracks.flatMap((t) => t.clips.map(clipEnd)));
export const trackEnd = (t: Track): number => Math.max(0, ...t.clips.map(clipEnd));

/** ثانیه‌ای از «منبع» که در لحظهٔ `t` (تایم‌لاین) دیده می‌شود */
export function srcTimeAt(c: MediaClip, t: number): number {
  if (c.freeze) return c.start;
  if (c.kind === "image") return 0;
  const L = clipLength(c);
  let local = Math.max(0, Math.min(L, t - c.at));
  if (c.reverse) local = L - local;
  const sp = clipSpeeds(c);
  if (sp.length === 1) return c.start + local * sp[0];
  const step = (c.end - c.start) / sp.length;
  let cum = 0;
  for (let i = 0; i < sp.length; i++) {
    const dur = step / sp[i];
    if (local <= cum + dur) return c.start + i * step + (local - cum) * sp[i];
    cum += dur;
  }
  return c.end;
}

/** سرعتِ پخش در لحظهٔ `t` (برای element ِ ویدیو/صدا) */
export function speedAt(c: MediaClip, t: number): number {
  const sp = clipSpeeds(c);
  if (sp.length === 1) return sp[0];
  const L = clipLength(c);
  let local = Math.max(0, Math.min(L, t - c.at));
  if (c.reverse) local = L - local;
  const step = (c.end - c.start) / sp.length;
  let cum = 0;
  for (let i = 0; i < sp.length; i++) {
    const dur = step / sp[i];
    if (local <= cum + dur) return sp[i];
    cum += dur;
  }
  return sp[sp.length - 1];
}

/** مقدارِ یک کانالِ کلیدفریم‌شده (یا مقدارِ ثابتِ قطعه) در لحظهٔ `t` ِ تایم‌لاین */
export function propAt(c: MediaClip, ch: KfChannel, t: number): number {
  const base: Record<KfChannel, number> = {
    px: c.px ?? 0, py: c.py ?? 0, scale: c.scale ?? 1, rot: c.rot ?? 0, opacity: c.opacity, volume: c.volume,
    crop_l: c.crop?.l ?? 0, crop_r: c.crop?.r ?? 0, crop_t: c.crop?.t ?? 0, crop_b: c.crop?.b ?? 0,
  };
  return valueAt(c.kf?.[ch], t - c.at, base[ch]);
}

export function findClip(p: Project, id: string | null): { track: Track; clip: AnyClip } | null {
  if (!id) return null;
  for (const track of p.tracks) {
    const clip = track.clips.find((c) => c.id === id);
    if (clip) return { track, clip };
  }
  return null;
}

export const isMedia = (c: AnyClip | undefined | null): c is MediaClip => !!c && c.type === "media";

const map = (p: Project, fn: (t: Track) => Track): Project => ({ ...p, tracks: p.tracks.map(fn) });
const sortClips = (cs: AnyClip[]) => [...cs].sort((a, b) => a.at - b.at);

export function updateClip(p: Project, id: string, patch: Partial<MediaClip> | Partial<TextClip>): Project {
  return map(p, (t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? ({ ...c, ...patch } as AnyClip) : c)) }));
}
/** همان پچ را روی چند قطعه */
export function updateClips(p: Project, ids: string[], patch: Partial<MediaClip> | Partial<TextClip>): Project {
  const set = new Set(ids);
  return map(p, (t) => ({ ...t, clips: t.clips.map((c) => (set.has(c.id) ? ({ ...c, ...patch } as AnyClip) : c)) }));
}
export function updateTrack(p: Project, id: string, patch: Partial<Track>): Project {
  return map(p, (t) => (t.id === id ? { ...t, ...patch } : t));
}

/** آیا بازهٔ [at, at+len) روی این ترک با قطعه‌ای (جز `ignore`) برخورد دارد؟ */
export function overlaps(t: Track, at: number, len: number, ignore?: string | Set<string>): boolean {
  const skip = typeof ignore === "string" ? new Set([ignore]) : ignore;
  return t.clips.some((c) => !skip?.has(c.id) && at < clipEnd(c) - 0.001 && at + len > c.at + 0.001);
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

export function newMediaClip(item: MediaItem, at: number): MediaClip {
  const dur = item.kind === "image" ? 5 : Math.max(0.5, item.duration || 5);
  return {
    id: uid(), type: "media", ref: item.ref, label: item.title, kind: item.kind, at, start: 0, end: dur,
    src: item.kind === "image" ? 0 : item.duration, opacity: 1, x: 0, y: 0, width: 1, height: 1, volume: 1, speed: 1,
    fit: "cover", fade_in: 0, fade_out: 0, audio_on: true, has_audio: item.has_audio, effects: [], transition: null,
  };
}

export function addMedia(p: Project, trackId: string, item: MediaItem, at: number): Project {
  const track = p.tracks.find((t) => t.id === trackId);
  if (!track) return p;
  const clip = newMediaClip(item, 0);
  const spot = freeSpot(track, at, clipLength(clip));
  if (spot === null) return p;
  clip.at = spot;
  return map(p, (t) => (t.id === trackId ? { ...t, clips: sortClips([...t.clips, clip]) } : t));
}

export function newTextClip(text: string, at: number, duration = 2.5): TextClip {
  return { id: uid(), type: "text", text, at, duration, position: "bottom", size: 6, color: "#ffffff", box: true, opacity: 1, label: text.slice(0, 20) };
}

export function addText(p: Project, trackId: string, text: string, at: number, duration = 2.5, extra: Partial<TextClip> = {}): Project {
  const track = p.tracks.find((t) => t.id === trackId);
  if (!track) return p;
  const spot = freeSpot(track, at, duration);
  if (spot === null) return p;
  const clip: TextClip = { ...newTextClip(text, spot, duration), ...extra, at: spot, duration };
  return map(p, (t) => (t.id === trackId ? { ...t, clips: sortClips([...t.clips, clip]) } : t));
}

/** چند قطعهٔ آماده (مثلاً زیرنویسِ خودکار) را روی یک ترکِ متن می‌گذارد؛ ترکِ تازه‌ای می‌سازد اگر `trackId` خالی باشد */
export function addTextClips(p: Project, trackId: string | null, clips: Partial<TextClip>[], opts: { caption?: boolean } = {}): Project {
  let next = p;
  let tid = trackId;
  if (!tid) {
    next = addTrack(next, "text");
    const made = next.tracks.filter((t) => t.kind === "text").slice(-1)[0];
    tid = made.id;
    if (opts.caption) next = updateTrack(next, tid, { caption: true, name: "زیرنویس" });
  }
  const track = next.tracks.find((t) => t.id === tid);
  if (!track) return p;
  const made: TextClip[] = clips.map((c) => ({ ...newTextClip(c.text ?? "", c.at ?? 0, c.duration ?? 2), ...c, id: uid(), type: "text" }) as TextClip);
  return map(next, (t) => (t.id === tid ? { ...t, clips: sortClips([...t.clips, ...made]) } : t));
}

export function addTrack(p: Project, kind: Track["kind"], role: TrackRole = ""): Project {
  const n = p.tracks.filter((t) => t.kind === kind).length + 1;
  const name = { video: `تصویر ${n}`, audio: `صدا ${n}`, text: `متن ${n}` }[kind];
  const track: Track = { id: uid("t"), kind, name, muted: false, locked: false, ...(role ? { role } : {}), clips: [] };
  // ترکِ تصویرِ تازه رویِ ترک‌های تصویر (و زیرِ متن)؛ ترکِ متن بالاتر از همه؛ صدا در پایین
  const kinds = p.tracks.map((t) => t.kind);
  let at: number;
  if (kind === "audio") at = p.tracks.length;
  else if (kind === "video") at = kinds.lastIndexOf("video") + 1;
  else at = Math.max(kinds.lastIndexOf("video"), kinds.lastIndexOf("text")) + 1;
  return { ...p, tracks: [...p.tracks.slice(0, at), track, ...p.tracks.slice(at)] };
}

export function removeTrack(p: Project, id: string): Project {
  const t = p.tracks.find((x) => x.id === id);
  if (!t || (p.tracks.filter((x) => x.kind === t.kind).length <= 1 && t.kind === "video")) return p;
  return { ...p, tracks: p.tracks.filter((x) => x.id !== id) };
}

/** ترکِ «اصلیِ تصویر» برای سرور = اولین ترکِ تصویر در آرایه (پایین‌ترین لایه). در UI ترک‌ها از بالا به پایین‌اند؛ لایهٔ بالاتر = ایندکسِ بزرگ‌تر. */
export const mainVideoTrack = (p: Project): Track | undefined => p.tracks.find((t) => t.kind === "video");

// ───────────── گروهِ پیوندی (صدا/تصویرِ جداشده)
export function withLinked(p: Project, ids: string[]): string[] {
  const links = new Set<string>();
  const all = p.tracks.flatMap((t) => t.clips);
  for (const id of ids) {
    const c = all.find((x) => x.id === id);
    if (c && c.type === "media" && c.link) links.add(c.link);
  }
  if (links.size === 0) return ids;
  const out = new Set(ids);
  for (const c of all) if (c.type === "media" && c.link && links.has(c.link)) out.add(c.id);
  return [...out];
}

/** صدای قطعهٔ ویدیو را جدا می‌کند: یک قطعهٔ صدا روی ترکِ صدا (هم‌زمان، پیوندی) و صدای خودِ ویدیو خاموش می‌شود. ⇒ J/L-cut با کشیدنِ جداگانه */
export function extractAudio(p: Project, id: string): Project {
  const f = findClip(p, id);
  if (!f || f.clip.type !== "media" || f.clip.kind !== "video" || !f.clip.has_audio || !f.clip.audio_on) return p;
  const c = f.clip;
  const link = c.link || uid("L");
  const dest = p.tracks.filter((t) => t.kind === "audio" && !t.locked).find((t) => !overlaps(t, c.at, clipLength(c)));
  let next = p;
  let tid = dest?.id;
  if (!tid) {
    next = addTrack(next, "audio", "speech");
    tid = next.tracks.filter((t) => t.kind === "audio").slice(-1)[0].id;
  }
  const a: MediaClip = { ...c, id: uid(), kind: "audio", label: `${c.label} (صدا)`, link, transition: null, effects: [], kf: c.kf?.volume ? { volume: c.kf.volume } : undefined,
    color: undefined, chroma: undefined, mask: undefined, crop: undefined, blend: undefined, rot: undefined, scale: undefined, px: undefined, py: undefined, flip_h: undefined, flip_v: undefined,
    x: 0, y: 0, width: 1, height: 1, opacity: 1, fit: "cover", audio_on: true, has_audio: true };
  next = updateClip(next, id, { audio_on: false, link });
  return map(next, (t) => (t.id === tid ? { ...t, clips: sortClips([...t.clips, a]) } : t));
}

export function unlinkClips(p: Project, ids: string[]): Project {
  const set = new Set(withLinked(p, ids));
  return map(p, (t) => ({ ...t, clips: t.clips.map((c) => (set.has(c.id) && c.type === "media" ? { ...c, link: undefined } : c)) }));
}

export function linkClips(p: Project, ids: string[]): Project {
  const link = uid("L");
  const set = new Set(ids);
  return map(p, (t) => ({ ...t, clips: t.clips.map((c) => (set.has(c.id) && c.type === "media" ? { ...c, link } : c)) }));
}

// ───────────── جابه‌جایی
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

/** چند قطعه با هم، به اندازهٔ `dt` ثانیه (و `rows` ترک بالا/پایین هم‌نوع). اگر برخورد کند همان پروژه برمی‌گردد. */
export function moveClips(p: Project, ids: string[], dt: number, rows = 0): Project {
  const set = new Set(ids);
  const picked = p.tracks.flatMap((t, ti) => t.clips.filter((c) => set.has(c.id)).map((c) => ({ c, ti })));
  if (picked.length === 0) return p;
  const minAt = Math.min(...picked.map((x) => x.c.at));
  const d = Math.max(dt, -minAt);
  const byTrack = new Map<string, AnyClip[]>();
  for (const { c, ti } of picked) {
    const track = p.tracks[ti];
    let target = track;
    if (rows !== 0) {
      const same = p.tracks.filter((t) => t.kind === track.kind && !t.locked);
      const i = same.findIndex((t) => t.id === track.id);
      target = same[Math.max(0, Math.min(same.length - 1, i + rows))] ?? track;
    }
    if (target.locked) return p;
    byTrack.set(target.id, [...(byTrack.get(target.id) ?? []), { ...c, at: c.at + d } as AnyClip]);
  }
  for (const [tid, cs] of byTrack) {
    const t = p.tracks.find((x) => x.id === tid)!;
    for (const c of cs) if (overlaps(t, c.at, clipLength(c), set)) return p;
    for (let i = 0; i < cs.length; i++) for (let j = i + 1; j < cs.length; j++) if (cs[i].at < clipEnd(cs[j]) - 0.001 && cs[j].at < clipEnd(cs[i]) - 0.001) return p;
  }
  return map(p, (t) => {
    const rest = t.clips.filter((c) => !set.has(c.id));
    const add = byTrack.get(t.id) ?? [];
    return rest.length === t.clips.length && add.length === 0 ? t : { ...t, clips: sortClips([...rest, ...add]) };
  });
}

// ───────────── برشِ لبه‌ها
/** پایانِ قطعهٔ پیشین روی همان ترک (لبه‌ای که این قطعه نمی‌تواند از آن عقب‌تر برود) */
const prevEdge = (tr: Track, c: AnyClip): number => Math.max(0, ...tr.clips.filter((x) => x.id !== c.id && clipEnd(x) <= c.at + 0.001).map(clipEnd));
/** آغازِ قطعهٔ بعدی روی همان ترک */
const nextEdge = (tr: Track, c: AnyClip): number => Math.min(Infinity, ...tr.clips.filter((x) => x.id !== c.id && x.at >= clipEnd(c) - 0.001).map((x) => x.at));

/** لبهٔ چپِ قطعه را به `t` ببر (برش از ابتدا): شروعِ منبع جلو می‌رود. `free` = از همسایه رد نشدن را وارسی نکن (ریپل/رول/اسلاید خودشان جبران می‌کنند). */
export function trimStart(p: Project, id: string, t: number, free = false): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  if (!free) t = Math.max(t, prevEdge(f.track, c));
  if (c.type === "text") {
    const next = Math.max(0, Math.min(clipEnd(c) - 0.1, t));
    return updateClip(p, id, { at: next, duration: c.duration - (next - c.at) });
  }
  if (c.kind === "image" || c.freeze) {
    const next = Math.max(0, Math.min(clipEnd(c) - 0.1, t));
    return updateClip(p, id, { at: next, end: c.end - (next - c.at), ...(c.freeze ? {} : {}) });
  }
  const spd = c.ramp && c.ramp.length >= 2 ? clipSpeeds(c)[0] : c.speed || 1;
  // بیشترین جلو آمدنِ ممکن به عقب = منبعی که پشتِ نقطهٔ شروع هست
  const room = c.reverse ? (c.src ? c.src - c.end : Infinity) : c.start;
  const minAt = c.at - room / (c.ramp?.length ? 1 : spd);
  const next = Math.max(minAt, Math.min(clipEnd(c) - 0.1, Math.max(0, t)));
  if (c.ramp && c.ramp.length >= 2) {
    // با منحنیِ سرعت: نقطهٔ شروع/پایان را از روی نگاشتِ زمان→منبع برمی‌داریم
    const s = srcTimeAt(c, Math.max(c.at, next));
    return c.reverse ? updateClip(p, id, { at: Math.max(0, next), end: s }) : updateClip(p, id, { at: Math.max(0, next), start: s });
  }
  const d = next - c.at;
  return c.reverse ? updateClip(p, id, { at: next, end: c.end - d * spd }) : updateClip(p, id, { at: next, start: c.start + d * spd });
}

/** لبهٔ راستِ قطعه را به `t` ببر (تا قطعهٔ بعدی؛ بیشتر از آن فقط با `free`) */
export function trimEnd(p: Project, id: string, t: number, free = false): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  if (!free) t = Math.min(t, nextEdge(f.track, c));
  const minEnd = c.at + 0.1;
  if (c.type === "text") return updateClip(p, id, { duration: Math.max(minEnd, t) - c.at });
  if (c.kind === "image" || c.freeze) return updateClip(p, id, { end: c.start + (Math.max(minEnd, t) - c.at) });
  if (c.ramp && c.ramp.length >= 2) {
    const next = Math.max(minEnd, Math.min(clipEnd(c), t));
    const s = srcTimeAt(c, next);
    return c.reverse ? updateClip(p, id, { start: s }) : updateClip(p, id, { end: s });
  }
  const spd = c.speed || 1;
  if (c.reverse) {
    const maxEnd = c.at + c.start / spd;
    const next = Math.max(minEnd, Math.min(maxEnd, t));
    return updateClip(p, id, { start: c.end - (next - c.at) * spd });
  }
  const maxEnd = c.src ? c.at + (c.src - c.start) / spd : Infinity;
  const next = Math.max(minEnd, Math.min(maxEnd, t));
  return updateClip(p, id, { end: c.start + (next - c.at) * spd });
}

/** ریپل: لبه را ببر و قطعه‌های بعدیِ همان ترک را به همان اندازه جابه‌جا کن */
export function rippleTrim(p: Project, id: string, side: "l" | "r", t: number): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const before = clipEnd(f.clip);
  const startAt = f.clip.at;
  const q = side === "l" ? trimStart(p, id, t, true) : trimEnd(p, id, t, true);
  const g = findClip(q, id);
  if (!g) return p;
  // لبهٔ راست: بقیه به اندازهٔ تغییرِ طول؛ لبهٔ چپ: قطعه سرِ جایش (startAt) می‌ماند و بقیه به اندازهٔ تغییرِ طول
  const delta = clipEnd(g.clip) - before;
  const moved = side === "l" ? updateClip(q, id, { at: startAt } as Partial<MediaClip>) : q;
  return map(moved, (tr) => (tr.id !== f.track.id ? tr : { ...tr, clips: sortClips(tr.clips.map((c) => (c.id !== id && c.at >= before - 0.001 ? ({ ...c, at: Math.max(0, c.at + delta) } as AnyClip) : c))) }));
}

/** Roll: برشِ بینِ دو قطعهٔ چسبیده را به `t` ببر (قطعهٔ چپ طولانی‌تر می‌شود، راست کوتاه‌تر) */
export function rollEdit(p: Project, leftId: string, rightId: string, t: number): Project {
  const l = findClip(p, leftId);
  const r = findClip(p, rightId);
  if (!l || !r || l.clip.type !== "media" || r.clip.type !== "media") return p;
  const cut = clipEnd(l.clip);
  const lo = l.clip.at + 0.1;
  const hi = clipEnd(r.clip) - 0.1;
  const nt = Math.max(lo, Math.min(hi, t));
  const a = trimEnd(p, leftId, nt, true);
  const la = findClip(a, leftId);
  if (!la) return p;
  const got = clipEnd(la.clip);
  if (Math.abs(got - cut) < 0.001) return p;
  return trimStart(a, rightId, got, true);
}

/** Slip: همان طول و جا؛ فقط بازهٔ منبع به اندازهٔ `dSrc` ثانیه جابه‌جا می‌شود */
export function slipClip(p: Project, id: string, dSrc: number): Project {
  const f = findClip(p, id);
  if (!f || f.clip.type !== "media" || f.clip.kind === "image" || f.clip.freeze) return p;
  const c = f.clip;
  const len = c.end - c.start;
  const lo = -c.start;
  const hi = c.src ? c.src - c.end : Infinity;
  const d = Math.max(lo, Math.min(hi, dSrc));
  return updateClip(p, id, { start: c.start + d, end: c.start + d + len });
}

/** Slide: قطعه را جابه‌جا کن؛ قطعهٔ قبلی دراز/کوتاه و قطعهٔ بعدی کوتاه/دراز می‌شود (طولِ کل ثابت) */
export function slideClip(p: Project, id: string, dt: number): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  const prev = f.track.clips.find((x) => Math.abs(clipEnd(x) - c.at) < 0.06 && x.id !== id);
  const next = f.track.clips.find((x) => Math.abs(x.at - clipEnd(c)) < 0.06 && x.id !== id);
  if (!prev && !next) return p;
  let d = dt;
  if (prev) d = Math.max(d, -(clipLength(prev) - 0.1));
  if (next) d = Math.min(d, clipLength(next) - 0.1);
  if (!prev) d = Math.max(d, -c.at);
  if (Math.abs(d) < 1e-4) return p;
  let q = p;
  if (prev) q = trimEnd(q, prev.id, clipEnd(prev) + d, true);
  if (next) q = trimStart(q, next.id, next.at + d, true);
  return updateClip(q, id, { at: c.at + d } as Partial<MediaClip>);
}

/** Rate Stretch: قطعه را طوری سرعت بده که طولش `newLen` شود (منبع همان) */
export function rateStretch(p: Project, id: string, newLen: number): Project {
  const f = findClip(p, id);
  if (!f || f.clip.type !== "media" || f.clip.kind === "image" || f.clip.freeze) return p;
  const c = f.clip;
  const speed = Math.max(0.25, Math.min(4, (c.end - c.start) / Math.max(0.1, newLen)));
  return updateClip(p, id, { speed: Math.round(speed * 1000) / 1000, ramp: undefined });
}

// ───────────── تقسیم، حذف، تکرار
const sliceKf = (kf: Kf | undefined, t0: number, t1: number): Kf | undefined => {
  if (!kf) return kf;
  const out: Kf = {};
  for (const ch of Object.keys(kf) as KfChannel[]) {
    const s = sliceKeys(kf[ch], t0, t1);
    if (s) out[ch] = s;
  }
  return out;
};

/** تقسیم در زمانِ `t` (S / Ctrl+K). ⇐ پروژهٔ تازه؛ اگر `t` داخلِ قطعه نبود همان پروژه.
 *  `links`: نگاشتِ پیوندِ قدیم ⇒ پیوندِ تازهٔ نیمهٔ راست. بدونِ آن نیمهٔ راست از جفتش جدا می‌شود؛ با آن (splitMany) نیمه‌های راستِ صدا و تصویر
 *  با هم پیوند می‌مانند و به نیمهٔ چپ نمی‌چسبند — وگرنه کشیدنِ یک نیمه هر چهار قطعه را می‌برد و J/L جفتِ غلط را می‌گرفت. */
export function splitAt(p: Project, id: string, t: number, links?: Map<string, string>): Project {
  const f = findClip(p, id);
  if (!f) return p;
  const c = f.clip;
  if (t <= c.at + 0.05 || t >= clipEnd(c) - 0.05) return p;
  const L = clipLength(c);
  const lt = t - c.at;
  let left: AnyClip;
  let right: AnyClip;
  if (c.type === "text") {
    left = { ...c, duration: lt };
    right = { ...c, id: uid(), at: t, duration: c.duration - lt };
    if (c.words) {
      left = { ...left, words: c.words.filter((w) => w.s < lt).map((w) => ({ ...w, e: Math.min(w.e, lt) })) } as TextClip;
      right = { ...right, words: c.words.filter((w) => w.e > lt).map((w) => ({ ...w, s: Math.max(0, w.s - lt), e: w.e - lt })) } as TextClip;
    }
  } else if (c.kind === "image" || c.freeze) {
    left = { ...c, end: c.start + lt, fade_out: 0, kf: sliceKf(c.kf, 0, lt) };
    right = { ...c, id: uid(), at: t, end: c.start + (L - lt), transition: null, fade_in: 0, link: c.link, kf: sliceKf(c.kf, lt, L) };
  } else {
    const s = srcTimeAt(c, t);
    let lEnd = c.end, lStart = c.start, rEnd = c.end, rStart = c.start;
    let lRamp = c.ramp, rRamp = c.ramp;
    if (c.reverse) {
      // لبهٔ چپ در تایم‌لاین = بخشِ آخرِ منبع
      lStart = s; rEnd = s;
      if (c.ramp && c.ramp.length >= 2) {
        const pf = (s - c.start) / (c.end - c.start);
        lRamp = sliceRamp(c.ramp, pf, 1);
        rRamp = sliceRamp(c.ramp, 0, pf);
      }
    } else {
      lEnd = s; rStart = s;
      if (c.ramp && c.ramp.length >= 2) {
        const pf = (s - c.start) / (c.end - c.start);
        lRamp = sliceRamp(c.ramp, 0, pf);
        rRamp = sliceRamp(c.ramp, pf, 1);
      }
    }
    left = { ...c, start: lStart, end: lEnd, fade_out: 0, kf: sliceKf(c.kf, 0, lt), ramp: lRamp };
    right = { ...c, id: uid(), at: t, start: rStart, end: rEnd, transition: null, fade_in: 0, kf: sliceKf(c.kf, lt, L), ramp: rRamp };
  }
  if (right.type === "media") {
    const old = (c as MediaClip).link;
    let next: string | undefined;
    if (old && links) {
      if (!links.has(old)) links.set(old, uid("L"));
      next = links.get(old);
    }
    right = { ...right, link: next };
  }
  return map(p, (tr) => (tr.id === f.track.id ? { ...tr, clips: sortClips(tr.clips.map((x) => (x.id === id ? left : x)).concat(right)) } : tr));
}

/** چند قطعه (مثلاً یک جفتِ صدا/تصویر) را با هم در `t` می‌شکافد؛ نیمه‌های راست جفتِ تازهٔ خودشان را می‌سازند. */
export function splitMany(p: Project, ids: string[], t: number): Project {
  const links = new Map<string, string>();
  let next = p;
  for (const id of ids) next = splitAt(next, id, t, links);
  return next;
}

/** حذف. `ripple` ⇒ قطعه‌های بعدیِ همان ترک جلو می‌آیند. قطعه‌های پیوندی با هم می‌روند. */
export function deleteClips(p: Project, ids: string[], ripple: boolean): Project {
  const all = new Set(withLinked(p, ids));
  let next = p;
  const gone = p.tracks.flatMap((t) => t.clips.filter((c) => all.has(c.id)).map((c) => ({ tid: t.id, at: c.at, len: clipLength(c) })));
  next = map(next, (t) => ({ ...t, clips: t.clips.filter((c) => !all.has(c.id)) }));
  if (ripple) {
    for (const g of gone.sort((a, b) => b.at - a.at)) {
      next = map(next, (t) => (t.id !== g.tid ? t : { ...t, clips: t.clips.map((c) => (c.at >= g.at ? ({ ...c, at: Math.max(0, c.at - g.len) } as AnyClip) : c)) }));
    }
  }
  return next;
}
export const deleteClip = (p: Project, id: string, ripple: boolean): Project => deleteClips(p, [id], ripple);

/** «بازه‌ای را بردار»: همهٔ ترک‌های بازِ [a,b) از قطعه‌ها خالی و (اگر ripple) بسته می‌شود */
export function liftRange(p: Project, a: number, b: number, ripple: boolean): Project {
  let q = p;
  for (const tr of p.tracks) {
    if (tr.locked) continue;
    for (const c of tr.clips) {
      if (c.type === "media" || c.type === "text") {
        if (clipEnd(c) > a + 0.05 && c.at < b - 0.05) {
          if (c.at < a) q = splitMany(q, [c.id], a);
        }
      }
    }
  }
  for (const tr of q.tracks) {
    if (tr.locked) continue;
    for (const c of tr.clips) if (clipEnd(c) > b + 0.05 && c.at < b - 0.05) q = splitMany(q, [c.id], b);
  }
  const ids = q.tracks.flatMap((t) => (t.locked ? [] : t.clips.filter((c) => c.at >= a - 0.02 && clipEnd(c) <= b + 0.02).map((c) => c.id)));
  q = deleteClips(q, ids, false);
  if (ripple) {
    const d = b - a;
    q = map(q, (t) => (t.locked ? t : { ...t, clips: t.clips.map((c) => (c.at >= b - 0.02 ? ({ ...c, at: Math.max(0, c.at - d) } as AnyClip) : c)) }));
  }
  return q;
}

export function duplicateClips(p: Project, ids: string[]): Project {
  const set = new Set(withLinked(p, ids));
  let q = p;
  const remap = new Map<string, string>();
  for (const t of p.tracks) {
    for (const c of t.clips) {
      if (!set.has(c.id)) continue;
      const tr = q.tracks.find((x) => x.id === t.id)!;
      const spot = freeSpot(tr, clipEnd(c), clipLength(c));
      if (spot === null) continue;
      const link = c.type === "media" && c.link ? (remap.get(c.link) ?? (remap.set(c.link, uid("L")), remap.get(c.link))) : undefined;
      const copy = { ...c, id: uid(), at: spot, ...(link ? { link } : {}) } as AnyClip;
      q = map(q, (x) => (x.id === t.id ? { ...x, clips: sortClips([...x.clips, copy]) } : x));
    }
  }
  return q;
}
export const duplicateClip = (p: Project, id: string): Project => duplicateClips(p, [id]);

/** Alt+کشیدن: نسخه‌ای از قطعه در همان جا بگذار و نسخهٔ تازه را برگردان (برای کشیدن) */
export function cloneInPlace(p: Project, id: string): { project: Project; newId: string } | null {
  const f = findClip(p, id);
  if (!f) return null;
  const copy = { ...f.clip, id: uid(), link: undefined } as AnyClip;
  return { project: map(p, (t) => (t.id === f.track.id ? { ...t, clips: sortClips([...t.clips, copy]) } : t)), newId: copy.id };
}

/** Freeze frame: در `t` قطعه را می‌شکافد، فریمِ آن لحظه را `hold` ثانیه نگه می‌دارد و بقیه را عقب می‌برد */
export function freezeFrameAt(p: Project, id: string, t: number, hold = 2): Project {
  const f = findClip(p, id);
  if (!f || f.clip.type !== "media" || f.clip.kind !== "video") return p;
  const c = f.clip;
  if (t < c.at - 0.001 || t > clipEnd(c) + 0.001) return p;
  const s = srcTimeAt(c, t);
  let q = splitAt(p, id, Math.min(Math.max(t, c.at + 0.06), clipEnd(c) - 0.06));
  const cut = Math.min(Math.max(t, c.at + 0.06), clipEnd(c) - 0.06);
  q = map(q, (tr) => (tr.id !== f.track.id ? tr : { ...tr, clips: tr.clips.map((x) => (x.id !== id && x.at >= cut - 0.001 ? ({ ...x, at: x.at + hold } as AnyClip) : x)) }));
  const fr: MediaClip = {
    ...c, id: uid(), at: cut, start: s, end: s + hold, speed: 1, freeze: true, reverse: false, ramp: undefined, transition: null,
    fade_in: 0, fade_out: 0, audio_on: false, link: undefined, kf: undefined, label: `${c.label} (فریمِ ثابت)`,
  };
  return map(q, (tr) => (tr.id === f.track.id ? { ...tr, clips: sortClips([...tr.clips, fr]) } : tr));
}

// ───────────── کپی/پیستِ ویژگی‌ها
export type AttrGroup = "transform" | "color" | "effects" | "audio" | "chroma" | "blend" | "speed";
export const ATTR_GROUPS: { key: AttrGroup; title: string }[] = [
  { key: "transform", title: "جابه‌جایی / اندازه / چرخش / شفافیت / برش" },
  { key: "color", title: "رنگ (Lumetri)" },
  { key: "effects", title: "افکت‌ها" },
  { key: "chroma", title: "کلیدِ رنگی (Chroma key)" },
  { key: "blend", title: "حالتِ ترکیب" },
  { key: "audio", title: "صدا (بلندی، EQ، پن)" },
  { key: "speed", title: "سرعت" },
];

export type AttrClip = Partial<MediaClip>;

export function copyAttrs(c: MediaClip, groups: AttrGroup[]): AttrClip {
  const out: AttrClip = {};
  if (groups.includes("transform")) Object.assign(out, { opacity: c.opacity, rot: c.rot, scale: c.scale, px: c.px, py: c.py, flip_h: c.flip_h, flip_v: c.flip_v, crop: c.crop, mask: c.mask,
    kf: c.kf ? Object.fromEntries(Object.entries(c.kf).filter(([k]) => k !== "volume")) as Kf : undefined, x: c.x, y: c.y, width: c.width, height: c.height, fit: c.fit });
  if (groups.includes("color")) out.color = c.color;
  if (groups.includes("effects")) out.effects = c.effects;
  if (groups.includes("chroma")) out.chroma = c.chroma;
  if (groups.includes("blend")) out.blend = c.blend;
  if (groups.includes("audio")) {
    out.volume = c.volume;
    out.audio = c.audio;
    if (c.kf?.volume) out.kf = { ...(out.kf ?? {}), volume: c.kf.volume };
  }
  if (groups.includes("speed")) Object.assign(out, { speed: c.speed, ramp: c.ramp, reverse: c.reverse });
  return out;
}

export function pasteAttrs(p: Project, ids: string[], attrs: AttrClip): Project {
  const set = new Set(ids);
  return map(p, (t) => ({ ...t, clips: t.clips.map((c) => (set.has(c.id) && c.type === "media" ? ({ ...c, ...JSON.parse(JSON.stringify(attrs)) } as MediaClip) : c)) }));
}

// ───────────── نشانگرها
export function addMarker(p: Project, t: number, label = "", kind: Marker["kind"] = "marker"): Project {
  const color = kind === "beat" ? "#38bdf8" : kind === "chapter" ? "#a78bfa" : "#facc15";
  const ms = (p.markers ?? []).filter((m) => Math.abs(m.t - t) > 0.04);
  return { ...p, markers: [...ms, { id: uid("m"), t: Math.max(0, t), label, color, kind }].sort((a, b) => a.t - b.t).slice(0, 400) };
}
export const removeMarker = (p: Project, id: string): Project => ({ ...p, markers: (p.markers ?? []).filter((m) => m.id !== id) });
export const clearMarkers = (p: Project, kind?: Marker["kind"]): Project => ({ ...p, markers: (p.markers ?? []).filter((m) => (kind ? m.kind !== kind : false)) });

// ───────────── چسبیدن (snap)
/** نقطه‌هایی که قطعه به آن‌ها می‌چسبد (snap): صفر، سرِ پخش، نشانگرها، ورودی/خروجی، لبهٔ همهٔ قطعه‌ها */
export function snapPoints(p: Project, playhead: number, ignore?: string | Set<string>): number[] {
  const skip = typeof ignore === "string" ? new Set([ignore]) : ignore;
  const pts = [0, playhead];
  for (const m of p.markers ?? []) pts.push(m.t);
  if (p.inout) pts.push(p.inout.in, p.inout.out);
  for (const t of p.tracks) for (const c of t.clips) if (!skip?.has(c.id)) pts.push(c.at, clipEnd(c));
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
    ...d,
    format: { ...base.format, ...(d.format ?? {}) },
    tracks: d.tracks.map((t) => ({
      ...t,
      id: t.id ?? uid("t"), kind: t.kind ?? "video", name: t.name ?? "", muted: !!t.muted, locked: !!t.locked,
      clips: (t.clips ?? []).map((c) => ({ ...c, id: c.id ?? uid() }) as AnyClip),
    })),
    global_ops: (d.global_ops ?? []).map((o) => ({ id: (o as ProgramOp).id ?? uid("g"), tool: o.tool, params: o.params ?? {} })),
    markers: d.markers ?? [],
    inout: d.inout ?? null,
  };
}

// ───────────── ابزارهای برشِ فریمی و خطِ بلندی (تایم‌لاین)
const clampN = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

/** زمان را به نزدیک‌ترین فریم گرد می‌کند (۱/fps). */
export function quantize(t: number, fps: number): number {
  const f = fps > 0 ? fps : 30;
  return Math.round(t * f) / f;
}

/** اگر `t` تا نویزِ ممیزِ شناور روی فریم است همان فریم را برمی‌گرداند؛ وگرنه خودِ `t` (چسبیدن به لبهٔ بی‌فریم، بی‌شکاف می‌ماند). */
export function tidyFrame(t: number, fps: number): number {
  const q = quantize(t, fps);
  return Math.abs(q - t) < 0.002 ? q : t;
}

/** تعدادِ فریمِ (با علامت) از زمانِ `a` تا `b`. */
export function framesBetween(a: number, b: number, fps: number): number {
  return Math.round((b - a) * (fps > 0 ? fps : 30));
}

/** همسایهٔ چسبیدهٔ یک لبه روی همان ترک (برای رول): جفتِ { l: قطعهٔ چپ, r: قطعهٔ راست } یا null اگر لبه به چیزی نچسبیده. */
export function touchingPair(p: Project, id: string, side: "l" | "r"): { l: string; r: string } | null {
  const f = findClip(p, id);
  if (!f) return null;
  const c = f.clip;
  const sorted = [...f.track.clips].sort((a, b) => a.at - b.at);
  const i = sorted.findIndex((x) => x.id === id);
  const other = side === "l" ? sorted[i - 1] : sorted[i + 1];
  if (!other || other.type !== "media" || c.type !== "media") return null;
  const gap = side === "l" ? c.at - clipEnd(other) : other.at - clipEnd(c);
  if (Math.abs(gap) >= 0.06) return null;
  return side === "l" ? { l: other.id, r: id } : { l: id, r: other.id };
}

/** جابه‌جاییِ فریم‌به‌فریم: `pos` = خودِ قطعه‌ها، `l`/`r` = لبهٔ شروع/پایان. قطعه‌های پیوندی هم می‌روند؛ `frames` می‌تواند منفی باشد؛ جابه‌جایی همیشه روی شبکهٔ فریم می‌نشیند. */
export function nudgeEdge(p: Project, ids: string[], side: "pos" | "l" | "r", frames: number, fps: number): Project {
  const group = withLinked(p, ids);
  const d = frames / (fps > 0 ? fps : 30);
  if (side === "pos") {
    const lead = findClip(p, ids[ids.length - 1] ?? group[0]) ?? findClip(p, group[0]);
    if (!lead) return p;
    const dt = quantize(lead.clip.at + d, fps) - lead.clip.at;
    return Math.abs(dt) < 1e-6 ? p : moveClips(p, group, dt);
  }
  let q = p;
  for (const id of group) {
    const f = findClip(q, id);
    if (!f) continue;
    q = side === "l" ? trimStart(q, id, quantize(f.clip.at + d, fps)) : trimEnd(q, id, quantize(clipEnd(f.clip) + d, fps));
  }
  return q;
}

/** پایین‌ترین بلندیِ خط (−∞ = بی‌صدا) و بالاترینِ آن (بالای قطعه = +۶ dB)؛ همان MIN_DB ِ پنلِ صدا. */
export const VOL_MIN_DB = -60;
export const VOL_TOP_DB = 6;
/** نقطه‌های (dB، کسرِ ارتفاع از بالا) که خطِ بلندی از آن‌ها می‌گذرد؛ ۰ dB حدودِ ۶۵٪ ارتفاع از پایین است. */
const VOL_STOPS: [number, number][] = [[6, 0], [0, 0.35], [-6, 0.5], [-12, 0.62], [-24, 0.8], [-48, 0.95], [-60, 1]];

/** بلندیِ خطی (۰..۳) ⇐ dB (همان linToDb ِ پنلِ صدا). */
export const volLinToDb = (lin: number): number => (lin <= 0.001 ? VOL_MIN_DB : clampN(20 * Math.log10(lin), VOL_MIN_DB, 9.5));
/** dB ⇐ بلندیِ خطی (۰..۳)؛ نزدیکِ −۶۰ dB یعنی بی‌صدا. */
export const volDbToLin = (db: number): number => (db <= VOL_MIN_DB + 0.5 ? 0 : clampN(Math.pow(10, db / 20), 0, 3));

/** dB ⇐ کسرِ ارتفاع از بالای قطعه (۰ = بالا، ۱ = پایین). */
export function volDbToFrac(db: number): number {
  if (db >= VOL_STOPS[0][0]) return 0;
  for (let i = 0; i + 1 < VOL_STOPS.length; i++) {
    const [d0, f0] = VOL_STOPS[i];
    const [d1, f1] = VOL_STOPS[i + 1];
    if (db >= d1) return f0 + ((d0 - db) / (d0 - d1)) * (f1 - f0);
  }
  return 1;
}
/** کسرِ ارتفاع از بالا ⇐ dB (۳٪ آخرِ پایین = بی‌صدا). */
export function volFracToDb(f: number): number {
  const x = clampN(f, 0, 1);
  if (x >= 0.97) return VOL_MIN_DB;
  for (let i = 0; i + 1 < VOL_STOPS.length; i++) {
    const [d0, f0] = VOL_STOPS[i];
    const [d1, f1] = VOL_STOPS[i + 1];
    if (x <= f1) return d0 + ((x - f0) / (f1 - f0)) * (d1 - d0);
  }
  return VOL_MIN_DB;
}
/** بلندیِ خطی ⇐ کسرِ ارتفاع از بالا. */
export const volToFrac = (lin: number): number => volDbToFrac(volLinToDb(lin));
/** dB را به گام‌های ۰٫۵ گرد می‌کند و نزدیکِ ۰ dB به خودِ ۰ می‌چسباند. */
export const snapDb = (db: number): number => (db <= VOL_MIN_DB + 0.5 ? VOL_MIN_DB : Math.abs(db) < 0.75 ? 0 : Math.round(db * 2) / 2);

/** بیشترین محوِ مجازِ یک قطعه (ثانیه): min(۱۰، نصفِ طول). */
export const fadeMax = (len: number): number => Math.max(0.05, Math.min(10, len / 2));
/** محو را به گام‌های ۰٫۰۵ ثانیه گرد و در [۰، fadeMax] نگه می‌دارد. */
export const snapFade = (v: number, len: number): number => (clampN(Math.round(v / 0.05), 0, Math.floor(fadeMax(len) / 0.05 + 1e-6)) * 5) / 100;

export { shiftKeys, RAMP_STEPS };
