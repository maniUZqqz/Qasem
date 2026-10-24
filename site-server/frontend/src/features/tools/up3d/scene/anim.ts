import type { Ease, KeyFrame, Transform, Vec3 } from "../types";

/**
 * ریاضیِ کلیدهای ویرایشگرِ آزاد — عیناً همان up3d/keys.py (پنل) و engine/up3d_engine/keys.py (Blender)،
 * تا آن‌چه در مرورگر پخش می‌شود همان باشد که رندر می‌شود.
 *
 * ease ِ هر کلید = گذار از همین کلید تا کلیدِ بعدی:
 *   smooth آرام-آرام · linear یکنواخت · ease_in آرام شروع · ease_out آرام پایان · step پله · auto منحنیِ پیوسته (Catmull-Rom)
 */

export const EASES: { id: Ease; fa: string }[] = [
  { id: "smooth", fa: "نرم (آرام شروع و پایان)" },
  { id: "auto", fa: "منحنیِ پیوسته (برای مسیرِ دوربین)" },
  { id: "linear", fa: "یکنواخت" },
  { id: "ease_in", fa: "آرام شروع" },
  { id: "ease_out", fa: "آرام پایان" },
  { id: "step", fa: "پله‌ای (پرش)" },
];

export function ease(kind: Ease | undefined, u0: number): number {
  const u = u0 < 0 ? 0 : u0 > 1 ? 1 : u0;
  switch (kind) {
    case "linear":
    case "auto":
      return u;
    case "ease_in":
      return u * u * u;
    case "ease_out":
      return 1 - (1 - u) ** 3;
    case "step":
      return 0;
    default:
      return u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2;
  }
}

type Chan = "pos" | "rot" | "scale" | "target";

function catmull(a: number, b: number, c: number, d: number, u: number): number {
  const u2 = u * u;
  const u3 = u2 * u;
  return 0.5 * (2 * b + (-a + c) * u + (2 * a - 5 * b + 4 * c - d) * u2 + (-a + 3 * b - 3 * c + d) * u3);
}

/** مقدارِ برداریِ یک کانال در زمانِ t (ثانیه). */
export function sampleVec(keys: KeyFrame[] | undefined, t: number, ch: Chan, def: Vec3): Vec3 {
  const ks = (keys || []).filter((k) => k[ch] != null);
  if (!ks.length) return def;
  if (t <= ks[0].t) return ks[0][ch] as Vec3;
  const last = ks[ks.length - 1];
  if (t >= last.t) return last[ch] as Vec3;
  let i = 0;
  while (i + 1 < ks.length - 1 && ks[i + 1].t <= t) i++;
  const a = ks[i];
  const b = ks[i + 1];
  const u = (t - a.t) / (b.t - a.t || 1e-9);
  const A = a[ch] as Vec3;
  const B = b[ch] as Vec3;
  if ((a.ease || "smooth") === "auto") {
    const P0 = (i > 0 ? ks[i - 1][ch] : A) as Vec3;
    const P3 = (i + 2 < ks.length ? ks[i + 2][ch] : B) as Vec3;
    return [0, 1, 2].map((j) => catmull(P0[j], A[j], B[j], P3[j], u)) as Vec3;
  }
  const w = ease(a.ease, u);
  return [A[0] + (B[0] - A[0]) * w, A[1] + (B[1] - A[1]) * w, A[2] + (B[2] - A[2]) * w];
}

export function sampleNum(keys: KeyFrame[] | undefined, t: number, def: number): number {
  const ks = (keys || []).filter((k) => k.lens != null);
  if (!ks.length) return def;
  if (t <= ks[0].t) return ks[0].lens as number;
  const last = ks[ks.length - 1];
  if (t >= last.t) return last.lens as number;
  let i = 0;
  while (i + 1 < ks.length - 1 && ks[i + 1].t <= t) i++;
  const a = ks[i];
  const b = ks[i + 1];
  const u = (t - a.t) / (b.t - a.t || 1e-9);
  if ((a.ease || "smooth") === "auto") {
    const p0 = (i > 0 ? ks[i - 1].lens : a.lens) as number;
    const p3 = (i + 2 < ks.length ? ks[i + 2].lens : b.lens) as number;
    return catmull(p0, a.lens as number, b.lens as number, p3, u);
  }
  return (a.lens as number) + ((b.lens as number) - (a.lens as number)) * ease(a.ease, u);
}

export const IDENTITY: Transform = { pos: [0, 0, 0], rot: [0, 0, 0], scale: [1, 1, 1] };

/** جای شیء در زمانِ t: کلیدها (کانالِ بی‌کلید از base). */
export function transformAt(base: Transform, keys: KeyFrame[] | undefined, t: number): Transform {
  if (!keys || !keys.length) return base;
  return {
    pos: sampleVec(keys, t, "pos", base.pos),
    rot: sampleVec(keys, t, "rot", base.rot),
    scale: sampleVec(keys, t, "scale", base.scale),
  };
}

/** چرخشِ تازه را نزدیکِ قبلی نگه می‌دارد (۱۷۰ ⇐ -۱۷۰ نشود ۳۴۰ درجه چرخش). */
export function unwrapRot(rot: Vec3, near: Vec3 | undefined): Vec3 {
  if (!near) return rot;
  return rot.map((a, i) => a + Math.round((near[i] - a) / 360) * 360) as Vec3;
}

// ───────────────────────── دوربین: لنز ⇐ زاویهٔ دید (همان sensor ِ camera.py)

/** ارتفاعِ سنسور: قابِ عمودی ۳۶mm، افقی ۲۴mm (fit = VERTICAL) */
export function sensorFor(aspect: string): number {
  const [a, b] = aspect.split(":").map(Number);
  return b >= a ? 36 : 24;
}

export function lensToFovY(lens: number, aspect: string): number {
  return (2 * Math.atan(sensorFor(aspect) / 2 / lens) * 180) / Math.PI;
}

export function fovYToLens(fovDeg: number, aspect: string): number {
  return sensorFor(aspect) / 2 / Math.tan((fovDeg * Math.PI) / 360);
}

export function aspectRatio(aspect: string): number {
  const [a, b] = aspect.split(":").map(Number);
  return a / b || 9 / 16;
}

export const round3 = (v: number) => Math.round(v * 1000) / 1000;
export const roundVec = (v: Vec3): Vec3 => [round3(v[0]), round3(v[1]), round3(v[2])];
export const rad = (d: number) => (d * Math.PI) / 180;
export const deg = (r: number) => (r * 180) / Math.PI;

export function smootherstep(u0: number): number {
  const u = Math.max(0, Math.min(1, u0));
  return u * u * u * (u * (u * 6 - 15) + 10);
}
