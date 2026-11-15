// AUTO-FIT text: wrap + shrink-to-fit by MEASURING the real font (canvas measureText = the same shaping engine as the page, so Persian
// joins and widths are right). A text that does not fit its box is made smaller, never allowed to overflow.
import React from "react";
import { fontStack, useCtx } from "./ctx";
import type { Ctx } from "./ctx";
import { T } from "./text";
import type { TProps } from "./text";
import { hasArabic, toEnDigits, toFaDigits } from "./util";

let _cx: CanvasRenderingContext2D | null = null;
function cx(): CanvasRenderingContext2D | null {
  if (_cx) return _cx;
  try {
    _cx = document.createElement("canvas").getContext("2d");
  } catch {
    _cx = null;
  }
  return _cx;
}

const cache = new Map<string, number>();

export function textWidth(text: string, font: string, rtl: boolean): number {
  const key = `${(globalThis as any).__NM_FONTS_READY ? 1 : 0}|${font}|${rtl ? 1 : 0}|${text}`;     // a width measured with a fallback font must not survive the real font
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const c = cx();
  let w: number;
  if (c) {
    c.font = font;
    (c as any).direction = rtl ? "rtl" : "ltr";
    w = c.measureText(text).width;
  } else {
    w = Array.from(text).length * parseFloat(font.match(/([\d.]+)px/)?.[1] || "16") * 0.55;     // no canvas (never in a browser): a rough width
  }
  if (cache.size > 4000) cache.clear();
  cache.set(key, w);
  return w;
}

export type FitOpts = {
  text: string;
  stack: string;            // CSS font-family list
  weight: number;
  lh: number;               // line-height (x font size)
  boxW: number; boxH: number;   // px of the composition
  max: number; min: number;     // font size range (px)
  maxLines?: number;
  rtl?: boolean;
  wordPad?: number;         // extra width per word in em (effects that draw a box around each word)
  upper?: boolean;
};
export type FitResult = { size: number; lines: string[]; width: number; height: number; fits: boolean };

export function wrapWords(text: string, font: string, maxW: number, rtl: boolean, wordPadPx = 0): { lines: string[]; width: number } {
  const lines: string[] = [];
  let widest = 0;
  const space = textWidth(" ", font, rtl);
  for (const para of text.split(/\n+/)) {
    const words = para.split(/[ \t]+/).filter(Boolean);
    let cur = "", curW = 0;
    for (const w of words) {
      const ww = textWidth(w, font, rtl) + wordPadPx;
      if (cur && curW + space + ww > maxW) {
        lines.push(cur);
        widest = Math.max(widest, curW);
        cur = w;
        curW = ww;
      } else {
        cur = cur ? `${cur} ${w}` : w;
        curW = cur === w ? ww : curW + space + ww;
      }
    }
    if (cur) {
      lines.push(cur);
      widest = Math.max(widest, curW);
    }
  }
  return { lines, width: widest };
}

/** the largest font size in [min, max] at which the text, wrapped to boxW, fits boxW x boxH (and maxLines) */
export function fitText(o: FitOpts): FitResult {
  const text = o.upper ? o.text.toUpperCase() : o.text;
  let size = o.max;
  let last: FitResult | null = null;
  for (let i = 0; i < 60; i++) {
    const font = `${o.weight} ${size}px ${o.stack}`;
    const { lines, width } = wrapWords(text, font, o.boxW, !!o.rtl, (o.wordPad ?? 0) * size);
    const height = lines.length * size * o.lh;
    const longest = Math.max(0, ...text.split(/[\s]+/).map((w) => textWidth(w, font, !!o.rtl) + (o.wordPad ?? 0) * size));
    const fits = longest <= o.boxW + 0.5 && height <= o.boxH + 0.5 && (!o.maxLines || lines.length <= o.maxLines);
    last = { size, lines, width, height, fits };
    if (fits || size <= o.min) break;
    size = Math.max(o.min, size * 0.95);
  }
  return last as FitResult;
}

export const prepText = (ctx: Ctx, s: string): string => {
  const raw = String(s ?? "");
  return ctx.faDigits ? toFaDigits(raw) : ctx.spec.digits === "en" ? toEnDigits(raw) : raw;
};

const WORD_BOX_FX = new Set(["cutout", "brick", "glass", "stamp", "sticker", "marker"]);

export function useFit(text: string, o: { role?: "display" | "body" | "label"; box: [number, number]; max: number; min?: number; weight?: number; lh?: number; maxLines?: number; upper?: boolean; fx?: string }) {
  const ctx = useCtx();
  const { style, u } = ctx;
  const role = o.role ?? "display";
  const f = style.font;
  const raw = prepText(ctx, text);
  const fa = hasArabic(raw);
  const latin = role === "display" ? f.latin : f.body_latin ?? "vazirmatn";
  const faKey = role === "display" ? f.fa : f.body_fa ?? "vazirmatn";
  const fx = o.fx ?? (role === "display" ? style.text.fx : style.text.body_fx ?? "plain");
  const upper = (o.upper ?? (f.case === "upper" && role !== "body")) && !fa;
  const res = fitText({
    text: raw, stack: fontStack(latin, faKey), weight: o.weight ?? (role === "display" ? f.weight : role === "label" ? 700 : 500),
    lh: o.lh ?? (role === "display" ? f.lh ?? 1.3 : 1.55),
    boxW: o.box[0] * u * 0.97, boxH: o.box[1] * u, max: o.max * u * ctx.fontScale, min: (o.min ?? 22) * u, maxLines: o.maxLines,
    rtl: fa, wordPad: WORD_BOX_FX.has(fx) ? 0.42 : 0, upper,
  });
  return { ...res, sizeU: res.size / u / ctx.fontScale, ctx };
}

export type FTProps = Omit<TProps, "size" | "maxWidth"> & {
  box: [number, number];     // max width / height in px at 1080
  max: number;               // the size wanted when everything fits (px at 1080)
  min?: number;
  maxLines?: number;
};

/** T whose size is chosen so that the text fits its box */
export const FT: React.FC<FTProps> = ({ children, box, max, min, maxLines, ...rest }) => {
  const r = useFit(String(children ?? ""), { role: rest.role, box, max, min, weight: rest.weight, lh: rest.lh, maxLines, upper: rest.upper, fx: rest.fx });
  return (
    <T {...rest} size={r.sizeU} maxWidth={box[0]}>
      {children}
    </T>
  );
};
