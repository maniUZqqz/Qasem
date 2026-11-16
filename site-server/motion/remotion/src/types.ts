// Types shared by the motion engine (the Remotion bundle on the node/site AND the in-panel player).
// The catalog of styles is generated from backend/apps/motion/catalog.py (styles.generated.json) - never edited by hand.

export type Any = { [k: string]: any };

export type Pal = {
  bg: string; bg2: string; ink: string; paper: string;
  accent: string; accent2: string; accent3: string; muted: string;
};

export type StyleDef = {
  id: string;
  name_fa: string;
  name_en: string;
  inspired?: string | null;   // «الهام‌گرفته از …» - never a copy of the studio's characters, logos or assets
  group: string;
  about?: string;
  palette: Pal;
  font: {
    latin: string; fa: string; weight: number;
    body_latin?: string; body_fa?: string;
    case?: "upper" | "none"; track?: number; lh?: number; italic?: boolean;
  };
  bg: Any & { kind: string };
  bg2?: (Any & { kind: string }) | null;
  tex: (Any & { kind: string })[];
  text: Any & { fx: string };
  shape: Any;
  decor: (Any & { kind: string })[];
  motion: {
    enter: string; spring: [number, number, number]; stagger: number;
    stepFps?: number | null; wobble?: number; cam?: Any; hold?: number;
    ease?: string;            // the style's default easing preset name (presets.ts EASES); a scene's own `ease` wins
  };
  trans: { kind: string; frames: number };
  fx?: Any;
};

export type Brand = {
  name?: string;
  colors?: string[];
  logo?: string | null;          // "asset:<name>" or a data: URI
  use_brand_colors?: boolean;
  show_logo?: boolean;
};

export type Cue = { w: string; s: number; e: number };      // one spoken word: start / end in SECONDS from the start of its scene

export type Overlay = {
  type: string;                  // a component that can be an overlay (lower_third, sticker, captions, social_cta, ticker, tags, rating ...)
  at?: number;                   // seconds from the scene start (default 0)
  dur?: number;                  // seconds shown (default: until the scene ends)
  anchor?: string;               // top | upper | center | lower | bottom | top-start | top-end | bottom-start | bottom-end
  dx?: number; dy?: number;      // offset as a fraction of the safe area (-0.5..0.5)
  [k: string]: any;
};

export type Scene = {
  type: string;                  // component id (see COMPONENTS): title, list, quote, stat ... bar_chart, kinetic_title ...
  duration: number;              // seconds
  enter?: string;                // enter animation (ENTER_KINDS) instead of the style's
  exit?: string;                 // none | fade | slide | zoom | drop
  ease?: string;                 // easing preset name (presets.ts EASES)
  spring?: string;               // spring preset name (presets.ts SPRINGS)
  emphasis?: string[];           // words that are drawn in the accent colour and pop
  camera?: { move?: string; amount?: number };
  transition?: string;           // the transition into the NEXT scene
  tokens?: { accent?: string; text?: string; bg?: string; font_scale?: number; align?: string; calm?: boolean };
  overlays?: Overlay[];
  narration?: string;            // what the voice says over this scene
  cues?: Cue[];                  // word timings of the narration (filled in by the server)
  [k: string]: any;
};

export type Spec = {
  version?: number;
  style: string;
  aspect: "9:16" | "1:1" | "4:5" | "16:9";
  fps?: number;
  lang?: "fa" | "en";
  digits?: "fa" | "en" | "auto";
  brand?: Brand;
  scenes: Scene[];
  assets?: { [name: string]: string };   // name -> data: URI (filled in by the site/runner, never by the user)
  intensity?: number;                    // 0.5..1.5 motion strength
  transition?: string | null;            // override the style's transition kind
  platform?: string;                     // reels | story | tiktok | shorts | feed | youtube : which UI bars the safe area keeps clear
  safe?: { top: number; right: number; bottom: number; left: number };   // fractions of the frame (filled in by the server from platform)
  captions?: { on?: boolean; position?: string };                      // a captions track over the whole video (needs cues)
  bare?: boolean;                        // a plain black background without decoration (a clip that is laid over a picture with the screen blend)
  qa?: boolean;                          // QA mode: the page reports the geometry of every text block (console, prefix NMQA:)
};

export const ASPECTS: { [k: string]: [number, number] } = {
  "9:16": [1080, 1920],
  "1:1": [1080, 1080],
  "4:5": [1080, 1350],
  "16:9": [1920, 1080],
};
