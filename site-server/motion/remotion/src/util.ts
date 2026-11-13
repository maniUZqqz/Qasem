import { random } from "remotion";
import type { Pal } from "./types";

/** palette name ("accent") or a literal colour ("#fff", "rgba(...)", "transparent") -> CSS colour */
export function col(pal: Pal, name: string | undefined, fallback = "#000"): string {
  if (!name) return fallback;
  return (pal as any)[name] ?? name;
}

export function hex2rgb(h: string): [number, number, number] {
  let s = (h || "").trim();
  if (s.startsWith("rgb")) {
    const m = s.match(/[\d.]+/g) || ["0", "0", "0"];
    return [Number(m[0]), Number(m[1]), Number(m[2])];
  }
  s = s.replace("#", "");
  if (s.length === 3) s = s.split("").map((c) => c + c).join("");
  const n = parseInt(s.slice(0, 6) || "0", 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function rgba(h: string, a: number): string {
  const [r, g, b] = hex2rgb(h);
  return `rgba(${r},${g},${b},${a})`;
}

export function toHex(r: number, g: number, b: number): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

export function mix(a: string, b: string, t: number): string {
  const x = hex2rgb(a), y = hex2rgb(b);
  return toHex(x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t);
}

export function lum(h: string): number {
  const [r, g, b] = hex2rgb(h).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const la = lum(a), lb = lum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** readable text colour on a background */
export function onColor(bg: string, light = "#ffffff", dark = "#111111"): string {
  return lum(bg) > 0.42 ? dark : light;
}

export function shade(h: string, t: number): string {
  return t >= 0 ? mix(h, "#ffffff", t) : mix(h, "#000000", -t);
}

export const R = (seed: string | number): number => random(String(seed));

export function pick<T>(arr: T[], seed: string | number): T {
  return arr[Math.floor(R(seed) * arr.length) % arr.length];
}

export function clamp(v: number, a = 0, b = 1): number {
  return Math.max(a, Math.min(b, v));
}

export const hasArabic = (s: string): boolean => /[؀-ۿݐ-ݿ]/.test(s || "");

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export function toFaDigits(s: string): string {
  return String(s).replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)]);
}
export function toEnDigits(s: string): string {
  return String(s).replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d))).replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x660));
}

export function fmtNumber(n: number, fa: boolean, decimals = 0): string {
  const fixed = n.toFixed(decimals);
  const [ip, dp] = fixed.split(".");
  const grouped = ip.replace(/\B(?=(\d{3})+(?!\d))/g, fa ? "٬" : ",");
  const out = dp ? grouped + (fa ? "٫" : ".") + dp : grouped;
  return fa ? toFaDigits(out) : out;
}

/** font size that keeps a long line inside the frame: base for <= ok chars, shrinking above */
export function fitSize(text: string, base: number, ok: number, min = 0.55): number {
  const len = Array.from(text || "").length;
  if (len <= ok) return base;
  return base * Math.max(min, Math.sqrt(ok / len));
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** the candidate colour with the best contrast on `bg` */
export function bestText(bg: string, cands: string[]): string {
  // the first candidate that is comfortably readable (style colours come first); else the best contrast
  let best = cands[0], bc = 0;
  for (const c of cands) {
    if (!/^#|^rgb/.test(c)) continue;
    const k = contrast(c, bg);
    if (k >= 4.5) return c;
    if (k > bc) { best = c; bc = k; }
  }
  return best;
}
