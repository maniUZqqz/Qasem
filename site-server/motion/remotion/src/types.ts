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

export type Scene = {
  type: "title" | "list" | "quote" | "stat" | "compare" | "product" | "logo" | "app" | "cta";
  duration: number;              // seconds
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
};

export const ASPECTS: { [k: string]: [number, number] } = {
  "9:16": [1080, 1920],
  "1:1": [1080, 1080],
  "4:5": [1080, 1350],
  "16:9": [1920, 1080],
};
