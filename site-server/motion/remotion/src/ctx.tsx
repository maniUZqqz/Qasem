import React, { createContext, useContext, useEffect, useState } from "react";
import { continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brand, Pal, Spec, StyleDef } from "./types";
import { contrast, hasArabic, hex2rgb, lum, mix, shade } from "./util";
import FONTS from "./fonts.generated.json";

export type Ctx = {
  style: StyleDef;
  spec: Spec;
  W: number; H: number; fps: number;
  u: number;                // min(W,H)/1080: every size in the engine is written for a 1080 short side
  wide: boolean;
  rtl: boolean;             // the video is Persian
  faDigits: boolean;
  pal: Pal;                 // style palette + brand colours
  intensity: number;
  scene: { index: number; frames: number; count: number };
};

export const CtxC = createContext<Ctx | null>(null);
export function useCtx(): Ctx {
  const c = useContext(CtxC);
  if (!c) throw new Error("nm-motion: no style context (render inside <Template>)");
  return c;
}

/** frame of the current scene, quantised for stop-motion styles (stepFps) */
export function useQF(): number {
  const f = useCurrentFrame();
  const { style, fps } = useCtx();
  const s = style.motion.stepFps;
  if (!s) return f;
  const step = Math.max(1, fps / s);
  return Math.floor(f / step) * step;
}

// ───────────────────────────────────────────── brand colours on top of the style palette

export function brandPalette(pal: Pal, brand?: Brand): Pal {
  if (!brand || brand.use_brand_colors === false) return pal;
  const cols = (brand.colors || []).filter((c) => /^#?[0-9a-fA-F]{6}$/.test((c || "").trim())).map((c) => (c.startsWith("#") ? c : "#" + c));
  if (!cols.length) return pal;
  const out = { ...pal };
  const fit = (c: string) => {
    // keep the accent readable on this style's background
    if (contrast(c, pal.bg) >= 2.2) return c;
    return lum(pal.bg) > 0.4 ? shade(c, -0.45) : shade(c, 0.45);
  };
  out.accent = fit(cols[0]);
  if (cols[1]) out.accent2 = fit(cols[1]);
  if (cols[2]) out.accent3 = fit(cols[2]);
  return out;
}

// ───────────────────────────────────────────── fonts

type FontEntry = { family: string; files: { w: number; url: string; subset: string; ur?: string; fmt?: string }[] };
const MANIFEST = FONTS as unknown as { [k: string]: FontEntry };

export function fontFamily(key: string): string {
  return MANIFEST[key]?.family ?? key;
}
const q = (f: string) => (/^[a-z-]+$/i.test(f) && !f.includes(" ") ? f : `"${f}"`);

/** font-family stack: per glyph the browser falls back from the Latin display font to the Persian one */
export function fontStack(latin: string, fa: string): string {
  return [fontFamily(latin), fontFamily(fa), fontFamily("vazirmatn"), "sans-serif"].map(q).join(", ");
}

export function fontUrl(rel: string): string {
  const base = (globalThis as any).__NM_FONT_BASE as string | undefined;
  return base ? base + rel.replace(/^fonts\//, "") : staticFile(rel);
}

const LOADED: { [k: string]: Promise<void> } = {};
export function loadFontKey(key: string): Promise<void> {
  const e = MANIFEST[key];
  if (!e) return Promise.resolve();
  if (!LOADED[key]) {
    LOADED[key] = Promise.all(
      e.files.map(async (f) => {
        try {
          const face = new FontFace(e.family, `url(${fontUrl(f.url)}) format("${f.fmt || "woff2"}")`, { weight: String(f.w), display: "block", unicodeRange: f.ur || "U+0-10FFFF" } as any);
          await face.load();
          (document as any).fonts.add(face);
        } catch (err) {
          // a missing font must never stop a render: the stack falls back to Vazirmatn
          // eslint-disable-next-line no-console
          console.warn("nm-motion: font failed", key, f.url, String(err));
        }
      }),
    ).then(() => undefined);
  }
  return LOADED[key];
}

export function fontKeysOf(style: StyleDef): string[] {
  const f = style.font;
  return Array.from(new Set([f.latin, f.fa, f.body_latin, f.body_fa, "vazirmatn"].filter(Boolean) as string[]));
}

/** blocks the frame until the fonts of this style are in the page */
export function useFonts(keys: string[]): void {
  const [handle] = useState(() => delayRender("nm-motion fonts", { timeoutInMilliseconds: 60000 }));
  useEffect(() => {
    let done = false;
    Promise.all(keys.map(loadFontKey))
      .then(() => (document as any).fonts.ready)
      .catch(() => undefined)
      .then(() => {
        if (!done) {
          done = true;
          continueRender(handle);
        }
      });
    return () => {
      if (!done) {
        done = true;
        continueRender(handle);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

// ───────────────────────────────────────────── context builder

export function buildCtx(style: StyleDef, spec: Spec, W: number, H: number, fps: number): Omit<Ctx, "scene"> {
  const rtl = (spec.lang || "fa") === "fa";
  const digits = spec.digits || "auto";
  return {
    style, spec, W, H, fps,
    u: Math.min(W, H) / 1080,
    wide: W > H * 1.2,
    rtl,
    faDigits: digits === "fa" || (digits === "auto" && rtl),
    pal: brandPalette(style.palette, spec.brand),
    intensity: Math.max(0.4, Math.min(1.8, spec.intensity ?? 1)),
  };
}

export function useAsset(ref?: string | null): string | null {
  const { spec } = useCtx();
  if (!ref) return null;
  if (ref.startsWith("data:") || ref.startsWith("blob:")) return ref;
  if (ref.startsWith("asset:")) return spec.assets?.[ref.slice(6)] ?? null;
  return null;
}

export { hasArabic, hex2rgb, mix };
