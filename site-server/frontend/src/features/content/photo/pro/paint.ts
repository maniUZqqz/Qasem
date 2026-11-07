/**
 * لایهٔ نقاشی و خانوادهٔ قلم‌مو (نوبت ۵): قلم، مداد، پاک‌کن، سطلِ رنگ، قلمِ تاریخچه.
 *
 * هر لایهٔ نقاشی یک ImageLayer با `src = {kind:"paint", id, rev}` است؛ پیکسل‌هایش یک بومِ RGBA هم‌اندازهٔ بوم‌اند که در PaintStore می‌ماند
 * (مثلِ MaskStore ولی رنگی). `rev` با هر ضربه یک واحد بالا می‌رود تا برگشت/جلوِ تاریخچه پیکسل‌ها را هم برگرداند.
 * سرور همان PNG را (paint-<id>.png) می‌گیرد و در «ساخت» زیرِ همان لایه می‌گذارد (backend/apps/photoedit/layers.py).
 *
 * هیچ‌چیزِ React/GL این‌جا نیست؛ فقط <canvas> ⇒ در آزمونِ Node با یک canvas ِ ساختگی هم می‌شود چرخاند (flood fill و ریاضی).
 */
import type { MaskEntry } from "./gl/engine";
import { newCanvas } from "./gl/raster";

export type BrushKind = "soft" | "hard" | "spray";
export type StrokeMode = "paint" | "pencil" | "erase" | "history";
export type BrushOpts = { color: string; size: number; hardness: number; opacity: number; kind: BrushKind };

const HEX = /^#[0-9a-fA-F]{6}$/;
export const normColor = (c: string, fallback = "#e11d48"): string => (HEX.test(c) ? c.toLowerCase() : fallback);
export function hexRgb(c: string): [number, number, number] {
  const h = normColor(c);
  return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}
export const rgbHex = (r: number, g: number, b: number): string =>
  "#" + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");

// ───────────────────────────── ذخیرهٔ بومِ نقاشی‌ها + نسخه‌ها برای برگشت

const MAX_SNAPS_PER_LAYER = 14;
const SNAP_BUDGET = 192 * 1024 * 1024;

export class PaintStore {
  map = new Map<string, MaskEntry>();
  revs = new Map<string, number>();
  dirty = new Set<string>();
  /** null = بومِ کاملاً شفاف (جا نمی‌گیرد) */
  private snaps = new Map<string, Uint8ClampedArray | null>();
  private order: string[] = [];
  private bytes = 0;
  w = 1;
  h = 1;

  setSize(w: number, h: number) {
    this.w = w;
    this.h = h;
  }

  has(id: string) {
    return this.map.has(id);
  }

  get(id: string) {
    return this.map.get(id) ?? null;
  }

  private key(id: string, rev: number) {
    return `${id}@${rev}`;
  }

  create(id: string): HTMLCanvasElement {
    const c = newCanvas(this.w, this.h);
    this.map.set(id, { canvas: c, ver: 1 });
    this.revs.set(id, 0);
    this.dirty.add(id);
    this.put(this.key(id, 0), null);
    return c;
  }

  touch(id: string) {
    const e = this.map.get(id);
    if (e) {
      e.ver++;
      this.dirty.add(id);
    }
  }

  private put(k: string, data: Uint8ClampedArray | null) {
    const old = this.snaps.get(k);
    if (old) this.bytes -= old.length;
    this.snaps.set(k, data);
    if (data) this.bytes += data.length;
    this.order = this.order.filter((x) => x !== k);
    this.order.push(k);
    this.evict(k.split("@")[0]);
  }

  private evict(justId: string) {
    const mine = this.order.filter((k) => k.startsWith(justId + "@"));
    while (mine.length > MAX_SNAPS_PER_LAYER) this.drop(mine.shift()!);
    while (this.bytes > SNAP_BUDGET && this.order.length > 1) {
      const k = this.order[0];
      if (k.startsWith(justId + "@") && this.order.filter((x) => x.startsWith(justId + "@")).length <= 2) break;
      this.drop(k);
    }
  }

  private drop(k: string) {
    const d = this.snaps.get(k);
    if (d) this.bytes -= d.length;
    this.snaps.delete(k);
    this.order = this.order.filter((x) => x !== k);
  }

  /** حالتِ فعلیِ بوم را به‌عنوانِ نسخهٔ rev نگه می‌دارد */
  snapshot(id: string, rev: number) {
    const e = this.map.get(id);
    if (!e) return;
    const c = e.canvas;
    const d = c.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, c.width, c.height).data;
    this.revs.set(id, rev);
    this.put(this.key(id, rev), d);
  }

  /** بوم را به نسخهٔ rev برمی‌گرداند (اگر مانده باشد) */
  restore(id: string, rev: number): boolean {
    const e = this.map.get(id);
    const k = this.key(id, rev);
    if (!e || !this.snaps.has(k)) return false;
    const g = this.snaps.get(k);
    const x = e.canvas.getContext("2d", { willReadFrequently: true })!;
    if (g === null || g === undefined) x.clearRect(0, 0, e.canvas.width, e.canvas.height);
    else x.putImageData(new ImageData(new Uint8ClampedArray(g), e.canvas.width, e.canvas.height), 0, 0);
    this.revs.set(id, rev);
    this.touch(id);
    return true;
  }

  /**
   * بومِ نسخهٔ rev به‌صورتِ یک بومِ تازه (برای رندرِ عکسِ لحظه‌ای / منبعِ قلمِ تاریخچه)؛
   * rev همان نسخهٔ فعلی باشد یا آن نسخه دیگر نمانده باشد ⇒ null (یعنی از بومِ زنده استفاده کن).
   */
  canvasAt(id: string, rev: number): HTMLCanvasElement | null {
    const e = this.map.get(id);
    if (!e || (this.revs.get(id) ?? 0) === rev) return null;
    const k = this.key(id, rev);
    if (!this.snaps.has(k)) return null;
    const g = this.snaps.get(k);
    const c = newCanvas(e.canvas.width, e.canvas.height);
    if (g) c.getContext("2d", { willReadFrequently: true })!.putImageData(new ImageData(new Uint8ClampedArray(g), c.width, c.height), 0, 0);
    return c;
  }

  loadUrl(id: string, url: string): Promise<boolean> {
    return new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        const c = newCanvas(img.naturalWidth || this.w, img.naturalHeight || this.h);
        c.getContext("2d", { willReadFrequently: true })!.drawImage(img, 0, 0, c.width, c.height);
        this.map.set(id, { canvas: c, ver: 1 });
        this.revs.set(id, 0);
        this.snapshot(id, 0);
        resolve(true);
      };
      img.onerror = () => resolve(false);
      img.src = url;
    });
  }

  copy(from: string, to: string): boolean {
    const e = this.map.get(from);
    if (!e) return false;
    const c = newCanvas(e.canvas.width, e.canvas.height);
    c.getContext("2d", { willReadFrequently: true })!.drawImage(e.canvas, 0, 0);
    this.map.set(to, { canvas: c, ver: 1 });
    this.revs.set(to, 0);
    this.dirty.add(to);
    this.snapshot(to, 0);
    return true;
  }

  toBlob(id: string): Promise<Blob | null> {
    const e = this.map.get(id);
    return new Promise((resolve) => (e ? e.canvas.toBlob((b) => resolve(b), "image/png") : resolve(null)));
  }

  remove(id: string) {
    this.map.delete(id);
    this.revs.delete(id);
    this.dirty.delete(id);
    for (const k of [...this.order]) if (k.startsWith(id + "@")) this.drop(k);
  }

  /** بومِ شفاف است؟ (برای «پاک‌کردنِ محتوا» و پیامِ خالی) */
  isEmpty(id: string): boolean {
    const e = this.map.get(id);
    if (!e) return true;
    const d = e.canvas.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, e.canvas.width, e.canvas.height).data;
    for (let i = 3; i < d.length; i += 4) if (d[i]) return false;
    return true;
  }
}

// ───────────────────────────── قلم‌مو

const sprites = new Map<string, HTMLCanvasElement>();

/** دایرهٔ رنگیِ قطرِ d با لبهٔ نرم؛ hardness ۱ = لبهٔ تیز (با کمی آنتی‌آلیاس) */
function sprite(d: number, hardness: number, color: string): HTMLCanvasElement {
  const dd = Math.max(1, Math.round(d));
  const k = `${dd}|${hardness.toFixed(2)}|${color}`;
  let s = sprites.get(k);
  if (s) return s;
  s = newCanvas(dd, dd);
  const x = s.getContext("2d")!;
  const r = dd / 2;
  const [cr, cg, cb] = hexRgb(color);
  const g = x.createRadialGradient(r, r, 0, r, r, r);
  const h = Math.min(0.97, Math.max(0, hardness));
  g.addColorStop(0, `rgba(${cr},${cg},${cb},1)`);
  g.addColorStop(h, `rgba(${cr},${cg},${cb},1)`);
  g.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
  x.fillStyle = g;
  x.fillRect(0, 0, dd, dd);
  if (sprites.size > 80) sprites.clear();
  sprites.set(k, s);
  return s;
}

/**
 * یک ضربهٔ نقاشی. شفافیت برای کلِ ضربه یکی است (هم‌پوشانیِ نقطه‌ها شفافیت را زیاد نمی‌کند): نقطه‌ها روی یک بومِ موقت با آلفای کامل کشیده
 * می‌شوند و بعد (پیش‌نمایشِ زنده) روی «نسخهٔ پیش از ضربه» با globalAlpha گذاشته می‌شوند؛ فقط مستطیلِ تغییرکرده تازه می‌شود.
 */
export class StrokeSession {
  private before: HTMLCanvasElement;
  private layer: HTMLCanvasElement;
  private shape: HTMLCanvasElement | null = null;
  private tmp: HTMLCanvasElement | null = null;
  private W: number;
  private H: number;
  changed = false;

  constructor(
    readonly target: HTMLCanvasElement,
    readonly mode: StrokeMode,
    readonly o: BrushOpts,
    readonly source: HTMLCanvasElement | null = null,
    /** بومِ آلفا (هم‌اندازهٔ بوم یا هم‌نسبت): نقاشی فقط داخلِ ناحیهٔ سفید/غیرشفاف اثر می‌کند (انتخاب) */
    readonly clip: HTMLCanvasElement | null = null,
  ) {
    this.W = target.width;
    this.H = target.height;
    this.before = newCanvas(this.W, this.H);
    this.before.getContext("2d")!.drawImage(target, 0, 0);
    this.layer = newCanvas(this.W, this.H);
    if (mode === "history") this.shape = newCanvas(this.W, this.H);
    if (clip) this.tmp = newCanvas(this.W, this.H);
  }

  /** شعاعِ قلم به پیکسلِ بوم */
  get radius(): number {
    return Math.max(this.mode === "pencil" ? 0.5 : 0.75, this.o.size * this.W);
  }

  private dab(x: number, y: number) {
    const R = this.radius;
    const d = R * 2;
    const draw = this.mode === "history" ? this.shape!.getContext("2d")! : this.layer.getContext("2d")!;
    const color = this.mode === "erase" || this.mode === "history" ? "#ffffff" : this.o.color;
    if (this.mode === "pencil") {
      const s = Math.max(1, Math.round(d));
      draw.imageSmoothingEnabled = false;
      draw.fillStyle = color;
      draw.fillRect(Math.round(x - s / 2), Math.round(y - s / 2), s, s);
      return;
    }
    if (this.o.kind === "spray") {
      const n = Math.max(3, Math.round((d * d) / 70));
      const dotR = Math.max(0.6, R * 0.05);
      const sp = sprite(dotR * 2, 0.4, color);
      for (let i = 0; i < n; i++) {
        const a = Math.random() * Math.PI * 2;
        const rr = R * Math.sqrt(Math.random());
        draw.globalAlpha = 0.35 + Math.random() * 0.5;
        draw.drawImage(sp, x + Math.cos(a) * rr - dotR, y + Math.sin(a) * rr - dotR);
      }
      draw.globalAlpha = 1;
      return;
    }
    const hard = this.o.kind === "hard" ? 1 : this.o.hardness;
    draw.drawImage(sprite(d, hard, color), x - R, y - R);
  }

  /** پاره‌خطی از a تا b (پیکسلِ بوم)؛ فقط مستطیلِ تغییرکرده در بومِ هدف تازه می‌شود */
  line(ax: number, ay: number, bx: number, by: number): void {
    const R = this.radius;
    const step = Math.max(this.mode === "pencil" ? 1 : 0.75, (this.o.kind === "hard" || this.mode === "pencil" ? 0.1 : 0.14) * R * 2);
    const dist = Math.hypot(bx - ax, by - ay);
    const n = Math.max(1, Math.ceil(dist / step));
    for (let k = 1; k <= n; k++) this.dab(ax + ((bx - ax) * k) / n, ay + ((by - ay) * k) / n);
    const pad = Math.ceil(R + 3);
    this.flush(Math.min(ax, bx) - pad, Math.min(ay, by) - pad, Math.max(ax, bx) + pad, Math.max(ay, by) + pad);
    this.changed = true;
  }

  private flush(x0: number, y0: number, x1: number, y1: number) {
    const x = Math.max(0, Math.floor(x0));
    const y = Math.max(0, Math.floor(y0));
    const w = Math.min(this.W, Math.ceil(x1)) - x;
    const h = Math.min(this.H, Math.ceil(y1)) - y;
    if (w <= 0 || h <= 0) return;
    let paintSrc: HTMLCanvasElement = this.layer;
    if (this.mode === "history" && this.source && this.shape) {
      // پیکسل‌های منبع فقط داخلِ شکلِ ضربه
      const lx = this.layer.getContext("2d")!;
      lx.save();
      lx.globalCompositeOperation = "source-over";
      lx.clearRect(x, y, w, h);
      const sw = this.source.width / this.W;
      const sh = this.source.height / this.H;
      lx.drawImage(this.source, x * sw, y * sh, w * sw, h * sh, x, y, w, h);
      lx.globalCompositeOperation = "destination-in";
      lx.drawImage(this.shape, x, y, w, h, x, y, w, h);
      lx.restore();
      paintSrc = this.layer;
    }
    if (this.clip && this.tmp) {
      const tx = this.tmp.getContext("2d")!;
      tx.save();
      tx.globalCompositeOperation = "source-over";
      tx.clearRect(x, y, w, h);
      tx.drawImage(paintSrc, x, y, w, h, x, y, w, h);
      tx.globalCompositeOperation = "destination-in";
      const cw = this.clip.width / this.W;
      const chh = this.clip.height / this.H;
      tx.drawImage(this.clip, x * cw, y * chh, w * cw, h * chh, x, y, w, h);
      tx.restore();
      paintSrc = this.tmp;
    }
    const t = this.target.getContext("2d", { willReadFrequently: true })!;
    t.save();
    t.beginPath();
    t.rect(x, y, w, h);
    t.clip();
    t.clearRect(x, y, w, h);
    t.drawImage(this.before, x, y, w, h, x, y, w, h);
    t.globalAlpha = Math.max(0.01, Math.min(1, this.o.opacity));
    t.globalCompositeOperation = this.mode === "erase" ? "destination-out" : "source-over";
    t.drawImage(paintSrc, x, y, w, h, x, y, w, h);
    t.restore();
  }
}

// ───────────────────────────── سطلِ رنگ

/**
 * پر کردنِ ناحیه: پیکسل‌هایی که با پیکسلِ نقطهٔ کلیک (در کانال‌های R,G,B,A) حداکثر `tol` درصد فرق دارند؛ contiguous ⇒ فقط ناحیهٔ پیوسته.
 * ⇒ آرایهٔ ۰/۱ هم‌اندازهٔ تصویر + تعدادِ پیکسل‌های انتخاب‌شده.
 */
export function floodMask(ref: { data: Uint8ClampedArray; width: number; height: number }, sx: number, sy: number, tol: number, contiguous: boolean): { mask: Uint8Array; count: number } {
  const { data: d, width: w, height: h } = ref;
  const x0 = Math.min(w - 1, Math.max(0, Math.round(sx)));
  const y0 = Math.min(h - 1, Math.max(0, Math.round(sy)));
  const si = (y0 * w + x0) * 4;
  const sr = d[si], sg = d[si + 1], sb = d[si + 2], sa = d[si + 3];
  const lim = (Math.max(0, Math.min(100, tol)) * 255) / 100;
  const match = (i: number) => Math.abs(d[i] - sr) <= lim && Math.abs(d[i + 1] - sg) <= lim && Math.abs(d[i + 2] - sb) <= lim && Math.abs(d[i + 3] - sa) <= lim;
  const mask = new Uint8Array(w * h);
  let count = 0;
  if (!contiguous) {
    for (let p = 0, i = 0; p < mask.length; p++, i += 4) if (match(i)) { mask[p] = 1; count++; }
    return { mask, count };
  }
  const stack = new Int32Array(w * h + 1);
  let sp = 0;
  const push = (x: number, y: number) => {
    const p = y * w + x;
    if (!mask[p] && match(p * 4)) {
      mask[p] = 1;
      count++;
      stack[sp++] = p;
    }
  };
  push(x0, y0);
  while (sp) {
    const p = stack[--sp];
    const x = p % w;
    const y = (p - x) / w;
    if (x > 0) push(x - 1, y);
    if (x < w - 1) push(x + 1, y);
    if (y > 0) push(x, y - 1);
    if (y < h - 1) push(x, y + 1);
  }
  return { mask, count };
}

/** ماسکِ ۰/۱ را با `grow` پیکسل (به‌خاطرِ لبهٔ دندانه‌دار) پهن می‌کند */
export function growMask(mask: Uint8Array, w: number, h: number, grow: number): Uint8Array {
  let cur = mask;
  for (let it = 0; it < grow; it++) {
    const nxt = new Uint8Array(cur);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const p = y * w + x;
        if (cur[p]) continue;
        if ((x > 0 && cur[p - 1]) || (x < w - 1 && cur[p + 1]) || (y > 0 && cur[p - w]) || (y < h - 1 && cur[p + w])) nxt[p] = 1;
      }
    }
    cur = nxt;
  }
  return cur;
}

/** ناحیهٔ ماسک را با رنگ در بومِ هدف می‌ریزد (شفافیتِ opacity) */
export function fillMask(target: HTMLCanvasElement, mask: Uint8Array, color: string, opacity: number, grow = 1): void {
  const w = target.width;
  const h = target.height;
  const m = grow > 0 ? growMask(mask, w, h, grow) : mask;
  const t = newCanvas(w, h);
  const tx = t.getContext("2d", { willReadFrequently: true })!;
  const id = tx.createImageData(w, h);
  const [r, g, b] = hexRgb(color);
  for (let p = 0, i = 0; p < m.length; p++, i += 4) {
    if (m[p]) {
      id.data[i] = r;
      id.data[i + 1] = g;
      id.data[i + 2] = b;
      id.data[i + 3] = 255;
    }
  }
  tx.putImageData(id, 0, 0);
  const x = target.getContext("2d", { willReadFrequently: true })!;
  x.save();
  x.globalAlpha = Math.max(0.01, Math.min(1, opacity));
  x.drawImage(t, 0, 0);
  x.restore();
}

/** کلِ بوم با یک رنگ (پرکردنِ لایه) */
export function fillAll(target: HTMLCanvasElement, color: string, opacity = 1): void {
  const x = target.getContext("2d", { willReadFrequently: true })!;
  x.save();
  x.globalAlpha = Math.max(0.01, Math.min(1, opacity));
  x.fillStyle = normColor(color);
  x.fillRect(0, 0, target.width, target.height);
  x.restore();
}

/** رنگِ میانگینِ یک ناحیهٔ کوچک (قطره‌چکان) ⇒ #rrggbb */
export function sampleHex(data: Uint8ClampedArray, w: number, h: number, nx: number, ny: number, radius = 1): string {
  const cx = Math.min(w - 1, Math.max(0, Math.round(nx * (w - 1))));
  const cy = Math.min(h - 1, Math.max(0, Math.round(ny * (h - 1))));
  let r = 0, g = 0, b = 0, n = 0;
  for (let y = Math.max(0, cy - radius); y <= Math.min(h - 1, cy + radius); y++) {
    for (let x = Math.max(0, cx - radius); x <= Math.min(w - 1, cx + radius); x++) {
      const i = (y * w + x) * 4;
      r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
    }
  }
  return n ? rgbHex(r / n, g / n, b / n) : "#000000";
}

/** بومِ خاکستریِ انتخاب (سفید = انتخاب‌شده) ⇒ بومِ آلفا (برای clip) هم‌اندازهٔ w×h */
export function selectionAlpha(sel: HTMLCanvasElement, w: number, h: number): HTMLCanvasElement {
  const g = newCanvas(w, h);
  const gx = g.getContext("2d", { willReadFrequently: true })!;
  gx.drawImage(sel, 0, 0, w, h);
  const d = gx.getImageData(0, 0, w, h);
  for (let i = 0; i < d.data.length; i += 4) {
    const v = d.data[i];
    d.data[i] = d.data[i + 1] = d.data[i + 2] = 255;
    d.data[i + 3] = v;
  }
  gx.putImageData(d, 0, 0);
  return g;
}

/** انتخاب ⇒ ماسکِ ۰/۱ (برای سطلِ رنگ و پرکردن) */
export function selectionMask(sel: HTMLCanvasElement, w: number, h: number): Uint8Array {
  const g = newCanvas(w, h);
  const gx = g.getContext("2d", { willReadFrequently: true })!;
  gx.drawImage(sel, 0, 0, w, h);
  const d = gx.getImageData(0, 0, w, h).data;
  const m = new Uint8Array(w * h);
  for (let p = 0, i = 0; p < m.length; p++, i += 4) m[p] = d[i] > 127 ? 1 : 0;
  return m;
}
