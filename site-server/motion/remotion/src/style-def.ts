// Inline style definitions: a render may carry its OWN style (`spec.style_def`, a StyleDef written by the style editor, backend/apps/motion/custom.py)
// instead of one from the bundled catalog. The backend validates every field (whitelisted kinds, hex colours, number ranges); this file is the engine's
// second line of defence: it never trusts the shape, fills what is missing with the same defaults as catalog.py's S(), and returns null when the object
// cannot be a style at all (the caller then falls back to the catalogue style named by `spec.style`).
//
// PURE (no React / Remotion imports) so a plain-node test can run it.
import type { Spec, StyleDef } from "./types";

/** what this engine can do beyond the base catalogue. The node pack writes it into its FEATURES file; the node refuses a render that needs more than the pack offers. */
export const ENGINE_FEATURES = ["style_def"];

const PAL_KEYS = ["bg", "bg2", "ink", "paper", "accent", "accent2", "accent3", "muted"] as const;
const HEX = /^#[0-9a-fA-F]{6}$/;
const isObj = (v: any) => v && typeof v === "object" && !Array.isArray(v);
const num = (v: any, lo: number, hi: number, d: number) => {
  const x = Number(v);
  return Number.isFinite(x) ? Math.max(lo, Math.min(hi, x)) : d;
};
const kindList = (v: any, max: number) => (Array.isArray(v) ? v.filter((x) => isObj(x) && typeof x.kind === "string" && x.kind).slice(0, max) : []);

export function sanitizeStyleDef(d: any, fallbackId = "custom"): StyleDef | null {
  if (!isObj(d) || !isObj(d.palette) || !isObj(d.font) || !isObj(d.bg) || typeof d.bg.kind !== "string") return null;
  const palette: any = {};
  for (const k of PAL_KEYS) {
    const v = d.palette[k];
    if (typeof v !== "string" || !HEX.test(v.trim())) return null;
    palette[k] = v.trim();
  }
  const f = d.font;
  if (typeof f.latin !== "string" || typeof f.fa !== "string" || !f.latin || !f.fa) return null;
  const sp = Array.isArray(d.motion?.spring) && d.motion.spring.length === 3 ? d.motion.spring : [14, 140, 0.9];
  const m = isObj(d.motion) ? d.motion : {};
  const t = isObj(d.trans) ? d.trans : {};
  return {
    id: typeof d.id === "string" && d.id ? d.id : fallbackId,
    name_fa: String(d.name_fa || "سبکِ من"),
    name_en: String(d.name_en || "My style"),
    inspired: d.inspired ?? null,
    group: String(d.group || "graphic"),
    about: String(d.about || ""),
    palette,
    font: {
      latin: f.latin, fa: f.fa, weight: num(f.weight, 100, 900, 700),
      body_latin: typeof f.body_latin === "string" && f.body_latin ? f.body_latin : undefined,
      body_fa: typeof f.body_fa === "string" && f.body_fa ? f.body_fa : undefined,
      case: f.case === "upper" ? "upper" : "none", track: num(f.track, -0.1, 0.5, 0), lh: num(f.lh, 1, 2, 1.3), italic: !!f.italic,
    },
    bg: d.bg,
    bg2: isObj(d.bg2) && typeof d.bg2.kind === "string" ? d.bg2 : null,
    tex: kindList(d.tex, 6),
    text: isObj(d.text) && typeof d.text.fx === "string" ? d.text : { fx: "plain" },
    shape: { radius: 16, border: 0, shadow: "soft", fill: "paper", ...(isObj(d.shape) ? d.shape : {}) },
    decor: kindList(d.decor, 8),
    motion: {
      enter: typeof m.enter === "string" && m.enter ? m.enter : "pop",
      spring: [num(sp[0], 1, 80, 14), num(sp[1], 20, 400, 140), num(sp[2], 0.2, 3, 0.9)],
      stagger: num(m.stagger, 0, 40, 6),
      stepFps: m.stepFps ? num(m.stepFps, 4, 30, 12) : null,
      wobble: num(m.wobble, 0, 12, 0),
      ease: typeof m.ease === "string" && m.ease ? m.ease : undefined,
      cam: isObj(m.cam) ? m.cam : null,
    } as StyleDef["motion"],
    trans: { kind: typeof t.kind === "string" && t.kind ? t.kind : "fade", frames: Math.round(num(t.frames, 0, 40, 16)) },
    fx: isObj(d.fx) ? d.fx : {},
  };
}

/** the style a spec is drawn with: its own `style_def` when it carries a usable one, else the catalogue's `getStyle(spec.style)` */
export function resolveStyle(spec: Spec, getStyle: (id: string) => StyleDef): StyleDef {
  const own = (spec as any).style_def;
  if (own) {
    const s = sanitizeStyleDef(own, spec.style || "custom");
    if (s) return s;
  }
  return getStyle(spec.style);
}
