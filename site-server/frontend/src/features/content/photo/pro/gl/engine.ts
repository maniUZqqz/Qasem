import type { Adjust, Curve } from "../../manual/engine";
import type { Layer, MaskSpec, ProState, Quad } from "../types";
import type { M3 } from "../geo";
import { GLCtx, Tex, UValue } from "./glutil";
import { LUT_N, buildCurveLut, newCanvas, rasterShape, rasterStrokes, rasterText } from "./raster";
import { SH } from "./shaders";

/**
 * موتورِ پیش‌نمایشِ فوری (WebGL2): فرمول‌های لغزنده‌ها از کدِ C# کیت برگردانده شده (shaders.ts)، لایه‌ها با همهٔ حالت‌های
 * آمیزشِ W3C و ماسک ترکیب می‌شوند. «پایه» می‌تواند خروجیِ دقیقِ کیت (setExact) باشد؛ آن‌وقت لغزنده‌های پایه دوباره اعمال نمی‌شوند.
 */
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
  onNeedRender: (() => void) | null = null;

  private baseSrc: Tex | null = null;
  baseCpu: ImageData | null = null;
  private air: [number, number, number] = [1, 1, 1];
  private exactTex: Tex | null = null;
  private devTex: Tex | null = null;
  private devKey = "";
  private view: Tex | null = null;
  private images = new Map<string, { tex: Tex; w: number; h: number }>();
  private imageLoads = new Map<string, Promise<{ w: number; h: number } | null>>();
  private rasters = new Map<string, Raster>();
  private retouches = new Map<string, Retouch>();
  private maskTex = new Map<string, { tex: Tex; ver: number }>();
  private lutTex: Tex | null = null;
  private lutKey = "";
  private smallBase = new Map<number, ImageData>();
  private histTex: Tex | null = null;
  private fontWait = new Set<string>();
  private selTex: { tex: Tex; ver: number } | null = null;
  private selVer = -1;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.g = new GLCtx(canvas);
    canvas.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.ok = false;
    });
  }

  // ───────────────────────── منابع

  setBase(img: HTMLImageElement | HTMLCanvasElement | ImageBitmap, origW: number, origH: number, maxSide = 1600): void {
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
    this.baseSrc = this.g.upload(c, { premult: false });
    this.Wd = w;
    this.Hd = h;
    this.Wo = origW;
    this.Ho = origH;
    this.devKey = "";
    this.smallBase.clear();
    const tiny = this.smallOf(200);
    this.air = airLight(tiny);
    this.g.clearPool();
    if (this.devTex) this.g.destroy(this.devTex);
    this.devTex = null;
    if (this.view) this.g.destroy(this.view);
    this.view = null;
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
    this.exactTex = img ? this.g.upload(img, { premult: false }) : null;
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
    const sig = JSON.stringify([l.text, l.font, l.weight, l.size, l.color, l.align, l.dir, l.line_height, l.letter_spacing, l.width, l.stroke, l.shadow, l.box, l.tile, l.lines, this.Wd, this.Hd]);
    const have = this.rasters.get(key);
    if (have && have.sig === sig) return have;
    if (!this.fontReady(l.weight)) return have ?? null;
    const r = rasterText(l, this.Wd, this.Hd);
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
    const sig = JSON.stringify([l.shape, l.w, l.h, l.fill, l.stroke, l.radius, this.Wd]);
    const have = this.rasters.get(key);
    if (have && have.sig === sig) return have;
    const r = rasterShape(l, this.Wd);
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
    const sig = JSON.stringify([l.strokes, this.Wd, this.Hd]);
    const have = this.retouches.get(l.id);
    if (have && have.sig === sig) return have;
    if (have) have.groups.forEach((gr) => this.g.destroy(gr.brush));
    const groups: Retouch["groups"] = [];
    let cur: typeof l.strokes = [];
    let prevKey = "";
    const flush = () => {
      if (!cur.length) return;
      const s0 = cur[0];
      const dx = Math.round(s0.dx * this.Wd) / this.Wd;
      const dy = Math.round(s0.dy * this.Hd) / this.Hd;
      if (dx === 0 && dy === 0) return;
      const cv = rasterStrokes(cur, this.Wd, this.Hd);
      const brush = this.g.upload(cv, { premult: false });
      groups.push({ brush, dx, dy, heal: cur.some((s) => s.mode === "heal"), sigma: Math.max(1, 0.5 * Math.max(...cur.map((s) => s.r)) * this.Wd) });
    };
    for (const s of l.strokes) {
      const key = `${Math.round(s.dx * this.Wd)}:${Math.round(s.dy * this.Hd)}`;
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

  private baseDeveloped(state: ProState, noDevelop: boolean): Tex | null {
    if (!this.baseSrc) return null;
    if (noDevelop) return this.baseSrc;
    if (this.exactTex) return this.exactTex;
    const key = JSON.stringify([state.adjust, state.curve, this.Wd, this.Hd]);
    if (this.devTex && this.devKey === key) return this.devTex;
    const scale = this.Wo ? this.Wd / this.Wo : 1;
    const r = this.develop(this.baseSrc, state.adjust, state.curve, scale);
    if (!r.temp) {
      this.devKey = key;
      if (this.devTex) this.g.destroy(this.devTex);
      this.devTex = null;
      return this.baseSrc;
    }
    if (!this.devTex || this.devTex.w !== r.tex.w || this.devTex.h !== r.tex.h) {
      if (this.devTex) this.g.destroy(this.devTex);
      this.devTex = this.g.create(r.tex.w, r.tex.h, true);
    }
    this.g.pass("copy", SH.copy, this.devTex, { uT: r.tex });
    this.g.release(r.tex);
    this.devKey = key;
    return this.devTex;
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

  /** همهٔ لایه‌ها ⇐ بافتِ ترکیب (با اندازهٔ کاری). مالکیت با موتور است؛ نگه‌داری یا کپی کنید. */
  render(state: ProState, rc: RenderCtx): Tex | null {
    const g = this.g;
    if (!this.baseSrc || !this.ok) return null;
    const W = this.Wd;
    const H = this.Hd;
    const doc: [number, number] = [W, H];
    let acc = g.take(W, H);
    g.clear(acc, 0, 0, 0, 0);
    const swap = (out: Tex) => {
      g.release(acc);
      acc = out;
    };
    for (const l of state.layers) {
      if (!l.visible) continue;
      if (rc.only && !rc.only.has(l.id)) continue;
      const mu = this.maskU(l.mask, rc.masks);
      const op = l.opacity;
      if (l.type === "base") {
        const dev = this.baseDeveloped(state, !!rc.noDevelop);
        if (!dev) continue;
        const out = g.take(W, H);
        g.pass("comp", SH.comp, out, { uDst: acc, uSrc: dev, uDoc: doc, uC: [0, 0], uS: [1, 1], uRot: 0, uFlip: [1, 1], uFull: 1, uPremul: 0, uOpacity: op, uMode: BLEND_INDEX[l.blend] ?? 0, ...mu });
        swap(out);
      } else if (l.type === "image" || l.type === "text" || l.type === "shape") {
        let tex: Tex | null = null;
        let bw = 0;
        let bh = 0;
        let full = false;
        if (l.type === "image") {
          const i = this.images.get(this.srcKey(l));
          if (!i) continue;
          tex = i.tex;
          bw = l.w;
          bh = (l.w * i.h) / i.w;
        } else if (l.type === "text") {
          const r = this.textRaster(l);
          if (!r) continue;
          tex = r.tex;
          bw = r.bw;
          bh = r.bh;
          full = r.full;
        } else {
          const r = this.shapeRaster(l);
          if (!r) continue;
          tex = r.tex;
          bw = r.bw;
          bh = r.bh;
        }
        const out = g.take(W, H);
        const cx = "cx" in l ? l.cx : 0.5;
        const cy = "cy" in l ? l.cy : 0.5;
        const rot = "rot" in l && !full ? l.rot : 0;
        g.pass("comp", SH.comp, out, {
          uDst: acc, uSrc: tex, uDoc: doc, uC: [cx * W, cy * H], uS: [bw * W, bh * W], uRot: (rot * Math.PI) / 180,
          uFlip: [l.type === "image" && l.flip_h ? -1 : 1, l.type === "image" && l.flip_v ? -1 : 1], uFull: full ? 1 : 0, uPremul: 1,
          uOpacity: op, uMode: BLEND_INDEX[l.blend] ?? 0, ...mu,
        });
        swap(out);
      } else if (l.type === "adjust") {
        const scale = this.Wo ? W / this.Wo : 1;
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
      }
    }
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

  /** M: صفحه(پیکسلِ دستگاه) ⇐ پیکسلِ سند (اندازهٔ اصل) */
  present(M: M3, size: [number, number], opts: { before?: boolean; split?: number; bg?: [number, number, number] } = {}): void {
    const g = this.g;
    if (!this.view || !this.baseSrc) {
      g.gl.bindFramebuffer(g.gl.FRAMEBUFFER, null);
      g.gl.viewport(0, 0, size[0], size[1]);
      g.gl.clearColor(0.05, 0.06, 0.09, 1);
      g.gl.clear(g.gl.COLOR_BUFFER_BIT);
      return;
    }
    g.pass(
      "display", SH.display, null,
      { uA: this.view, uB: this.baseSrc, uM: M, uRes: size, uDocSize: [this.Wo || this.Wd, this.Ho || this.Hd], uSplit: opts.split ?? -1, uBefore: opts.before ? 1 : 0, uBg: opts.bg ?? [0.08, 0.09, 0.13], uMax: 1, uSelOn: this.selTex ? 1 : 0, uSel: this.selTex ? this.selTex.tex : this.view },
      size,
    );
  }

  /** RGBA ِ کوچکِ نتیجه (برای هیستوگرام) */
  readSmall(maxSide = 256): { data: Uint8ClampedArray; w: number; h: number } | null {
    const g = this.g;
    if (!this.view) return null;
    const k = Math.min(1, maxSide / Math.max(this.view.w, this.view.h));
    const w = Math.max(1, Math.round(this.view.w * k));
    const h = Math.max(1, Math.round(this.view.h * k));
    if (!this.histTex || this.histTex.w !== w || this.histTex.h !== h) {
      if (this.histTex) g.destroy(this.histTex);
      this.histTex = g.create(w, h, false);
    }
    g.pass("quant", SH.quant, this.histTex, { uT: this.view });
    return { data: g.read(this.histTex), w, h };
  }

  /** بافتِ کاملِ ترکیب ⇐ بوم 2D (برای تلفیق لایه‌ها: آلفای مستقیم) */
  readFull(): { data: Uint8ClampedArray; w: number; h: number } | null {
    const g = this.g;
    if (!this.view) return null;
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
      floatOK: g.floatOK, fboErrors: g.fboErrors, glError: g.gl.getError(), Wd: this.Wd, Hd: this.Hd,
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
