import { MediaClip, propAt } from "./model";

/**
 * هندسهٔ جایگذاریِ یک قطعه روی قاب — همان ترتیبی که Compositor.drawClip و سرور (compose.py) می‌کشند:
 * جعبه (x,y,width,height) ← جا دادنِ منبع در جعبه (fit) ← وارونگی ← اندازه ← چرخش دورِ مرکزِ جعبه ← جابه‌جایی (px,py).
 * برای ردیابی (نقطهٔ منبع ⇄ نقطهٔ قاب) و ویرایشِ ماسکِ آزاد روی تصویر (نقطهٔ جعبه ⇄ نقطهٔ قاب).
 * همهٔ مختصاتِ ورودی/خروجی «کسری از قاب» یا «کسری از جعبه/منبع» است، نه پیکسل.
 */
export type Placement = {
  /** مرکزِ جعبه روی قاب (کسری از قاب) */
  cx: number;
  cy: number;
  /** اندازهٔ جعبه (کسری از قاب) */
  bw: number;
  bh: number;
  scale: number;
  rot: number;
  flipH: boolean;
  flipV: boolean;
};

export function placement(c: MediaClip, t: number): Placement {
  return {
    cx: c.x + c.width / 2 + propAt(c, "px", t),
    cy: c.y + c.height / 2 + propAt(c, "py", t),
    bw: c.width,
    bh: c.height,
    scale: propAt(c, "scale", t),
    rot: propAt(c, "rot", t),
    flipH: !!c.flip_h,
    flipV: !!c.flip_v,
  };
}

const rad = (d: number) => (d * Math.PI) / 180;

/** نقطهٔ (u,v) از جعبه (۰..۱) ⇒ نقطه روی قاب (کسری). `frameAspect` = عرض/ارتفاعِ قاب (چرخش باید در پیکسل انجام شود) */
export function boxToFrame(pl: Placement, u: number, v: number, frameAspect: number): [number, number] {
  let rx = (u - 0.5) * pl.bw * (pl.flipH ? -1 : 1) * pl.scale;
  let ry = (v - 0.5) * pl.bh * (pl.flipV ? -1 : 1) * pl.scale;
  if (pl.rot) {
    const px = rx * frameAspect; // به «واحدِ ارتفاع»
    const a = rad(pl.rot);
    const x2 = px * Math.cos(a) - ry * Math.sin(a);
    const y2 = px * Math.sin(a) + ry * Math.cos(a);
    rx = x2 / frameAspect;
    ry = y2;
  }
  return [pl.cx + rx, pl.cy + ry];
}

/** وارونِ boxToFrame: نقطهٔ قاب ⇒ (u,v) در جعبه */
export function frameToBox(pl: Placement, X: number, Y: number, frameAspect: number): [number, number] {
  let rx = X - pl.cx;
  let ry = Y - pl.cy;
  if (pl.rot) {
    const px = rx * frameAspect;
    const a = -rad(pl.rot);
    const x2 = px * Math.cos(a) - ry * Math.sin(a);
    const y2 = px * Math.sin(a) + ry * Math.cos(a);
    rx = x2 / frameAspect;
    ry = y2;
  }
  const sx = pl.bw * pl.scale * (pl.flipH ? -1 : 1);
  const sy = pl.bh * pl.scale * (pl.flipV ? -1 : 1);
  return [rx / (Math.abs(sx) < 1e-9 ? 1e-9 : sx) + 0.5, ry / (Math.abs(sy) < 1e-9 ? 1e-9 : sy) + 0.5];
}

/** نقطه از «منبع» (کسری از قابِ ویدیوی اصلی) ⇒ (u,v) در جعبه، با fit ِ قطعه. `srcAspect` = عرض/ارتفاعِ منبع، `boxAspect` = عرض/ارتفاعِ جعبه (پیکسل) */
export function sourceToBox(fit: MediaClip["fit"], srcAspect: number, boxAspect: number, su: number, sv: number): [number, number] {
  if (fit === "stretch") return [su, sv];
  // اندازهٔ نمایشیِ منبع نسبت به جعبه
  const rel = srcAspect / boxAspect; // >1: منبع پهن‌تر از جعبه
  let kx: number;
  let ky: number;
  if (fit === "cover") {
    if (rel > 1) { ky = 1; kx = rel; } else { kx = 1; ky = 1 / rel; }
  } else if (rel > 1) { kx = 1; ky = 1 / rel; } else { ky = 1; kx = rel; }
  return [0.5 + (su - 0.5) * kx, 0.5 + (sv - 0.5) * ky];
}

export function boxToSource(fit: MediaClip["fit"], srcAspect: number, boxAspect: number, u: number, v: number): [number, number] {
  if (fit === "stretch") return [u, v];
  const rel = srcAspect / boxAspect;
  let kx: number;
  let ky: number;
  if (fit === "cover") {
    if (rel > 1) { ky = 1; kx = rel; } else { kx = 1; ky = 1 / rel; }
  } else if (rel > 1) { kx = 1; ky = 1 / rel; } else { ky = 1; kx = rel; }
  return [0.5 + (u - 0.5) / kx, 0.5 + (v - 0.5) / ky];
}

/** نقطهٔ منبع ⇒ قاب */
export function sourceToFrame(c: MediaClip, t: number, su: number, sv: number, frameAspect: number, srcAspect: number): [number, number] {
  const pl = placement(c, t);
  const [u, v] = sourceToBox(c.fit, srcAspect, (c.width * frameAspect) / Math.max(1e-9, c.height), su, sv);
  return boxToFrame(pl, u, v, frameAspect);
}

/** نقطهٔ قاب ⇒ منبع (برای انتخابِ ناحیهٔ ردیابی روی تصویر) */
export function frameToSource(c: MediaClip, t: number, X: number, Y: number, frameAspect: number, srcAspect: number): [number, number] {
  const pl = placement(c, t);
  const [u, v] = frameToBox(pl, X, Y, frameAspect);
  return boxToSource(c.fit, srcAspect, (c.width * frameAspect) / Math.max(1e-9, c.height), u, v);
}
