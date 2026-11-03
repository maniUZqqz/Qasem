/**
 * کلیدفریم‌ها، منحنیِ سرعت (speed ramp) و کم‌کردنِ خودکارِ موسیقی — همان ریاضیاتِ سرور
 * (backend/services/editing/keyframes.py, timeline.py: ramp_speeds, audiofx.py: duck_gain_at)
 * تا پیش‌نمایشِ فوری با رندرِ نهایی یکی باشد.
 */
export type Easing = "linear" | "ease_in" | "ease_out" | "ease_in_out" | "hold";
export type Key = { t: number; v: number; e: Easing };
export type KfChannel = "px" | "py" | "scale" | "rot" | "opacity" | "volume" | "crop_l" | "crop_r" | "crop_t" | "crop_b";
export type Kf = Partial<Record<KfChannel, Key[]>>;

export const EASINGS: { key: Easing; title: string }[] = [
  { key: "linear", title: "خطی" },
  { key: "ease_in", title: "شروعِ آرام" },
  { key: "ease_out", title: "پایانِ آرام" },
  { key: "ease_in_out", title: "آرام در دو سو" },
  { key: "hold", title: "ثابت (پرش)" },
];

/** بازهٔ مجازِ هر کانال (همان clean_keys سرور) */
export const KF_RANGE: Record<KfChannel, [number, number]> = {
  px: [-2, 2], py: [-2, 2], scale: [0.05, 8], rot: [-720, 720], opacity: [0, 1], volume: [0, 3],
  crop_l: [0, 0.95], crop_r: [0, 0.95], crop_t: [0, 0.95], crop_b: [0, 0.95],
};
export const KF_TITLE: Record<KfChannel, string> = {
  px: "جابه‌جایی افقی", py: "جابه‌جایی عمودی", scale: "اندازه", rot: "چرخش", opacity: "شفافیت", volume: "بلندی صدا",
  crop_l: "برش چپ", crop_r: "برش راست", crop_t: "برش بالا", crop_b: "برش پایین",
};
export const MAX_KEYS = 24;

export function ease(kind: Easing, u: number): number {
  const x = u < 0 ? 0 : u > 1 ? 1 : u;
  if (kind === "ease_in") return x * x;
  if (kind === "ease_out") return x * (2 - x);
  if (kind === "ease_in_out") return x * x * (3 - 2 * x);
  if (kind === "hold") return 0;
  return x;
}

export function valueAt(keys: Key[] | undefined, t: number, dflt: number): number {
  if (!keys || keys.length === 0) return dflt;
  if (t <= keys[0].t) return keys[0].v;
  for (let i = 0; i + 1 < keys.length; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (t < b.t) return a.v + (b.v - a.v) * ease(a.e, (t - a.t) / Math.max(1e-9, b.t - a.t));
  }
  return keys[keys.length - 1].v;
}

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

/** کلیدی را در زمانِ `t` (نسبت به شروعِ قطعه) می‌گذارد یا اگر نزدیکش هست جایگزین می‌کند. */
export function setKey(keys: Key[] | undefined, t: number, v: number, ch: KfChannel, e: Easing = "linear"): Key[] {
  const [lo, hi] = KF_RANGE[ch];
  const val = Math.round(clamp(v, lo, hi) * 10000) / 10000;
  const tt = Math.max(0, Math.round(t * 1000) / 1000);
  const rest = (keys ?? []).filter((k) => Math.abs(k.t - tt) > 0.02);
  const old = (keys ?? []).find((k) => Math.abs(k.t - tt) <= 0.02);
  const next = [...rest, { t: tt, v: val, e: old?.e ?? e }].sort((a, b) => a.t - b.t);
  return next.slice(0, MAX_KEYS);
}

export function removeKey(keys: Key[] | undefined, t: number): Key[] {
  return (keys ?? []).filter((k) => Math.abs(k.t - t) > 0.02);
}

export function keyNear(keys: Key[] | undefined, t: number, tol = 0.04): Key | undefined {
  return (keys ?? []).find((k) => Math.abs(k.t - t) <= tol);
}

/** برای برشِ قطعه: کلیدها نسبت به `t0` از نو می‌شوند؛ در دو لبه کلیدِ تازه با مقدارِ دقیق می‌آید و بخشِ «نرم»ی که وسطش بریده شده با چند کلیدِ خطی نمونه‌برداری می‌شود (همان keyframes.py: sliced). */
export function sliceKeys(keys: Key[] | undefined, t0: number, t1: number): Key[] | undefined {
  if (!keys || keys.length === 0) return undefined;
  const pts: { t: number; v: number; e: Easing }[] = [];
  const prev = [...keys].reverse().find((k) => k.t <= t0);
  const startEase: Easing = prev?.e ?? "linear";
  const inner = keys.filter((k) => k.t > t0 && k.t < t1);
  const run = (a: number, b: number, kind: Easing) => {
    if (kind === "linear" || kind === "hold" || b - a < 0.05) return;
    for (let i = 1; i <= 5; i++) {
      const t = a + ((b - a) * i) / 6;
      pts.push({ t, v: valueAt(keys, t, keys[0].v), e: "linear" });
    }
  };
  const softStart = startEase !== "linear" && startEase !== "hold";
  pts.push({ t: t0, v: valueAt(keys, t0, keys[0].v), e: softStart ? "linear" : startEase });
  if (softStart) run(t0, inner.length ? inner[0].t : t1, startEase);
  inner.forEach((k, i) => {
    const last = i + 1 === inner.length;
    const soft = last && k.e !== "linear" && k.e !== "hold";
    pts.push({ t: k.t, v: k.v, e: soft ? "linear" : k.e });
    if (soft) run(k.t, t1, k.e);
  });
  pts.push({ t: t1, v: valueAt(keys, t1, keys[keys.length - 1].v), e: "linear" });
  pts.sort((x, y) => x.t - y.t);
  return pts.slice(0, MAX_KEYS).map((p) => ({ t: Math.round((p.t - t0) * 1000) / 1000, v: Math.round(p.v * 10000) / 10000, e: p.e }));
}

export function shiftKeys(keys: Key[] | undefined, dt: number): Key[] | undefined {
  return keys && keys.length ? keys.map((k) => ({ ...k, t: Math.max(0, Math.round((k.t + dt) * 1000) / 1000) })) : keys;
}

// ───────────── منحنیِ سرعت
export type RampKey = { p: number; v: number };
export const RAMP_STEPS = 16;

/** سرعتِ هر یک از ۱۶ تکهٔ مساویِ بازهٔ منبع (خطی بینِ کلیدها) — همان ramp_speeds ِ سرور */
export function rampSpeeds(ramp: RampKey[]): number[] {
  const keys = [...ramp].sort((a, b) => a.p - b.p);
  const out: number[] = [];
  for (let i = 0; i < RAMP_STEPS; i++) {
    const p = (i + 0.5) / RAMP_STEPS;
    let v = keys[keys.length - 1].v;
    if (p <= keys[0].p) v = keys[0].v;
    else if (p < keys[keys.length - 1].p) {
      for (let k = 0; k + 1 < keys.length; k++) {
        if (keys[k].p <= p && p <= keys[k + 1].p) {
          const u = (p - keys[k].p) / Math.max(1e-9, keys[k + 1].p - keys[k].p);
          v = keys[k].v + (keys[k + 1].v - keys[k].v) * u;
          break;
        }
      }
    }
    out.push(clamp(v, 0.1, 8));
  }
  return out;
}

/** سرعتِ منحنی در نقطهٔ `p` (۰..۱) از بازهٔ منبع (برای نمودار) */
export function rampValueAt(ramp: RampKey[], p: number): number {
  const keys = [...ramp].sort((a, b) => a.p - b.p);
  if (p <= keys[0].p) return keys[0].v;
  for (let k = 0; k + 1 < keys.length; k++) {
    if (p <= keys[k + 1].p) return keys[k].v + (keys[k + 1].v - keys[k].v) * ((p - keys[k].p) / Math.max(1e-9, keys[k + 1].p - keys[k].p));
  }
  return keys[keys.length - 1].v;
}

/** بخشی از منحنی که بینِ کسرهای a..b می‌افتد، دوباره روی ۰..۱ (برای تقسیمِ قطعهٔ دارای ramp) */
export function sliceRamp(ramp: RampKey[], a: number, b: number): RampKey[] {
  const span = Math.max(1e-9, b - a);
  const inner = ramp.filter((k) => k.p > a && k.p < b).map((k) => ({ p: (k.p - a) / span, v: k.v }));
  return [{ p: 0, v: rampValueAt(ramp, a) }, ...inner, { p: 1, v: rampValueAt(ramp, b) }];
}

// ───────────── کم‌کردنِ موسیقی زیرِ گفتار (audiofx.py: duck_gain_at)
export type Span = [number, number];

export function duckGainAt(spans: Span[], amountDb: number, attackS: number, releaseS: number, t: number): number {
  const g = Math.pow(10, -amountDb / 20);
  const atk = Math.max(0.005, attackS);
  const rel = Math.max(0.05, releaseS);
  let env = 0;
  for (const [s, e] of spans) {
    const up = clamp((t - (s - atk)) / atk, 0, 1);
    const down = clamp((e + rel - t) / rel, 0, 1);
    env = Math.max(env, Math.min(up, down));
  }
  return 1 - (1 - g) * env;
}
