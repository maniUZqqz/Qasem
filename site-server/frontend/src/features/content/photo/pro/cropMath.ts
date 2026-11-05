import type { Rect } from "../manual/model";

const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/** مستطیلِ تازه با اندازهٔ پیکسلیِ خواسته، حولِ مرکزِ فعلی؛ با نسبتِ قفل‌شده هم‌نسبت می‌ماند و از عکس بیرون نمی‌زند */
export function resizeCrop(c: Rect, Wt: number, Ht: number, wpx: number | null, hpx: number | null, ratio: number | null): Rect {
  const cx = c.x + c.w / 2;
  const cy = c.y + c.h / 2;
  let w = wpx !== null ? wpx / Wt : c.w;
  let h = hpx !== null ? hpx / Ht : c.h;
  if (ratio && ratio > 0) {
    if (wpx !== null) h = (w * Wt) / ratio / Ht;
    else if (hpx !== null) w = (h * Ht * ratio) / Wt;
  }
  w = clamp(w, 0.02, 1);
  h = clamp(h, 0.02, 1);
  if (ratio && ratio > 0) {
    // یکی از دو سو به ۱ خورد ⇒ دیگری هم‌نسبت کوچک می‌شود
    const hFromW = (w * Wt) / ratio / Ht;
    if (hFromW > 1) {
      h = 1;
      w = (Ht * ratio) / Wt;
    } else h = hFromW;
  }
  return { x: clamp(cx - w / 2, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h };
}
