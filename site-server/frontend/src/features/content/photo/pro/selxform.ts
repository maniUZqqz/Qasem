import { newCanvas } from "./gl/raster";

/**
 * «تبدیلِ انتخاب» (دورِ ۸): خودِ ناحیهٔ انتخاب (نه پیکسل‌های عکس) را بزرگ/کوچک، بچرخان و جابه‌جا می‌کند — حولِ مرکزِ جعبهٔ انتخاب.
 * ورودی: بومِ انتخاب (سفید = انتخاب‌شده، سیاه = نه). dx و dy به پیکسل، rot درجه (ساعتگرد)، sx و sy ضریب (۱ = بی‌تغییر).
 */
export type SelXform = { sx: number; sy: number; rot: number; dx: number; dy: number };

export const IDENTITY_XFORM: SelXform = { sx: 1, sy: 1, rot: 0, dx: 0, dy: 0 };

/** جعبهٔ پیرامونِ ناحیهٔ انتخاب‌شده (روشنایی > ۱۲۸) یا null — روی نسخهٔ کوچک‌شده می‌شمارد ⇒ سریع */
export function selectionBox(src: HTMLCanvasElement): { x0: number; y0: number; x1: number; y1: number } | null {
  const k = Math.min(1, 256 / Math.max(src.width, src.height));
  const w = Math.max(1, Math.round(src.width * k));
  const h = Math.max(1, Math.round(src.height * k));
  const t = newCanvas(w, h);
  const x = t.getContext("2d", { willReadFrequently: true })!;
  x.drawImage(src, 0, 0, w, h);
  const d = x.getImageData(0, 0, w, h).data;
  let x0 = w;
  let y0 = h;
  let x1 = -1;
  let y1 = -1;
  for (let j = 0; j < h; j++) {
    for (let i = 0; i < w; i++) {
      if (d[(j * w + i) * 4] > 128) {
        x0 = Math.min(x0, i);
        x1 = Math.max(x1, i);
        y0 = Math.min(y0, j);
        y1 = Math.max(y1, j);
      }
    }
  }
  if (x1 < 0) return null;
  return { x0: x0 / k, y0: y0 / k, x1: Math.min(src.width, (x1 + 1) / k), y1: Math.min(src.height, (y1 + 1) / k) };
}

/** نتیجه یک بومِ تازهٔ هم‌اندازه است؛ ناحیه‌ای که بیرون از بوم بیفتد بریده می‌شود */
export function transformSelection(src: HTMLCanvasElement, t: SelXform): HTMLCanvasElement | null {
  const box = selectionBox(src);
  if (!box) return null;
  const cx = (box.x0 + box.x1) / 2;
  const cy = (box.y0 + box.y1) / 2;
  const out = newCanvas(src.width, src.height);
  const c = out.getContext("2d", { willReadFrequently: true })!;
  c.fillStyle = "#000";
  c.fillRect(0, 0, out.width, out.height);
  c.save();
  c.translate(cx + t.dx, cy + t.dy);
  c.rotate((t.rot * Math.PI) / 180);
  c.scale(Math.max(0.02, t.sx), Math.max(0.02, t.sy));
  c.translate(-cx, -cy);
  c.imageSmoothingQuality = "high";
  c.drawImage(src, 0, 0);
  c.restore();
  return out;
}
