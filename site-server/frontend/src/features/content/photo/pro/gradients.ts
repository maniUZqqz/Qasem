/**
 * شیبِ چندتوقفی (دورِ ۸): فهرستِ [جایگاه ۰..۱، رنگِ #rrggbb]. همان قراردادِ backend/effects.py › _clean_stops و `_ramp`.
 * جزءِ مشترکِ «ویرایشگرِ توقف‌های شیب»، لایهٔ پرکنندهٔ شیب و «پرکردنِ لایهٔ نقاشی با شیب».
 */
export type Stop = [number, string];

export const MAX_STOPS = 12;
export const DEFAULT_STOPS: Stop[] = [[0, "#7c3aed"], [0.55, "#ec4899"], [1, "#f59e0b"]];

const HEX = /^#[0-9a-fA-F]{6}$/;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** هر ورودی ⇒ فهرستِ معتبر: ۲ تا ۱۲ توقف، جایگاه‌ها در ۰..۱ و مرتب، رنگ‌ها شش‌رقمی */
export function normStops(raw: unknown): Stop[] {
  const out: Stop[] = [];
  if (Array.isArray(raw)) {
    for (const s of raw.slice(0, MAX_STOPS)) {
      if (!Array.isArray(s)) continue;
      const pos = Number(s[0]);
      const col = typeof s[1] === "string" ? s[1].toLowerCase() : "";
      if (Number.isFinite(pos) && HEX.test(col)) out.push([Math.round(clamp01(pos) * 1000) / 1000, col]);
    }
  }
  if (out.length < 2) return DEFAULT_STOPS.map((s) => [s[0], s[1]] as Stop);
  out.sort((a, b) => a[0] - b[0]);
  return out;
}

const rgb = (h: string): [number, number, number] => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
const hex = (c: number[]) => "#" + c.map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0")).join("");

/** رنگِ شیب در جایگاهِ t (درون‌یابیِ خطی میانِ توقف‌ها؛ بیرون از دو سر همان رنگِ سر) */
export function colorAt(stops: Stop[], t: number): string {
  const s = normStops(stops);
  if (t <= s[0][0]) return s[0][1];
  if (t >= s[s.length - 1][0]) return s[s.length - 1][1];
  for (let i = 1; i < s.length; i++) {
    if (t <= s[i][0]) {
      const a = s[i - 1];
      const b = s[i];
      const k = b[0] === a[0] ? 0 : (t - a[0]) / (b[0] - a[0]);
      const ca = rgb(a[1]);
      const cb = rgb(b[1]);
      return hex([0, 1, 2].map((j) => ca[j] + (cb[j] - ca[j]) * k));
    }
  }
  return s[s.length - 1][1];
}

/** CSS برای نوارِ نمایش (چپ → راست) */
export const cssGradient = (stops: Stop[]): string => `linear-gradient(90deg, ${normStops(stops).map(([p, c]) => `${c} ${(p * 100).toFixed(1)}%`).join(", ")})`;

/** توقفِ تازه در جایگاهِ t با رنگِ درون‌یابی‌شده؛ سقفِ ۱۲ */
export function addStop(stops: Stop[], t: number): Stop[] {
  const s = normStops(stops);
  if (s.length >= MAX_STOPS) return s;
  const p = Math.round(clamp01(t) * 1000) / 1000;
  return [...s, [p, colorAt(s, p)] as Stop].sort((a, b) => a[0] - b[0]);
}

/** برداشتنِ توقفِ i (دست‌کم ۲ توقف می‌ماند) */
export const removeStop = (stops: Stop[], i: number): Stop[] => (stops.length <= 2 ? stops : stops.filter((_, k) => k !== i));

/** ساختنِ شیبِ بومِ دوبعدی روی ctx: kind خطی/شعاعی/زاویه‌ای؛ angle درجه (۹۰ = بالا ⇒ پایین) روی مستطیلِ w×h */
export function canvasGradient(ctx: CanvasRenderingContext2D, w: number, h: number, stops: Stop[], kind: "linear" | "radial" | "angle", angle: number, reverse: boolean): CanvasGradient {
  const s = normStops(stops).map(([p, c]) => [reverse ? 1 - p : p, c] as Stop).sort((a, b) => a[0] - b[0]);
  let g: CanvasGradient;
  const cx = w / 2;
  const cy = h / 2;
  if (kind === "radial") g = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.hypot(cx, cy));
  else if (kind === "angle" && "createConicGradient" in ctx) g = (ctx as CanvasRenderingContext2D & { createConicGradient(a: number, x: number, y: number): CanvasGradient }).createConicGradient(((angle - 90) * Math.PI) / 180, cx, cy);
  else {
    const th = (angle * Math.PI) / 180;
    const dx = Math.cos(th);
    const dy = Math.sin(th);
    const half = (Math.abs(dx) * w + Math.abs(dy) * h) / 2;
    g = ctx.createLinearGradient(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half);
  }
  for (const [p, c] of s) g.addColorStop(clamp01(p), c);
  return g;
}
