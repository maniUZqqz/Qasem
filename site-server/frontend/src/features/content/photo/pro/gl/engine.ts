import type { Adjust, Curve } from "../../manual/engine";
import type { Layer, MaskSpec, ProState, Quad } from "../types";
import type { M3 } from "../geo";
import type { FrameSpec } from "../frame";
import { canvasToPhoto, cropFormatGeometry, cropFormatTarget, frameUniforms, normalizeWindow } from "../frame";
import type { EnergyMap } from "../smartFocus";
import { energyMap, energyOffset, subjectView, thumbSize } from "../smartFocus";
import { GLCtx, Tex, UValue } from "./glutil";
import { LUT_N, buildCurveLut, newCanvas, rasterShape, rasterStrokes, rasterText } from "./raster";
import { SH } from "./shaders";
import { FxCache, bakeFx, effectiveFx, freeFxCache, fxActive, newFxCache } from "./fxbake";
import { childrenMap } from "../tree";
import type { LayerFx } from "../types";

/**
 * موتورِ پیش‌نمایشِ فوری (WebGL2): فرمول‌های لغزنده‌ها از کدِ C# کیت برگردانده شده (shaders.ts)، لایه‌ها با همهٔ حالت‌های
 * آمیزشِ W3C و ماسک ترکیب می‌شوند. «پایه» می‌تواند خروجیِ دقیقِ کیت (setExact) باشد؛ آن‌وقت لغزنده‌های پایه دوباره اعمال نمی‌شوند.
 *
 * خطِ لولهٔ نسخهٔ ۲ (قاب‌اول؛ همان ترتیبِ سرور):
 *   ۱) عکسِ پایه ⇒ ظهور/خروجیِ دقیقِ کیت  (فضای «عکس»، اندازهٔ Wd×Hd)           — baseDeveloped()   [جای مایع‌سازی: همان‌جا]
 *   ۲) قاب: پرسپکتیو/چرخش/صاف/قرینه/برش/قابِ شبکه ⇒ بومِ نهایی (Wc×Hc)           — frameTexture()    (setFrame(spec))
 *   ۳) لایه‌ها روی بومِ نهایی (لایهٔ پایه = بافتِ قاب با پوششِ کامل)               — render()
 *   نمایش = زوم/جابه‌جاییِ بوم (present mode="canvas")؛ وقتی ابزارِ هندسه (برش/صاف/پرسپکتیو/لکه) فعال است، کلِ عکسِ بی‌برش
 *   (مرحلهٔ ۱ به‌تنهایی، renderPhoto + present mode="photo") و لایه‌ها پنهان‌اند.
 * مختصاتِ لایه/ماسک/انتخاب/روتوش همه نسبت به بومِ نهایی است؛ Wo/Ho = اندازهٔ عکسِ اصل، Wf/Hf (در frameSpec) = اندازهٔ واقعیِ بوم.
 */
export const WORK_MAX = 1600;
const D: Record<string, number> = {
  shadowsHue: 220, highlightsHue: 40, levelsWhite: 255, levelsGamma: 1, sharpenRadius: 1, vignetteMidpoint: 50, vignetteFeather: 50, grainSize: 25,
};
const val = (a: Adjust, k: string) => (typeof a[k] === "number" ? a[k] : (D[k] ?? 0));
const has = (a: Adjust, k: string) => Math.abs(val(a, k) - (D[k] ?? 0)) > 1e-9;

export const BLEND_INDEX: Record<string, number> = {
  normal: 0, multiply: 1, screen: 2, overlay: 3, "soft-light": 4, "hard-light": 5, darken: 6, lighten: 7, "color-dodge": 8,
  "color-burn": 9, difference: 10, exclusion: 11, hue: 12, saturation: 13, color: 14, luminosity: 15,
};

const BANDS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"];
const Wr = 0.2126;
const Wg = 0.7152;
const Wb = 0.0722;

function whiteBalanceGains(temp: number, tint: number): [number, number, number] {
  const t = temp / 100;
  const ti = tint / 100;
  const gr = Math.exp(0.6 * t + 0.125 * ti);
  const gb = Math.exp(-0.6 * t + 0.125 * ti);
  const gg = Math.exp(-0.25 * ti);
  const norm = 1 / (Wr * gr + Wg * gg + Wb * gb);
  return [gr * norm, gg * norm, gb * norm];
}

function hsv2rgb(h: number, s: number, v: number): [number, number, number] {
  if (s <= 0) return [v, v, v];
  const hh = (((h % 360) + 360) % 360) / 60;
  const i = Math.floor(hh);
  const f = hh - i;
  const p = v * (1 - s);
  const q = v * (1 - s * f);
  const t = v * (1 - s * (1 - f));
  switch (i) {
    case 0: return [v, t, p];
    case 1: return [q, v, p];
    case 2: return [p, v, t];
    case 3: return [p, q, v];
    case 4: return [t, p, v];
    default: return [v, p, q];
  }
}

function tintDir(hue: number): [number, number, number] {
  const [r, g, b] = hsv2rgb(hue % 360, 1, 1);
  const l = Wr * r + Wg * g + Wb * b;
  return [r - l, g - l, b - l];
}

/** نورِ هوا برای مه‌زدایی: میانگینِ روشن‌ترین ۰٫۱٪ِ کانالِ تیره (روی نسخهٔ کوچک) */
export function airLight(img: ImageData): [number, number, number] {
  const { width: w, height: h, data } = img;
  const dark = new Float32Array(w * h);
  for (let i = 0, p = 0; p < dark.length; i += 4, p++) dark[p] = Math.min(data[i], data[i + 1], data[i + 2]) / 255;
  const patch = Math.max(3, Math.floor(Math.max(w, h) * 0.02)) | 1;
  const r = (patch - 1) >> 1;
  const tmp = new Float32Array(w * h);
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 1;
    for (let k = Math.max(0, x - r); k <= Math.min(w - 1, x + r); k++) m = Math.min(m, dark[y * w + k]);
    tmp[y * w + x] = m;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 1;
    for (let k = Math.max(0, y - r); k <= Math.min(h - 1, y + r); k++) m = Math.min(m, tmp[k * w + x]);
    out[y * w + x] = m;
  }
  const sorted = Float32Array.from(out).sort();
  const thr = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.999))];
  let rr = 0;
  let gg = 0;
  let bb = 0;
  let n = 0;
  for (let i = 0, p = 0; p < out.length; i += 4, p++) {
    if (out[p] >= thr) {
      rr += data[i] / 255;
      gg += data[i + 1] / 255;
      bb += data[i + 2] / 255;
      n++;
    }
  }
  if (!n) return [1, 1, 1];
  const c = (v: number) => Math.min(1, Math.max(0.3, v / n));
  return [c(rr), c(gg), c(bb)];
}

export type MaskEntry = { canvas: HTMLCanvasElement; ver: number };
export type RenderCtx = {
  masks: Map<string, MaskEntry>;
  /** فقط این لایه‌ها (برای تلفیق/خروجی گرفتن)؛ undefined = همه */
  only?: Set<string>;
  /** لایه‌ی پایه را به‌جای خودش از اصلِ بدونِ تنظیم بگیر (نمایشِ «قبل») */
  noDevelop?: boolean;
};

type Raster = { sig: string; tex: Tex; bw: number; bh: number; cw: number; ch: number; full: boolean };
type Retouch = { sig: string; groups: { brush: Tex; dx: number; dy: number; heal: boolean; sigma: number }[] };

const SIZE_FROM = (img: { width: number; height: number }) => [img.width, img.height] as const;

export class ProEngine {
  g: GLCtx;
  canvas: HTMLCanvasElement;
  ok = true;
  Wd = 0;
  Hd = 0;
  /** اندازهٔ واقعی (اصل) برای نسبتِ مقیاس */
  Wo = 0;
  Ho = 0;
  /** اندازهٔ کاریِ بومِ نهایی (لایه‌ها، ماسک‌ها و انتخاب در این اندازه‌اند) */
  Wc = 0;
  Hc = 0;
  /** عکسِ پایه شفاف است؟ (برای انرژیِ «سوژه (خودکار)»: آلفا به‌جای گرادیان) */
  baseHasAlpha = false;
  onNeedRender: (() => void) | null = null;

  private baseSrc: Tex | null = null;
  baseCpu: ImageData | null = null;
  private air: [number, number, number] = [1, 1, 1];
  private exactTex: Tex | null = null;
  private devTex: Tex | null = null;
  private devKey = "";
  /** خروجیِ مرحلهٔ ۱ (پایه/ظهور/دقیق) و امضای محتوای آن؛ ورودیِ مرحلهٔ قاب */
  private dev: Tex | null = null;
  private devSig = "";
  private baseVer = 0;
  private exactVer = 0;
  private frameSpec: FrameSpec | null = null;
  private frameTex: Tex | null = null;
  private frameSig = "";
  private beforeTex: Tex | null = null;
  private beforeSig = "";
  private energies = new Map<string, EnergyMap>();
  private lastMode: "canvas" | "photo" = "canvas";
  private view: Tex | null = null;
  private images = new Map<string, { tex: Tex; w: number; h: number }>();
  private imageLoads = new Map<string, Promise<{ w: number; h: number } | null>>();
  private rasters = new Map<string, Raster>();
  /** تایلِ لایه با جلوه‌های پخته (سایه/درخشش/دورخط)؛ کلید = شناسهٔ لایه؛ بر پایهٔ امضا و بافتِ منبع کَش می‌شود */
  private fxBaked = new Map<string, { sig: string; src: Tex; tex: Tex; bw: number; bh: number; cache: FxCache }>();
  /** بافتِ ۱×۱ برای نمونه‌گرهای بی‌استفاده (uClip/uMask)؛ وگرنه شمارهٔ واحدِ کهنه به بافتی اشاره می‌کند که الان هدفِ رسم است ⇒ feedback loop */
  private nullTexCache: Tex | null = null;
  private nullTex(): Tex {
    return (this.nullTexCache ??= this.g.fromBytes(new Uint8Array(4), 1, 1));
  }
  private retouches = new Map<string, Retouch>();
  private maskTex = new Map<string, { tex: Tex; ver: number }>();
  private lutTex: Tex | null = null;
  private lutKey = "";
  private smallBase = new Map<number, ImageData>();
  private histTex: Tex | null = null;
  private fontWait = new Set<string>();
  private selTex: { tex: Tex; ver: number } | null = null;
  private selVer = -1;
  /** مایع‌سازی (فضای عکس): نقشهٔ آپلودشده، آخرین نسخه‌ای که آپلود شد، و خروجیِ پاس (ورودیِ مرحلهٔ قاب) */
  private lq: { tex: Tex; gw: number; gh: number; ver: number } | null = null;
  private lqOn = false;
  private lqOut: Tex | null = null;
  private lqKey = "";

  private onContextLost = (e: Event) => {
    e.preventDefault(); // وگرنه مرورگر هرگز بافت را بازنمی‌گرداند
    this.ok = false;
  };

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.g = new GLCtx(canvas);
    canvas.addEventListener("webglcontextlost", this.onContextLost);
  }

  /**
   * کنارگذاشتنِ موتور (Stage هنگامِ بازیابیِ بافتِ WebGL یک موتورِ تازه روی همان بوم می‌سازد). به منابعِ GL دست نمی‌زند:
   * پس از از دست رفتنِ بافت همهٔ دستگیره‌ها نامعتبرند. حالتِ ماسک‌ها/انتخاب/مایع‌سازی جای دیگری (CPU) است و می‌ماند.
   */
  dispose(): void {
    this.ok = false;
    this.onNeedRender = null;
    this.canvas.removeEventListener("webglcontextlost", this.onContextLost);
  }

  // ───────────────────────── منابع

  setBase(img: HTMLImageElement | HTMLCanvasElement | ImageBitmap, origW: number, origH: number, maxSide = WORK_MAX, hasAlpha = false): void {
    const iw = (img as HTMLImageElement).naturalWidth || img.width;
    const ih = (img as HTMLImageElement).naturalHeight || img.height;
    const k = Math.min(1, maxSide / Math.max(iw, ih));
    const w = Math.max(1, Math.round(iw * k));
    const h = Math.max(1, Math.round(ih * k));
    const c = newCanvas(w, h);
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, 0, 0, w, h);
    this.baseCpu = ctx.getImageData(0, 0, w, h);
    if (this.baseSrc) this.g.destroy(this.baseSrc);
    this.baseSrc = this.g.upload(c, { premult: false, mips: true });
    this.Wd = w;
    this.Hd = h;
    this.Wo = origW;
    this.Ho = origH;
    this.baseHasAlpha = hasAlpha;
    this.baseVer++;
    this.energies.clear();
    this.devKey = "";
    this.smallBase.clear();
    const tiny = this.smallOf(200);
    this.air = airLight(tiny);
    this.g.clearPool();
    if (this.devTex) this.g.destroy(this.devTex);
    this.devTex = null;
    this.dev = null;
    if (this.frameTex) this.g.destroy(this.frameTex);
    this.frameTex = null;
    this.frameSig = "";
    if (this.beforeTex) this.g.destroy(this.beforeTex);
    this.beforeTex = null;
    this.beforeSig = "";
    if (this.view) this.g.destroy(this.view);
    this.view = null;
    if (this.frameSpec) this.setFrame(this.frameSpec);
  }

  private smallOf(side: number): ImageData {
    let s = this.smallBase.get(side);
    if (s) return s;
    const src = this.baseCpu!;
    const k = Math.min(1, side / Math.max(src.width, src.height));
    const w = Math.max(1, Math.round(src.width * k));
    const h = Math.max(1, Math.round(src.height * k));
    const a = newCanvas(src.width, src.height);
    a.getContext("2d")!.putImageData(src, 0, 0);
    const b = newCanvas(w, h);
    const bc = b.getContext("2d", { willReadFrequently: true })!;
    bc.imageSmoothingQuality = "high";
    bc.drawImage(a, 0, 0, w, h);
    s = bc.getImageData(0, 0, w, h);
    this.smallBase.set(side, s);
    return s;
  }

  /** انتخاب (selection) برای نمایش با رنگِ قرمزِ کم‌رنگ */
  setSelection(c: HTMLCanvasElement | null, ver: number): void {
    if (!c) {
      if (this.selTex) this.g.destroy(this.selTex.tex);
      this.selTex = null;
      this.selVer = -1;
      return;
    }
    if (!this.selTex) {
      this.selTex = { tex: this.g.upload(c, { premult: false }), ver };
      this.selVer = ver;
    } else if (this.selVer !== ver) {
      this.g.reupload(this.selTex.tex, c, false);
      this.selVer = ver;
    }
  }

  setExact(img: HTMLImageElement | HTMLCanvasElement | null): void {
    if (this.exactTex) this.g.destroy(this.exactTex);
    this.exactTex = img ? this.g.upload(img, { premult: false, mips: true }) : null;
    this.exactVer++;
  }
  get hasExact() {
    return !!this.exactTex;
  }

  /** بارگذاریِ تصویرِ یک لایه (دارایی یا لوگو)؛ ابعاد را برمی‌گرداند */
  ensureImage(key: string, url: string): Promise<{ w: number; h: number } | null> {
    const have = this.images.get(key);
    if (have) return Promise.resolve({ w: have.w, h: have.h });
    let p = this.imageLoads.get(key);
    if (p) return p;
    p = new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        if (!this.ok) {
          // بافتِ GL از دست رفته یا موتور کنار گذاشته شده؛ موتورِ تازه خودش تصویر را دوباره می‌گیرد
          this.imageLoads.delete(key);
          resolve(null);
          return;
        }
        const k = Math.min(1, 2048 / Math.max(img.naturalWidth, img.naturalHeight));
        let src: CanvasImageSource = img;
        let w = img.naturalWidth;
        let h = img.naturalHeight;
        if (k < 1) {
          w = Math.round(w * k);
          h = Math.round(h * k);
          const c = newCanvas(w, h);
          const cx = c.getContext("2d")!;
          cx.imageSmoothingQuality = "high";
          cx.drawImage(img, 0, 0, w, h);
          src = c;
        }
        const tex = this.g.upload(src as TexImageSource, { premult: true, mips: true });
        this.images.set(key, { tex, w, h });
        this.onNeedRender?.();
        resolve({ w, h });
      };
      img.onerror = () => resolve(null);
      img.src = url;
    });
    this.imageLoads.set(key, p);
    return p;
  }

  imageSize(key: string): { w: number; h: number } | null {
    const i = this.images.get(key);
    return i ? { w: i.w, h: i.h } : null;
  }

  invalidateText(): void {
    for (const [k, r] of this.rasters) {
      if (k.startsWith("t:")) {
        this.g.destroy(r.tex);
        this.rasters.delete(k);
      }
    }
  }

  private srcKey(l: Layer): string {
    if (l.type !== "image") return "";
    return l.src.kind === "logo" ? "logo" : `a${l.src.asset}`;
  }

  // ───────────────────────── رسمِ دوبعدیِ لایه‌ها ⇒ بافت

  private fontReady(weight: number, family = "Vazirmatn"): boolean {
    const spec = `${weight} 20px ${family}`;
    if (!document.fonts || document.fonts.check(spec, "آاب")) return true;
    if (!this.fontWait.has(spec)) {
      this.fontWait.add(spec);
      void document.fonts.load(spec, "آاب Abc").then(() => {
        this.invalidateText();
        this.onNeedRender?.();
      });
    }
    return false;
  }

  /** اندازهٔ لایه به‌صورتِ کسری از پهنا (برای دستگیره‌ها و کلیک)؛ null = هنوز آماده نیست */
  layerSize(l: Layer): { w: number; h: number } | null {
    if (l.type === "image") {
      const i = this.images.get(this.srcKey(l));
      return i ? { w: l.w, h: (l.w * i.h) / i.w } : null;
    }
    if (l.type === "shape") return { w: l.w, h: Math.max(l.h, (l.stroke?.w ?? 0) + 0.002) };
    if (l.type === "text") {
      if (!this.Wc) return null; // اندازهٔ بوم هنوز نیست (موتورِ تازه پس از بازیابیِ بافت، پیش از setFrame) ⇒ وگرنه NaN
      const r = this.textRaster(l);
      return r ? { w: r.cw, h: r.ch } : null;
    }
    return null;
  }

  textLines(l: Layer): string[] | null {
    if (l.type !== "text") return null;
    return this.rasters.get(`t:${l.id}`) ? this.textRasterLines(l.id) : null;
  }
  private textRasterLines(id: string) {
    return this.lineCache.get(id) ?? null;
  }
  private lineCache = new Map<string, string[]>();

  private textRaster(l: Layer & { type: "text" }): Raster | null {
    const key = `t:${l.id}`;
    const sig = JSON.stringify([l.text, l.font, l.weight, l.size, l.color, l.align, l.dir, l.line_height, l.letter_spacing, l.width, l.stroke, l.shadow, l.box, l.tile, l.lines, this.Wc, this.Hc]);
    const have = this.rasters.get(key);
    if (have && have.sig === sig) return have;
    if (!this.fontReady(l.weight)) return have ?? null;
    const r = rasterText(l, this.Wc, this.Hc);
    if (have) this.g.destroy(have.tex);
    if (!r) {
      this.rasters.delete(key);
      return null;
    }
    this.lineCache.set(l.id, r.lines);
    const tex = this.g.upload(r.canvas, { premult: true, mips: true });
    const entry: Raster = { sig, tex, bw: r.bw, bh: r.bh, cw: r.cw, ch: r.ch, full: r.full };
    this.rasters.set(key, entry);
    return entry;
  }

  private shapeRaster(l: Layer & { type: "shape" }): Raster | null {
    const key = `s:${l.id}`;
    const sig = JSON.stringify([l.shape, l.w, l.h, l.fill, l.stroke, l.radius, this.Wc, l.shape === "path" ? l.path : 0]);
    const have = this.rasters.get(key);
    if (have && have.sig === sig) return have;
    const r = rasterShape(l, this.Wc);
    if (have) this.g.destroy(have.tex);
    if (!r) {
      this.rasters.delete(key);
      return null;
    }
    const tex = this.g.upload(r.canvas, { premult: true, mips: true });
    const entry: Raster = { sig, tex, bw: r.bw, bh: r.bh, cw: l.w, ch: l.h, full: false };
    this.rasters.set(key, entry);
    return entry;
  }

  private retouchData(l: Layer & { type: "retouch" }): Retouch | null {
    const sig = JSON.stringify([l.strokes, this.Wc, this.Hc]);
    const have = this.retouches.get(l.id);
    if (have && have.sig === sig) return have;
    if (have) have.groups.forEach((gr) => this.g.destroy(gr.brush));
    const groups: Retouch["groups"] = [];
    let cur: typeof l.strokes = [];
    let prevKey = "";
    const flush = () => {
      if (!cur.length) return;
      const s0 = cur[0];
      const dx = Math.round(s0.dx * this.Wc) / this.Wc;
      const dy = Math.round(s0.dy * this.Hc) / this.Hc;
      if (dx === 0 && dy === 0) return;
      const cv = rasterStrokes(cur, this.Wc, this.Hc);
      const brush = this.g.upload(cv, { premult: false });
      groups.push({ brush, dx, dy, heal: cur.some((s) => s.mode === "heal"), sigma: Math.max(1, 0.5 * Math.max(...cur.map((s) => s.r)) * this.Wc) });
    };
    for (const s of l.strokes) {
      const key = `${Math.round(s.dx * this.Wc)}:${Math.round(s.dy * this.Hc)}`;
      if (key !== prevKey) {
        flush();
        cur = [];
        prevKey = key;
      }
      cur.push(s);
    }
    flush();
    const entry: Retouch = { sig, groups };
    this.retouches.set(l.id, entry);
    return entry;
  }

  /** پاکسازیِ منابعِ لایه‌های حذف‌شده */
  gc(layers: Layer[]): void {
    const ids = new Set(layers.map((l) => l.id));
    for (const [k, r] of this.rasters) {
      if (!ids.has(k.slice(2))) {
        this.g.destroy(r.tex);
        this.rasters.delete(k);
      }
    }
    for (const [k, r] of this.retouches) {
      if (!ids.has(k)) {
        r.groups.forEach((gr) => this.g.destroy(gr.brush));
        this.retouches.delete(k);
      }
    }
    const byId = new Map(layers.map((l) => [l.id, l]));
    for (const [k, b] of this.fxBaked) {
      const l = byId.get(k);
      if (!l || !fxActive((l as { fx?: LayerFx | null }).fx)) {
        this.g.destroy(b.tex);
        freeFxCache(this.g, b.cache);
        this.fxBaked.delete(k);
      }
    }
  }

  /**
   * تایلِ لایه + جلوه‌های پخته (سایه/درخشش/دورخط) ⇒ بافتِ تازه با حاشیهٔ متقارن (مرکزِ تایل = محورِ لایه)؛ null = بی‌اثر/بیش‌ازحد بزرگ.
   * cw×ch = اندازهٔ محتوا به پیکسلِ بوم (تصویر: اندازهٔ بومیِ لایه). کَش بر پایهٔ امضای جلوه و هویتِ بافتِ منبع.
   */
  private fxTile(
    l: { id: string; fx?: LayerFx | null }, src: Tex, cw: number, ch: number,
    o: { flipX?: boolean; flipY?: boolean; full?: boolean; kx?: number; ky?: number },
  ): { tex: Tex; bw: number; bh: number } | null {
    const e = effectiveFx(l.fx);
    const W = this.Wc;
    const kx = o.kx ?? 1;
    const ky = o.ky ?? 1;
    const sig = JSON.stringify([e, W, cw, ch, !!o.flipX, !!o.flipY, !!o.full, kx, ky]);
    const have = this.fxBaked.get(l.id);
    if (have && have.src === src && have.sig === sig) return have;
    const cache = have?.cache ?? newFxCache();
    if (have) {
      this.g.destroy(have.tex);
      this.fxBaked.delete(l.id);
    }
    const r = bakeFx(this.g, { tex: src, cw, ch, flipX: o.flipX, flipY: o.flipY, crop: o.full }, e, W, cache);
    if (!r) {
      freeFxCache(this.g, cache);
      return null;
    }
    const entry = { sig, src, tex: r.tex, bw: o.full ? r.w / W : (r.w * kx) / W, bh: o.full ? r.h / W : (r.h * ky) / W, cache };
    this.fxBaked.set(l.id, entry);
    return entry;
  }

  // ───────────────────────── خطِ لولهٔ لغزنده‌ها (Camera Raw)

  private smallSize(w: number, h: number, workSide: number): [number, number, number] {
    const dim = Math.max(w, h);
    const k = Math.min(1, workSide / dim);
    return [Math.max(1, Math.round(w * k)), Math.max(1, Math.round(h * k)), k];
  }

  private boxBlur(src: Tex, r: number): Tex {
    const g = this.g;
    const t = g.take(src.w, src.h);
    g.pass("box", SH.box, t, { uT: src, uStep: [1 / src.w, 0], uR: r });
    const o = g.take(src.w, src.h);
    g.pass("box", SH.box, o, { uT: t, uStep: [0, 1 / src.h], uR: r });
    g.release(t);
    return o;
  }

  /** فیلترِ هدایت‌شدهٔ سریع روی ip (R=I، G=p) ⇐ (میانگینِ a و b) در همان اندازه */
  private guidedAB(ip: Tex, r: number, eps: number): Tex {
    const g = this.g;
    const pk = g.take(ip.w, ip.h);
    g.pass("gfPack", SH.gfPack, pk, { uIP: ip });
    const m = this.boxBlur(pk, r);
    g.pass("gfAB", SH.gfAB, pk, { uM: m, uEps: eps });
    g.release(m);
    const out = this.boxBlur(pk, r);
    g.release(pk);
    return out;
  }

  private guidedSelf(src: Tex, rFrac: number, eps: number): Tex {
    const g = this.g;
    const dim = Math.max(src.w, src.h);
    const [sw, sh, k] = this.smallSize(src.w, src.h, 640);
    const r = Math.max(1, Math.round(dim * rFrac * k));
    const ip = g.take(sw, sh);
    g.pass("lumaOnly", SH.lumaOnly, ip, { uT: src });
    const ab = this.guidedAB(ip, Math.min(r, 38), eps);
    g.release(ip);
    return ab;
  }

  private gaussian(src: Tex, sigma: number): Tex {
    const g = this.g;
    let f = 1;
    while (sigma / f > 8) f *= 2;
    let base = src;
    let small: Tex | null = null;
    if (f > 1) {
      small = g.take(Math.max(1, Math.round(src.w / f)), Math.max(1, Math.round(src.h / f)));
      g.pass("copy", SH.copy, small, { uT: src });
      base = small;
    }
    const s = Math.max(0.3, sigma / f);
    const t = g.take(base.w, base.h);
    g.pass("blur", SH.blur, t, { uT: base, uStep: [1 / base.w, 0], uSigma: s });
    const o = g.take(base.w, base.h);
    g.pass("blur", SH.blur, o, { uT: t, uStep: [0, 1 / base.h], uSigma: s });
    g.release(t, small);
    return o;
  }

  private lut(a: Adjust, curve: Curve): Tex | null {
    const key = JSON.stringify([a.levelsBlack, a.levelsWhite, a.levelsGamma, a.blacks, a.whites, a.contrast, a.brightness, curve]);
    if (this.lutKey === key) return this.lutTex;
    const data = buildCurveLut(a, curve);
    if (this.lutTex) this.g.destroy(this.lutTex);
    this.lutTex = data ? this.g.fromBytes(data, LUT_N + 1, 1) : null;
    this.lutKey = key;
    return this.lutTex;
  }

  /** لغزنده‌ها را به ترتیبِ PhotoEngine.Render روی src اعمال می‌کند. src دست نمی‌خورد؛ اگر بی‌اثر باشد خودش برمی‌گردد. */
  develop(src: Tex, a: Adjust, curve: Curve, scale = 1): { tex: Tex; temp: boolean } {
    const g = this.g;
    const w = src.w;
    const h = src.h;
    let cur = src;
    let own = false;
    const step = (name: string, fs: string, u: Record<string, UValue>) => {
      const out = g.take(w, h);
      g.pass(name, fs, out, { uT: cur, ...u });
      if (own) g.release(cur);
      cur = out;
      own = true;
    };

    // ۱) تعادلِ سفیدی و نوردهی
    const temp = val(a, "temperature");
    const tint = val(a, "tint");
    const ev = val(a, "exposure");
    if (temp || tint || ev) {
      const [kr, kg, kb] = whiteBalanceGains(temp, tint);
      const e = Math.pow(2, ev);
      const k: [number, number, number] = [kr * e, kg * e, kb * e];
      step("wb", SH.wb, { uK: k, uShoulder: Math.max(...k) > 1.0001 ? 1 : 0 });
    }
    // ۲) مه‌زدایی
    if (has(a, "dehaze")) {
      const [sw, sh] = this.smallSize(w, h, 600);
      const patch = Math.max(3, Math.floor(Math.max(sw, sh) * 0.02)) | 1;
      const er = (patch - 1) >> 1;
      const nrm = g.take(sw, sh);
      g.pass("dzNorm", SH.dzNorm, nrm, { uT: cur, uAir: this.air });
      const e1 = g.take(sw, sh);
      g.pass("boxMin", SH.boxMin, e1, { uT: nrm, uStep: [1 / sw, 0], uR: er });
      g.pass("boxMin", SH.boxMin, nrm, { uT: e1, uStep: [0, 1 / sh], uR: er });
      const ip = g.take(sw, sh);
      g.pass("dzIP", SH.dzIP, ip, { uT: cur, uE: nrm });
      const ab = this.guidedAB(ip, Math.min(38, Math.max(1, Math.round(Math.max(sw, sh) * 0.03))), 1e-3);
      g.pass("gfOut", SH.gfOut, e1, { uAB: ab, uI: ip });
      step("dzApply", SH.dzApply, { uTr: e1, uAir: this.air, uA: val(a, "dehaze") / 100 });
      g.release(nrm, e1, ip, ab);
    }
    // ۳) روشنی‌ها / سایه‌ها
    if (has(a, "highlights") || has(a, "shadows")) {
      const gb = this.guidedSelf(cur, 0.025, 0.02);
      step("hs", SH.hs, { uGB: gb, uSh: val(a, "shadows") / 100, uHl: val(a, "highlights") / 100 });
      g.release(gb);
    }
    // ۴) منحنی‌ها
    const lut = this.lut(a, curve);
    if (lut) step("lut", SH.lut, { uLut: lut, uN: LUT_N });
    // ۵) بافت و وضوح
    const clar = val(a, "clarity");
    const tex = val(a, "texture");
    if (clar || tex) {
      const dim = Math.max(w, h);
      const gb = clar ? this.guidedSelf(cur, 0.015, 0.01) : null;
      const bl = tex ? this.gaussian(cur, Math.max(1, dim * 0.003)) : null;
      step("tc", SH.tc, { uGB: gb ?? cur, uBlur: bl ?? cur, uClar: (clar / 100) * 1.2 * (clar ? 1 : 0), uTex: tex / 100 });
      g.release(gb, bl);
    }
    // ۶) رنگ
    const dh = new Float32Array(9);
    const ds = new Float32Array(9);
    const dl = new Float32Array(9);
    let hsl = false;
    BANDS.forEach((b, i) => {
      dh[i] = (val(a, b + "Hue") / 100) * 30;
      ds[i] = val(a, b + "Sat") / 100;
      dl[i] = val(a, b + "Lum") / 100;
      hsl = hsl || dh[i] !== 0 || ds[i] !== 0 || dl[i] !== 0;
    });
    dh[8] = dh[0];
    ds[8] = ds[0];
    dl[8] = dl[0];
    const vib = val(a, "vibrance") / 100;
    const sat = val(a, "saturation") / 100;
    const shS = val(a, "shadowsSat") / 100;
    const hiS = val(a, "highlightsSat") / 100;
    const grade = shS > 0 || hiS > 0;
    if (hsl || vib || sat || grade) {
      step("color", SH.color, {
        "uDh[]": dh, "uDs[]": ds, "uDl[]": dl, uHsl: hsl ? 1 : 0, uVib: vib, uSat: sat, uGrade: grade ? 1 : 0, uShS: shS, uHiS: hiS,
        uBal: val(a, "gradingBalance") / 100, uShT: tintDir(val(a, "shadowsHue")), uHiT: tintDir(val(a, "highlightsHue")),
      });
    }
    // ۷) نویزگیری و شارپ
    const nl = val(a, "noiseLuma") / 100;
    const nc = val(a, "noiseColor") / 100;
    if (nl > 0 || nc > 0) step("denoise", SH.denoise, { uPx: [1 / w, 1 / h], uLuma: nl, uColor: nc });
    const sharp = val(a, "sharpen") / 100;
    if (sharp > 0) {
      const sigma = Math.max(0.4, val(a, "sharpenRadius") * scale);
      const bl = this.gaussian(cur, sigma);
      const masking = val(a, "sharpenMasking") / 100;
      step("sharpen", SH.sharpen, { uBlur: bl, uPx: [1 / w, 1 / h], uK: sharp * 1.6, uM0: masking * 0.35, uUseMask: masking > 0 ? 1 : 0 });
      g.release(bl);
    }
    // ۸) لنز
    const dist = val(a, "distortion");
    const lv = val(a, "lensVignette");
    if (dist || lv > 0) {
      const k = (-dist / 100) * 0.25;
      step("lens", SH.lens, { uSize: [w, h], uK: k, uNorm: k > 0 ? 1 / (1 + k) : 1, uLv: lv > 0 ? (lv / 100) * 0.9 : 0 });
    }
    // ۹) وینیت و دانه
    const vig = val(a, "vignette") / 100;
    const grain = val(a, "grain") / 100;
    if (vig || grain > 0) {
      const inner = 0.15 + (val(a, "vignetteMidpoint") / 100) * 0.7;
      const outer = inner + 0.05 + (val(a, "vignetteFeather") / 100) * 0.8;
      const cell = Math.max(1, (1 + (val(a, "grainSize") / 100) * 4) * scale);
      step("fx", SH.fx, { uSize: [w, h], uVig: vig, uInner: inner, uOuter: outer, uGrain: grain > 0 ? grain : 0, uCell: cell });
    }
    return { tex: cur, temp: own };
  }

  /**
   * مرحلهٔ ۱ (فضای عکس): عکسِ پایه ⇒ ظهورِ لغزنده‌ها، یا خروجیِ دقیقِ سرورِ پردازش (exact). خروجی ورودیِ مرحلهٔ قاب است و
   * `this.devSig` محتوایش را نشان می‌دهد (تغییرِ امضا ⇒ بافتِ قاب دوباره ساخته می‌شود).
   *
   * LIQUIFY SLOT: پاسِ مایع‌سازی (نقشهٔ جابه‌جایی liquify.bin، فقط روی عکسِ پایه) باید همین‌جا بین ظهور و قاب بنشیند —
   * یعنی نتیجهٔ پایین را به‌جای `return` مستقیم از یک پاسِ liquify رد کنید و `state.liquify?.rev` را در devSig بیاورید.
   * سرور هم همین ترتیب را دارد: develop ⇒ liquify ⇒ perspective/rotate/crop…
   * (پاسِ مایع‌سازی در `baseDeveloped` پایین است؛ `baseDevelopedRaw` فقط ظهور/دقیق را می‌سازد.)
   */
  /**
   * نقشهٔ مایع‌سازیِ پروژه (فضای عکس) را به موتور می‌دهد: `field` = (dx, dy) نرمال، ردیف‌به‌ردیف، gw·gh·2؛ `ver` با هر تغییر بالا می‌رود
   * (فقط آن‌وقت دوباره آپلود می‌شود)؛ `active=false` (نقشهٔ صفر) یا null ⇒ بی‌پاس. «قبل» همیشه بی مایع‌سازی است (beforeTexture از baseSrc).
   */
  setLiquify(m: { field: Float32Array; gw: number; gh: number; ver: number; active: boolean } | null): void {
    if (!m || !m.active) {
      if (this.lqOn) this.lqKey = "";
      this.lqOn = false;
      return;
    }
    if (!this.lq || this.lq.gw !== m.gw || this.lq.gh !== m.gh) {
      if (this.lq) this.g.destroy(this.lq.tex);
      this.lq = { tex: this.g.fromFloatRG(m.field, m.gw, m.gh), gw: m.gw, gh: m.gh, ver: m.ver };
    } else if (this.lq.ver !== m.ver) {
      this.g.reuploadFloatRG(this.lq.tex, m.field);
      this.lq.ver = m.ver;
    }
    this.lqOn = true;
  }

  private baseDeveloped(state: ProState, noDevelop: boolean): Tex | null {
    const t = this.baseDevelopedRaw(state, noDevelop);
    if (!t || noDevelop || !this.lqOn || !this.lq) return t;
    const g = this.g;
    const key = `${this.devSig}|lq${this.lq.ver}|${t.w}x${t.h}`;
    if (!this.lqOut || this.lqOut.w !== t.w || this.lqOut.h !== t.h) {
      if (this.lqOut) g.destroy(this.lqOut);
      this.lqOut = g.create(t.w, t.h, true);
      this.lqKey = "";
    }
    if (this.lqKey !== key) {
      g.pass("liquify", SH.liquify, this.lqOut, { uT: t, uF: this.lq.tex, uG: [this.lq.gw, this.lq.gh] });
      g.mips(this.lqOut);
      this.lqKey = key;
    }
    this.dev = this.lqOut;
    this.devSig = `${this.devSig}|lq${this.lq.ver}`;
    return this.lqOut;
  }

  private baseDevelopedRaw(state: ProState, noDevelop: boolean): Tex | null {
    if (!this.baseSrc) return null;
    const pick = (tex: Tex, sig: string): Tex => {
      this.dev = tex;
      this.devSig = `${this.baseVer}:${sig}`;
      return tex;
    };
    if (noDevelop) return pick(this.baseSrc, "raw");
    if (this.exactTex) return pick(this.exactTex, `exact${this.exactVer}`);
    const key = JSON.stringify([state.adjust, state.curve, this.Wd, this.Hd]);
    if (this.devTex && this.devKey === key) return pick(this.devTex, key);
    const scale = this.Wo ? this.Wd / this.Wo : 1;
    const r = this.develop(this.baseSrc, state.adjust, state.curve, scale);
    if (!r.temp) {
      this.devKey = key;
      if (this.devTex) this.g.destroy(this.devTex);
      this.devTex = null;
      return pick(this.baseSrc, "raw");
    }
    if (!this.devTex || this.devTex.w !== r.tex.w || this.devTex.h !== r.tex.h) {
      if (this.devTex) this.g.destroy(this.devTex);
      this.devTex = this.g.create(r.tex.w, r.tex.h, true);
    }
    this.g.pass("copy", SH.copy, this.devTex, { uT: r.tex });
    this.g.mips(this.devTex); // نمونه‌برداریِ سه‌خطیِ پاسِ قاب
    this.g.release(r.tex);
    this.devKey = key;
    return pick(this.devTex, key);
  }

  // ───────────────────────── مرحلهٔ ۲: قاب

  /** مشخصاتِ قاب (از frame.ts)؛ اندازهٔ کاریِ بوم از آن می‌آید */
  setFrame(spec: FrameSpec): void {
    this.frameSpec = spec;
    let w: number;
    let h: number;
    if (spec.trivial) {
      w = this.Wd;
      h = this.Hd;
    } else {
      const k = Math.min(1, WORK_MAX / Math.max(spec.Wf, spec.Hf));
      w = Math.max(1, Math.round(spec.Wf * k));
      h = Math.max(1, Math.round(spec.Hf * k));
    }
    this.Wc = w;
    this.Hc = h;
  }

  get frame(): FrameSpec | null {
    return this.frameSpec;
  }

  /** پاسِ قاب: src (فضای عکس) ⇒ target (بومِ نهایی). maskFill: بیرونِ عکس سیاهِ مات (برای نگاشتِ ماسک‌های فضای عکس) */
  private framePass(src: Tex, target: Tex, spec: FrameSpec, maskFill = false): void {
    const g = this.g;
    const u = frameUniforms(spec);
    let bg: Tex | null = null;
    const fill = maskFill ? 1 : u.fill;
    if (u.contain && fill === 3) {
      // پس‌زمینهٔ محو: بافتِ ۱/۸ ⇒ گاوسِ σ=۶ (به پیکسلِ همان مقیاس) — همان الگوریتمِ ops.op_crop_format
      const small = g.take(u.bgSize[0], u.bgSize[1]);
      g.pass("frameBg", SH.frameBg, small, { uT: src, uInv: u.bgInv });
      bg = this.gaussian(small, 6);
      g.release(small);
    }
    g.pass("frame", SH.frame, target, {
      uT: src, uBg: bg ?? src, uInv: u.inv, uCanvas: [spec.Wf, spec.Hf], uWork: [target.w, target.h], uContain: u.contain ? 1 : 0,
      uFg: u.fg, uFill: fill, uFillColor: u.color, uBias: -0.5,
    });
    if (bg) g.release(bg);
  }

  /** مرحلهٔ ۲: بافتِ بومِ نهایی از خروجیِ مرحلهٔ ۱. قابِ بی‌اثر ⇒ همان بافتِ ورودی (بی پاس) */
  private frameTexture(src: Tex, srcSig: string): Tex {
    const spec = this.frameSpec!;
    if (spec.trivial) return src;
    const key = `${spec.key}|${srcSig}|${this.Wc}x${this.Hc}`;
    if (this.frameTex && this.frameTex.w === this.Wc && this.frameTex.h === this.Hc && this.frameSig === key) return this.frameTex;
    if (!this.frameTex || this.frameTex.w !== this.Wc || this.frameTex.h !== this.Hc) {
      if (this.frameTex) this.g.destroy(this.frameTex);
      this.frameTex = this.g.create(this.Wc, this.Hc, true);
    }
    this.framePass(src, this.frameTex, spec);
    this.frameSig = key;
    return this.frameTex;
  }

  /** «قبل»: عکسِ دست‌نخوردهٔ اصل از همان پاسِ قاب (بی ظهور و لایه) */
  private beforeTexture(): Tex | null {
    const spec = this.frameSpec;
    if (!this.baseSrc || !spec) return null;
    if (spec.trivial) return this.baseSrc;
    const key = `${spec.key}|${this.baseVer}|${this.Wc}x${this.Hc}`;
    if (this.beforeTex && this.beforeTex.w === this.Wc && this.beforeTex.h === this.Hc && this.beforeSig === key) return this.beforeTex;
    if (!this.beforeTex || this.beforeTex.w !== this.Wc || this.beforeTex.h !== this.Hc) {
      if (this.beforeTex) this.g.destroy(this.beforeTex);
      this.beforeTex = this.g.create(this.Wc, this.Hc, true);
    }
    this.framePass(this.baseSrc, this.beforeTex, spec);
    this.beforeSig = key;
    return this.beforeTex;
  }

  /** نقطهٔ بوم (کسری) ⇒ نقطهٔ عکسِ اصل (کسری)؛ بیرون از عکس ⇒ null (برای قطره‌چکانِ تعادلِ سفیدی) */
  canvasToPhoto(nx: number, ny: number): [number, number] | null {
    return this.frameSpec ? canvasToPhoto(this.frameSpec, nx, ny) : null;
  }

  /** تصویرِ فضای عکس (مثلاً ماسکِ سوژه از سرور) ⇒ بومِ ۲بعدیِ فضای بوم (بیرونِ عکس سیاه) */
  warpToCanvas(img: TexImageSource): HTMLCanvasElement | null {
    const spec = this.frameSpec;
    if (!spec || !this.ok) return null;
    const out = newCanvas(this.Wc, this.Hc);
    const x = out.getContext("2d", { willReadFrequently: true })!;
    if (spec.trivial) {
      x.fillStyle = "#000";
      x.fillRect(0, 0, out.width, out.height);
      x.drawImage(img as CanvasImageSource, 0, 0, out.width, out.height);
      return out;
    }
    const g = this.g;
    const src = g.upload(img, { premult: false, mips: true });
    const t = g.create(this.Wc, this.Hc, false);
    this.framePass(src, t, spec, true);
    const data = g.read(t);
    g.destroy(src);
    g.destroy(t);
    x.putImageData(new ImageData(data, this.Wc, this.Hc), 0, 0);
    return out;
  }

  // ───────────────────────── «سوژه (خودکار)» برای قابِ cover

  /**
   * جای «خودکار»ِ قاب، یا null (قاب خودکار نیست / هنوز عکس نیامده):
   *  - cover + «سوژه (خودکار)»: پنجرهٔ برش [x, y, w, h] (کسری از تصویرِ پس از هندسه)؛
   *  - contain + «کالا وسطِ قاب»: جای دوربین [zoom, cx, cy] (کالا کامل و با حاشیه وسطِ قاب؛ کالا کلِ عکس است ⇒ [1، ۰٫۵، ۰٫۵]).
   * روی کوچک‌نمایِ ۳۲۰ پیکسلیِ عکسِ *بی‌ظهور* پس از پرسپکتیو/چرخش/برش حساب می‌شود (پس با لغزنده‌ها عوض نمی‌شود) و به‌ازای
   * امضای هندسه کَش می‌شود؛ پیش‌نمایش و خروجی (کارِ crop_format با window/view) هر دو همین را می‌بینند.
   * cacheOnly: فقط اگر از پیش حساب شده باشد (هنگامِ کشیدنِ دستگیره‌های برش گران نشود).
   */
  smartWindow(spec: FrameSpec, cacheOnly = false): number[] | null {
    const cf = spec.cf;
    const subject = !!cf && cf.fit === "contain" && cf.subject === "auto";
    if (!cf || (!subject && (cf.fit !== "cover" || cf.focus !== "smart")) || !this.baseSrc || !this.ok) return null;
    // «کالا وسطِ قاب» نقشهٔ انرژیِ بی سهمِ وسط می‌خواهد (جعبهٔ کالا)؛ «جای پنجره» با سهمِ وسط — کَشِ جدا
    const key = `${subject ? "s" : "c"}|${this.baseVer}|${JSON.stringify(spec.geoH.map((v) => Math.round(v * 1e6) / 1e6))}|${spec.gw}x${spec.gh}`;
    let em = this.energies.get(key);
    if (!em) {
      if (cacheOnly) return null;
      const [tw, th] = thumbSize(spec.gw, spec.gh);
      const g = this.g;
      const t = g.create(tw, th, false);
      // فقط هندسه (بی قابِ شبکه): H = geoH و بومِ gw×gh
      const geoOnly = { ...spec, H: spec.geoH, Wf: spec.gw, Hf: spec.gh, cf: null, social: null, trivial: false } as FrameSpec;
      this.framePass(this.baseSrc, t, geoOnly);
      const data = g.read(t);
      g.destroy(t);
      em = energyMap(data, tw, th, this.baseHasAlpha, !subject);
      if (this.energies.size > 8) this.energies.clear();
      this.energies.set(key, em);
    }
    const map = em;
    if (subject) {
      const [tw0, th0] = cropFormatTarget(cf);
      return subjectView(map, this.baseHasAlpha, spec.gw, spec.gh, tw0, th0) ?? [1, 0.5, 0.5];
    }
    // پنجره: هندسهٔ cover بی‌پنجره با energy ⇒ جعبه ⇒ کسری
    const noWin = { ...cf, window: [] as number[] };
    const geo = cropFormatGeometry(noWin, spec.gw, spec.gh, (cw, ch) => energyOffset(map, spec.gw, spec.gh, cw, ch));
    if (geo.mode !== "cover") return null;
    const [x0, y0, x1, y1] = geo.box;
    const win = normalizeWindow([x0 / spec.gw, y0 / spec.gh, (x1 - x0) / spec.gw, (y1 - y0) / spec.gh]);
    return win.length === 4 ? win : null;
  }

  // ───────────────────────── ترکیب

  private maskU(m: MaskSpec | null, masks: Map<string, MaskEntry>): Record<string, UValue> {
    const none = { uMType: 0, uMInv: 0, uMP: [0, 0, 0, 0], uMFeather: 0 };
    if (!m) return none;
    if (m.type === "paint") {
      const e = masks.get(m.id);
      if (!e) return none;
      let t = this.maskTex.get(m.id);
      if (!t) {
        t = { tex: this.g.upload(e.canvas, { premult: false }), ver: e.ver };
        this.maskTex.set(m.id, t);
      } else if (t.ver !== e.ver) {
        this.g.reupload(t.tex, e.canvas, false);
        t.ver = e.ver;
      }
      return { uMType: 1, uMInv: m.invert ? 1 : 0, uMP: [0, 0, 0, 0], uMFeather: 0, uMask: t.tex };
    }
    if (m.type === "linear") return { uMType: 2, uMInv: m.invert ? 1 : 0, uMP: [m.p0[0], m.p0[1], m.p1[0], m.p1[1]], uMFeather: 0 };
    return { uMType: 3, uMInv: m.invert ? 1 : 0, uMP: [m.c[0], m.c[1], Math.max(1e-4, m.rx), Math.max(1e-4, m.ry)], uMFeather: m.feather };
  }

  /**
   * حالتِ «عکس» (ابزارهای هندسه: برش/صاف/پرسپکتیو/لکه): فقط مرحلهٔ ۱ — کلِ عکسِ بی‌برش و بی‌لایه؛ present با mode="photo".
   */
  renderPhoto(state: ProState): Tex | null {
    if (!this.baseSrc || !this.ok) return null;
    this.lastMode = "photo";
    return this.baseDeveloped(state, false);
  }

  /**
   * همهٔ لایه‌ها ⇐ بافتِ بومِ نهایی (با اندازهٔ کاری Wc×Hc). مالکیت با موتور است؛ نگه‌داری یا کپی کنید.
   * خطِ لوله: ۱) baseDeveloped  ۲) frameTexture  ۳) لایه‌ها (پایین‌تر).
   */
  render(state: ProState, rc: RenderCtx): Tex | null {
    const g = this.g;
    if (!this.baseSrc || !this.ok || !this.frameSpec) return null;
    this.lastMode = "canvas";
    // ── مرحلهٔ ۱ (فضای عکس) و ۲ (قاب ⇒ بومِ نهایی)
    const dev = this.baseDeveloped(state, !!rc.noDevelop);
    if (!dev) return null;
    const frame = this.frameTexture(dev, this.devSig);
    // ── مرحلهٔ ۳: لایه‌ها روی بومِ نهایی (همه‌چیز از اینجا به بعد نسبت به بوم است)
    const W = this.Wc;
    const H = this.Hc;
    const doc: [number, number] = [W, H];
    const byParent = childrenMap(state.layers);
    const nul = this.nullTex();
    const CLIPPABLE = new Set(["image", "text", "shape", "group"]);
    /** یک لایهٔ پیکسل‌دار روی dst (بدونِ تغییرِ dst) ⇒ بافتِ تازه؛ clip = شکلِ هدفِ برش یا null */
    const compPass = (dst: Tex, geom: Record<string, UValue>, opacity: number, mode: number, mu: Record<string, UValue>, clip: Tex | null): Tex => {
      const out = g.take(W, H);
      g.pass("comp", SH.comp, out, { uDst: dst, uMask: nul, ...geom, uOpacity: opacity, uMode: mode, ...mu, uUseClip: clip ? 1 : 0, uClip: clip ?? nul });
      return out;
    };
    /** «شکلِ» لایه برای برشِ لایه‌های بالاتر: آلفای تایل × ماسک × (برشِ خودش)؛ روی بومِ شفاف و بی‌پیدایی/حالت */
    const shapeOf = (geom: Record<string, UValue>, mu: Record<string, UValue>, clip: Tex | null): Tex => {
      const empty = g.take(W, H);
      g.clear(empty, 0, 0, 0, 0);
      const t = compPass(empty, geom, 1, 0, mu, clip);
      g.release(empty);
      return t;
    };
    const FULL_GEOM = { uDoc: doc, uC: [0, 0], uS: [1, 1], uRot: 0, uFlip: [1, 1], uFull: 1 };
    /**
     * یک سطحِ درخت (فهرستِ هم‌خواهرها از پایین به بالا) روی acc0 (مالکیتِ acc0 با تابع است و بافتِ نهایی برمی‌گردد).
     * گروه = انباشتگرِ شفافِ تازه (فرزندان داخلش؛ تنظیم/روتوش هم فقط روی همان) و بعد با حالت/پیدایی/ماسکِ خودش روی acc.
     * برش: هدفِ هر لایهٔ clip = نزدیک‌ترین لایهٔ image|text|shape|group ِ پایین‌تر در همین سطح (پنهان هم)؛ شکلِ هدف یک‌بار ساخته می‌شود.
     */
    const level = (items: Layer[], acc0: Tex, depth: number): { acc: Tex; drawn: boolean } => {
      let acc = acc0;
      let drawn = false;
      const swap = (out: Tex) => {
        g.release(acc);
        acc = out;
      };
      const targetOf = new Map<string, string>();
      const targets = new Set<string>();
      let lastT: string | null = null;
      for (const l of items) {
        if (!CLIPPABLE.has(l.type)) continue;
        if (rc.only && !rc.only.has(l.id)) continue;
        if (l.clip && lastT) {
          targetOf.set(l.id, lastT);
          targets.add(lastT);
        }
        lastT = l.id;
      }
      const shapes = new Map<string, Tex>();
      for (const l of items) {
        if (!l.visible) continue;
        let clipTex: Tex | null = null;
        if (CLIPPABLE.has(l.type)) {
          const tid = targetOf.get(l.id);
          if (tid) {
            clipTex = shapes.get(tid) ?? null;
            if (!clipTex) continue; // هدفِ برش پنهان/بی‌پیکسل ⇒ این لایه هم دیده نمی‌شود
          }
        }
        if (l.type === "group") {
          const ch = byParent.get(l.id) ?? [];
          if (!ch.length || depth >= 8) continue;
          if (rc.only && !rc.only.has(l.id)) {
            // فقط‌-ها (تلفیق): گروه ظرفِ شفاف است، نه لایه
            const r = level(ch, acc, depth + 1);
            acc = r.acc;
            drawn = drawn || r.drawn;
            continue;
          }
          const g0 = g.take(W, H);
          g.clear(g0, 0, 0, 0, 0);
          const r = level(ch, g0, depth + 1);
          if (!r.drawn) {
            g.release(r.acc);
            continue;
          }
          const mu = this.maskU(l.mask, rc.masks);
          const geom = { ...FULL_GEOM, uSrc: r.acc, uPremul: 0 };
          swap(compPass(acc, geom, l.opacity, BLEND_INDEX[l.blend] ?? 0, mu, clipTex));
          if (targets.has(l.id)) shapes.set(l.id, shapeOf(geom, mu, clipTex));
          g.release(r.acc);
          drawn = true;
          continue;
        }
        if (rc.only && !rc.only.has(l.id)) continue;
        const mu = this.maskU(l.mask, rc.masks);
        const op = l.opacity;
        if (l.type === "base") {
          // لایهٔ پایه = بافتِ قاب با پوششِ کامل (uFull)
          const out = g.take(W, H);
          g.pass("comp", SH.comp, out, { uDst: acc, uSrc: frame, uDoc: doc, uC: [0, 0], uS: [1, 1], uRot: 0, uFlip: [1, 1], uFull: 1, uPremul: 0, uOpacity: op, uMode: BLEND_INDEX[l.blend] ?? 0, uMask: nul, ...mu, uUseClip: 0, uClip: nul });
          swap(out);
          drawn = true;
        } else if (l.type === "image" || l.type === "text" || l.type === "shape") {
          let tex: Tex | null = null;
          let bw = 0;
          let bh = 0;
          let full = false;
          let flipX = false;
          let flipY = false;
          if (l.type === "image") {
            const i = this.images.get(this.srcKey(l));
            if (!i) continue;
            tex = i.tex;
            bw = l.w;
            bh = (l.w * i.h) / i.w;
            flipX = l.flip_h;
            flipY = l.flip_v;
            if (fxActive(l.fx)) {
              // جلوه‌ها به پیکسلِ بوم‌اند ⇒ عکس اول به اندازهٔ بومیِ لایه می‌آید (قرینه هم پیش از جلوه، تا جهتِ سایه قرینه نشود)
              const wpx = l.w * W;
              const hpx = (wpx * i.h) / i.w;
              const nw = Math.max(1, Math.round(wpx));
              const nh = Math.max(1, Math.round(hpx));
              const b = this.fxTile(l, i.tex, nw, nh, { flipX, flipY, kx: wpx / nw, ky: hpx / nh });
              if (b) {
                tex = b.tex;
                bw = b.bw;
                bh = b.bh;
                flipX = false;
                flipY = false;
              }
            }
          } else if (l.type === "text") {
            const r = this.textRaster(l);
            if (!r) continue;
            tex = r.tex;
            bw = r.bw;
            bh = r.bh;
            full = r.full;
            if (fxActive(l.fx)) {
              const b = this.fxTile(l, r.tex, r.tex.w, r.tex.h, { full: r.full });
              if (b) {
                tex = b.tex;
                bw = b.bw;
                bh = b.bh;
              }
            }
          } else {
            const r = this.shapeRaster(l);
            if (!r) continue;
            tex = r.tex;
            bw = r.bw;
            bh = r.bh;
            if (fxActive(l.fx)) {
              const b = this.fxTile(l, r.tex, r.tex.w, r.tex.h, {});
              if (b) {
                tex = b.tex;
                bw = b.bw;
                bh = b.bh;
              }
            }
          }
          const cx = "cx" in l ? l.cx : 0.5;
          const cy = "cy" in l ? l.cy : 0.5;
          const rot = "rot" in l && !full ? l.rot : 0;
          const geom = {
            uSrc: tex, uDoc: doc, uC: [cx * W, cy * H], uS: [bw * W, bh * W], uRot: (rot * Math.PI) / 180,
            uFlip: [flipX ? -1 : 1, flipY ? -1 : 1], uFull: full ? 1 : 0, uPremul: 1,
          };
          swap(compPass(acc, geom, op, BLEND_INDEX[l.blend] ?? 0, mu, clipTex));
          if (targets.has(l.id)) shapes.set(l.id, shapeOf(geom, mu, clipTex));
          drawn = true;
        } else if (l.type === "adjust") {
          const wf = this.frameSpec?.Wf ?? 0;
          const scale = wf ? W / wf : 1;
          const r = this.develop(acc, l.adjust, l.curve, scale);
          if (!r.temp) continue;
          const out = g.take(W, H);
          g.pass("mix", SH.mix, out, { uDst: acc, uAdj: r.tex, uDoc: doc, uOpacity: op, uUseBrush: 0, ...mu });
          g.release(r.tex);
          swap(out);
        } else if (l.type === "retouch") {
          const rd = this.retouchData(l);
          if (!rd) continue;
          for (const grp of rd.groups) {
            const blur = grp.heal ? this.gaussian(acc, grp.sigma) : null;
            const smp = g.take(W, H);
            g.pass("rts", SH.retouchSample, smp, { uDst: acc, uBlur: blur ?? acc, uOff: [grp.dx, grp.dy], uHeal: grp.heal ? 1 : 0 });
            const out = g.take(W, H);
            g.pass("mix", SH.mix, out, { uDst: acc, uAdj: smp, uBrush: grp.brush, uDoc: doc, uOpacity: op, uUseBrush: 1, ...mu });
            g.release(smp, blur);
            swap(out);
          }
        } else if (l.type === "redeye") {
          // قرمزیِ چشم (فرمول = redeye.py): بی چشم، یا اولین لایهٔ سطح (چیزی زیرش نیست) ⇒ هیچ
          if (!l.eyes.length || !drawn) continue;
          const e = new Float32Array(48);
          l.eyes.slice(0, 16).forEach((eye, i) => {
            e[i * 3] = eye.x * W;
            e[i * 3 + 1] = eye.y * H;
            e[i * 3 + 2] = eye.r * W;
          });
          const out = g.take(W, H);
          g.pass("redeye", SH.redeye, out, { uDst: acc, uDoc: doc, uOpacity: op, uAmount: l.amount, uDarken: l.darken, uN: Math.min(16, l.eyes.length), "uE[]": e, ...mu });
          swap(out);
        }
      }
      for (const t of shapes.values()) g.release(t);
      return { acc, drawn };
    };
    let acc = g.take(W, H);
    g.clear(acc, 0, 0, 0, 0);
    acc = level(byParent.get(null) ?? [], acc, 0).acc;
    this.gc(state.layers);
    // نگه‌داشتنِ نتیجه در بافتِ همیشگیِ نما (با میپ‌مپ)
    if (!this.view || this.view.w !== W || this.view.h !== H) {
      if (this.view) g.destroy(this.view);
      this.view = g.create(W, H, true);
    }
    g.pass("copy", SH.copy, this.view, { uT: acc });
    g.mips(this.view);
    g.release(acc);
    return this.view;
  }

  // ───────────────────────── نمایش

  /**
   * M: صفحه (پیکسلِ دستگاه) ⇐ پیکسلِ واقعیِ بوم (mode="canvas"، پیش‌فرض) یا عکسِ اصل (mode="photo").
   * «قبل» = عکسِ دست‌نخوردهٔ اصل؛ در حالتِ بوم از همان پاسِ قاب می‌گذرد.
   */
  present(M: M3, size: [number, number], opts: { mode?: "canvas" | "photo"; before?: boolean; split?: number; bg?: [number, number, number] } = {}): void {
    const g = this.g;
    const photo = opts.mode === "photo";
    const a = photo ? this.dev : this.view;
    if (!a || !this.baseSrc || !this.frameSpec) {
      g.gl.bindFramebuffer(g.gl.FRAMEBUFFER, null);
      g.gl.viewport(0, 0, size[0], size[1]);
      g.gl.clearColor(0.05, 0.06, 0.09, 1);
      g.gl.clear(g.gl.COLOR_BUFFER_BIT);
      return;
    }
    const wantsBefore = !!opts.before || (opts.split !== undefined && opts.split >= 0);
    const b = photo || !wantsBefore ? this.baseSrc : (this.beforeTexture() ?? this.baseSrc);
    const docSize: [number, number] = photo ? [this.Wo || this.Wd, this.Ho || this.Hd] : [this.frameSpec.Wf, this.frameSpec.Hf];
    g.pass(
      "display", SH.display, null,
      { uA: a, uB: b, uM: M, uRes: size, uDocSize: docSize, uSplit: opts.split ?? -1, uBefore: opts.before ? 1 : 0, uBg: opts.bg ?? [0.08, 0.09, 0.13], uMax: 1, uSelOn: !photo && this.selTex ? 1 : 0, uSel: this.selTex ? this.selTex.tex : a },
      size,
    );
  }

  /** RGBA ِ کوچکِ نتیجه (برای هیستوگرام): بومِ نهایی، یا در حالتِ «عکس» خودِ عکسِ ظهورشده */
  readSmall(maxSide = 256): { data: Uint8ClampedArray; w: number; h: number } | null {
    const g = this.g;
    const src = this.lastMode === "photo" ? this.dev : this.view;
    if (!src || !this.ok) return null;
    const k = Math.min(1, maxSide / Math.max(src.w, src.h));
    const w = Math.max(1, Math.round(src.w * k));
    const h = Math.max(1, Math.round(src.h * k));
    if (!this.histTex || this.histTex.w !== w || this.histTex.h !== h) {
      if (this.histTex) g.destroy(this.histTex);
      this.histTex = g.create(w, h, false);
    }
    g.pass("quant", SH.quant, this.histTex, { uT: src });
    return { data: g.read(this.histTex), w, h };
  }

  /** بافتِ کاملِ بومِ نهایی (پس از render) ⇐ RGBA ِ خام (برای تلفیق لایه‌ها: آلفای مستقیم) */
  readFull(): { data: Uint8ClampedArray; w: number; h: number } | null {
    const g = this.g;
    if (!this.view || !this.ok) return null;
    const t = g.create(this.view.w, this.view.h, false);
    g.pass("quant", SH.quant, t, { uT: this.view });
    const data = g.read(t);
    const out = { data, w: t.w, h: t.h };
    g.destroy(t);
    return out;
  }

  /** ابزارِ عیب‌یابی (آزمونِ مرورگر) */
  debug(): Record<string, unknown> {
    const g = this.g;
    const px = (t: Tex | null): number[] | null => {
      if (!t) return null;
      const t8 = g.create(Math.min(8, t.w), Math.min(8, t.h), false);
      g.pass("quant", SH.quant, t8, { uT: t });
      const d = g.read(t8);
      g.destroy(t8);
      return Array.from(d.slice(0, 16));
    };
    return {
      floatOK: g.floatOK, fboErrors: g.fboErrors, glError: g.gl.getError(), Wd: this.Wd, Hd: this.Hd, Wc: this.Wc, Hc: this.Hc,
      Wf: this.frameSpec?.Wf ?? 0, Hf: this.frameSpec?.Hf ?? 0, trivial: this.frameSpec?.trivial ?? null, devSig: this.devSig,
      base: px(this.baseSrc), view: px(this.view), dev: px(this.devTex), hasExact: !!this.exactTex,
    };
  }

  /** کوچک‌نمایِ عکسِ پایه با تنظیم‌های داده‌شده (data URL) */
  thumbnail(a: Adjust, curve: Curve, size: number): string | null {
    if (!this.baseCpu || !this.ok) return null;
    const g = this.g;
    const small = this.smallOf(size);
    const key = `thumb${size}`;
    let src = this.thumbSrc.get(key);
    if (!src || src.w !== small.width || src.h !== small.height) {
      const c = newCanvas(small.width, small.height);
      c.getContext("2d")!.putImageData(small, 0, 0);
      if (src) g.destroy(src.tex);
      src = { tex: g.upload(c, { premult: false }), w: small.width, h: small.height };
      this.thumbSrc.set(key, src);
    }
    const r = this.develop(src.tex, a, curve, size / Math.max(1, this.Wo || this.Wd));
    const t8 = g.create(src.w, src.h, false);
    g.pass("quant", SH.quant, t8, { uT: r.tex });
    const data = g.read(t8);
    g.destroy(t8);
    if (r.temp) g.release(r.tex);
    const c = newCanvas(src.w, src.h);
    c.getContext("2d")!.putImageData(new ImageData(data, src.w, src.h), 0, 0);
    return c.toDataURL("image/jpeg", 0.8);
  }
  private thumbSrc = new Map<string, { tex: Tex; w: number; h: number }>();

  /** میانگینِ رنگِ یک ناحیه از اصلِ بدون تنظیم (۰..۱)، موقعیت نسبی */
  sampleBase(nx: number, ny: number, radius = 2): [number, number, number] | null {
    const b = this.baseCpu;
    if (!b) return null;
    const cx = Math.round(nx * (b.width - 1));
    const cy = Math.round(ny * (b.height - 1));
    let r = 0;
    let gg = 0;
    let bb = 0;
    let n = 0;
    for (let y = Math.max(0, cy - radius); y <= Math.min(b.height - 1, cy + radius); y++) {
      for (let x = Math.max(0, cx - radius); x <= Math.min(b.width - 1, cx + radius); x++) {
        const i = (y * b.width + x) * 4;
        r += b.data[i];
        gg += b.data[i + 1];
        bb += b.data[i + 2];
        n++;
      }
    }
    return n ? [r / n / 255, gg / n / 255, bb / n / 255] : null;
  }
}

/** از رنگِ خنثی ⇐ دما و ته‌رنگ (Tone.NeutralizeToTempTint، در فضای خطی) */
export function neutralizeToTempTint(r8: number, g8: number, b8: number): { temperature: number; tint: number } {
  const lin = (v: number) => Math.max(Math.pow(Math.min(1, Math.max(0, v)), 2.2), 1e-6);
  const r = lin(r8);
  const g = lin(g8);
  const b = lin(b8);
  return { temperature: (Math.log(b / r) / 1.2) * 100, tint: (Math.log(g / Math.sqrt(r * b)) / 0.375) * 100 };
}

export type { Quad };
export { SIZE_FROM };
