import type { PathPt, ShapeLayer, ShapePath } from "../types";

/**
 * رسمِ لایهٔ شکلِ `path` (قلم/Pen) روی بومِ دوبعدی؛ همان قراردادِ backend/apps/photoedit/layers._render_path و paths.py:
 *  - نقطه‌ها و دستگیره‌ها در واحدِ «جعبهٔ لایه» (کسری از w و h)، w و h کسری از پهنای بومِ نهایی، مرکزِ جعبه = (cx, cy) ِ لایه؛
 *  - پارهٔ i ⇒ i+1: P0 = pt_i، P1 = pt_i + ho_i، P2 = pt_{i+1} + hi_{i+1}، P3 = pt_{i+1}؛ مسیرِ بسته پارهٔ آخر ⇒ اول هم دارد؛
 *  - پر = nonzero؛ مسیرِ باز برای پر شدن ضمناً بسته است ولی خطِ دورش پارهٔ بستن ندارد؛ خطِ دور گوشه و سرِ گرد و ضخامتِ stroke.w·W
 *    و **وسطِ** مسیر (نه داخل)؛ تایل = جعبه + حاشیهٔ pad = ⌈stroke/2⌉ + ۲ از هر طرف.
 * تایل طوری رسم می‌شود که مرکزِ جعبه روی مرکزِ تایل بنشیند (موتور تایل را حولِ مرکزش می‌گذارد؛ سرور حولِ مرکزِ جعبه).
 */
const MAX_TILE = 8192;

const hexA = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
};

/** مسیر را روی ctx می‌سازد؛ مبدأ و مقیاسِ جعبه: (ox, oy)، (wpx, hpx). beginPath را خودش می‌زند */
export function tracePath(g: CanvasRenderingContext2D | Path2D, path: ShapePath, ox: number, oy: number, wpx: number, hpx: number): void {
  const pts = path.pts;
  const n = pts.length;
  if (!n) return;
  const X = (p: PathPt) => ox + p.x * wpx;
  const Y = (p: PathPt) => oy + p.y * hpx;
  if ("beginPath" in g) g.beginPath();
  g.moveTo(X(pts[0]), Y(pts[0]));
  const closed = path.closed && n > 1;
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    if (!a.ho && !b.hi) {
      if (!(closed && i === segs - 1)) g.lineTo(X(b), Y(b));
      continue;
    }
    g.bezierCurveTo(
      X(a) + (a.ho ? a.ho[0] * wpx : 0), Y(a) + (a.ho ? a.ho[1] * hpx : 0),
      X(b) + (b.hi ? b.hi[0] * wpx : 0), Y(b) + (b.hi ? b.hi[1] * hpx : 0),
      X(b), Y(b),
    );
  }
  if (closed) g.closePath();
}

export function rasterPath(layer: ShapeLayer, W: number): { canvas: HTMLCanvasElement; bw: number; bh: number } | null {
  const path = layer.path;
  if (!path || path.pts.length < 2) return null;
  const wpx = layer.w * W;
  const hpx = layer.h * W;
  const sw = layer.stroke ? layer.stroke.w * W : 0;
  const pad = Math.ceil(sw / 2) + 2;
  const tw = Math.min(MAX_TILE, Math.ceil(wpx) + 2 * pad);
  const th = Math.min(MAX_TILE, Math.ceil(hpx) + 2 * pad);
  if (tw < 2 || th < 2) return null;
  const c = document.createElement("canvas");
  c.width = tw;
  c.height = th;
  const g = c.getContext("2d")!;
  const ox = tw / 2 - wpx / 2;
  const oy = th / 2 - hpx / 2;
  const fill = layer.fill;
  if (fill) {
    tracePath(g, path, ox, oy, wpx, hpx);
    if (fill.type === "gradient") {
      const a = (fill.angle * Math.PI) / 180;
      const dx = Math.cos(a);
      const dy = Math.sin(a);
      const half = Math.max(1e-6, (Math.abs(dx) * tw + Math.abs(dy) * th) / 2);
      const cx = (tw - 1) / 2;
      const cy = (th - 1) / 2;
      const gr = g.createLinearGradient(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half);
      gr.addColorStop(0, fill.c0);
      gr.addColorStop(1, fill.c1);
      g.fillStyle = gr;
    } else {
      g.fillStyle = hexA(fill.color, fill.opacity);
    }
    g.fill("nonzero");
  }
  if (layer.stroke && sw > 0) {
    g.strokeStyle = layer.stroke.color;
    g.lineWidth = Math.max(1, sw);
    g.lineJoin = "round";
    g.lineCap = "round";
    tracePath(g, path, ox, oy, wpx, hpx);
    g.stroke();
  }
  return { canvas: c, bw: tw / W, bh: th / W };
}
