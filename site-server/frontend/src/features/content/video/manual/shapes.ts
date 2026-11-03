import type { ShapeKind, ShapeSpec } from "./model";

/**
 * شکل‌ها (مستطیل، دایره، ستاره، قلب، فلش …): همان طرحِ سرور (backend/services/editing/shapes.py: unit_shapes) تا پیش‌نمایشِ فوری با
 * رندرِ نهایی یکی باشد. طرح در جعبهٔ واحدِ ۰..۱ است؛ بوم آن را به اندازهٔ جعبهٔ قطعه می‌کشد.
 */
export const SHAPES: { key: ShapeKind; title: string }[] = [
  { key: "rect", title: "مستطیل" },
  { key: "rounded", title: "مستطیلِ گرد" },
  { key: "ellipse", title: "بیضی / دایره" },
  { key: "triangle", title: "مثلث" },
  { key: "star", title: "ستاره" },
  { key: "polygon", title: "چندضلعی" },
  { key: "heart", title: "قلب" },
  { key: "arrow", title: "فلش" },
  { key: "burst", title: "انفجار (برچسب)" },
];

export const defaultShape = (shape: ShapeKind = "rect"): ShapeSpec => ({
  shape, fill: "#ff3d71", fill_opacity: 1, stroke: "#ffffff", stroke_w: 0, radius: 18, points: 5, inner: shape === "burst" ? 0.78 : 0.45,
});

export type UnitShape = { kind: "poly"; pts: [number, number][] } | { kind: "rrect"; radius: number } | { kind: "ellipse" };

export const HEART_SAMPLES = 72;

/** همان unit_shapes ِ سرور */
export function unitShapes(spec: ShapeSpec): UnitShape[] {
  const shape = spec.shape;
  const points = Math.max(3, Math.min(16, Math.round(spec.points ?? 5)));
  const inner = Math.max(0.15, Math.min(0.9, spec.inner ?? (shape === "burst" ? 0.78 : 0.45)));
  if (shape === "rect") return [{ kind: "poly", pts: [[0, 0], [1, 0], [1, 1], [0, 1]] }];
  if (shape === "rounded") return [{ kind: "rrect", radius: Math.max(0, Math.min(50, spec.radius ?? 18)) / 100 }];
  if (shape === "ellipse") return [{ kind: "ellipse" }];
  if (shape === "triangle") return [{ kind: "poly", pts: [[0.5, 0], [1, 1], [0, 1]] }];
  if (shape === "arrow") return [{ kind: "poly", pts: [[0, 0.32], [0.58, 0.32], [0.58, 0.04], [1, 0.5], [0.58, 0.96], [0.58, 0.68], [0, 0.68]] }];
  if (shape === "star" || shape === "burst" || shape === "polygon") {
    const n = shape === "burst" ? Math.max(8, points * 2) : points;
    const pts: [number, number][] = [];
    if (shape === "polygon") {
      for (let i = 0; i < n; i++) {
        const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
        pts.push([0.5 + 0.5 * Math.cos(a), 0.5 + 0.5 * Math.sin(a)]);
      }
    } else {
      for (let i = 0; i < 2 * n; i++) {
        const r = i % 2 === 0 ? 0.5 : 0.5 * inner;
        const a = -Math.PI / 2 + (Math.PI * i) / n;
        pts.push([0.5 + r * Math.cos(a), 0.5 + r * Math.sin(a)]);
      }
    }
    return [{ kind: "poly", pts }];
  }
  if (shape === "heart") {
    const raw: [number, number][] = [];
    for (let i = 0; i < HEART_SAMPLES; i++) {
      const t = (2 * Math.PI * i) / HEART_SAMPLES;
      raw.push([16 * Math.sin(t) ** 3, -(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t))]);
    }
    const xs = raw.map((p) => p[0]);
    const ys = raw.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    return [{ kind: "poly", pts: raw.map(([x, y]) => [(x - x0) / (x1 - x0), (y - y0) / (y1 - y0)] as [number, number]) }];
  }
  return [{ kind: "poly", pts: [[0, 0], [1, 0], [1, 1], [0, 1]] }];
}

const cache = new Map<string, HTMLCanvasElement>();

/** شکل را روی یک بومِ w×h می‌کشد (کش‌شده؛ با تغییرِ مشخصات یا اندازه از نو) */
export function shapeCanvas(spec: ShapeSpec, w: number, h: number): HTMLCanvasElement {
  const W = Math.max(8, Math.min(2048, Math.round(w)));
  const H = Math.max(8, Math.min(2048, Math.round(h)));
  const key = JSON.stringify([spec, W, H]);
  const hit = cache.get(key);
  if (hit) return hit;
  const cv = document.createElement("canvas");
  cv.width = W;
  cv.height = H;
  const ctx = cv.getContext("2d")!;
  const sw = ((spec.stroke_w ?? 0) / 100) * Math.min(W, H);
  const inset = sw / 2 + 0.5;
  const x0 = inset, y0 = inset, x1 = W - inset, y1 = H - inset;
  const path = new Path2D();
  for (const item of unitShapes(spec)) {
    if (item.kind === "poly") {
      item.pts.forEach(([x, y], i) => {
        const px = x0 + x * (x1 - x0), py = y0 + y * (y1 - y0);
        if (i === 0) path.moveTo(px, py); else path.lineTo(px, py);
      });
      path.closePath();
    } else if (item.kind === "rrect") {
      const r = item.radius * Math.min(x1 - x0, y1 - y0);
      path.roundRect(x0, y0, x1 - x0, y1 - y0, r);
    } else {
      path.ellipse((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, 0, 0, Math.PI * 2);
    }
  }
  ctx.globalAlpha = spec.fill_opacity ?? 1;
  if (spec.fill2) {
    const a = ((spec.angle ?? 90) * Math.PI) / 180;
    const dx = Math.cos(a), dy = Math.sin(a);
    const k = (Math.abs(dx) + Math.abs(dy)) || 1;
    const g = ctx.createLinearGradient(W / 2 - (dx * W) / (2 * k) * 1, H / 2 - (dy * H) / (2 * k), W / 2 + (dx * W) / (2 * k), H / 2 + (dy * H) / (2 * k));
    g.addColorStop(0, spec.fill);
    g.addColorStop(1, spec.fill2);
    ctx.fillStyle = g;
  } else {
    ctx.fillStyle = spec.fill;
  }
  ctx.fill(path);
  ctx.globalAlpha = 1;
  if (sw > 0.4) {
    ctx.lineWidth = sw;
    ctx.lineJoin = "round";
    ctx.strokeStyle = spec.stroke ?? "#ffffff";
    ctx.stroke(path);
  }
  if (cache.size > 80) cache.clear();
  cache.set(key, cv);
  return cv;
}
