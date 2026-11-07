import type { Layer } from "./types";

/**
 * کتابخانهٔ سبک‌ها (دورِ ۸): «سبکِ لایه» (سایه، درخشش، دورخط، پیدایی، حالتِ ترکیب) و «سبکِ حرف/پاراگراف» (قلم، اندازه، رنگ، فاصله، تراز،
 * دورِ حرف، سایه، قاب…) — هر دو با یک سازوکار: ویژگی‌های لایهٔ فعال را با یک نام نگه می‌داریم و روی هر لایهٔ هم‌نوع می‌گذاریم.
 * سبک‌های ساخته‌شدهٔ کاربر در پیش‌تنظیم‌های فروشگاه (kind="style") می‌مانند؛ چند سبکِ آماده هم همراه است.
 */
export type StyleTarget = "text" | "shape" | "image" | "any";
export type StyleData = { target: StyleTarget; props: Record<string, unknown> };

export const COMMON_KEYS = ["opacity", "blend", "fx"] as const;
export const TEXT_KEYS = [
  "font", "weight", "size", "color", "align", "dir", "line_height", "letter_spacing", "stroke", "shadow", "box",
  "underline", "strike", "caps", "warp", "justify", "indent",
] as const;
export const SHAPE_KEYS = ["fill", "stroke", "radius"] as const;

/** کلیدهایی که روی لایه‌ای از این نوع مجازند */
export function allowedKeys(type: string): readonly string[] {
  if (type === "text") return [...COMMON_KEYS, ...TEXT_KEYS];
  if (type === "shape") return [...COMMON_KEYS, ...SHAPE_KEYS];
  if (type === "image") return COMMON_KEYS;
  return [];
}

const clone = <T,>(v: T): T => (v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T));

/** ویژگی‌های لایه ⇒ سبک؛ null = از این نوع لایه سبک گرفته نمی‌شود */
export function captureStyle(l: Layer | null | undefined): StyleData | null {
  if (!l || (l.type !== "text" && l.type !== "shape" && l.type !== "image")) return null;
  const props: Record<string, unknown> = {};
  for (const k of allowedKeys(l.type)) {
    const v = (l as unknown as Record<string, unknown>)[k];
    if (v !== undefined) props[k] = clone(v);
  }
  return { target: l.type, props };
}

/** سبک را روی لایه می‌گذارد ⇒ وصلهٔ ویژگی‌ها؛ null = هیچ‌چیز به این لایه نمی‌خورد */
export function styleToPatch(l: Layer | null | undefined, s: StyleData): Partial<Layer> | null {
  if (!l) return null;
  const ok = new Set(allowedKeys(l.type));
  const patch: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(s.props ?? {})) if (ok.has(k)) patch[k] = clone(v);
  if (!Object.keys(patch).length) return null;
  // متن: خط‌های شکسته‌شدهٔ قبلی دیگر معتبر نیستند
  if (l.type === "text") patch.lines = undefined;
  return patch as Partial<Layer>;
}

export type BuiltinStyle = { id: string; title: string; hint: string; style: StyleData };

const none = { shadow: null, glow: null, stroke: null };

/** سبک‌های آمادهٔ همراه (همه فقط با کلیدهای مجاز؛ طول‌ها کسری از پهنای بوم) */
export const BUILTIN_STYLES: BuiltinStyle[] = [
  { id: "b-soft-shadow", title: "سایهٔ نرم", hint: "سایهٔ ملایمِ زیرِ لایه", style: { target: "any", props: { fx: { ...none, shadow: { color: "#000000", opacity: 0.45, blur: 0.012, dx: 0.006, dy: 0.008 } } } } },
  { id: "b-hard-shadow", title: "سایهٔ سخت", hint: "سایهٔ تیز و جداشده", style: { target: "any", props: { fx: { ...none, shadow: { color: "#000000", opacity: 0.8, blur: 0, dx: 0.01, dy: 0.01 } } } } },
  { id: "b-neon", title: "درخششِ نئونی", hint: "هالهٔ فیروزه‌ای دورِ لایه", style: { target: "any", props: { fx: { ...none, glow: { color: "#22d3ee", opacity: 0.95, blur: 0.02, size: 0.008 } } } } },
  { id: "b-white-outline", title: "دورِ سفید", hint: "خطِ دورِ سفیدِ ضخیم", style: { target: "any", props: { fx: { ...none, stroke: { color: "#ffffff", w: 0.006, opacity: 1 } } } } },
  { id: "b-sticker", title: "برچسبی", hint: "دورِ سفید و سایه، مثلِ استیکر", style: { target: "any", props: { fx: { shadow: { color: "#000000", opacity: 0.35, blur: 0.01, dx: 0.004, dy: 0.006 }, glow: null, stroke: { color: "#ffffff", w: 0.008, opacity: 1 } } } } },
  { id: "b-text-sale", title: "متنِ تخفیف", hint: "متنِ سفیدِ ضخیم روی نوارِ قرمز", style: { target: "text", props: { color: "#ffffff", weight: 800, shadow: null, box: { color: "#e11d48", opacity: 1, pad: 0.4, radius: 0.35 }, letter_spacing: 0 } } },
  { id: "b-text-gold", title: "متنِ طلایی", hint: "طلایی با دورِ قهوه‌ای", style: { target: "text", props: { color: "#fbbf24", weight: 800, stroke: { w: 0.05, color: "#7c4a03" }, shadow: { color: "#000000", opacity: 0.4, blur: 0.06, dx: 0.02, dy: 0.03 }, box: null } } },
  { id: "b-text-clean", title: "متنِ تمیز", hint: "مشکیِ ساده بدونِ جلوه", style: { target: "text", props: { color: "#111827", weight: 600, stroke: null, shadow: null, box: null, letter_spacing: 0 } } },
  { id: "b-shape-glass", title: "شیشه‌ای", hint: "شکلِ سفیدِ نیمه‌شفاف با لبهٔ روشن", style: { target: "shape", props: { fill: { type: "solid", color: "#ffffff", opacity: 0.22 }, stroke: { color: "#ffffff", w: 0.003 }, opacity: 1 } } },
];
