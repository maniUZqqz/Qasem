/**
 * ابزارهای رنگِ خودکار: «رنگِ خودکار»، «تطبیقِ رنگِ دو نما» و «قطره‌چکانِ تعادلِ سفید». هر سه از روی آمارِ یک فریم (میانگینِ رنگ، میانهٔ روشنایی، گسترهٔ تُن،
 * اشباع) چند لغزندهٔ همان رنگِ قطعه را پیشنهاد می‌دهند (نوردهی، کنتراست، دما، تینت، اشباع) — پس نتیجه قابلِ ویرایش و برگشت‌پذیر است و در پیش‌نمایش
 * و خروجی یکسان دیده می‌شود. بدونِ React و بدونِ مرورگر (آزمون: tests/video-r5-color.test.ts).
 */
import type { ColorParams } from "./model";

export type Px = { data: Uint8ClampedArray | number[]; width: number; height: number };
export type Rgb3 = [number, number, number];
export type FrameStats = {
  n: number;
  mean: Rgb3;
  p2: number;
  p50: number;
  p98: number;
  /** میانگینِ اشباعِ HSV */
  sat: number;
  /** میانگینِ پیکسل‌های «تقریباً خنثی» (برای تعادلِ سفید)؛ اگر کم بود همان میانگینِ کل */
  neutral: Rgb3;
};

const luma = (r: number, g: number, b: number) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const clamp = (x: number, lo: number, hi: number) => (x < lo ? lo : x > hi ? hi : x);

export function frameStats(img: Px, step = 2): FrameStats {
  const d = img.data;
  const hist = new Uint32Array(256);
  let n = 0;
  let sr = 0, sg = 0, sb = 0, ss = 0;
  let nn = 0, nr = 0, ng = 0, nb = 0;
  const w = img.width;
  for (let y = 0; y < img.height; y += step) {
    for (let x = 0; x < w; x += step) {
      const i = (y * w + x) * 4;
      const r = d[i] / 255, g = d[i + 1] / 255, b = d[i + 2] / 255;
      if (d[i + 3] === 0) continue;
      n++;
      sr += r; sg += g; sb += b;
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      const s = mx > 0 ? (mx - mn) / mx : 0;
      ss += s;
      const l = luma(r, g, b);
      hist[Math.min(255, Math.round(l * 255))]++;
      if (s < 0.28 && l > 0.12 && l < 0.92) { nn++; nr += r; ng += g; nb += b; }
    }
  }
  if (!n) return { n: 0, mean: [0.5, 0.5, 0.5], p2: 0, p50: 0.5, p98: 1, sat: 0, neutral: [0.5, 0.5, 0.5] };
  const pct = (q: number) => {
    let acc = 0;
    const target = q * n;
    for (let i = 0; i < 256; i++) {
      acc += hist[i];
      if (acc >= target) return i / 255;
    }
    return 1;
  };
  const mean: Rgb3 = [sr / n, sg / n, sb / n];
  const neutral: Rgb3 = nn > n * 0.02 ? [nr / nn, ng / nn, nb / nn] : mean;
  return { n, mean, p2: pct(0.02), p50: pct(0.5), p98: pct(0.98), sat: ss / n, neutral };
}

/** همان بهره‌های دما/تینتِ color.ts (makeTone) */
export const wbGains = (t: number, n: number): Rgb3 => [1 + 0.2 * t + 0.05 * n, 1 - 0.15 * n, 1 - 0.2 * t + 0.05 * n];

/**
 * (دما، تینت) را (هر دو در −۱..۱) طوری پیدا می‌کند که بهره‌ها تا حدِ ممکن به نسبتِ `want` برسند (روشنایی کلی مهم نیست: نوردهی جدا حساب می‌شود).
 * جست‌وجوی شبکه‌ای + ریزسازی؛ ارزان و بی‌نیاز به کتابخانه.
 */
export function solveWb(want: Rgb3): { t: number; n: number } {
  const lw = want.map((x) => Math.log(Math.max(1e-3, x)));
  const cost = (t: number, n: number) => {
    const g = wbGains(t, n).map((x) => Math.log(Math.max(1e-3, x)));
    const e = g.map((x, i) => x - lw[i]);
    const m = (e[0] + e[1] + e[2]) / 3;
    return e.reduce((a, x) => a + (x - m) * (x - m), 0);
  };
  let best = { t: 0, n: 0, c: cost(0, 0) };
  for (let t = -1; t <= 1.0001; t += 0.05) for (let n = -1; n <= 1.0001; n += 0.05) {
    const c = cost(t, n);
    if (c < best.c) best = { t, n, c };
  }
  for (const h of [0.02, 0.005]) {
    const c0 = { ...best };
    for (let dt = -4; dt <= 4; dt++) for (let dn = -4; dn <= 4; dn++) {
      const t = clamp(c0.t + dt * h, -1, 1), n = clamp(c0.n + dn * h, -1, 1);
      const c = cost(t, n);
      if (c < best.c) best = { t, n, c };
    }
  }
  return { t: best.t, n: best.n };
}

const round = (x: number, d = 2) => Math.round(x * 10 ** d) / 10 ** d;

export type ColorPatch = Required<Pick<ColorParams, "exposure" | "contrast" | "temperature" | "tint" | "saturation">>;

/** هدفِ «رنگِ خودکار»: میانهٔ روشنایی، گسترهٔ تُن و اشباعِ یک تصویرِ معمولیِ خوب */
export const AUTO_TARGET = { p50: 0.46, spread: 0.86 };

export function autoColor(s: FrameStats): ColorPatch {
  const wb = solveWb([1 / Math.max(0.02, s.neutral[0]), 1 / Math.max(0.02, s.neutral[1]), 1 / Math.max(0.02, s.neutral[2])]);
  // سفیدِ تقریباً خنثی را فقط وقتی درست کن که واقعاً رنگ‌ِ غالب دارد (وگرنه صحنهٔ گرمِ عمدی را خراب می‌کنیم)
  const cast = Math.max(...s.neutral) - Math.min(...s.neutral);
  const k = clamp((cast - 0.02) / 0.06, 0, 1);
  const spread = Math.max(0.05, s.p98 - s.p2);
  const contrast = spread < AUTO_TARGET.spread ? clamp((AUTO_TARGET.spread / spread - 1) * 60, 0, 60) : spread > 0.99 ? -10 : 0;
  // کنتراست تُنِ تیره را پایین‌تر می‌برد؛ نوردهی کمی جبران می‌کند
  const ev = clamp(Math.log2(AUTO_TARGET.p50 / Math.max(0.03, s.p50)) * 0.85 + (s.p50 < 0.5 ? contrast * 0.004 : 0), -1.5, 1.5);
  const saturation = s.sat < 0.03 ? 100 : s.sat < 0.22 ? 118 : s.sat < 0.32 ? 108 : s.sat > 0.62 ? 92 : 100;      // (تقریباً) سیاه‌وسفید = عمدی
  return {
    exposure: Math.abs(ev) < 0.05 ? 0 : round(ev),
    contrast: Math.round(contrast),
    temperature: Math.round(wb.t * k * 100),
    tint: Math.round(wb.n * k * 100),
    saturation,
  };
}

/** تطبیقِ آمارِ `target` با `ref`؛ strength ۰..۱ */
export function matchColor(target: FrameStats, ref: FrameStats, strength = 1): ColorPatch {
  const sg = clamp(strength, 0, 1);
  const ev = clamp(Math.log2(Math.max(0.03, ref.p50) / Math.max(0.03, target.p50)), -2, 2) * sg;
  const tSpread = Math.max(0.05, target.p98 - target.p2);
  const rSpread = Math.max(0.05, ref.p98 - ref.p2);
  const contrast = clamp((rSpread / tSpread - 1) * 70, -50, 60) * sg;
  const lr = luma(...ref.mean) || 0.5;
  const lt = luma(...target.mean) || 0.5;
  const want: Rgb3 = [
    ref.mean[0] / Math.max(0.02, target.mean[0]) / (lr / lt),
    ref.mean[1] / Math.max(0.02, target.mean[1]) / (lr / lt),
    ref.mean[2] / Math.max(0.02, target.mean[2]) / (lr / lt),
  ];
  const wb = solveWb(want);
  const satRatio = ref.sat / Math.max(0.02, target.sat);
  const saturation = clamp(100 * Math.pow(clamp(satRatio, 0.4, 1.7), sg), 40, 170);
  return {
    exposure: Math.abs(ev) < 0.05 ? 0 : round(ev),
    contrast: Math.round(contrast),
    temperature: Math.round(wb.t * sg * 100),
    tint: Math.round(wb.n * sg * 100),
    saturation: Math.round(saturation),
  };
}

/** قطره‌چکان: رنگِ نمونه (همان‌طور که الان روی صفحه دیده می‌شود) خاکستری شود. `current` = دما/تینتِ فعلیِ قطعه برای افزودنِ اصلاح روی آن. */
export function eyedropper(sample: Rgb3, current: { temperature?: number; tint?: number } = {}): { temperature: number; tint: number } {
  const t0 = (current.temperature ?? 0) / 100;
  const n0 = (current.tint ?? 0) / 100;
  const g0 = wbGains(t0, n0);
  // نمونه الان از زیرِ بهره‌های فعلی گذشته؛ اصلاحِ نسبی را روی آن حساب کن
  const base: Rgb3 = [sample[0] / g0[0], sample[1] / g0[1], sample[2] / g0[2]];
  const wb = solveWb([1 / Math.max(0.02, base[0]), 1 / Math.max(0.02, base[1]), 1 / Math.max(0.02, base[2])]);
  return { temperature: Math.round(wb.t * 100), tint: Math.round(wb.n * 100) };
}

/** میانگینِ یک همسایگی (۹×۹ پیکسل) برای قطره‌چکان */
export function samplePixel(img: Px, fx: number, fy: number, radius = 4): Rgb3 {
  const cx = clamp(Math.round(fx * (img.width - 1)), 0, img.width - 1);
  const cy = clamp(Math.round(fy * (img.height - 1)), 0, img.height - 1);
  let r = 0, g = 0, b = 0, n = 0;
  for (let y = Math.max(0, cy - radius); y <= Math.min(img.height - 1, cy + radius); y++) {
    for (let x = Math.max(0, cx - radius); x <= Math.min(img.width - 1, cx + radius); x++) {
      const i = (y * img.width + x) * 4;
      r += img.data[i]; g += img.data[i + 1]; b += img.data[i + 2]; n++;
    }
  }
  return n ? [r / n / 255, g / n / 255, b / n / 255] : [0.5, 0.5, 0.5];
}

export const patchToParams = (cur: ColorParams | undefined, patch: Partial<ColorPatch>): ColorParams => {
  const out: ColorParams = { ...(cur ?? {}), ...patch };
  if (out.saturation === 100) delete out.saturation;
  for (const k of ["exposure", "contrast", "temperature", "tint"] as const) if (out[k] === 0) delete out[k];
  return out;
};

// ───────────── هیو در برابرِ (Hue-vs): شش نقطهٔ رنگ ⇒ همان HSLِ ثانویه
export const HUE_BANDS: { key: "red" | "yellow" | "green" | "cyan" | "blue" | "magenta"; title: string; hue: number; css: string }[] = [
  { key: "red", title: "قرمز", hue: 0, css: "#ef4444" },
  { key: "yellow", title: "زرد", hue: 60, css: "#eab308" },
  { key: "green", title: "سبز", hue: 120, css: "#22c55e" },
  { key: "cyan", title: "فیروزه‌ای", hue: 180, css: "#06b6d4" },
  { key: "blue", title: "آبی", hue: 240, css: "#3b82f6" },
  { key: "magenta", title: "ارغوانی", hue: 300, css: "#d946ef" },
];
export type HueMode = "sat" | "hue" | "lum";
export const HUE_MODES: { key: HueMode; title: string; field: "s" | "h" | "l"; min: number; max: number }[] = [
  { key: "sat", title: "رنگ در برابرِ اشباع (Hue vs Sat)", field: "s", min: -100, max: 100 },
  { key: "hue", title: "رنگ در برابرِ رنگ (Hue vs Hue)", field: "h", min: -180, max: 180 },
  { key: "lum", title: "رنگ در برابرِ روشنایی (Hue vs Lum)", field: "l", min: -100, max: 100 },
];

/** منحنیِ دورانیِ هموارِ شش مقدار (در مرکزِ هر محدوده) — برای کشیدنِ نمودار؛ x = زاویه ۰..۳۶۰ */
export function hueCurve(values: number[], x: number): number {
  const h = ((x % 360) + 360) % 360;
  const i = Math.floor(h / 60) % 6;
  const u = (h - i * 60) / 60;
  const p0 = values[(i + 5) % 6], p1 = values[i], p2 = values[(i + 1) % 6], p3 = values[(i + 2) % 6];
  // Catmull-Rom
  return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u);
}
