import { Rect, innerRect } from "../manual/model";
import type { Pt2, Quad } from "./types";

/** ماتریس ۳×۳ (سطری) و هندسهٔ نما: پرسپکتیو ⇐ چرخش/صاف کردن/قرینه ⇐ برش ⇐ زوم و جابه‌جایی */
export type M3 = number[];

export const I3: M3 = [1, 0, 0, 0, 1, 0, 0, 0, 1];

export function mul(a: M3, b: M3): M3 {
  const r = new Array<number>(9).fill(0);
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) r[i * 3 + j] += a[i * 3 + k] * b[k * 3 + j];
  return r;
}

export function inv(m: M3): M3 {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  const k = Math.abs(det) < 1e-12 ? 0 : 1 / det;
  return [A * k, -(b * i - c * h) * k, (b * f - c * e) * k, B * k, (a * i - c * g) * k, -(a * f - c * d) * k, C * k, -(a * h - b * g) * k, (a * e - b * d) * k];
}

export function apply(m: M3, x: number, y: number): [number, number] {
  const w = m[6] * x + m[7] * y + m[8];
  return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w];
}

export const tr = (x: number, y: number): M3 => [1, 0, x, 0, 1, y, 0, 0, 1];
export const sc = (x: number, y: number): M3 => [x, 0, 0, 0, y, 0, 0, 0, 1];
const rot = (deg: number): M3 => {
  const a = (deg * Math.PI) / 180;
  const c = Math.cos(a);
  const s = Math.sin(a);
  return [c, -s, 0, s, c, 0, 0, 0, 1];
};

/** مربعِ واحد ⇐ چهارضلعی (Heckbert) */
function unitToQuad(p: [Pt2, Pt2, Pt2, Pt2]): M3 {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = p;
  const dx1 = x1 - x2;
  const dx2 = x3 - x2;
  const dy1 = y1 - y2;
  const dy2 = y3 - y2;
  const sx = x0 - x1 + x2 - x3;
  const sy = y0 - y1 + y2 - y3;
  let g = 0;
  let h = 0;
  if (Math.abs(sx) > 1e-12 || Math.abs(sy) > 1e-12) {
    const det = dx1 * dy2 - dx2 * dy1;
    g = (sx * dy2 - dx2 * sy) / det;
    h = (dx1 * sy - sx * dy1) / det;
  }
  return [x1 - x0 + g * x1, x3 - x0 + h * x3, x0, y1 - y0 + g * y1, y3 - y0 + h * y3, y0, g, h, 1];
}

export const IDENTITY_QUAD: Quad = { tl: [0, 0], tr: [1, 0], br: [1, 1], bl: [0, 1] };

export function quadOutSize(q: Quad, Wo: number, Ho: number): [number, number] {
  const d = (a: Pt2, b: Pt2) => Math.hypot((a[0] - b[0]) * Wo, (a[1] - b[1]) * Ho);
  let w = (d(q.tl, q.tr) + d(q.bl, q.br)) / 2;
  let h = (d(q.tl, q.bl) + d(q.tr, q.br)) / 2;
  const k = Math.min(1, 8000 / Math.max(w, h, 1));
  w *= k;
  h *= k;
  return [Math.max(8, w), Math.max(8, h)];
}

export type GeoState = {
  turn: number;
  straighten: number;
  flipH: boolean;
  flipV: boolean;
  persp: Quad | null;
  crop: Rect;
};

export type ViewState = { s: number | null; x: number; y: number };

/** هندسهٔ بی‌اثر — برای نمای «بوم» (frame-first) که فقط زوم و جابه‌جایی دارد: `new Geo(Wf, Hf, GEO_IDENTITY, true, …)` */
export const GEO_IDENTITY: GeoState = {
  turn: 0, straighten: 0, flipH: false, flipV: false, persp: null, crop: { x: 0, y: 0, w: 1, h: 1 },
};

/** اندازهٔ عکس پس از پرسپکتیو، چرخش و صاف کردن (پیش از برش) — همان ریاضیِ سازندهٔ Geo، بی‌نیاز به نمونه */
export function photoGeoSizes(Wo: number, Ho: number, g: Pick<GeoState, "turn" | "straighten" | "persp">): { Wt: number; Ht: number } {
  const [pw, ph] = g.persp ? quadOutSize(g.persp, Wo, Ho) : [Wo, Ho];
  const turned = g.turn === 90 || g.turn === 270;
  const [Wt, Ht] = innerRect(turned ? ph : pw, turned ? pw : ph, g.straighten);
  return { Wt, Ht };
}

/** همهٔ نگاشت‌های بین صفحه و سند */
export class Geo {
  Wo: number;
  Ho: number;
  pw: number;
  ph: number;
  Wt: number;
  Ht: number;
  frame: { x0: number; y0: number; w: number; h: number };
  fitS: number;
  s: number;
  /** صفحه (پیکسل) ⇐ سند (پیکسلِ اصل) */
  M: M3;
  private toScr: M3;
  private tScr: M3;

  constructor(Wo: number, Ho: number, g: GeoState, showFull: boolean, box: { w: number; h: number }, view: ViewState) {
    this.Wo = Wo;
    this.Ho = Ho;
    const q = g.persp;
    [this.pw, this.ph] = q ? quadOutSize(q, Wo, Ho) : [Wo, Ho];
    const turned = g.turn === 90 || g.turn === 270;
    [this.Wt, this.Ht] = innerRect(turned ? this.ph : this.pw, turned ? this.pw : this.ph, g.straighten);
    const c = showFull ? { x: 0, y: 0, w: 1, h: 1 } : g.crop;
    this.frame = { x0: c.x * this.Wt, y0: c.y * this.Ht, w: Math.max(1, c.w * this.Wt), h: Math.max(1, c.h * this.Ht) };
    this.fitS = Math.max(0.01, Math.min((box.w * 0.94) / this.frame.w, (box.h * 0.94) / this.frame.h));
    this.s = view.s ?? this.fitS;
    const fcx = this.frame.x0 + this.frame.w / 2;
    const fcy = this.frame.y0 + this.frame.h / 2;
    // T (پیکسلِ قابِ تبدیل‌شده) ⇐ صفحه:  p_screen = center + s·(T − fc)
    const A_toScreen = mul(tr(box.w / 2 + view.x, box.h / 2 + view.y), mul(sc(this.s, this.s), tr(-fcx, -fcy)));
    // پرسپکتیو: خروجی (pw×ph) ⇐ سند
    const Hq = q ? mul(unitToQuad([q.tl, q.tr, q.br, q.bl].map((p) => [p[0] * Wo, p[1] * Ho] as Pt2) as [Pt2, Pt2, Pt2, Pt2]), sc(1 / this.pw, 1 / this.ph)) : I3;
    // تصویرِ خروجیِ پرسپکتیو ⇒ T
    const F = mul(tr(this.Wt / 2, this.Ht / 2), mul(sc(g.flipH ? -1 : 1, g.flipV ? -1 : 1), mul(rot(-g.straighten), mul(rot(-g.turn), tr(-this.pw / 2, -this.ph / 2)))));
    this.tScr = A_toScreen;
    this.toScr = mul(A_toScreen, mul(F, inv(Hq)));
    this.M = inv(this.toScr);
  }

  /** سند (۰..۱) ⇐ صفحه */
  toScreen(nx: number, ny: number): [number, number] {
    return apply(this.toScr, nx * this.Wo, ny * this.Ho);
  }

  /** صفحه ⇐ سند (۰..۱؛ ممکن است بیرون از بازه باشد) */
  toDoc(sx: number, sy: number): [number, number] {
    const [x, y] = apply(this.M, sx, sy);
    return [x / this.Wo, y / this.Ho];
  }

  /** قاب (دیده‌شده) روی صفحه */
  frameScreen(): { x0: number; y0: number; x1: number; y1: number } {
    const [x0, y0] = this.tToScreen(this.frame.x0, this.frame.y0);
    const [x1, y1] = this.tToScreen(this.frame.x0 + this.frame.w, this.frame.y0 + this.frame.h);
    return { x0, y0, x1, y1 };
  }

  /** فضای قابِ تبدیل‌شده (T) ⇐ صفحه و برعکس */
  tToScreen(x: number, y: number): [number, number] {
    return apply(this.tScr, x, y);
  }

  screenToT(sx: number, sy: number): [number, number] {
    return apply(inv(this.tScr), sx, sy);
  }
}
