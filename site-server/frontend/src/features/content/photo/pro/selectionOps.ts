/**
 * عملیاتِ روی «انتخاب» (نوبت ۴): گسترش، انقباض، هموارسازی، حاشیه، بازهٔ رنگ/عصای جادویی. همه روی بومِ خاکستریِ Selection کار می‌کنند
 * (سفید = انتخاب‌شده) و بی‌وابستگیِ DOM جز <canvas>؛ پس هم‌اندازهٔ بومِ نهایی‌اند و مستقیم به ماسک/فیلتر می‌روند.
 */
import type { Selection } from "./session";

const mk = (w: number, h: number): HTMLCanvasElement => {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
};

/** ⇒ بومِ سیاه/سفیدِ «محو و آستانه». سطحِ آستانه ۰..۲۵۵ */
function blurThreshold(src: HTMLCanvasElement, sigma: number, level: number): HTMLCanvasElement {
  const t = mk(src.width, src.height);
  const x = t.getContext("2d", { willReadFrequently: true })!;
  x.fillStyle = "#000";
  x.fillRect(0, 0, t.width, t.height);
  x.filter = `blur(${Math.max(0.5, sigma)}px)`;
  x.drawImage(src, 0, 0);
  x.filter = "none";
  const d = x.getImageData(0, 0, t.width, t.height);
  const p = d.data;
  for (let i = 0; i < p.length; i += 4) {
    const v = p[i] > level ? 255 : 0;
    p[i] = p[i + 1] = p[i + 2] = v;
    p[i + 3] = 255;
  }
  x.putImageData(d, 0, 0);
  return t;
}

// با σ = r/2 مرزِ انتخاب بعد از محو ۱۲۸ است و r پیکسل آن‌طرف‌تر ≈ ۶ (۲σ) ⇒ آستانهٔ ۶ = گسترش r، آستانهٔ ۲۴۹ = انقباض r
export const grow = (sel: Selection, r: number): void => {
  if (sel.canvas) sel.setCanvas(blurThreshold(sel.canvas, r / 2, 6));
};
export const shrink = (sel: Selection, r: number): void => {
  if (sel.canvas) sel.setCanvas(blurThreshold(sel.canvas, r / 2, 249));
};
export const smooth = (sel: Selection, r: number): void => {
  if (sel.canvas) sel.setCanvas(blurThreshold(sel.canvas, r, 127));
};
/** حلقه‌ای به پهنای r پیکسل به هر طرفِ لبهٔ انتخاب */
export function border(sel: Selection, r: number): void {
  if (!sel.canvas) return;
  const outer = blurThreshold(sel.canvas, r / 2, 6);
  const inner = blurThreshold(sel.canvas, r / 2, 249);
  const x = outer.getContext("2d", { willReadFrequently: true })!;
  x.globalCompositeOperation = "difference";
  x.drawImage(inner, 0, 0);
  x.globalCompositeOperation = "source-over";
  sel.setCanvas(outer);
}

export type RangeOpts = { seed: [number, number] | null; color: [number, number, number]; tol: number; contiguous: boolean; feather: number };

/** ⇒ بومِ ماسکِ هم‌اندازهٔ src. tol: ۰..۱۰۰. contiguous: فقط ناحیهٔ پیوسته به seed (عصای جادویی) */
export function colorRangeMask(src: HTMLCanvasElement, o: RangeOpts): HTMLCanvasElement {
  const w = src.width;
  const h = src.height;
  const d = src.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, w, h).data;
  const lim = (o.tol / 100) * 441.67 * 0.6; // فاصلهٔ اقلیدسیِ RGB (حداکثر ۴۴۱٫۷)
  const lim2 = lim * lim;
  const [r0, g0, b0] = o.color;
  const hit = new Uint8Array(w * h);
  for (let i = 0, j = 0; i < hit.length; i++, j += 4) {
    const dr = d[j] - r0;
    const dg = d[j + 1] - g0;
    const db = d[j + 2] - b0;
    if (d[j + 3] > 8 && dr * dr + dg * dg + db * db <= lim2) hit[i] = 1;
  }
  let out = hit;
  if (o.contiguous && o.seed) {
    out = new Uint8Array(w * h);
    const sx = Math.min(w - 1, Math.max(0, Math.round(o.seed[0])));
    const sy = Math.min(h - 1, Math.max(0, Math.round(o.seed[1])));
    const stack = new Int32Array(w * h);
    let sp = 0;
    if (hit[sy * w + sx]) {
      stack[sp++] = sy * w + sx;
      out[sy * w + sx] = 1;
    }
    while (sp) {
      const p = stack[--sp];
      const x = p % w;
      const y = (p - x) / w;
      if (x > 0 && hit[p - 1] && !out[p - 1]) { out[p - 1] = 1; stack[sp++] = p - 1; }
      if (x < w - 1 && hit[p + 1] && !out[p + 1]) { out[p + 1] = 1; stack[sp++] = p + 1; }
      if (y > 0 && hit[p - w] && !out[p - w]) { out[p - w] = 1; stack[sp++] = p - w; }
      if (y < h - 1 && hit[p + w] && !out[p + w]) { out[p + w] = 1; stack[sp++] = p + w; }
    }
  }
  const c = mk(w, h);
  const x = c.getContext("2d", { willReadFrequently: true })!;
  const id = x.createImageData(w, h);
  for (let i = 0, j = 0; i < out.length; i++, j += 4) {
    const v = out[i] ? 255 : 0;
    id.data[j] = id.data[j + 1] = id.data[j + 2] = v;
    id.data[j + 3] = 255;
  }
  x.putImageData(id, 0, 0);
  if (o.feather >= 0.5) {
    const f = mk(w, h);
    const fx = f.getContext("2d", { willReadFrequently: true })!;
    fx.fillStyle = "#000";
    fx.fillRect(0, 0, w, h);
    fx.filter = `blur(${o.feather}px)`;
    fx.drawImage(c, 0, 0);
    return f;
  }
  return c;
}

/** درصدِ سفیدِ یک بومِ ماسک (برای پیامِ «چیزی پیدا نشد») */
export function coverage(c: HTMLCanvasElement): number {
  const d = c.getContext("2d", { willReadFrequently: true })!.getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i] > 127) n++;
  return n / (c.width * c.height);
}
