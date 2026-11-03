/**
 * رنگِ قطعه (Lumetri‌مانند) — آینهٔ دقیقِ backend/services/editing/color.py تا پیش‌نمایشِ فوری با رندرِ ffmpeg یکی باشد.
 *
 * خط‌لولهٔ پیکسل (ترتیبِ فیلترهای ffmpeg):
 *   ۱. منحنیِ تُن  — برای هر کانال ۹ نقطه (x = i/8) + درون‌یابیِ PCHIP؛ همان `curves=interp=pchip`. در مرورگر یک LUT ِ ۲۵۶تایی.
 *      (نوردهی → دمای رنگ/تینت → کنتراست → سایه/هایلایت/سفید/سیاه → منحنیِ اصلی → منحنیِ کانال → منحنیِ حالت)
 *   ۲. اشباع      — ماتریسِ ۳×۳ حولِ لومای Rec.709 (دقیق، مثلِ colorchannelmixer)
 *   ۳. ویبرنس    — دقیقاً الگوریتمِ ffmpeg: k = 1 + I·(1 + sgn(I)·(max−min))، c' = Y + (c−Y)·k (Y لومای 709) [خطا < ۱ سطح]
 *   ۴. HSL        — دقیقِ huesaturation: وزنِ محدوده w = (r − max(g,b)) و … ؛ ماتریسِ (1+I)·Sat(1+S)·Hue(H) و
 *                   c' = c + w·(M·c − c) برای هر محدودهٔ فعال به‌ترتیب [خطا ≈ ۰٫۱ سطح]
 *   ۵. چرخ‌ها    — فرمولِ colorbalance (سایه/میانه/هایلایت با l = max+min)
 *   ۶. پس‌افکت‌ها — شارپ (unsharp ۵×۵ روی لوما)، تیرگیِ لبه (cos⁴)، دانه، محو، حذفِ نویز: `postFx` + `applyPostFx`
 *                   (محو و حذفِ نویز را کامپوزیتور با `ctx.filter` می‌زند)
 */
import type { ColorParams, HslKey, Rgb } from "./model";

export type LookDef = { key: string; title: string; params: ColorParams };
export type Curve = [number, number][];
export type CurveKey = "m" | "r" | "g" | "b";

export const SLIDER_KEYS = [
  "exposure", "contrast", "highlights", "shadows", "whites", "blacks", "temperature", "tint", "saturation", "vibrance",
  "sharpen", "denoise", "blur", "vignette", "grain",
] as const;
export type SliderKey = (typeof SLIDER_KEYS)[number];

/** [min, max, پیش‌فرض] — همان SLIDERS ِ color.py */
export const SLIDERS: Record<SliderKey, [number, number, number]> = {
  exposure: [-3, 3, 0], contrast: [-100, 100, 0], highlights: [-100, 100, 0], shadows: [-100, 100, 0], whites: [-100, 100, 0],
  blacks: [-100, 100, 0], temperature: [-100, 100, 0], tint: [-100, 100, 0], saturation: [0, 200, 100], vibrance: [-100, 100, 0],
  sharpen: [0, 100, 0], denoise: [0, 100, 0], blur: [0, 100, 0], vignette: [0, 100, 0], grain: [0, 100, 0],
};
export const ZONES = ["shadows", "mids", "highs"] as const;
export type Zone = (typeof ZONES)[number];
export const HSL_KEYS: HslKey[] = ["red", "yellow", "green", "cyan", "blue", "magenta"];
export const CURVE_KEYS: CurveKey[] = ["m", "r", "g", "b"];
export const MAX_CURVE_POINTS = 8;
export const IDENTITY_CURVE: Curve = [[0, 0], [1, 1]];

export type FullColor = Record<SliderKey, number> & {
  wheels: Record<Zone, Rgb>;
  curves: Record<CurveKey, Curve>;
  hsl: Record<HslKey, { h: number; s: number; l: number }>;
  look: string;
  look_amount: number;
};
export type EffectiveColor = FullColor & { lookCurves: null | ({ a: number } & Record<CurveKey, Curve>) };

const clamp = (x: number, lo: number, hi: number) => (x < lo ? lo : x > hi ? hi : x);
const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
const num = (v: unknown, lo: number, hi: number, d: number): number => {
  const x = typeof v === "number" ? v : Number(v);
  if (v === undefined || v === null || !Number.isFinite(x)) return d;
  return Math.round(clamp(x, lo, hi) * 10000) / 10000;
};

/** منحنی را مثلِ سرور مرتب/یکتا/دوسرچسبیده و حداکثر ۸ نقطه می‌کند؛ اگر همانی بود [[0,0],[1,1]] */
export function cleanCurve(raw: unknown): Curve {
  const pts: Curve = [];
  if (Array.isArray(raw)) {
    for (const it of raw.slice(0, 24)) {
      if (!Array.isArray(it) || it.length < 2) continue;
      const x = Number(it[0]);
      const y = Number(it[1]);
      if (Number.isFinite(x) && Number.isFinite(y)) pts.push([clamp01(x), clamp01(y)]);
    }
  }
  pts.sort((a, b) => a[0] - b[0]);
  const merged: Curve = [];
  for (const p of pts) {
    if (merged.length && p[0] - merged[merged.length - 1][0] < 0.01) merged[merged.length - 1] = p;
    else merged.push(p);
  }
  if (!merged.length || merged[0][0] > 0.0005) merged.unshift([0, 0]);
  if (merged[merged.length - 1][0] < 0.9995) merged.push([1, 1]);
  let out = merged;
  if (out.length > MAX_CURVE_POINTS) {
    const inner = out.slice(1, -1);
    const keep = MAX_CURVE_POINTS - 2;
    const step = inner.length / keep;
    out = [out[0], ...Array.from({ length: keep }, (_, i) => inner[Math.floor(i * step)]), out[out.length - 1]];
  }
  const rounded = out.map(([x, y]) => [Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000] as [number, number]);
  return rounded.every(([x, y]) => Math.abs(x - y) < 1e-4) ? [[0, 0], [1, 1]] : rounded;
}

const isIdentity = (c: Curve) => c.every(([x, y]) => Math.abs(x - y) < 1e-4);

/** پارامترهای ناقص ⇒ همه‌چیز پُر و محدود (همان `clean` ِ سرور) */
export function cleanColor(src?: ColorParams | null): FullColor {
  const s = (src ?? {}) as ColorParams & Record<string, unknown>;
  const out = {} as FullColor;
  for (const k of SLIDER_KEYS) out[k] = num(s[k], SLIDERS[k][0], SLIDERS[k][1], SLIDERS[k][2]);
  const wheels = (s.wheels ?? {}) as Record<string, unknown>;
  out.wheels = {} as Record<Zone, Rgb>;
  for (const z of ZONES) {
    const raw = Array.isArray(wheels[z]) ? (wheels[z] as unknown[]) : [];
    out.wheels[z] = [num(raw[0], -1, 1, 0), num(raw[1], -1, 1, 0), num(raw[2], -1, 1, 0)];
  }
  const curves = (s.curves ?? {}) as Record<string, unknown>;
  out.curves = {} as Record<CurveKey, Curve>;
  for (const c of CURVE_KEYS) out.curves[c] = cleanCurve(curves[c]);
  const hsl = (s.hsl ?? {}) as Record<string, { h?: number; s?: number; l?: number } | undefined>;
  out.hsl = {} as FullColor["hsl"];
  for (const k of HSL_KEYS) {
    const r = hsl[k] ?? {};
    out.hsl[k] = { h: num(r.h, -180, 180, 0), s: num(r.s, -100, 100, 0), l: num(r.l, -100, 100, 0) };
  }
  out.look = typeof s.look === "string" ? s.look : "";
  out.look_amount = num(s.look_amount, 0, 100, 100);
  return out;
}

export const neutralColor = (): FullColor => cleanColor(null);

/** همان `effective` ِ سرور: حالت (look) با مقدارِ look_amount روی پارامترها ادغام می‌شود */
export function effectiveColor(p: ColorParams | undefined | null, looks: LookDef[]): EffectiveColor {
  const pc = cleanColor(p);
  const e: EffectiveColor = { ...structuredCloneColor(pc), lookCurves: null };
  const look = looks.find((l) => l.key === pc.look);
  const a = pc.look_amount / 100;
  if (!look || a <= 0) {
    if (!look) e.look = "";
    return e;
  }
  const lp = cleanColor(look.params);
  for (const k of SLIDER_KEYS) {
    if (k === "saturation") e[k] = num(pc[k] + a * (lp[k] - 100), 0, 200, 100);
    else e[k] = num(pc[k] + a * lp[k], SLIDERS[k][0], SLIDERS[k][1], SLIDERS[k][2]);
  }
  for (const z of ZONES) e.wheels[z] = [0, 1, 2].map((i) => num(pc.wheels[z][i] + a * lp.wheels[z][i], -1, 1, 0)) as Rgb;
  for (const k of HSL_KEYS) {
    e.hsl[k] = {
      h: num(pc.hsl[k].h + a * lp.hsl[k].h, -180, 180, 0),
      s: num(pc.hsl[k].s + a * lp.hsl[k].s, -100, 100, 0),
      l: num(pc.hsl[k].l + a * lp.hsl[k].l, -100, 100, 0),
    };
  }
  e.lookCurves = { a, m: lp.curves.m, r: lp.curves.r, g: lp.curves.g, b: lp.curves.b };
  return e;
}

function structuredCloneColor(c: FullColor): FullColor {
  return {
    ...c,
    wheels: { shadows: [...c.wheels.shadows], mids: [...c.wheels.mids], highs: [...c.wheels.highs] },
    curves: { m: c.curves.m.map((p) => [...p] as [number, number]), r: c.curves.r.map((p) => [...p] as [number, number]), g: c.curves.g.map((p) => [...p] as [number, number]), b: c.curves.b.map((p) => [...p] as [number, number]) },
    hsl: Object.fromEntries(HSL_KEYS.map((k) => [k, { ...c.hsl[k] }])) as FullColor["hsl"],
  };
}

// ─────────────────────────────────────────────────────────── PCHIP
const sign = (v: number) => (v > 0 ? 1 : v < 0 ? -1 : 0);

function edgeSlope(h0: number, h1: number, d0: number, d1: number): number {
  const s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1);
  if (sign(s) !== sign(d0)) return 0;
  if (sign(d0) !== sign(d1) && Math.abs(s) > 3 * Math.abs(d0)) return 3 * d0;
  return s;
}

/** تابعِ y = f(x) از میانِ نقطه‌ها (x صعودی): هرمیتِ مکعبیِ یکنوا؛ بیرونِ نقطه‌ها = مقدارِ لبه */
export function pchip(points: Curve): (x: number) => number {
  const n = points.length;
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  if (n < 2) {
    const c = ys[0] ?? 0;
    return () => c;
  }
  const h: number[] = [];
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    h.push(xs[i + 1] - xs[i]);
    d.push((ys[i + 1] - ys[i]) / h[i]);
  }
  const m = new Array<number>(n).fill(0);
  if (n === 2) {
    m[0] = d[0];
    m[1] = d[0];
  } else {
    for (let k = 1; k < n - 1; k++) {
      if (d[k - 1] * d[k] > 0) {
        const w1 = 2 * h[k] + h[k - 1];
        const w2 = h[k] + 2 * h[k - 1];
        m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k]);
      }
    }
    m[0] = edgeSlope(h[0], h[1], d[0], d[1]);
    m[n - 1] = edgeSlope(h[n - 2], h[n - 3], d[n - 2], d[n - 3]);
  }
  return (x: number) => {
    if (x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let k = 0;
    while (k < n - 2 && x > xs[k + 1]) k++;
    const u = (x - xs[k]) / h[k];
    const u2 = u * u;
    const u3 = u2 * u;
    return (2 * u3 - 3 * u2 + 1) * ys[k] + (u3 - 2 * u2 + u) * h[k] * m[k] + (-2 * u3 + 3 * u2) * ys[k + 1] + (u3 - u2) * h[k] * m[k + 1];
  };
}

// ─────────────────────────────────────────────────────────── tone chain
const SAMPLES = 9;
const ZONE_NORM = 256 / 27;
const smootherstep = (y: number) => y * y * y * (y * (6 * y - 15) + 10);

type Tone = (ci: number, x: number) => number;

function makeTone(e: EffectiveColor): Tone {
  const t = e.temperature / 100;
  const n = e.tint / 100;
  const gains = [1 + 0.2 * t + 0.05 * n, 1 - 0.15 * n, 1 - 0.2 * t + 0.05 * n];
  const expo = Math.pow(2, e.exposure);
  const c = e.contrast / 100;
  const sh = e.shadows / 100;
  const hi = e.highlights / 100;
  const wh = e.whites / 100;
  const bl = e.blacks / 100;
  const zones = sh !== 0 || hi !== 0 || wh !== 0 || bl !== 0;
  const master = isIdentity(e.curves.m) ? null : pchip(e.curves.m);
  const chan = (["r", "g", "b"] as const).map((k) => (isIdentity(e.curves[k]) ? null : pchip(e.curves[k])));
  const lc = e.lookCurves;
  const la = lc ? lc.a : 0;
  const lMaster = lc && !isIdentity(lc.m) ? pchip(lc.m) : null;
  const lChan = (["r", "g", "b"] as const).map((k) => (lc && !isIdentity(lc[k]) ? pchip(lc[k]) : null));
  return (ci, x) => {
    let y = clamp01(x * expo);
    y = clamp01(y * gains[ci]);
    if (c) y = clamp01(y + c * (smootherstep(y) - y));
    if (zones) {
      const y0 = y;
      const iy = 1 - y0;
      y = clamp01(y0 + 0.3 * sh * ZONE_NORM * y0 * iy * iy * iy + 0.3 * hi * ZONE_NORM * iy * y0 * y0 * y0 + 0.2 * wh * y0 * y0 * y0 + 0.2 * bl * iy * iy * iy);
    }
    if (master) y = clamp01(master(y));
    const ch = chan[ci];
    if (ch) y = clamp01(ch(y));
    if (la > 0) {
      if (lMaster) y = clamp01(y + la * (lMaster(y) - y));
      const lcn = lChan[ci];
      if (lcn) y = clamp01(y + la * (lcn(y) - y));
    }
    return y;
  };
}

function tonePointsEff(e: EffectiveColor): { r: Curve; g: Curve; b: Curve } {
  const tone = makeTone(e);
  const out = { r: [] as Curve, g: [] as Curve, b: [] as Curve };
  (["r", "g", "b"] as const).forEach((ch, ci) => {
    let run = 0;
    for (let i = 0; i < SAMPLES; i++) {
      const x = i / (SAMPLES - 1);
      run = Math.max(run, tone(ci, x));
      out[ch].push([Math.round(x * 10000) / 10000, Math.round(run * 10000) / 10000]);
    }
  });
  return out;
}

/** {r,g,b: [(x,y)×۹]} — همان `tone_points` ِ سرور (همان چیزی که به `curves` داده می‌شود) */
export function tonePoints(p: ColorParams | undefined | null, looks: LookDef[]): { r: Curve; g: Curve; b: Curve } {
  return tonePointsEff(effectiveColor(p, looks));
}

const lutCache = new Map<string, Uint8Array>();
function lutFromPoints(pts: Curve): Uint8Array {
  const key = pts.map((p) => p[1]).join(",");
  const hit = lutCache.get(key);
  if (hit) return hit;
  const f = pchip(pts);
  const lut = new Uint8Array(256);
  for (let i = 0; i < 256; i++) lut[i] = Math.round(255 * clamp01(f(i / 255)));
  if (lutCache.size > 64) lutCache.clear();
  lutCache.set(key, lut);
  return lut;
}

export function toneLuts(p: ColorParams | undefined | null, looks: LookDef[]): { r: Uint8Array; g: Uint8Array; b: Uint8Array } {
  const pts = tonePoints(p, looks);
  return { r: lutFromPoints(pts.r), g: lutFromPoints(pts.g), b: lutFromPoints(pts.b) };
}

// ─────────────────────────────────────────────────────────── prepared state
export type PostFx = { blur: number; vignette: number; grain: number; sharpen: number; denoise: number };

type HslStage = { flag: number; m: Float32Array };
type Prepared = {
  neutral: boolean;
  lutR: Uint8Array; lutG: Uint8Array; lutB: Uint8Array;
  satRR: number; satRG: number; satRB: number; satGR: number; satGG: number; satGB: number; satBR: number; satBG: number; satBB: number;
  sat: boolean;
  vib: number;
  hsl: HslStage[];
  wheels: null | { offR: Float32Array; offG: Float32Array; offB: Float32Array };
  fx: PostFx;
  float: boolean;
};

const diag = (c: Curve) => c.every(([x, y]) => Math.abs(x - y) < 0.0015);
const nz = (...v: number[]) => v.some((x) => Math.abs(x) > 1e-6);

function hueMatrix(deg: number): number[] {
  const a = (deg * Math.PI) / 180;
  const c = Math.cos(a);
  const s = Math.sin(a);
  const k = (1 - c) / 3;
  const d = s / Math.sqrt(3);
  return [c + k, k - d, k + d, k + d, c + k, k - d, k - d, k + d, c + k];
}
function mul3(a: number[], b: number[]): number[] {
  const o = new Array<number>(9).fill(0);
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) o[i * 3 + j] += a[i * 3 + k] * b[k * 3 + j];
  return o;
}
function satMatrix(k: number): number[] {
  const o = (1 - k) / 3;
  return [k + o, o, o, o, k + o, o, o, o, k + o];
}

/** وزنِ سایه/میانه/هایلایتِ colorbalance به‌ازای l = max+min (۰..۵۱۰) ⇒ جابه‌جاییِ هر کانال، پیش‌محاسبه */
function wheelTables(sh: Rgb, mid: Rgb, hi: Rgb) {
  const offR = new Float32Array(511), offG = new Float32Array(511), offB = new Float32Array(511);
  for (let i = 0; i <= 510; i++) {
    const l = i / 255;
    const wS = clamp01((0.333 - l) * 4 + 0.5);
    const wM = clamp01((l - 0.333) * 4 + 0.5) * clamp01((1 - l - 0.333) * 4 + 0.5);
    const wH = clamp01((l + 0.333 - 1) * 4 + 0.5);
    const k = 0.7 * 255;
    offR[i] = k * (sh[0] * wS + mid[0] * wM + hi[0] * wH);
    offG[i] = k * (sh[1] * wS + mid[1] * wM + hi[1] * wH);
    offB[i] = k * (sh[2] * wS + mid[2] * wM + hi[2] * wH);
  }
  return { offR, offG, offB };
}

const FLAGS: Record<HslKey, number> = { red: 0, yellow: 1, green: 2, cyan: 3, blue: 4, magenta: 5 };

function prepareEff(e: EffectiveColor): Prepared {
  const pts = tonePointsEff(e);
  const toneId = diag(pts.r) && diag(pts.g) && diag(pts.b);
  const S = e.saturation / 100;
  const sat = Math.abs(S - 1) > 1e-4;
  const k = 1 - S;
  const wr = 0.2126, wg = 0.7152, wb = 0.0722;
  const vib = Math.abs(e.vibrance) > 0.4 ? e.vibrance / 100 : 0;
  const hsl: HslStage[] = [];
  for (const key of HSL_KEYS) {
    const v = e.hsl[key];
    if (nz(v.h, v.s, v.l)) {
      const m = mul3(mul3([1 + v.l / 100, 0, 0, 0, 1 + v.l / 100, 0, 0, 0, 1 + v.l / 100], satMatrix(1 + v.s / 100)), hueMatrix(v.h));
      hsl.push({ flag: FLAGS[key], m: Float32Array.from(m) });
    }
  }
  const w = e.wheels;
  const wheels = nz(...w.shadows, ...w.mids, ...w.highs) ? wheelTables(w.shadows, w.mids, w.highs) : null;
  const fx: PostFx = {
    blur: e.blur > 0.4 ? e.blur / 100 : 0, vignette: e.vignette > 0.4 ? e.vignette / 100 : 0, grain: e.grain > 0.4 ? e.grain / 100 : 0,
    sharpen: e.sharpen > 0.4 ? e.sharpen / 100 : 0, denoise: e.denoise / 100 > 0.004 ? e.denoise / 100 : 0,
  };
  const neutral = toneId && !sat && !vib && hsl.length === 0 && !wheels && !fx.blur && !fx.vignette && !fx.grain && !fx.sharpen && !fx.denoise;
  return {
    neutral,
    lutR: lutFromPoints(pts.r), lutG: lutFromPoints(pts.g), lutB: lutFromPoints(pts.b),
    satRR: S + k * wr, satRG: k * wg, satRB: k * wb, satGR: k * wr, satGG: S + k * wg, satGB: k * wb, satBR: k * wr, satBG: k * wg, satBB: S + k * wb,
    sat, vib, hsl, wheels, fx,
    float: sat || vib !== 0 || hsl.length > 0 || !!wheels,
  };
}

const NEUTRAL = prepareEff(effectiveColor(null, []));
const byObject = new WeakMap<object, { looks: LookDef[]; prep: Prepared }>();
const byKey = new Map<string, Prepared>();

function prepare(p: ColorParams | undefined | null, looks: LookDef[]): Prepared {
  if (!p) return NEUTRAL;
  const hit = byObject.get(p);
  if (hit && hit.looks === looks) return hit.prep;
  const e = effectiveColor(p, looks);
  const key = JSON.stringify([e, e.lookCurves]);
  let prep = byKey.get(key);
  if (!prep) {
    prep = prepareEff(e);
    if (byKey.size > 24) byKey.clear();
    byKey.set(key, prep);
  }
  byObject.set(p, { looks, prep });
  return prep;
}

/** آیا رنگ اثری ندارد؟ (همان `is_neutral` ِ سرور: build_filters خالی است) */
export function colorIsNeutral(p: ColorParams | undefined | null, looks: LookDef[]): boolean {
  return !p || prepare(p, looks).neutral;
}

/** افکت‌های پس از رنگ، مقیاس ۰..۱ — کامپوزیتور محو/حذفِ نویز را با `ctx.filter` و بقیه را با `applyPostFx` می‌زند */
export function postFx(p: ColorParams | undefined | null, looks: LookDef[]): PostFx {
  return prepare(p, looks).fx;
}

/** شعاعِ محو به پیکسل (boxblur=min(w,h)·0.03·blur ⇒ تقریباً σ = ۰٫۶ شعاع) */
export function blurPx(fx: PostFx, width: number, height: number): number {
  return fx.blur > 0 ? 0.03 * fx.blur * Math.min(width, height) * 0.6 : 0;
}

// ─────────────────────────────────────────────────────────── the pixel pass
/**
 * رنگ را روی ImageData اعمال می‌کند (درجا). LUT و ماتریس‌ها با پارامترها کش می‌شوند؛ شیءِ `p` را بینِ فریم‌ها نگه دارید
 * (کش اوّل با هویتِ شیء است، بعد با مقدار). فقط-LUT ≈ ۱٫۵ms برای ۳۶۰×۶۴۰.
 */
export function applyColor(img: ImageData, p: ColorParams | undefined | null, looks: LookDef[]): void {
  const st = prepare(p, looks);
  const d = img.data;
  const lr = st.lutR, lg = st.lutG, lb = st.lutB;
  const n = d.length;
  if (!st.float) {
    for (let i = 0; i < n; i += 4) {
      d[i] = lr[d[i]];
      d[i + 1] = lg[d[i + 1]];
      d[i + 2] = lb[d[i + 2]];
    }
    return;
  }
  // نوشتن از راهِ Uint8Array (بدونِ مسیرِ کُندِ تبدیلِ double→clamped)
  const u8 = new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
  const sat = st.sat, vib = st.vib, hsl = st.hsl, wheels = st.wheels;
  const { satRR, satRG, satRB, satGR, satGG, satGB, satBR, satBG, satBB } = st;
  const vsign = vib > 0 ? 1 : -1;
  const hn = hsl.length;
  const offR = wheels ? wheels.offR : null, offG = wheels ? wheels.offG : null, offB = wheels ? wheels.offB : null;
  for (let i = 0; i < n; i += 4) {
    let r = lr[d[i]], g = lg[d[i + 1]], b = lb[d[i + 2]];
    if (sat) {
      const nr = satRR * r + satRG * g + satRB * b;
      const ng = satGR * r + satGG * g + satGB * b;
      const nb = satBR * r + satBG * g + satBB * b;
      r = nr < 0 ? 0 : nr > 255 ? 255 : nr;
      g = ng < 0 ? 0 : ng > 255 ? 255 : ng;
      b = nb < 0 ? 0 : nb > 255 ? 255 : nb;
    }
    if (vib !== 0) {
      const mx = r > g ? (r > b ? r : b) : g > b ? g : b;
      const mn = r < g ? (r < b ? r : b) : g < b ? g : b;
      const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      const k = 1 + vib * (1 + (vsign * (mx - mn)) / 255);
      const nr = y + (r - y) * k;
      const ng = y + (g - y) * k;
      const nb = y + (b - y) * k;
      r = nr < 0 ? 0 : nr > 255 ? 255 : nr;
      g = ng < 0 ? 0 : ng > 255 ? 255 : ng;
      b = nb < 0 ? 0 : nb > 255 ? 255 : nb;
    }
    for (let h = 0; h < hn; h++) {
      const stage = hsl[h];
      const m = stage.m;
      let w: number;
      switch (stage.flag) {
        case 0: w = r - (g > b ? g : b); break;
        case 1: w = (r < g ? r : g) - b; break;
        case 2: w = g - (r > b ? r : b); break;
        case 3: w = (g < b ? g : b) - r; break;
        case 4: w = b - (r > g ? r : g); break;
        default: w = (r < b ? r : b) - g;
      }
      if (w > 0) {
        w /= 255;
        const nr = r + w * (m[0] * r + m[1] * g + m[2] * b - r);
        const ng = g + w * (m[3] * r + m[4] * g + m[5] * b - g);
        const nb = b + w * (m[6] * r + m[7] * g + m[8] * b - b);
        r = nr < 0 ? 0 : nr > 255 ? 255 : nr;
        g = ng < 0 ? 0 : ng > 255 ? 255 : ng;
        b = nb < 0 ? 0 : nb > 255 ? 255 : nb;
      }
    }
    if (offR && offG && offB) {
      const mx = r > g ? (r > b ? r : b) : g > b ? g : b;
      const mn = r < g ? (r < b ? r : b) : g < b ? g : b;
      const idx = (mx + mn + 0.5) | 0;
      r += offR[idx];
      g += offG[idx];
      b += offB[idx];
    }
    u8[i] = r < 0 ? 0 : r > 255 ? 255 : (r + 0.5) | 0;
    u8[i + 1] = g < 0 ? 0 : g > 255 ? 255 : (g + 0.5) | 0;
    u8[i + 2] = b < 0 ? 0 : b > 255 ? 255 : (b + 0.5) | 0;
  }
}

// ─────────────────────────────────────────────────────────── post effects
const vigCache = new Map<string, Float32Array>();
/** هستهٔ محوِ unsharp ِ ffmpeg (۵×۵، تقریباً گاوسی؛ σ با کمترین خطا نسبت به خروجیِ واقعی انتخاب شد) */
export const SHARPEN_SIGMA = 0.9;
const SHARPEN_KERNEL = (() => {
  const g = [-2, -1, 0, 1, 2].map((j) => Math.exp(-(j * j) / (2 * SHARPEN_SIGMA * SHARPEN_SIGMA)));
  const t = g.reduce((a, b) => a + b, 0);
  return g.map((v) => v / t);
})();
let bufLum = new Float32Array(0);
let bufTmp = new Float32Array(0);
let noiseTable: Float32Array | null = null;
const NOISE_N = 1 << 18;

/** شارپ (unsharp ۵×۵ روی لوما: amount = 1.5·sharpen)، تیرگیِ لبه (cos⁴(angle·d/dmax)، angle = π/(5−3s)) و دانهٔ فیلم — درجا */
export function applyPostFx(img: ImageData, fx: PostFx, seed = 0): void {
  const { width: w, height: h, data: d } = img;
  const u8 = new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
  const px = w * h;
  if (fx.sharpen > 0) {
    const amt = 1.5 * fx.sharpen;
    if (bufLum.length < px) {
      bufLum = new Float32Array(px);
      bufTmp = new Float32Array(px);
    }
    const lum = bufLum, tmp = bufTmp;
    for (let i = 0, p = 0; p < px; i += 4, p++) lum[p] = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
    const k0 = SHARPEN_KERNEL[0], k1 = SHARPEN_KERNEL[1], k2 = SHARPEN_KERNEL[2];
    for (let y = 0; y < h; y++) {
      const row = y * w;
      for (let x = 0; x < w; x++) {
        const a = row + (x < 2 ? 0 : x - 2), b = row + (x < 1 ? 0 : x - 1), c = row + (x > w - 2 ? w - 1 : x + 1), e = row + (x > w - 3 ? w - 1 : x + 2);
        tmp[row + x] = k0 * (lum[a] + lum[e]) + k1 * (lum[b] + lum[c]) + k2 * lum[row + x];
      }
    }
    for (let y = 0; y < h; y++) {
      const r0 = (y < 2 ? 0 : y - 2) * w, r1 = (y < 1 ? 0 : y - 1) * w, r2 = y * w, r3 = (y > h - 2 ? h - 1 : y + 1) * w, r4 = (y > h - 3 ? h - 1 : y + 2) * w;
      for (let x = 0; x < w; x++) {
        const s = k0 * (tmp[r0 + x] + tmp[r4 + x]) + k1 * (tmp[r1 + x] + tmp[r3 + x]) + k2 * tmp[r2 + x];
        const delta = amt * (lum[r2 + x] - s);
        const i = (r2 + x) * 4;
        let v = d[i] + delta;
        u8[i] = v < 0 ? 0 : v > 255 ? 255 : (v + 0.5) | 0;
        v = d[i + 1] + delta;
        u8[i + 1] = v < 0 ? 0 : v > 255 ? 255 : (v + 0.5) | 0;
        v = d[i + 2] + delta;
        u8[i + 2] = v < 0 ? 0 : v > 255 ? 255 : (v + 0.5) | 0;
      }
    }
  }
  if (fx.vignette > 0) {
    const key = `${w}x${h}:${fx.vignette.toFixed(3)}`;
    let table = vigCache.get(key);
    if (!table) {
      table = new Float32Array(px);
      const angle = Math.PI / (5 - 3 * Math.max(0.1, fx.vignette));
      const cx = w / 2, cy = h / 2, dmax = Math.hypot(cx, cy);
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const dn = Math.hypot(x - cx, y - cy) / dmax;
          const c = dn > 1 ? 0 : Math.cos(angle * dn);
          table[y * w + x] = c * c * c * c;
        }
      }
      if (vigCache.size > 6) vigCache.clear();
      vigCache.set(key, table);
    }
    for (let p = 0, i = 0; p < px; p++, i += 4) {
      const f = table[p];
      u8[i] = (d[i] * f + 0.5) | 0;
      u8[i + 1] = (d[i + 1] * f + 0.5) | 0;
      u8[i + 2] = (d[i + 2] * f + 0.5) | 0;
    }
  }
  if (fx.grain > 0) {
    if (!noiseTable) {
      noiseTable = new Float32Array(NOISE_N);
      let s = 123456789;
      for (let i = 0; i < NOISE_N; i++) {
        s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
        noiseTable[i] = (s / 4294967296) * 2 - 1;
      }
    }
    const amp = 0.4 * fx.grain * 100 * 0.5;
    const off = (Math.imul(seed | 0, 7919) + 104729) & (NOISE_N - 1);
    for (let p = 0, i = 0; p < px; p++, i += 4) {
      const nv = noiseTable[(p + off) & (NOISE_N - 1)] * amp;
      let v = d[i] + nv;
      u8[i] = v < 0 ? 0 : v > 255 ? 255 : (v + 0.5) | 0;
      v = d[i + 1] + nv;
      u8[i + 1] = v < 0 ? 0 : v > 255 ? 255 : (v + 0.5) | 0;
      v = d[i + 2] + nv;
      u8[i + 2] = v < 0 ? 0 : v > 255 ? 255 : (v + 0.5) | 0;
    }
  }
}

// ─────────────────────────────────────────────────────────── helpers for the panel
/** فقط مقدارهای غیرپیش‌فرض را نگه می‌دارد (JSONِ پروژه کوچک بماند)؛ اگر چیزی نماند `undefined` */
export function compactColor(p: ColorParams | undefined | null): ColorParams | undefined {
  if (!p) return undefined;
  const c = cleanColor(p);
  const out: ColorParams = {};
  for (const k of SLIDER_KEYS) if (Math.abs(c[k] - SLIDERS[k][2]) > 1e-6) (out as Record<string, number>)[k] = c[k];
  const wheels: ColorParams["wheels"] = {};
  for (const z of ZONES) if (nz(...c.wheels[z])) wheels[z] = c.wheels[z];
  if (Object.keys(wheels).length) out.wheels = wheels;
  const curves: NonNullable<ColorParams["curves"]> = {};
  for (const k of CURVE_KEYS) if (!isIdentity(c.curves[k])) curves[k] = c.curves[k];
  if (Object.keys(curves).length) out.curves = curves;
  const hsl: NonNullable<ColorParams["hsl"]> = {};
  for (const k of HSL_KEYS) if (nz(c.hsl[k].h, c.hsl[k].s, c.hsl[k].l)) hsl[k] = c.hsl[k];
  if (Object.keys(hsl).length) out.hsl = hsl;
  if (c.look) {
    out.look = c.look;
    if (c.look_amount !== 100) out.look_amount = c.look_amount;
  }
  return Object.keys(out).length ? out : undefined;
}

/** ردهٔ چرخ: (x,y) در دایرهٔ واحد ⇒ [r,g,b] (جمعِ صفر)، و برعکس. `AMAX` بیشینهٔ جابه‌جاییِ هر کانال در لبهٔ چرخ */
export const WHEEL_AMAX = 0.35;
export function wheelToRgb(x: number, y: number): Rgb {
  const rho = Math.min(1, Math.hypot(x, y));
  const th = Math.atan2(y, x);
  const a = rho * WHEEL_AMAX;
  const rad = Math.PI / 180;
  return [a * Math.cos(th), a * Math.cos(th - 120 * rad), a * Math.cos(th + 120 * rad)].map((v) => Math.round(v * 10000) / 10000) as Rgb;
}
export function rgbToWheel(c: Rgb): [number, number] {
  const rad = Math.PI / 180;
  const re = c[0] + c[1] * Math.cos(120 * rad) + c[2] * Math.cos(-120 * rad);
  const im = c[1] * Math.sin(120 * rad) + c[2] * Math.sin(-120 * rad);
  const k = 2 / 3 / WHEEL_AMAX;
  return [re * k, im * k];
}
