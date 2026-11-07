import type { MaskEntry } from "./gl/engine";
import { newCanvas } from "./gl/raster";

export type ToolId =
  | "move" | "hand" | "crop" | "straighten" | "persp" | "text" | "brush" | "gradient" | "clone" | "heal" | "spot"
  | "marquee" | "ellipse" | "lasso" | "subject" | "wb" | "redeye" | "pen" | "liquify" | "genfill";

export type ToolOpts = {
  /** شعاعِ قلم، کسری از پهنای بوم */
  size: number;
  hardness: number;
  flow: number;
  /** پاک‌کردن (ماسک را سیاه می‌کند) */
  erase: boolean;
  gradKind: "linear" | "radial";
  feather: number;
  spotR: number;
  heal: boolean;
  grid: "off" | "thirds" | "golden" | "diag";
  /** قرمزیِ چشم: شعاعِ پیش‌فرض (کسری از پهنای بوم؛ اگر برآوردِ خودکار نشد)، شدت و تیره‌کردن */
  eyeR: number;
  eyeAmount: number;
  eyeDarken: number;
  /** مایع‌سازی: قلم، شعاع (کسری از پهنای عکس)، فشار، آهنگِ ثابت‌ماندن */
  liq: "push" | "bloat" | "pucker" | "reconstruct";
  liqSize: number;
  liqStrength: number;
  liqRate: number;
};

export const defaultToolOpts = (): ToolOpts => ({
  size: 0.04, hardness: 0.5, flow: 1, erase: false, gradKind: "linear", feather: 0, spotR: 0.02, heal: false, grid: "off",
  eyeR: 0.012, eyeAmount: 1, eyeDarken: 0.6, liq: "push", liqSize: 0.08, liqStrength: 0.7, liqRate: 0.5,
});

export type ZoomCmd = { id: number; kind: "fit" | "100" | "in" | "out" } | null;

/** بومِ ماسک‌های نقاشی‌شده (خاکستری در RGB)، نسخه‌ها برای برگشت */
export class MaskStore {
  map = new Map<string, MaskEntry>();
  revs = new Map<string, number>();
  dirty = new Set<string>();
  private snaps = new Map<string, Uint8Array>();
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

  create(id: string, white: boolean): HTMLCanvasElement {
    const c = newCanvas(this.w, this.h);
    const x = c.getContext("2d", { willReadFrequently: true })!;
    x.fillStyle = white ? "#fff" : "#000";
    x.fillRect(0, 0, c.width, c.height);
    this.map.set(id, { canvas: c, ver: 1 });
    this.revs.set(id, 0);
    this.dirty.add(id);
    this.snapshot(id, 0);
    return c;
  }

  touch(id: string) {
    const e = this.map.get(id);
    if (e) {
      e.ver++;
      this.dirty.add(id);
    }
  }

  private key(id: string, rev: number) {
    return `${id}@${rev}`;
  }

  snapshot(id: string, rev: number) {
    const e = this.map.get(id);
    if (!e) return;
    const d = e.canvas.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, e.canvas.width, e.canvas.height).data;
    const g = new Uint8Array(d.length / 4);
    for (let i = 0, p = 0; p < g.length; i += 4, p++) g[p] = d[i];
    this.snaps.set(this.key(id, rev), g);
    this.revs.set(id, rev);
    // فقط ۳۰ نسخهٔ آخر برای هر ماسک
    const mine = [...this.snaps.keys()].filter((k) => k.startsWith(id + "@"));
    if (mine.length > 30) {
      mine.sort((a, b) => Number(a.split("@")[1]) - Number(b.split("@")[1]));
      this.snaps.delete(mine[0]);
    }
  }

  /** حالتِ ماسک را به نسخهٔ rev برمی‌گرداند (اگر نسخه‌اش مانده باشد) */
  restore(id: string, rev: number): boolean {
    const e = this.map.get(id);
    const g = this.snaps.get(this.key(id, rev));
    if (!e || !g) return false;
    const x = e.canvas.getContext("2d", { willReadFrequently: true })!;
    const img = x.createImageData(e.canvas.width, e.canvas.height);
    for (let p = 0, i = 0; p < g.length; p++, i += 4) {
      img.data[i] = g[p];
      img.data[i + 1] = g[p];
      img.data[i + 2] = g[p];
      img.data[i + 3] = 255;
    }
    x.putImageData(img, 0, 0);
    this.revs.set(id, rev);
    this.touch(id);
    return true;
  }

  loadUrl(id: string, url: string): Promise<boolean> {
    return new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => {
        const c = newCanvas(img.naturalWidth || this.w, img.naturalHeight || this.h);
        const x = c.getContext("2d", { willReadFrequently: true })!;
        x.fillStyle = "#000";
        x.fillRect(0, 0, c.width, c.height);
        x.drawImage(img, 0, 0, c.width, c.height);
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
  }
}

/** انتخاب (selection): بومِ خاکستری هم‌اندازهٔ بوم؛ ۲۵۵ = انتخاب‌شده */
export class Selection {
  canvas: HTMLCanvasElement | null = null;
  ver = 0;
  w = 1;
  h = 1;

  setSize(w: number, h: number) {
    this.w = w;
    this.h = h;
  }

  get active() {
    return !!this.canvas;
  }

  private ctx() {
    if (!this.canvas) {
      this.canvas = newCanvas(this.w, this.h);
      const x = this.canvas.getContext("2d", { willReadFrequently: true })!;
      x.fillStyle = "#000";
      x.fillRect(0, 0, this.w, this.h);
    }
    return this.canvas.getContext("2d", { willReadFrequently: true })!;
  }

  clear() {
    this.canvas = null;
    this.ver++;
  }

  /** جایگزینیِ کاملِ انتخاب با یک بومِ هم‌اندازهٔ سیاه/سفید (گسترش، انقباض، بازهٔ رنگ…) */
  setCanvas(c: HTMLCanvasElement) {
    this.canvas = c;
    this.ver++;
  }

  /** رونوشتِ مستقل از بومِ انتخاب (برای «انتخابِ دوباره» و «ذخیرهٔ انتخاب») یا null */
  snapshot(): HTMLCanvasElement | null {
    if (!this.canvas) return null;
    const c = newCanvas(this.w, this.h);
    c.getContext("2d", { willReadFrequently: true })!.drawImage(this.canvas, 0, 0);
    return c;
  }

  /** shape: تابعی که مسیر را روی ctx بسازد. mode: new / add / sub */
  paint(shape: (c: CanvasRenderingContext2D) => void, mode: "new" | "add" | "sub") {
    if (mode === "new") this.canvas = null;
    const c = this.ctx();
    c.save();
    c.fillStyle = mode === "sub" ? "#000" : "#fff";
    c.beginPath();
    shape(c);
    c.fill();
    c.restore();
    this.ver++;
  }

  invert() {
    const c = this.ctx();
    c.save();
    c.globalCompositeOperation = "difference";
    c.fillStyle = "#fff";
    c.fillRect(0, 0, this.w, this.h);
    c.restore();
    this.ver++;
  }

  feather(px: number) {
    if (!this.canvas || px < 0.5) return;
    const t = newCanvas(this.w, this.h);
    const x = t.getContext("2d")!;
    x.filter = `blur(${px}px)`;
    x.drawImage(this.canvas, 0, 0);
    const c = this.ctx();
    c.clearRect(0, 0, this.w, this.h);
    c.fillStyle = "#000";
    c.fillRect(0, 0, this.w, this.h);
    c.drawImage(t, 0, 0);
    this.ver++;
  }

  /** از یک ماسکِ خاکستری (مثلاً سوژه) */
  fromImage(img: CanvasImageSource, mode: "new" | "add" | "sub" = "new") {
    if (mode === "new") this.canvas = null;
    const c = this.ctx();
    c.save();
    if (mode === "sub") {
      const t = newCanvas(this.w, this.h);
      const x = t.getContext("2d")!;
      x.drawImage(img, 0, 0, this.w, this.h);
      c.globalCompositeOperation = "difference";
      c.drawImage(t, 0, 0);
    } else {
      c.globalCompositeOperation = mode === "add" ? "lighten" : "source-over";
      c.drawImage(img, 0, 0, this.w, this.h);
    }
    c.restore();
    this.ver++;
  }

  /** به یک بومِ ماسکِ تازه */
  toMask(id: string, store: MaskStore) {
    if (!this.canvas) return false;
    const c = newCanvas(store.w, store.h);
    c.getContext("2d", { willReadFrequently: true })!.drawImage(this.canvas, 0, 0, store.w, store.h);
    store.map.set(id, { canvas: c, ver: 1 });
    store.revs.set(id, 0);
    store.dirty.add(id);
    store.snapshot(id, 0);
    return true;
  }
}
