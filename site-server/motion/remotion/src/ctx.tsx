import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import type { Brand, Cue, Pal, Spec, StyleDef } from "./types";
import { easeOf, springOf } from "./presets";
import { brandPalette } from "./brand";
import { hasArabic, hex2rgb, mix } from "./util";
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
  safe: { top: number; right: number; bottom: number; left: number };   // px of the frame that the platform's UI covers (the layout keeps clear of it)
  platform: string;
  fonts: boolean;           // the fonts of this style are loaded: text measured now is measured right
  qa: boolean;
  cues: Cue[];              // word timings of this scene's narration (scene-local seconds)
  emphasis: string[];       // lower-case words drawn in the accent colour
  fontScale: number;        // scene token: every text of the scene grows / shrinks (auto-fit still keeps it inside its box)
  enter: string;            // the enter animation of this scene (the style's, or the scene's own)
  spring: [number, number, number];
  easeName: string;
  align: "center" | "start" | "end";
  capBand: { top: number; bottom: number };   // px kept free for the word-highlight captions track (only while this scene has narration words)
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

export { brandPalette, fitOn } from "./brand";

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

/** the display font stack of the current style (for pieces that draw their own text: captions, ticker) */
export function fontStackOf(ctx: Ctx, role: "display" | "body" = "display"): string {
  const f = ctx.style.font;
  return role === "display" ? fontStack(f.latin, f.fa) : fontStack(f.body_latin ?? "vazirmatn", f.body_fa ?? "vazirmatn");
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

/** blocks the frame until the fonts of this style are in the page. Returns true once they are (and the tree has re-rendered with them:
 *  text that was measured with a fallback font is measured again before the frame may be captured). */
export function useFonts(keys: string[]): boolean {
  const [handle] = useState(() => delayRender("nm-motion fonts", { timeoutInMilliseconds: 60000 }));
  const [ready, setReady] = useState(false);
  const released = useRef(false);
  useEffect(() => {
    let cancelled = false;
    Promise.all(keys.map(loadFontKey))
      .then(() => (document as any).fonts.ready)
      .catch(() => undefined)
      .then(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
      if (!released.current) {
        released.current = true;
        continueRender(handle);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (ready && !released.current) {
      (globalThis as any).__NM_FONTS_READY = true;
      released.current = true;
      continueRender(handle);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
  return ready;
}

// ───────────────────────────────────────────── context builder

/** the platform's UI bars in px of this frame */
export function safePx(spec: Spec, W: number, H: number): { top: number; right: number; bottom: number; left: number } {
  const s = spec.safe;
  if (!s) return { top: 0, right: 0, bottom: 0, left: 0 };
  const f = (v: any) => Math.max(0, Math.min(0.4, Number(v) || 0));
  return { top: f(s.top) * H, right: f(s.right) * W, bottom: f(s.bottom) * H, left: f(s.left) * W };
}

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
    safe: safePx(spec, W, H),
    platform: spec.platform || "",
    fonts: false,
    qa: !!spec.qa,
    cues: [],
    emphasis: [],
    fontScale: 1,
    enter: style.motion.enter,
    spring: style.motion.spring,
    easeName: "out-expo",
    align: "center",
    capBand: { top: 0, bottom: 0 },
  };
}

/** the context of ONE scene: the base context + the scene's own tokens (palette, text scale, enter / spring / ease presets, words of the narration) */
function captionBand(base: Omit<Ctx, "scene">, sc: any, nCues: number): { top: number; bottom: number } {
  const cap = base.spec.captions;
  const own = Array.isArray(sc?.overlays) && sc.overlays.some((o: any) => o && o.type === "captions");
  if (!cap?.on || !nCues || own) return { top: 0, bottom: 0 };
  const band = 230 * base.u;
  const pos = cap.position || "lower";
  return { top: pos === "upper" ? band : 0, bottom: pos === "lower" || pos === "bottom" ? band : 0 };
}

export function sceneCtx(base: Omit<Ctx, "scene">, sc: any, frames: number, index: number, count: number, fonts: boolean): Ctx {
  const t = (sc && sc.tokens) || {};
  const hex = (c: any) => (typeof c === "string" && /^#?[0-9a-fA-F]{6}$/.test(c.trim()) ? (c.startsWith("#") ? c : "#" + c) : null);
  const pal = { ...base.pal };
  const acc = hex(t.accent), txt = hex(t.text), bg = hex(t.bg);
  if (acc) pal.accent = acc;
  if (txt) pal.ink = txt;
  if (bg) { pal.bg = bg; pal.bg2 = bg; }
  const style = txt || bg || acc ? { ...base.style, palette: pal, text: { ...base.style.text, color: txt ? "ink" : base.style.text.color, body_color: txt ? "ink" : base.style.text.body_color } } : base.style;
  const fs = Math.max(0.6, Math.min(1.6, Number(t.font_scale) || 1));
  const cues = Array.isArray(sc?.cues) ? sc.cues.filter((c: any) => c && typeof c.w === "string" && Number.isFinite(c.s)) : [];
  const emphasis = (Array.isArray(sc?.emphasis) ? sc.emphasis : []).map((w: any) => String(w).trim().toLowerCase()).filter(Boolean);
  return {
    ...base, style, pal, fonts, cues, emphasis, fontScale: fs,
    scene: { index, frames, count },
    enter: typeof sc?.enter === "string" && sc.enter ? sc.enter : base.style.motion.enter,
    spring: springOf(sc?.spring) ?? base.style.motion.spring,
    easeName: typeof sc?.ease === "string" && sc.ease ? sc.ease : (typeof base.style.motion.ease === "string" && base.style.motion.ease ? base.style.motion.ease : "out-expo"),
    align: t.align === "start" || t.align === "end" ? t.align : "center",
    capBand: captionBand(base, sc, cues.length),
  };
}

export { easeOf };

export function useAsset(ref?: string | null): string | null {
  const { spec } = useCtx();
  if (!ref) return null;
  if (ref.startsWith("data:") || ref.startsWith("blob:")) return ref;
  if (ref.startsWith("asset:")) return spec.assets?.[ref.slice(6)] ?? null;
  return null;
}

export { hasArabic, hex2rgb, mix };
