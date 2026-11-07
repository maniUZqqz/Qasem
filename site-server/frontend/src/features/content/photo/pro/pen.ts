import { tracePath } from "./gl/pathraster";
import type { Selection } from "./session";
import type { PathPt, Pt2, ShapePath } from "./types";

/**
 * ابزارِ قلم (Pen): مسیرِ بزیه روی بومِ نهایی.
 * مختصاتِ نقطه‌ها و دستگیره‌ها «کسری از پهنا/ارتفاعِ بوم» است (همان واحدِ جعبه در backend/paths.py با جعبه = کلِ بوم)؛
 * دستگیره‌ها جابه‌جایی نسبت به نقطه‌اند (hi = ورودی، ho = خروجی؛ null = گوشه).
 * خروجی‌ها: انتخاب (Selection)، ماسک (از همان انتخاب)، لایهٔ شکلِ `path` (نقطه‌ها به جعبهٔ پیرامونِ خمِ مسطح‌شده نرمال می‌شوند).
 */
export const PEN_MAX = 200;

export class PenPath {
  pts: PathPt[] = [];
  closed = false;
  /** مسیرِ باز با Enter تمام شد (کلیکِ بعدی مسیرِ تازه شروع می‌کند) */
  done = false;
  /** با هر تغییر بالا می‌رود (Stage برای بازرسمِ رویه) */
  ver = 0;
  /** نقطهٔ انتخاب‌شده (آخرین نقطه‌ای که ساخته یا کلیک شد)؛ Delete همین را برمی‌دارد */
  sel: number | null = null;

  get active(): boolean {
    return this.pts.length > 0;
  }

  touch(): void {
    this.ver++;
  }

  clear(): void {
    this.pts = [];
    this.closed = false;
    this.done = false;
    this.sel = null;
    this.touch();
  }

  /** مسیرِ ذخیره‌شده را جایگزینِ مسیرِ فعلی می‌کند (نقطه‌ها کپی می‌شوند) */
  load(path: ShapePath, done = true): void {
    this.pts = path.pts.map((p) => ({ x: p.x, y: p.y, hi: p.hi ? [p.hi[0], p.hi[1]] : null, ho: p.ho ? [p.ho[0], p.ho[1]] : null }));
    this.closed = !!path.closed && this.pts.length >= 3;
    this.done = !this.closed && done && this.pts.length >= 2;
    this.sel = null;
    this.touch();
  }

  /** بسته یا تمام‌شده: کلیکِ بعدی روی جای خالی مسیرِ تازه است */
  get finished(): boolean {
    return this.closed || this.done;
  }

  finish(): void {
    if (this.pts.length >= 2) this.done = true;
    this.touch();
  }

  add(x: number, y: number): number {
    this.pts.push({ x, y, hi: null, ho: null });
    this.done = false;
    this.sel = this.pts.length - 1;
    this.touch();
    return this.pts.length - 1;
  }

  removeLast(): void {
    this.done = false;
    if (this.closed) this.closed = false; // اول بازش کن
    else this.pts.pop();
    this.sel = this.pts.length ? this.pts.length - 1 : null;
    this.touch();
  }

  /** نقطهٔ i را برمی‌دارد (دستگیره‌های بقیه دست‌نخورده)؛ مسیرِ بسته با کمتر از ۳ نقطه باز می‌شود */
  removeAt(i: number): boolean {
    if (i < 0 || i >= this.pts.length) return false;
    this.pts.splice(i, 1);
    if (this.closed && this.pts.length < 3) this.closed = false;
    if (this.pts.length < 2) this.done = false;
    this.sel = this.pts.length ? Math.min(i, this.pts.length - 1) : null;
    this.touch();
    return true;
  }

  /** حذفِ نقطهٔ انتخاب‌شده (وگرنه آخری) */
  removeSelected(): boolean {
    if (!this.pts.length) return false;
    if (this.sel === null || this.sel >= this.pts.length || this.sel === this.pts.length - 1) {
      this.removeLast();
      return true;
    }
    return this.removeAt(this.sel);
  }

  /** پاره‌هایی که می‌شود روی‌شان نقطه گذاشت: i ⇒ i+1 (و آخر ⇒ اول در مسیرِ بسته) */
  get segCount(): number {
    const n = this.pts.length;
    return n < 2 ? 0 : this.closed && n > 2 ? n : n - 1;
  }

  /** نقطهٔ خمِ پارهٔ seg در پارامترِ t (مختصاتِ نرمال) */
  segPoint(seg: number, t: number): Pt2 {
    const n = this.pts.length;
    const a = this.pts[seg];
    const b = this.pts[(seg + 1) % n];
    const u = 1 - t;
    const p1: Pt2 = [a.x + (a.ho ? a.ho[0] : 0), a.y + (a.ho ? a.ho[1] : 0)];
    const p2: Pt2 = [b.x + (b.hi ? b.hi[0] : 0), b.y + (b.hi ? b.hi[1] : 0)];
    const c0 = u * u * u;
    const c1 = 3 * u * u * t;
    const c2 = 3 * u * t * t;
    const c3 = t * t * t;
    return [c0 * a.x + c1 * p1[0] + c2 * p2[0] + c3 * b.x, c0 * a.y + c1 * p1[1] + c2 * p2[1] + c3 * b.y];
  }

  /**
   * نزدیک‌ترین نقطهٔ مسیر به (sx, sy) در مختصاتِ صفحه؛ sc نرمال ⇒ صفحه. ⇒ {seg, t, d} (d فاصله به پیکسلِ صفحه) یا null
   */
  nearestSegment(sc: (nx: number, ny: number) => [number, number], sx: number, sy: number): { seg: number; t: number; d: number } | null {
    let best: { seg: number; t: number; d: number } | null = null;
    for (let s = 0; s < this.segCount; s++) {
      const steps = 40;
      let prev = sc(...this.segPoint(s, 0));
      for (let k = 1; k <= steps; k++) {
        const t1 = k / steps;
        const cur = sc(...this.segPoint(s, t1));
        const vx = cur[0] - prev[0];
        const vy = cur[1] - prev[1];
        const l2 = vx * vx + vy * vy;
        const f = l2 > 1e-9 ? Math.max(0, Math.min(1, ((sx - prev[0]) * vx + (sy - prev[1]) * vy) / l2)) : 0;
        const d = Math.hypot(prev[0] + vx * f - sx, prev[1] + vy * f - sy);
        if (!best || d < best.d) best = { seg: s, t: (k - 1 + f) / steps, d };
        prev = cur;
      }
    }
    return best;
  }

  /** روی پارهٔ seg در t یک نقطه می‌گذارد؛ شکلِ خم عوض نمی‌شود (de Casteljau). ⇒ شاخصِ نقطهٔ تازه */
  insertAt(seg: number, t: number): number {
    const n = this.pts.length;
    if (seg < 0 || seg >= this.segCount) return -1;
    t = Math.max(0.001, Math.min(0.999, t));
    const a = this.pts[seg];
    const b = this.pts[(seg + 1) % n];
    const lerp = (p: Pt2, q: Pt2): Pt2 => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
    const P0: Pt2 = [a.x, a.y];
    const P1: Pt2 = [a.x + (a.ho ? a.ho[0] : 0), a.y + (a.ho ? a.ho[1] : 0)];
    const P2: Pt2 = [b.x + (b.hi ? b.hi[0] : 0), b.y + (b.hi ? b.hi[1] : 0)];
    const P3: Pt2 = [b.x, b.y];
    const P01 = lerp(P0, P1);
    const P12 = lerp(P1, P2);
    const P23 = lerp(P2, P3);
    const P012 = lerp(P01, P12);
    const P123 = lerp(P12, P23);
    const M = lerp(P012, P123);
    const straight = !a.ho && !b.hi;
    const off = (p: Pt2, q: Pt2): Pt2 | null => (Math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-9 ? null : [q[0] - p[0], q[1] - p[1]]);
    const mid: PathPt = { x: +M[0].toFixed(6), y: +M[1].toFixed(6), hi: straight ? null : off(M, P012), ho: straight ? null : off(M, P123) };
    if (!straight) {
      a.ho = off(P0, P01);
      b.hi = off(P3, P23);
    }
    const at = seg + 1;
    this.pts.splice(at, 0, mid);
    this.sel = at;
    this.touch();
    return at;
  }

  /** وسطِ هر پاره یک نقطه (برای ظریف‌کردنِ مسیر) ⇒ تعدادِ نقطه‌های افزوده */
  subdivide(max = 200): number {
    let added = 0;
    for (let s = this.segCount - 1; s >= 0; s--) {
      if (this.pts.length >= max) break;
      if (this.insertAt(s, 0.5) >= 0) added++;
    }
    return added;
  }

  /** جهتِ مسیر را برعکس می‌کند (ورودی و خروجیِ دستگیره‌ها جابه‌جا می‌شود) */
  reverse(): void {
    this.pts.reverse();
    for (const p of this.pts) [p.hi, p.ho] = [p.ho, p.hi];
    this.sel = this.sel === null ? null : this.pts.length - 1 - this.sel;
    this.touch();
  }

  close(): void {
    if (this.pts.length >= 3) this.closed = true;
    this.touch();
  }

  /** گوشه ⇄ نرم: نرم = دستگیره‌ها از روی همسایه‌ها (ثلثِ فاصله، راستای همسایه‌ها) */
  toggleSmooth(i: number): void {
    const p = this.pts[i];
    if (!p) return;
    if (p.hi || p.ho) {
      p.hi = null;
      p.ho = null;
    } else {
      const n = this.pts.length;
      const prev = this.pts[this.closed ? (i - 1 + n) % n : i - 1] ?? p;
      const next = this.pts[this.closed ? (i + 1) % n : i + 1] ?? p;
      const tx = next.x - prev.x;
      const ty = next.y - prev.y;
      const tl = Math.hypot(tx, ty) || 1;
      const dn = Math.hypot(next.x - p.x, next.y - p.y) / 3;
      const dp = Math.hypot(p.x - prev.x, p.y - prev.y) / 3;
      if (next !== p) p.ho = [(tx / tl) * dn, (ty / tl) * dn];
      if (prev !== p) p.hi = [(-tx / tl) * dp, (-ty / tl) * dp];
    }
    this.touch();
  }

  /** نقطهٔ i نرم است؟ (هر دو دستگیره هست و روی یک خط) — برای هماهنگ‌ماندنِ دستگیرهٔ مقابل */
  isSmooth(i: number, W: number, H: number): boolean {
    const p = this.pts[i];
    if (!p?.hi || !p.ho) return false;
    const ax = p.hi[0] * W;
    const ay = p.hi[1] * H;
    const bx = p.ho[0] * W;
    const by = p.ho[1] * H;
    const la = Math.hypot(ax, ay);
    const lb = Math.hypot(bx, by);
    if (la < 1e-6 || lb < 1e-6) return false;
    return Math.abs(ax * by - ay * bx) / (la * lb) < 0.02 && ax * bx + ay * by < 0;
  }

  toShapePath(): ShapePath {
    return { closed: this.closed, pts: this.pts.map((p) => ({ x: p.x, y: p.y, hi: p.hi ? [p.hi[0], p.hi[1]] : null, ho: p.ho ? [p.ho[0], p.ho[1]] : null })) };
  }
}

/** مثلِ paths.flatten (نقطه‌ها به پیکسل نسبت به گوشهٔ جعبهٔ w×h) — برای جعبهٔ پیرامون */
export function flattenPx(path: ShapePath, wpx: number, hpx: number): Pt2[] {
  const pts = path.pts;
  const n = pts.length;
  if (!n) return [];
  const closed = path.closed && n > 1;
  const out: Pt2[] = [[pts[0].x * wpx, pts[0].y * hpx]];
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    const p0: Pt2 = [a.x * wpx, a.y * hpx];
    const p3: Pt2 = [b.x * wpx, b.y * hpx];
    const last = closed && i === segs - 1;
    if (!a.ho && !b.hi) {
      if (!last) out.push(p3);
      continue;
    }
    const p1: Pt2 = [p0[0] + (a.ho ? a.ho[0] * wpx : 0), p0[1] + (a.ho ? a.ho[1] * hpx : 0)];
    const p2: Pt2 = [p3[0] + (b.hi ? b.hi[0] * wpx : 0), p3[1] + (b.hi ? b.hi[1] * hpx : 0)];
    const length = Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) + Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) + Math.hypot(p3[0] - p2[0], p3[1] - p2[1]);
    const steps = Math.max(6, Math.min(400, Math.ceil(length / 1.5)));
    for (let s = 1; s <= steps; s++) {
      if (last && s === steps) break;
      const t = s / steps;
      const u = 1 - t;
      const c0 = u * u * u;
      const c1 = 3 * u * u * t;
      const c2 = 3 * u * t * t;
      const c3 = t * t * t;
      out.push([c0 * p0[0] + c1 * p1[0] + c2 * p2[0] + c3 * p3[0], c0 * p0[1] + c1 * p1[1] + c2 * p2[1] + c3 * p3[1]]);
    }
  }
  return out;
}

const r5 = (v: number) => Math.round(v * 1e5) / 1e5;
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/**
 * مسیر (بومِ نرمال) ⇒ لایهٔ شکلِ path: جعبهٔ پیرامونِ خمِ مسطح‌شده به پیکسلِ بوم؛ نقطه‌ها و دستگیره‌ها به همان جعبه نرمال
 * (x' = (X − bx0)/bw، دستگیره ÷ bw / ÷ bh). w و h کسری از پهنای بوم؛ cx کسری از پهنا، cy کسری از ارتفاعِ بوم.
 */
export function penToShape(pen: PenPath, Wc: number, Hc: number): { path: ShapePath; box: { cx: number; cy: number; w: number; h: number } } | null {
  if (pen.pts.length < 2) return null;
  const poly = flattenPx(pen.toShapePath(), Wc, Hc);
  if (poly.length < 2) return null;
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const [x, y] of poly) {
    x0 = Math.min(x0, x);
    y0 = Math.min(y0, y);
    x1 = Math.max(x1, x);
    y1 = Math.max(y1, y);
  }
  const bw = Math.max(1, x1 - x0);
  const bh = Math.max(1, y1 - y0);
  const h = (v: Pt2 | null): Pt2 | null => (v ? [r5(clamp((v[0] * Wc) / bw, -3, 3)), r5(clamp((v[1] * Hc) / bh, -3, 3))] : null);
  const pts: PathPt[] = pen.pts.map((p) => ({
    x: r5(clamp((p.x * Wc - x0) / bw, -2, 3)),
    y: r5(clamp((p.y * Hc - y0) / bh, -2, 3)),
    hi: h(p.hi),
    ho: h(p.ho),
  }));
  return {
    path: { closed: pen.closed, pts },
    box: { cx: r5((x0 + bw / 2) / Wc), cy: r5((y0 + bh / 2) / Hc), w: r5(bw / Wc), h: r5(bh / Wc) },
  };
}

/** مسیر ⇒ انتخاب (nonzero؛ مسیرِ باز ضمناً بسته است). false = کمتر از ۳ نقطه */
export function penToSelection(pen: PenPath, sel: Selection, mode: "new" | "add" | "sub"): boolean {
  if (pen.pts.length < 3) return false;
  const path = pen.toShapePath();
  sel.paint((c) => tracePath(c, path, 0, 0, sel.w, sel.h), mode);
  return true;
}

/** مسیرِ نمایشِ SVG به مختصاتِ صفحه؛ cursor = نقطهٔ نشانگر (ریسمانِ کشسان از آخرین نقطه) */
export function penSvgD(pen: PenPath, sc: (nx: number, ny: number) => [number, number], cursor?: Pt2 | null): string {
  const pts = pen.pts;
  const n = pts.length;
  if (!n) return "";
  const P = (p: PathPt): [number, number] => sc(p.x, p.y);
  const H = (p: PathPt, h: Pt2 | null): [number, number] => (h ? sc(p.x + h[0], p.y + h[1]) : P(p));
  let d = `M${P(pts[0]).join(",")}`;
  const closed = pen.closed && n > 1;
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const a = pts[i];
    const b = pts[(i + 1) % n];
    if (!a.ho && !b.hi) d += ` L${P(b).join(",")}`;
    else d += ` C${H(a, a.ho).join(",")} ${H(b, b.hi).join(",")} ${P(b).join(",")}`;
  }
  if (closed) d += " Z";
  else if (cursor) {
    const a = pts[n - 1];
    const c = sc(cursor[0], cursor[1]);
    d += a.ho ? ` C${H(a, a.ho).join(",")} ${c.join(",")} ${c.join(",")}` : ` L${c.join(",")}`;
  }
  return d;
}
