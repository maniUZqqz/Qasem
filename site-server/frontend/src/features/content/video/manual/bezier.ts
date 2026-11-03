import type { BezierPt } from "./model";

/**
 * ماسکِ آزاد (Bézier): همان flatten ِ سرور (backend/services/editing/masks.py) تا لبهٔ پیش‌نمایش با رندر یکی باشد.
 * هر نقطه یک لنگر + دو دستگیره (جابه‌جایی از لنگر)؛ همه کسری از جعبهٔ قطعه.
 */
export const STEPS = 24;
export const MIN_POINTS = 3;
export const MAX_POINTS = 64;

export function flatten(points: BezierPt[], steps = STEPS): [number, number][] {
  const out: [number, number][] = [];
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const a = points[i];
    const b = points[(i + 1) % n];
    const straight = a.ox === 0 && a.oy === 0 && b.ix === 0 && b.iy === 0;
    const count = straight ? 1 : steps;
    for (let s = 0; s < count; s++) {
      const t = s / count;
      const u = 1 - t;
      const p1x = a.x + a.ox, p1y = a.y + a.oy, p2x = b.x + b.ix, p2y = b.y + b.iy;
      out.push([
        u ** 3 * a.x + 3 * u * u * t * p1x + 3 * u * t * t * p2x + t ** 3 * b.x,
        u ** 3 * a.y + 3 * u * u * t * p1y + 3 * u * t * t * p2y + t ** 3 * b.y,
      ]);
    }
  }
  return out;
}

/** مسیرِ بسته در بومِ w×h */
export function pathOf(points: BezierPt[], w: number, h: number): Path2D {
  const path = new Path2D();
  flatten(points).forEach(([x, y], i) => {
    if (i === 0) path.moveTo(x * w, y * h); else path.lineTo(x * w, y * h);
  });
  path.closePath();
  return path;
}

/** یک بیضیِ نرم (چهار نقطه با دستگیره) — نقطهٔ شروعِ ماسکِ آزاد */
export function defaultBezier(): BezierPt[] {
  const c = 0.5523 * 0.3;
  return [
    { x: 0.5, y: 0.2, ix: -c, iy: 0, ox: c, oy: 0 },
    { x: 0.8, y: 0.5, ix: 0, iy: -c, ox: 0, oy: c },
    { x: 0.5, y: 0.8, ix: c, iy: 0, ox: -c, oy: 0 },
    { x: 0.2, y: 0.5, ix: 0, iy: c, ox: 0, oy: -c },
  ];
}

const dist2 = (ax: number, ay: number, bx: number, by: number) => (ax - bx) ** 2 + (ay - by) ** 2;

/** نزدیک‌ترین پاره‌خط (شماره‌ی نقطهٔ آغازش) به (u,v) */
export function nearestSegment(points: BezierPt[], u: number, v: number): number {
  let best = 0;
  let bd = Infinity;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const seg = flatten([points[i], points[(i + 1) % n]], 12);
    for (const [x, y] of seg) {
      const d = dist2(x, y, u, v);
      if (d < bd) { bd = d; best = i; }
    }
  }
  return best;
}

/** نقطهٔ تازه روی پاره‌خطِ i در (u,v)، با دستگیره‌های هم‌راستا با همسایه‌ها */
export function insertPoint(points: BezierPt[], u: number, v: number): BezierPt[] {
  if (points.length >= MAX_POINTS) return points;
  const i = nearestSegment(points, u, v);
  const a = points[i];
  const b = points[(i + 1) % points.length];
  const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  const tx = (b.x - a.x) / len, ty = (b.y - a.y) / len;
  const h = len * 0.18;
  const pt: BezierPt = { x: u, y: v, ix: -tx * h, iy: -ty * h, ox: tx * h, oy: ty * h };
  const next = [...points];
  next.splice(i + 1, 0, pt);
  return next;
}

export function removePoint(points: BezierPt[], i: number): BezierPt[] {
  return points.length <= MIN_POINTS ? points : points.filter((_p, k) => k !== i);
}

/** نقطه را «تیز» (بی‌دستگیره) یا «نرم» می‌کند */
export function togglePointSmooth(points: BezierPt[], i: number): BezierPt[] {
  const n = points.length;
  const p = points[i];
  const sharp = p.ix === 0 && p.iy === 0 && p.ox === 0 && p.oy === 0;
  if (!sharp) return points.map((q, k) => (k === i ? { ...q, ix: 0, iy: 0, ox: 0, oy: 0 } : q));
  const a = points[(i + n - 1) % n];
  const b = points[(i + 1) % n];
  const tx = b.x - a.x, ty = b.y - a.y;
  const len = Math.hypot(tx, ty) || 1;
  const h = 0.12;
  return points.map((q, k) => (k === i ? { ...q, ix: -(tx / len) * h, iy: -(ty / len) * h, ox: (tx / len) * h, oy: (ty / len) * h } : q));
}
