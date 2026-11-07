import { pathOf } from "./bezier";
import { applyColor, applyPostFx, blurPx, colorIsNeutral, postFx, type LookDef } from "./color";
import { valueAt } from "./keyframes";
import { applyLut, type Lut } from "./lut";
import {
  AnyClip, Effect, MediaClip, Project, TextClip, Track, clipEnd, clipLength, propAt, srcTimeAt,
} from "./model";
import { reframeWindow, type Rect } from "./reframe";
import { planMattes } from "./r5fx";
import { shapeCanvas } from "./shapes";
import { drawText } from "./textRender";

/**
 * مونتاژگرِ پیش‌نمایشِ فوری (Canvas 2D). همان ترتیبِ لایه‌هایی که سرور (compose.py) می‌سازد:
 * هر کلیپ ← جا دادن (fit) ← رنگ ← کلیدِ رنگی ← برش/ماسک/شفافیت ← چرخش و اندازه دورِ مرکز ← حالتِ ترکیب.
 * گذارها پنجره‌ای دورِ برش‌اند [برش − d/2, برش + d/2]. چیزهایی که مرورگر دقیق نشان نمی‌دهد
 * (ثابت‌کردنِ تصویر، رفعِ نویز، بیشترِ گذارها، کیفیتِ کلیدِ رنگی) با «پیش‌نمایشِ دقیق» از سرور می‌آید.
 */
export type Source = HTMLVideoElement | HTMLImageElement | HTMLCanvasElement;

export type RenderArgs = {
  project: Project;
  time: number;
  sources: Map<string, Source>;
  looks: LookDef[];
  /** شناسهٔ قطعه‌ای که رنگش موقتاً نادیده گرفته می‌شود (مقایسهٔ قبل/بعد) */
  compare?: string | null;
  /** LUT های خوانده‌شده (کلید ⇒ جدول) */
  luts?: Record<string, Lut>;
  /** فریمِ ماتِ هر قطعه (شناسهٔ قطعه ⇒ ویدیوی خاکستری) برای حذفِ پس‌زمینه */
  mattes?: Map<string, Source>;
  /** عمقِ توالیِ تودرتو (برای جلوگیری از بی‌نهایت) */
  depth?: number;
};

const BLEND_OP: Record<string, GlobalCompositeOperation> = {
  normal: "source-over", multiply: "multiply", screen: "screen", overlay: "overlay", add: "lighter",
  softlight: "soft-light", lighten: "lighten", darken: "darken", difference: "difference",
};

/** گروهِ هر نوعِ گذار برای پیش‌نمایشِ تقریبی */
const TRANSITION_PREVIEW: Record<string, string> = {
  fade: "dissolve", crossfade: "dissolve", dissolve: "dissolve", pixelize: "dissolve", distance: "dissolve", fadefast: "dissolve", fadeslow: "dissolve",
  fadegrays: "dissolve", hblur: "dissolve", hlslice: "dissolve", hrslice: "dissolve", vuslice: "dissolve", vdslice: "dissolve", squeezeh: "dissolve", squeezev: "dissolve",
  fadeblack: "dipblack", fadewhite: "dipwhite",
  wipeleft: "wipeleft", wiperight: "wiperight", wipeup: "wipeup", wipedown: "wipedown", wipetl: "diagtl", wipetr: "diagtr", wipebl: "diagbl", wipebr: "diagbr",
  slideleft: "slideleft", slideright: "slideright", slideup: "slideup", slidedown: "slidedown",
  smoothleft: "slideleft", smoothright: "slideright", smoothup: "slideup", smoothdown: "slidedown",
  coverleft: "coverleft", coverright: "coverright", coverup: "coverup", coverdown: "coverdown",
  revealleft: "revealleft", revealright: "revealright", revealup: "revealup", revealdown: "revealdown",
  circleopen: "circleopen", circleclose: "circleclose", circlecrop: "circleopen", rectcrop: "horzopen", radial: "circleopen",
  vertopen: "vertopen", vertclose: "vertclose", horzopen: "horzopen", horzclose: "horzclose",
  diagtl: "diagtl", diagtr: "diagtr", diagbl: "diagbl", diagbr: "diagbr", zoomin: "zoomin",
};

/** آیا پیش‌نمایشِ این گذار تقریبی است؟ (برای برچسب در رابط) */
export const transitionIsApproximate = (kind: string) => !["fade", "crossfade", "fadeblack", "fadewhite", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown", "circleopen", "circleclose", "horzopen", "vertopen", "horzclose", "vertclose"].includes(kind);

export type Pair = { a: MediaClip; b: MediaClip; d: number; kind: string; cut: number };

export function planTransitions(track: Track): Pair[] {
  const out: Pair[] = [];
  const sorted = [...track.clips].filter((c): c is MediaClip => c.type === "media" && c.kind !== "audio").sort((x, y) => x.at - y.at);
  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    const tr = b.transition;
    if (!tr || Math.abs(b.at - clipEnd(a)) > 0.15) continue;
    const d = Math.max(0.1, Math.min(tr.duration, 2, 0.9 * Math.min(clipLength(a), clipLength(b))));
    out.push({ a, b, d, kind: tr.kind, cut: b.at });
  }
  return out;
}

const cssFilterOf = (effects: Effect[]): string => {
  const f: string[] = [];
  for (const e of effects) {
    const a = Number(e.params.amount ?? 0);
    if (e.tool === "brightness") f.push(`brightness(${1 + a * 1.4})`);
    else if (e.tool === "contrast") f.push(`contrast(${a || 1})`);
    else if (e.tool === "saturation") f.push(`saturate(${a || 1})`);
    else if (e.tool === "white_balance") {
      const t = Number(e.params.temperature ?? 0);
      f.push(t >= 0 ? `sepia(${Math.min(1, t * 2)}) saturate(1.1)` : `hue-rotate(${t * 60}deg) saturate(1.05)`);
    }
  }
  return f.join(" ");
};

const dims = (s: Source): [number, number] => {
  if (s instanceof HTMLVideoElement) return [s.videoWidth, s.videoHeight];
  if (s instanceof HTMLImageElement) return [s.naturalWidth, s.naturalHeight];
  return [s.width, s.height];
};

const ready = (s: Source | undefined): s is Source => {
  if (!s) return false;
  if (s instanceof HTMLVideoElement) return s.readyState >= 2 && s.videoWidth > 0;
  if (s instanceof HTMLImageElement) return s.complete && s.naturalWidth > 0;
  return true;
};

/** برشِ قاب: فقط پنجرهٔ `win` (پیکسلِ منبع) به‌جای کلِ منبع با همان منطقِ جا دادن کشیده می‌شود */
function drawWindowed(ctx: CanvasRenderingContext2D, s: Source, win: Rect, x: number, y: number, w: number, h: number, fit: MediaClip["fit"]) {
  if (fit === "stretch") {
    ctx.drawImage(s, win.x, win.y, win.w, win.h, x, y, w, h);
    return;
  }
  const k = fit === "cover" ? Math.max(w / win.w, h / win.h) : Math.min(w / win.w, h / win.h);
  if (fit === "cover") {
    const cw = w / k;
    const ch = h / k;
    ctx.drawImage(s, win.x + (win.w - cw) / 2, win.y + (win.h - ch) / 2, cw, ch, x, y, w, h);
  } else {
    const dw = win.w * k;
    const dh = win.h * k;
    ctx.fillStyle = "#000";
    ctx.fillRect(x, y, w, h);
    ctx.drawImage(s, win.x, win.y, win.w, win.h, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  }
}

/** منبع را داخلِ مستطیلِ (x,y,w,h) می‌کشد: cover / contain / stretch؛ با `win` فقط پنجرهٔ بُرشِ قاب (reframe) */
function drawFitted(ctx: CanvasRenderingContext2D, s: Source, x: number, y: number, w: number, h: number, fit: MediaClip["fit"], win?: Rect) {
  const [sw, sh] = dims(s);
  if (!sw || !sh) return;
  if (win && win.w > 0 && win.h > 0) {
    drawWindowed(ctx, s, win, x, y, w, h, fit);
    return;
  }
  if (fit === "stretch") {
    ctx.drawImage(s, x, y, w, h);
    return;
  }
  const k = fit === "cover" ? Math.max(w / sw, h / sh) : Math.min(w / sw, h / sh);
  const dw = sw * k;
  const dh = sh * k;
  if (fit === "cover") {
    // برشِ منبع (نه کشیدنِ بیرون از مستطیل)
    const cw = w / k;
    const ch = h / k;
    ctx.drawImage(s, (sw - cw) / 2, (sh - ch) / 2, cw, ch, x, y, w, h);
  } else {
    ctx.fillStyle = "#000";
    ctx.fillRect(x, y, w, h);
    ctx.drawImage(s, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  }
}

const hex = (c: string): [number, number, number] => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];

/** کلیدِ رنگی مثلِ ffmpeg chromakey (فاصله در Cb/Cr) + despill */
function chromaKey(img: ImageData, key: NonNullable<MediaClip["chroma"]>) {
  const [kr, kg, kb] = hex(key.color);
  const cb0 = 128 - 0.168736 * kr - 0.331264 * kg + 0.5 * kb;
  const cr0 = 128 + 0.5 * kr - 0.418688 * kg - 0.081312 * kb;
  const d = img.data;
  const sim = key.similarity;
  const bl = Math.max(0.0001, key.blend);
  const spill = key.spill;
  const greenish = kg >= kb;
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], g = d[i + 1], b = d[i + 2];
    const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b;
    const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
    const diff = Math.sqrt(((cb - cb0) ** 2 + (cr - cr0) ** 2) / (255 * 255 * 2));
    const a = Math.min(1, Math.max(0, (diff - sim) / bl));
    d[i + 3] = d[i + 3] * a;
    if (spill > 0.01) {
      if (greenish) {
        const avg = (r + b) / 2;
        if (g > avg) d[i + 1] = g - (g - avg) * spill;
      } else {
        const avg = (r + g) / 2;
        if (b > avg) d[i + 2] = b - (b - avg) * spill;
      }
    }
  }
}

/** «کلیدِ روشنایی» مثلِ ffmpeg lumakey: هرچه از آستانه کمتر/بیشتر (با تلورانس و نرمی) باشد شفاف می‌شود */
/** اصلاحِ لنز مثلِ lenscorrection ِ ffmpeg (مرکز وسطِ قاب): هر پیکسلِ خروجی از نقطهٔ c + d·(1 + r²(k1 + k2·r²)) خوانده می‌شود،
 *  r² = مجذورِ فاصله از مرکز تقسیم بر مجذورِ نیم‌قطر. با خروجیِ واقعیِ ffmpeg سنجیده شده (میانگینِ خطا ≈ ۱ از ۲۵۵). */
export function lensSource(x: number, y: number, w: number, h: number, k1: number, k2: number): [number, number] {
  const dx = x - w / 2, dy = y - h / 2;
  const r2 = (dx * dx + dy * dy) / ((w / 2) ** 2 + (h / 2) ** 2);
  const c = 1 + r2 * (k1 + k2 * r2);
  return [w / 2 + dx * c, h / 2 + dy * c];
}

/** روی خودِ تصویر (درجا). بیرون از منبع سیاهِ کدر، مثلِ ffmpeg */
export function lensCorrect(img: ImageData, k1: number, k2: number): void {
  const { width: w, height: h } = img;
  const src = new Uint8ClampedArray(img.data);
  const out = img.data;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const [sx, sy] = lensSource(x, y, w, h, k1, k2);
      const o = (y * w + x) * 4;
      if (sx < 0 || sy < 0 || sx > w - 1 || sy > h - 1) {
        out[o] = out[o + 1] = out[o + 2] = 0;
        out[o + 3] = 255;
        continue;
      }
      const x0 = Math.floor(sx), y0 = Math.floor(sy);
      const x1 = Math.min(w - 1, x0 + 1), y1 = Math.min(h - 1, y0 + 1);
      const fx = sx - x0, fy = sy - y0;
      for (let k = 0; k < 4; k++) {
        out[o + k] =
          src[(y0 * w + x0) * 4 + k] * (1 - fx) * (1 - fy) + src[(y0 * w + x1) * 4 + k] * fx * (1 - fy) +
          src[(y1 * w + x0) * 4 + k] * (1 - fx) * fy + src[(y1 * w + x1) * 4 + k] * fx * fy;
      }
    }
  }
}

export function matteMultiply(target: ImageData, matte: ImageData, mode: "luma" | "alpha", invert: boolean) {
  const d = target.data, m = matte.data;
  for (let i = 0; i < d.length; i += 4) {
    let v = mode === "alpha" ? m[i + 3] / 255 : ((0.299 * m[i] + 0.587 * m[i + 1] + 0.114 * m[i + 2]) / 255) * (m[i + 3] / 255);
    if (invert) v = 1 - v;
    d[i + 3] = d[i + 3] * v;
  }
}

export function lumaKey(img: ImageData, key: { mode: "dark" | "bright"; tolerance: number; softness: number }) {
  const d = img.data;
  const th = key.mode === "bright" ? 1 : 0;
  const tol = Math.max(0, key.tolerance);
  const soft = Math.max(0.0001, key.softness);
  for (let i = 0; i < d.length; i += 4) {
    const y = (0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]) / 255;
    const a = Math.min(1, Math.max(0, (Math.abs(y - th) - tol) / soft));
    d[i + 3] = d[i + 3] * a;
  }
}

function clipPathRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number) {
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
}

type Scratch = { c: HTMLCanvasElement; x: CanvasRenderingContext2D };

export class Compositor {
  readonly canvas: HTMLCanvasElement;
  readonly ctx: CanvasRenderingContext2D;
  private scratch = new Map<string, Scratch>();
  private frameNo = 0;
  w = 0;
  h = 0;

  constructor(canvas?: HTMLCanvasElement) {
    this.canvas = canvas ?? document.createElement("canvas");
    this.ctx = this.canvas.getContext("2d", { willReadFrequently: true })!;
  }

  setSize(w: number, h: number) {
    const W = Math.max(16, Math.round(w));
    const H = Math.max(16, Math.round(h));
    if (this.canvas.width !== W || this.canvas.height !== H) {
      this.canvas.width = W;
      this.canvas.height = H;
      this.scratch.clear();
    }
    this.w = W;
    this.h = H;
  }

  private get(name: string, w: number, h: number): Scratch {
    let s = this.scratch.get(name);
    if (!s || s.c.width !== w || s.c.height !== h) {
      const c = document.createElement("canvas");
      c.width = Math.max(2, w);
      c.height = Math.max(2, h);
      s = { c, x: c.getContext("2d", { willReadFrequently: true })! };
      this.scratch.set(name, s);
    }
    return s;
  }

  /** فریمِ زیرِ سرِ پخش برای اسکوپ‌ها */
  getImageData(): ImageData | null {
    try {
      return this.ctx.getImageData(0, 0, this.w, this.h);
    } catch {
      return null;
    }
  }

  private mattes: { of: Map<string, MediaClip>; src: Set<string> } = { of: new Map(), src: new Set() };

  render(a: RenderArgs): void {
    const { ctx, w, h } = this;
    const t = a.time;
    this.mattes = planMattes(a.project);
    this.frameNo++;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    ctx.filter = "none";
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);
    for (const track of a.project.tracks) {
      if (track.kind === "video") {
        if (track.hidden) continue;
        this.videoTrack(track, a);
      } else if (track.kind === "text") {
        for (const c of track.clips) if (c.type === "text") drawText(ctx, c as TextClip, t, w, h);
      }
    }
  }

  private visible(clip: MediaClip, pairs: Pair[]): [number, number] {
    let vs = clip.at;
    let ve = clipEnd(clip);
    for (const p of pairs) {
      if (p.a === clip) ve = Math.min(ve, p.cut - p.d / 2);
      if (p.b === clip) vs = Math.max(vs, p.cut + p.d / 2);
    }
    return [vs, ve];
  }

  private videoTrack(track: Track, a: RenderArgs) {
    const t = a.time;
    const pairs = planTransitions(track);
    for (const c of [...track.clips].sort((x, y) => x.at - y.at)) {
      if (c.type !== "media" || c.kind === "audio") continue;
      const [vs, ve] = this.visible(c, pairs);
      if (t < vs - 1e-6 || t >= ve) continue;
      if (c.adjust) {
        this.adjustLayer(c, a);
        continue;
      }
      const m = this.mattes.of.get(c.id);
      if (m) {
        this.drawMatted(c, m, t, a);
        continue;
      }
      if (this.mattes.src.has(c.id)) continue;                // مات خودش نمایش داده نمی‌شود
      this.drawClip(this.ctx, c, t, a, this.w, this.h);
    }
    for (const p of pairs) {
      if (t >= p.cut - p.d / 2 && t < p.cut + p.d / 2) this.drawTransition(p, a);
    }
  }

  /** Track matte: قطعه روی بومِ شفاف، مات روی بومِ سیاه؛ روشنی (یا شفافیتِ) مات در شفافیتِ قطعه ضرب می‌شود */
  private drawMatted(c: MediaClip, m: MediaClip, t: number, a: RenderArgs) {
    const { w, h } = this;
    const tm = c.track_matte ?? { mode: "luma" as const, invert: false };
    const SA = this.get("mtA", w, h);
    const SM = this.get("mtM", w, h);
    for (const s of [SA, SM]) {
      s.x.setTransform(1, 0, 0, 1, 0, 0);
      s.x.globalAlpha = 1;
      s.x.globalCompositeOperation = "source-over";
      s.x.clearRect(0, 0, w, h);
    }
    if (tm.mode === "luma") {
      SM.x.fillStyle = "#000";
      SM.x.fillRect(0, 0, w, h);
    }
    this.drawClip(SA.x, c, t, a, w, h);
    if (t >= m.at - 1e-6 && t < clipEnd(m)) this.drawClip(SM.x, m, t, a, w, h);
    const ia = SA.x.getImageData(0, 0, w, h);
    matteMultiply(ia, SM.x.getImageData(0, 0, w, h), tm.mode, tm.invert);
    SA.x.putImageData(ia, 0, 0);
    this.ctx.drawImage(SA.c, 0, 0);
  }

  /** «لایهٔ تنظیم»: هرچه تا این‌جا کشیده شده رنگ/LUT این لایه را می‌گیرد (با شفافیتِ لایه) */
  private adjustLayer(c: MediaClip, a: RenderArgs) {
    if (a.compare === c.id) return;
    const color = c.color && !colorIsNeutral(c.color, a.looks) ? c.color : undefined;
    const lut = c.lut && a.luts?.[c.lut.key] ? { table: a.luts[c.lut.key], amount: c.lut.amount } : null;
    if (!color && !lut) return;
    const { ctx, w, h } = this;
    const img = ctx.getImageData(0, 0, w, h);
    const op = Math.max(0, Math.min(1, propAt(c, "opacity", a.time)));
    const before = op < 0.999 ? new Uint8ClampedArray(img.data) : null;
    if (color) applyColor(img, color, a.looks);
    if (lut) applyLut(img, lut.table, lut.amount);
    if (before) for (let i = 0; i < img.data.length; i += 4) for (let k = 0; k < 3; k++) img.data[i + k] = before[i + k] + (img.data[i + k] - before[i + k]) * op;
    ctx.putImageData(img, 0, 0);
  }

  // ───────────── گذار
  private drawTransition(p: Pair, a: RenderArgs) {
    const { w, h } = this;
    const u = Math.max(0, Math.min(1, (a.time - (p.cut - p.d / 2)) / p.d));
    const A = this.get("tA", w, h);
    const B = this.get("tB", w, h);
    for (const s of [A, B]) {
      s.x.setTransform(1, 0, 0, 1, 0, 0);
      s.x.globalAlpha = 1;
      s.x.globalCompositeOperation = "source-over";
      s.x.fillStyle = "#000";
      s.x.fillRect(0, 0, w, h);
    }
    this.drawClip(A.x, p.a, Math.min(a.time, clipEnd(p.a) - 0.001), a, w, h);
    this.drawClip(B.x, p.b, Math.max(a.time, p.b.at), a, w, h);
    const ctx = this.ctx;
    const kind = TRANSITION_PREVIEW[p.kind] ?? "dissolve";
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const draw = (s: Scratch, dx = 0, dy = 0, alpha = 1) => {
      ctx.globalAlpha = alpha;
      ctx.drawImage(s.c, dx, dy);
      ctx.globalAlpha = 1;
    };
    const clipTo = (fn: () => void, s: Scratch) => {
      ctx.save();
      ctx.beginPath();
      fn();
      ctx.clip();
      ctx.drawImage(s.c, 0, 0);
      ctx.restore();
    };
    const R = Math.hypot(w, h) / 2;
    switch (kind) {
      case "dipblack":
      case "dipwhite": {
        ctx.fillStyle = kind === "dipblack" ? "#000" : "#fff";
        ctx.fillRect(0, 0, w, h);
        if (u < 0.5) draw(A, 0, 0, 1 - u * 2);
        else draw(B, 0, 0, (u - 0.5) * 2);
        break;
      }
      case "wipeleft": draw(A); clipTo(() => ctx.rect(w * (1 - u), 0, w * u, h), B); break;
      case "wiperight": draw(A); clipTo(() => ctx.rect(0, 0, w * u, h), B); break;
      case "wipeup": draw(A); clipTo(() => ctx.rect(0, h * (1 - u), w, h * u), B); break;
      case "wipedown": draw(A); clipTo(() => ctx.rect(0, 0, w, h * u), B); break;
      case "diagtl": draw(A); clipTo(() => { ctx.moveTo(0, 0); ctx.lineTo(2 * w * u, 0); ctx.lineTo(0, 2 * h * u); }, B); break;
      case "diagtr": draw(A); clipTo(() => { ctx.moveTo(w, 0); ctx.lineTo(w - 2 * w * u, 0); ctx.lineTo(w, 2 * h * u); }, B); break;
      case "diagbl": draw(A); clipTo(() => { ctx.moveTo(0, h); ctx.lineTo(2 * w * u, h); ctx.lineTo(0, h - 2 * h * u); }, B); break;
      case "diagbr": draw(A); clipTo(() => { ctx.moveTo(w, h); ctx.lineTo(w - 2 * w * u, h); ctx.lineTo(w, h - 2 * h * u); }, B); break;
      case "slideleft": draw(A, -w * u); draw(B, w * (1 - u)); break;
      case "slideright": draw(A, w * u); draw(B, -w * (1 - u)); break;
      case "slideup": draw(A, 0, -h * u); draw(B, 0, h * (1 - u)); break;
      case "slidedown": draw(A, 0, h * u); draw(B, 0, -h * (1 - u)); break;
      case "coverleft": draw(A); draw(B, w * (1 - u)); break;
      case "coverright": draw(A); draw(B, -w * (1 - u)); break;
      case "coverup": draw(A); draw(B, 0, h * (1 - u)); break;
      case "coverdown": draw(A); draw(B, 0, -h * (1 - u)); break;
      case "revealleft": draw(B); draw(A, -w * u); break;
      case "revealright": draw(B); draw(A, w * u); break;
      case "revealup": draw(B); draw(A, 0, -h * u); break;
      case "revealdown": draw(B); draw(A, 0, h * u); break;
      case "circleopen": draw(A); clipTo(() => ctx.arc(w / 2, h / 2, R * u, 0, Math.PI * 2), B); break;
      case "circleclose": draw(B); clipTo(() => ctx.arc(w / 2, h / 2, R * (1 - u), 0, Math.PI * 2), A); break;
      case "horzopen": draw(A); clipTo(() => ctx.rect(0, h * (0.5 - u / 2), w, h * u), B); break;
      case "vertopen": draw(A); clipTo(() => ctx.rect(w * (0.5 - u / 2), 0, w * u, h), B); break;
      case "horzclose": draw(B); clipTo(() => { ctx.rect(0, 0, w, h); ctx.rect(0, h * (0.5 - (1 - u) / 2) + h * (1 - u), w, -h * (1 - u)); }, A); break;
      case "vertclose": draw(B); clipTo(() => { ctx.rect(0, 0, w, h); ctx.rect(w * (0.5 - (1 - u) / 2) + w * (1 - u), 0, -w * (1 - u), h); }, A); break;
      case "zoomin": {
        draw(A);
        ctx.save();
        ctx.globalAlpha = u;
        ctx.translate(w / 2, h / 2);
        ctx.scale(0.6 + 0.4 * u, 0.6 + 0.4 * u);
        ctx.drawImage(B.c, -w / 2, -h / 2);
        ctx.restore();
        break;
      }
      default: draw(A); draw(B, 0, 0, u);
    }
    ctx.restore();
  }

  // ───────────── یک کلیپ
  private nested = new Map<string, Compositor>();

  /** توالیِ تودرتو را روی بومِ کوچکِ خودش می‌کشد و همان بوم را مثلِ یک ویدیو برمی‌گرداند */
  private nestedSource(clip: MediaClip, t: number, a: RenderArgs, bw: number): Source | undefined {
    const sid = clip.ref.slice(4);
    const seq = a.project.sequences?.[sid];
    if (!seq || (a.depth ?? 0) >= 3) return undefined;
    let comp = this.nested.get(sid);
    if (!comp) {
      comp = new Compositor();
      this.nested.set(sid, comp);
    }
    const fmt = seq.format ?? a.project.format;
    const w = Math.max(16, Math.min(1280, Math.round(bw)));
    comp.setSize(w, Math.max(16, Math.round((w * fmt.height) / fmt.width)));
    const tn = srcTimeAt(clip, Math.max(clip.at, Math.min(clipEnd(clip), t)));
    comp.render({ ...a, project: { ...a.project, format: fmt, tracks: seq.tracks, markers: [], inout: null }, time: tn, depth: (a.depth ?? 0) + 1 });
    return comp.canvas;
  }

  private drawClip(ctx: CanvasRenderingContext2D, clip: MediaClip, t: number, a: RenderArgs, W: number, H: number) {
    const bw = Math.max(2, Math.round(clip.width * W));
    const bh = Math.max(2, Math.round(clip.height * H));
    const src: Source | undefined = clip.shape ? shapeCanvas(clip.shape, bw, bh) : clip.ref.startsWith("seq:") ? this.nestedSource(clip, t, a, bw) : a.sources.get(clip.id);
    if (!ready(src)) return;
    // برشِ قاب: پنجرهٔ منبع در این لحظه (کلیدهای kx/ky نسبت به شروعِ قطعه)؛ بدونِ reframe هیچ‌چیز عوض نمی‌شود
    const win = clip.reframe ? reframeWindow(clip, t, ...dims(src)) : undefined;
    const opacity = propAt(clip, "opacity", t);
    let fade = 1;
    if (clip.fade_in > 0) fade *= Math.min(1, Math.max(0, (t - clip.at) / clip.fade_in));
    if (clip.fade_out > 0) fade *= Math.min(1, Math.max(0, (clipEnd(clip) - t) / clip.fade_out));
    const alpha = Math.max(0, Math.min(1, opacity * fade));
    if (alpha <= 0.001) return;
    const px = propAt(clip, "px", t);
    const py = propAt(clip, "py", t);
    const scale = propAt(clip, "scale", t);
    const rot = propAt(clip, "rot", t);
    const cl = propAt(clip, "crop_l", t), cr = propAt(clip, "crop_r", t), ct = propAt(clip, "crop_t", t), cb = propAt(clip, "crop_b", t);
    const cx = (clip.x + clip.width / 2 + px) * W;
    const cy = (clip.y + clip.height / 2 + py) * H;

    const bypass = a.compare === clip.id;
    const color = !bypass && clip.color && !colorIsNeutral(clip.color, a.looks) ? clip.color : undefined;
    const fx = color ? postFx(color, a.looks) : null;
    const luma = clip.luma?.on ? clip.luma : undefined;
    const lens = clip.lens && (Math.abs(clip.lens.k1) > 0.005 || Math.abs(clip.lens.k2) > 0.005) ? clip.lens : undefined;
    const keyed = !!clip.chroma?.on || !!luma;
    const lut = clip.lut && a.luts?.[clip.lut.key] ? { table: a.luts[clip.lut.key], amount: clip.lut.amount } : null;
    const matte = clip.matte ? a.mattes?.get(clip.id) : undefined;
    const needPixels = !!color || keyed || !!lut || !!lens || ready(matte);
    const mask = clip.mask && clip.mask.shape !== "none" && (clip.mask.shape !== "bezier" || (clip.mask.points?.length ?? 0) >= 3) ? clip.mask : null;
    const css = cssFilterOf(clip.effects);
    const rotate = clip.effects.find((e) => e.tool === "rotate");
    const vignette = clip.effects.find((e) => e.tool === "vignette");
    const blurs = clip.effects.filter((e) => e.tool === "blur_region");

    // ۱) محتوای لایه در بومِ کمکیِ هم‌اندازهٔ جعبه
    const needLayer = needPixels || !!mask || !!vignette || blurs.length > 0 || !!rotate;
    let layerCanvas: HTMLCanvasElement | null = null;
    if (needLayer) {
      const L = this.get(`layer`, bw, bh);
      const lx = L.x;
      lx.setTransform(1, 0, 0, 1, 0, 0);
      lx.globalCompositeOperation = "source-over";
      lx.globalAlpha = 1;
      lx.clearRect(0, 0, bw, bh);
      lx.filter = css || "none";
      lx.save();
      if (clip.flip_h || clip.flip_v) {
        lx.translate(clip.flip_h ? bw : 0, clip.flip_v ? bh : 0);
        lx.scale(clip.flip_h ? -1 : 1, clip.flip_v ? -1 : 1);
      }
      if (rotate) {
        lx.translate(bw / 2, bh / 2);
        lx.rotate((Number(rotate.params.degrees) * Math.PI) / 180);
        lx.translate(-bw / 2, -bh / 2);
      }
      drawFitted(lx, src, 0, 0, bw, bh, clip.fit, win);
      lx.restore();
      lx.filter = "none";
      if (needPixels) {
        const img = lx.getImageData(0, 0, bw, bh);
        if (lens) lensCorrect(img, lens.k1, lens.k2);
        if (color) applyColor(img, color, a.looks);
        if (lut) applyLut(img, lut.table, lut.amount);
        if (fx && (fx.sharpen > 0 || fx.vignette > 0 || fx.grain > 0)) applyPostFx(img, fx, this.frameNo);
        if (luma) lumaKey(img, luma);
        if (clip.chroma?.on) chromaKey(img, clip.chroma);
        if (matte && ready(matte)) {
          // ماتِ حذفِ پس‌زمینه: همان جا دادنِ منبع در جعبه، روشنیِ آن می‌شود شفافیت
          const M = this.get("matte", bw, bh);
          M.x.setTransform(1, 0, 0, 1, 0, 0);
          M.x.globalAlpha = 1;
          M.x.fillStyle = "#000";
          M.x.fillRect(0, 0, bw, bh);
          drawFitted(M.x, matte, 0, 0, bw, bh, clip.fit, clip.reframe ? reframeWindow(clip, t, ...dims(matte)) : undefined);
          const mm = M.x.getImageData(0, 0, bw, bh).data;
          for (let i = 0; i < img.data.length; i += 4) img.data[i + 3] = (img.data[i + 3] * mm[i]) / 255;
        }
        lx.putImageData(img, 0, 0);
      }
      if (vignette) {
        const s = Number(vignette.params.strength ?? 0.4);
        const g = lx.createRadialGradient(bw / 2, bh / 2, Math.min(bw, bh) * (0.3 - s * 0.1), bw / 2, bh / 2, Math.hypot(bw, bh) / 2);
        g.addColorStop(0, "rgba(0,0,0,0)");
        g.addColorStop(1, `rgba(0,0,0,${0.35 + s * 0.6})`);
        lx.fillStyle = g;
        lx.fillRect(0, 0, bw, bh);
      }
      for (const b of blurs) {
        const bx = (Number(b.params.x) / 100) * bw, by = (Number(b.params.y) / 100) * bh;
        const bww = (Number(b.params.width) / 100) * bw, bhh = (Number(b.params.height) / 100) * bh;
        lx.save();
        lx.beginPath();
        lx.rect(bx, by, bww, bhh);
        lx.clip();
        lx.filter = `blur(${2 + Number(b.params.strength ?? 6) * 1.6}px)`;
        lx.drawImage(L.c, 0, 0);
        lx.restore();
        lx.filter = "none";
      }
      if (mask) this.applyMask(lx, bw, bh, mask, t - clip.at);
      layerCanvas = L.c;
    }

    // ۲) نشاندن روی بوم با چرخش/اندازه دورِ مرکز
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.globalCompositeOperation = BLEND_OP[clip.blend ?? "normal"] ?? "source-over";
    const an = clip.anchor;
    ctx.translate(cx + (an ? an.x * bw : 0), cy + (an ? an.y * bh : 0));      // چرخش و اندازه دورِ نقطهٔ لنگر (پیش‌فرض: مرکز)
    if (rot) ctx.rotate((rot * Math.PI) / 180);
    const s = Math.max(0.01, scale);
    ctx.scale(s, s);
    if (an) ctx.translate(-an.x * bw, -an.y * bh);
    if (cl > 0 || cr > 0 || ct > 0 || cb > 0) clipPathRect(ctx, -bw / 2 + cl * bw, -bh / 2 + ct * bh, bw * (1 - cl - cr), bh * (1 - ct - cb));
    const bl = fx ? blurPx(fx, bw, bh) : 0;
    if (layerCanvas) {
      if (bl > 0) ctx.filter = `blur(${bl}px)`;
      ctx.drawImage(layerCanvas, -bw / 2, -bh / 2);
    } else {
      if (css) ctx.filter = css;
      if (clip.flip_h || clip.flip_v) ctx.scale(clip.flip_h ? -1 : 1, clip.flip_v ? -1 : 1);
      drawFitted(ctx, src, -bw / 2, -bh / 2, bw, bh, clip.fit, win);
    }
    ctx.restore();
  }

  private applyMask(lx: CanvasRenderingContext2D, bw: number, bh: number, m: NonNullable<MediaClip["mask"]>, local = 0) {
    const M = this.get("mask", bw, bh);
    const mx = M.x;
    mx.setTransform(1, 0, 0, 1, 0, 0);
    mx.globalCompositeOperation = "source-over";
    mx.clearRect(0, 0, bw, bh);
    mx.fillStyle = "#fff";
    const f = Math.max(0, m.feather) * Math.min(bw, bh) * 0.5;
    mx.filter = f > 0.5 ? `blur(${f}px)` : "none";
    // ردیابیِ حرکت: مرکزِ ماسک در زمانِ قطعه جابه‌جا می‌شود (کسری از جعبه)
    const kx = valueAt(m.kx, local, 0);
    const ky = valueAt(m.ky, local, 0);
    if (m.shape === "bezier" && m.points && m.points.length >= 3) {
      mx.save();
      mx.translate(kx * bw, ky * bh);
      mx.fill(pathOf(m.points, bw, bh));
      mx.restore();
    } else {
      mx.beginPath();
      const cx = m.cx + kx;
      const cy = m.cy + ky;
      if (m.shape === "ellipse") mx.ellipse(cx * bw, cy * bh, (m.w * bw) / 2, (m.h * bh) / 2, 0, 0, Math.PI * 2);
      else mx.rect((cx - m.w / 2) * bw, (cy - m.h / 2) * bh, m.w * bw, m.h * bh);
      mx.fill();
    }
    mx.filter = "none";
    lx.save();
    lx.globalCompositeOperation = m.invert ? "destination-out" : "destination-in";
    lx.drawImage(M.c, 0, 0);
    lx.restore();
  }
}

/** ثانیه‌ای از منبع که باید دیده شود (به‌همراهِ نگه‌داشتنِ فریمِ لبه‌ها وقتی بیرونِ قطعه‌ایم) */
export function sourceTimeFor(c: MediaClip, t: number): number {
  return srcTimeAt(c, Math.max(c.at, Math.min(clipEnd(c), t)));
}

export type { AnyClip };
/** پنجرهٔ بُرشِ قاب (reframe) در لحظهٔ t به پیکسلِ منبع — خالص؛ جزئیات در reframe.ts */
export { reframeWindow };
