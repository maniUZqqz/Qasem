/**
 * ریاضیِ «برشِ قاب» (Reframe): پنجره‌ای در خودِ منبع که پیش از جا دادن (fit) بریده می‌شود.
 * همه‌چیز در این‌جا خالص (بدون DOM) است تا Compositor، رابطِ برش و آزمون‌ها از یک منبع استفاده کنند؛
 * همان ریاضیِ سرور (ffmpeg crop با عبارتِ x/y در هر فریم).
 *
 * مختصات: «کسری از منبع» (۰..۱) مگر جایی که صریحاً «پیکسل» گفته شده.
 */
import { Key, setKey, valueAt } from "./keyframes";
import type { MediaClip, Reframe } from "./model";

/** مستطیل: x,y گوشهٔ بالا-چپ؛ w,h اندازه */
export type Rect = { x: number; y: number; w: number; h: number };

/** کوچک‌ترین اندازهٔ مجازِ پنجره (کسری از پهنا/ارتفاعِ منبع) */
export const MIN_REFRAME = 0.05;

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));
const fin = (x: number, d: number) => (Number.isFinite(x) ? x : d);
const r4 = (x: number) => Math.round(x * 10000) / 10000;

/**
 * مرکزِ پنجره (کسری از منبع) در لحظهٔ `t` ِ تایم‌لاین. کلیدهای kx/ky نسبت به شروعِ قطعه‌اند (t − clip.at)؛
 * اگر نباشند cx/cy ثابت‌اند. بدونِ reframe ⇒ وسطِ منبع.
 */
export function reframeCenter(clip: Pick<MediaClip, "at" | "reframe">, t: number): [number, number] {
  const rf = clip.reframe;
  if (!rf) return [0.5, 0.5];
  const rel = t - clip.at;
  return [fin(valueAt(rf.kx, rel, rf.cx), 0.5), fin(valueAt(rf.ky, rel, rf.cy), 0.5)];
}

/**
 * پنجرهٔ بُرشِ منبع به «پیکسلِ منبع» در لحظهٔ `t` ِ تایم‌لاین (ثانیه)، برای منبعی به اندازهٔ sw×sh.
 * بدونِ `clip.reframe` کلِ منبع برمی‌گردد. اندازه به [۰٫۰۵..۱] و موقعیت به‌طوری که پنجره کاملاً داخلِ منبع بماند بریده می‌شود.
 * اگر sw=sh=1 بدهید خروجی «کسری از منبع» است.
 */
export function reframeWindow(clip: Pick<MediaClip, "at" | "reframe">, t: number, sw: number, sh: number): Rect {
  const rf = clip.reframe;
  if (!rf) return { x: 0, y: 0, w: sw, h: sh };
  const w = clamp(fin(rf.w, 1), MIN_REFRAME, 1);
  const h = clamp(fin(rf.h, 1), MIN_REFRAME, 1);
  const [cx, cy] = reframeCenter(clip, t);
  const x = clamp(cx - w / 2, 0, 1 - w);
  const y = clamp(cy - h / 2, 0, 1 - h);
  return { x: x * sw, y: y * sh, w: w * sw, h: h * sh };
}

/** کلیدِ مرکزِ پنجره (۰..۱) با آرام در دو سو. برای کلیدِ ۰..۱ از بازهٔ کانالِ «opacity» استفاده می‌شود (همان بازه). */
export function setCenterKey(keys: Key[] | undefined, rel: number, v: number): Key[] {
  return setKey(keys, rel, v, "opacity", "ease_in_out");
}

export const hasReframeKeys = (rf: Reframe | undefined): boolean => !!rf && (!!rf.kx?.length || !!rf.ky?.length);

// ───────────── نسبت‌های آماده
export type AspectKey = "free" | "9x16" | "1x1" | "4x5" | "16x9" | "frame";
export const ASPECTS: { key: AspectKey; title: string; ratio: number | null }[] = [
  { key: "free", title: "آزاد", ratio: null },
  { key: "9x16", title: "۹:۱۶", ratio: 9 / 16 },
  { key: "1x1", title: "۱:۱", ratio: 1 },
  { key: "4x5", title: "۴:۵", ratio: 4 / 5 },
  { key: "16x9", title: "۱۶:۹", ratio: 16 / 9 },
  { key: "frame", title: "هم‌اندازهٔ قاب", ratio: null },
];

/** نسبتِ پیکسلی (عرض/ارتفاع) یک پیش‌تنظیم؛ null = آزاد */
export function aspectRatio(key: AspectKey, frameAspect: number): number | null {
  if (key === "free") return null;
  if (key === "frame") return frameAspect > 0 ? frameAspect : null;
  return ASPECTS.find((a) => a.key === key)?.ratio ?? null;
}

/** بزرگ‌ترین پنجرهٔ هم‌نسبتِ `aspect` (عرض/ارتفاعِ پیکسلی) داخلِ منبعی با نسبتِ `srcAspect`؛ خروجی کسری از منبع */
export function largestWindow(aspect: number, srcAspect: number): { w: number; h: number } {
  if (!(aspect > 0) || !(srcAspect > 0)) return { w: 1, h: 1 };
  const k = aspect / srcAspect; // w/h در فضای کسری
  return k >= 1 ? { w: 1, h: 1 / k } : { w: k, h: 1 };
}

/** نسبتِ پیکسلیِ پنجره */
export const windowAspect = (rf: Pick<Reframe, "w" | "h">, srcAspect: number): number => (rf.w / Math.max(1e-6, rf.h)) * srcAspect;

/** پیش‌تنظیمی که با نسبتِ پنجره می‌خواند (۱٪ تلورانس)؛ وگرنه «آزاد» */
export function detectAspect(rf: Reframe | undefined, srcAspect: number, frameAspect: number): AspectKey {
  if (!rf || !(srcAspect > 0)) return "free";
  const a = windowAspect(rf, srcAspect);
  for (const p of ASPECTS) {
    const r = aspectRatio(p.key, frameAspect);
    if (r && Math.abs(a / r - 1) < 0.01) return p.key;
  }
  return "free";
}

/** نسبتِ w/h در «فضای کسری» برای قفلِ نسبتِ پیکسلیِ `ratio` روی منبعی با نسبتِ srcAspect (null = قفل نیست) */
export const lockK = (ratio: number | null, srcAspect: number): number | null => (ratio && srcAspect > 0 ? ratio / srcAspect : null);

/** پنجرهٔ مرکزیِ بزرگ‌ترین برای یک نسبت (کسری از منبع)؛ اگر کلِ منبع شد undefined (یعنی بدونِ reframe) */
export function centredWindow(ratio: number, srcAspect: number, prev?: Reframe): Reframe | undefined {
  const { w, h } = largestWindow(ratio, srcAspect);
  if (w >= 0.999 && h >= 0.999) return undefined;
  const keep = prev && hasReframeKeys(prev) ? { kx: prev.kx, ky: prev.ky } : {};
  return { w: r4(w), h: r4(h), cx: 0.5, cy: 0.5, ...keep };
}

// ───────────── جابه‌جایی و تغییرِ اندازه
export type Handle = "tl" | "tr" | "bl" | "br" | "t" | "b" | "l" | "r" | "body";

/** نگه‌داشتنِ مستطیل داخلِ منبع */
export function clampRect(r: Rect): Rect {
  const w = clamp(r.w, MIN_REFRAME, 1);
  const h = clamp(r.h, MIN_REFRAME, 1);
  return { x: clamp(r.x, 0, 1 - w), y: clamp(r.y, 0, 1 - h), w, h };
}

/**
 * مستطیلِ تازه وقتی دستگیرهٔ `handle` به اندازهٔ (dx,dy) (کسری از منبع) از حالتِ شروعِ `r0` کشیده شد.
 * lock = نسبتِ w/h در فضای کسری (از lockK) یا null برای آزاد.
 * قفل: گوشه‌ها با لنگرِ گوشهٔ مقابل؛ لبه‌ها «متناسب» تغییر اندازه می‌دهند (دیگر بُعد از مرکز).
 */
export function dragWindow(r0: Rect, handle: Handle, dx: number, dy: number, lock: number | null): Rect {
  if (handle === "body") return clampRect({ ...r0, x: r0.x + dx, y: r0.y + dy });
  const hasL = handle.includes("l"), hasR = handle.includes("r"), hasT = handle.includes("t"), hasB = handle.includes("b");
  const L0 = r0.x, T0 = r0.y, R0 = r0.x + r0.w, B0 = r0.y + r0.h;
  if (!lock) {
    let L = L0, T = T0, R = R0, B = B0;
    if (hasL) L = clamp(L0 + dx, 0, R0 - MIN_REFRAME);
    if (hasR) R = clamp(R0 + dx, L0 + MIN_REFRAME, 1);
    if (hasT) T = clamp(T0 + dy, 0, B0 - MIN_REFRAME);
    if (hasB) B = clamp(B0 + dy, T0 + MIN_REFRAME, 1);
    return { x: L, y: T, w: R - L, h: B - T };
  }
  const k = lock;
  const minW = Math.max(MIN_REFRAME, MIN_REFRAME * k);
  const corner = (hasL || hasR) && (hasT || hasB);
  if (corner) {
    const sx = hasL ? -1 : 1, sy = hasT ? -1 : 1;
    const ax = hasL ? R0 : L0, ay = hasT ? B0 : T0;
    const px = (hasL ? L0 : R0) + dx, py = (hasT ? T0 : B0) + dy;
    const w1 = Math.max(0, sx * (px - ax)), h1 = Math.max(0, sy * (py - ay));
    const maxW = Math.min(sx > 0 ? 1 - ax : ax, (sy > 0 ? 1 - ay : ay) * k);
    let w = Math.max(w1, h1 * k);
    w = maxW < minW ? maxW : clamp(w, minW, maxW);
    const h = w / k;
    return { x: sx > 0 ? ax : ax - w, y: sy > 0 ? ay : ay - h, w, h };
  }
  if (hasL || hasR) {
    const sx = hasL ? -1 : 1;
    const ax = hasL ? R0 : L0;
    const cy0 = r0.y + r0.h / 2;
    const w1 = sx * ((hasL ? L0 : R0) + dx - ax);
    const maxW = Math.min(sx > 0 ? 1 - ax : ax, k * 2 * Math.min(cy0, 1 - cy0));
    const w = maxW < minW ? maxW : clamp(w1, minW, maxW);
    const h = w / k;
    return { x: sx > 0 ? ax : ax - w, y: cy0 - h / 2, w, h };
  }
  const sy = hasT ? -1 : 1;
  const ay = hasT ? B0 : T0;
  const cx0 = r0.x + r0.w / 2;
  const h1 = sy * ((hasT ? T0 : B0) + dy - ay);
  const minH = minW / k;
  const maxH = Math.min(sy > 0 ? 1 - ay : ay, (2 * Math.min(cx0, 1 - cx0)) / k);
  const h = maxH < minH ? maxH : clamp(h1, minH, maxH);
  const w = h * k;
  return { x: cx0 - w / 2, y: sy > 0 ? ay : ay - h, w, h };
}

/**
 * ویرایشِ عددیِ یک فیلد (کسری): l = چپ، t = بالا، w = پهنا، h = ارتفاع.
 * چپ/بالا فقط جابه‌جا می‌کنند؛ پهنا/ارتفاع گوشهٔ بالا-چپ را نگه می‌دارند و با قفل، بُعدِ دیگر را هم‌نسبت می‌کنند.
 */
export function withNumeric(r: Rect, field: "l" | "t" | "w" | "h", v: number, lock: number | null): Rect {
  if (field === "l") return clampRect({ ...r, x: v });
  if (field === "t") return clampRect({ ...r, y: v });
  if (field === "w") {
    let w = clamp(v, MIN_REFRAME, 1 - r.x);
    let h = lock ? w / lock : r.h;
    if (lock && r.y + h > 1) { h = 1 - r.y; w = h * lock; }
    return clampRect({ x: r.x, y: r.y, w, h });
  }
  let h = clamp(v, MIN_REFRAME, 1 - r.y);
  let w = lock ? h * lock : r.w;
  if (lock && r.x + w > 1) { w = 1 - r.x; h = w / lock; }
  return clampRect({ x: r.x, y: r.y, w, h });
}

/**
 * مستطیلِ تازه ⇒ Reframe. اگر کلیدِ مرکز دارد (kx/ky)، مرکزِ تازه در لحظهٔ `rel` (ثانیه از شروعِ قطعه) کلید می‌خورد
 * (همان قراردادِ px/py)؛ وگرنه cx/cy ثابت می‌شود. کلِ منبع ⇒ undefined (بدونِ برش).
 */
export function rectToReframe(r: Rect, prev: Reframe | undefined, rel: number): Reframe | undefined {
  const c = clampRect(r);
  if (c.w >= 0.999 && c.h >= 0.999) return undefined;
  const cx = r4(c.x + c.w / 2), cy = r4(c.y + c.h / 2);
  const hasX = !!prev?.kx?.length, hasY = !!prev?.ky?.length;
  const out: Reframe = { w: r4(c.w), h: r4(c.h), cx: hasX ? prev!.cx : cx, cy: hasY ? prev!.cy : cy };
  if (hasX) out.kx = setCenterKey(prev!.kx, rel, cx);
  if (hasY) out.ky = setCenterKey(prev!.ky, rel, cy);
  return out;
}

/** بدونِ کلید: مرکزِ لحظهٔ `t` را ثابت می‌کند (برای «حذفِ همهٔ کلیدها») */
export function withoutKeys(clip: Pick<MediaClip, "at" | "reframe">, t: number): Reframe | undefined {
  const rf = clip.reframe;
  if (!rf) return undefined;
  const [cx, cy] = reframeCenter(clip, t);
  return { w: rf.w, h: rf.h, cx: r4(cx), cy: r4(cy) };
}

/** برای «جا دادنِ خودکار»: پنجرهٔ مرکزیِ هم‌نسبتِ جعبه (نسبتِ پیکسلیِ جعبهٔ قطعه روی قاب) */
export function fitToBoxWindow(boxAspect: number, srcAspect: number): Reframe | undefined {
  return centredWindow(boxAspect, srcAspect);
}
