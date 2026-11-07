import type { Operation, Params } from "../api";
import type { Adjust, Curve } from "../manual/engine";
import { EditState, defaultState, stateFromOperations } from "../manual/model";
import { cropFormatOpParams, effectiveCropFormat } from "./frame";

/**
 * مدلِ پروژهٔ ادیتورِ حرفه‌ای. غیرمخرب: عکسِ اصل دست نمی‌خورد و پروژه فقط JSON است
 * (همین شیء در `PhotoProject.data` ذخیره می‌شود).
 *
 * مختصات (قاب‌اول، `fv = 2`): همه نسبت به «بومِ نهایی» = خروجیِ مرحلهٔ قاب (پرسپکتیو ⇒ چرخش ⇒ برش ⇒ قابِ شبکه؛ بی‌قاب ⇒ خودِ
 * عکس). `cx, cy` کسری از پهنا و ارتفاعِ بوم؛ همهٔ طول‌ها (w, h, size, r, ضخامت‌ها…) کسری از «پهنای» بوم. `rot` درجه، ساعتگرد،
 * حولِ مرکزِ لایه. ماسک‌ها و ضربه‌های روتوش هم نسبت به همین بوم‌اند. لایه‌ها از پایین به بالا.
 * پروژه‌های قدیمی (بی `fv`) را سرور هنگامِ بازکردن به همین مدل کوچ می‌دهد؛ مرورگر همیشه `fv: 2` می‌زند.
 */
export type BlendMode =
  | "normal" | "multiply" | "screen" | "overlay" | "soft-light" | "hard-light" | "darken" | "lighten"
  | "color-dodge" | "color-burn" | "difference" | "exclusion" | "hue" | "saturation" | "color" | "luminosity";

export const BLEND_MODES: { value: BlendMode; label: string }[] = [
  { value: "normal", label: "عادی" },
  { value: "multiply", label: "ضرب (Multiply)" },
  { value: "screen", label: "صفحه (Screen)" },
  { value: "overlay", label: "روکش (Overlay)" },
  { value: "soft-light", label: "نور ملایم (Soft Light)" },
  { value: "hard-light", label: "نور سخت (Hard Light)" },
  { value: "darken", label: "تیره‌تر (Darken)" },
  { value: "lighten", label: "روشن‌تر (Lighten)" },
  { value: "color-dodge", label: "روشن‌کنندهٔ رنگ (Dodge)" },
  { value: "color-burn", label: "سوزاندنِ رنگ (Burn)" },
  { value: "difference", label: "تفاضل (Difference)" },
  { value: "exclusion", label: "حذف (Exclusion)" },
  { value: "hue", label: "فام (Hue)" },
  { value: "saturation", label: "اشباع (Saturation)" },
  { value: "color", label: "رنگ (Color)" },
  { value: "luminosity", label: "درخشندگی (Luminosity)" },
];

export type Pt2 = [number, number];

export type MaskSpec =
  | { type: "paint"; id: string; invert: boolean; rev: number }
  | { type: "linear"; p0: Pt2; p1: Pt2; invert: boolean }
  | { type: "radial"; c: Pt2; rx: number; ry: number; feather: number; invert: boolean };

export type LayerType = "base" | "image" | "text" | "shape" | "adjust" | "retouch" | "group" | "redeye";

type Common = {
  id: string;
  name: string;
  visible: boolean;
  locked: boolean;
  opacity: number;
  blend: BlendMode;
  mask: MaskSpec | null;
  /** عضویت در گروه (شناسهٔ لایهٔ `group`)؛ فهرست تخت است. null/نبود = سطحِ بالا. (SPEC §3) */
  parent?: string | null;
  /** بریده‌شده به لایهٔ زیرین (clipping mask): آلفای این لایه × آلفای نزدیک‌ترین لایهٔ تصویر/متن/شکل/گروهِ هم‌سطحِ پایین‌تر */
  clip?: boolean;
};

/** جلوه‌های لایه (SPEC §3): همهٔ طول‌ها کسری از پهنای بوم؛ پیش از حالتِ ترکیب/پیدایی/ماسک در خودِ لایه پخته می‌شوند.
 *  ترتیبِ کشیدن از پایین: سایه، درخشش، دورخط، پیکسل‌های لایه. */
export type FxShadow = { color: string; opacity: number; blur: number; dx: number; dy: number };
export type FxStroke = { color: string; w: number; opacity: number };
export type FxGlow = { color: string; opacity: number; blur: number; size: number };
export type LayerFx = { shadow: FxShadow | null; stroke: FxStroke | null; glow: FxGlow | null };

export type BaseLayer = Common & { type: "base" };

export type ImageLayer = Common & {
  type: "image";
  /** paint = لایهٔ نقاشی (نوبت ۵): پیکسل‌هایش در PaintStore/paint-<id>.png؛ همیشه کلِ بوم را می‌پوشاند؛ rev = شمارندهٔ ضربه‌ها برای برگشت */
  src: { kind: "asset"; asset: number } | { kind: "logo" } | { kind: "paint"; id: string; rev: number };
  cx: number;
  cy: number;
  w: number;
  rot: number;
  flip_h: boolean;
  flip_v: boolean;
  fx?: LayerFx | null;
};

export type TextStroke = { w: number; color: string } | null;
export type TextShadow = { color: string; opacity: number; blur: number; dx: number; dy: number } | null;
export type TextBox = { color: string; opacity: number; pad: number; radius: number } | null;

export type TextWarpStyle = "arc" | "wave" | "flag" | "bulge" | "rise";
/** متنِ خمیده (نوبت ۶): amount −۱..۱؛ فرمولش در gl/raster.ts › warpParams و backend textlayer.warp_params یکی است */
export type TextWarp = { style: TextWarpStyle; amount: number };

export type TextLayer = Common & {
  type: "text";
  underline?: boolean;
  strike?: boolean;
  /** حروفِ لاتین بزرگ نمایش داده می‌شود (فارسی بی‌اثر) */
  caps?: boolean;
  warp?: TextWarp | null;
  text: string;
  font: string;
  weight: number;
  size: number;
  color: string;
  align: "right" | "center" | "left";
  dir: "auto" | "rtl" | "ltr";
  line_height: number;
  letter_spacing: number;
  width: number;
  cx: number;
  cy: number;
  rot: number;
  stroke: TextStroke;
  shadow: TextShadow;
  box: TextBox;
  tile: { angle: number; gap: number } | null;
  /** خط‌های شکسته‌شده توسطِ مرورگر (خروجی همان را عیناً می‌کشد) */
  lines?: string[];
  fx?: LayerFx | null;
};

export type ShapeFill =
  | { type: "solid"; color: string; opacity: number }
  | { type: "gradient"; c0: string; c1: string; angle: number }
  | null;

/** نقطهٔ مسیرِ قلم (Pen): x,y و دستگیره‌ها در واحدِ «جعبهٔ لایه» (کسری از w و h)؛ hi = دستگیرهٔ ورودی، ho = خروجی (جابه‌جایی نسبت به نقطه) */
export type PathPt = { x: number; y: number; hi: Pt2 | null; ho: Pt2 | null };
export type ShapePath = { closed: boolean; pts: PathPt[] };

export type ShapeLayer = Common & {
  type: "shape";
  shape: "rect" | "ellipse" | "line" | "path";
  cx: number;
  cy: number;
  w: number;
  h: number;
  rot: number;
  fill: ShapeFill;
  stroke: { color: string; w: number } | null;
  radius: number;
  /** فقط وقتی shape === "path" */
  path?: ShapePath;
  fx?: LayerFx | null;
};

export type AdjustLayer = Common & { type: "adjust"; adjust: Adjust; curve: Curve };

export type Stroke = {
  mode: "clone" | "heal";
  pts: Pt2[];
  r: number;
  hardness: number;
  opacity: number;
  /** جابه‌جاییِ منبع: پیکسلِ منبع = مقصد + (dx·W, dy·H) */
  dx: number;
  dy: number;
};

export type RetouchLayer = Common & { type: "retouch"; strokes: Stroke[] };

/** گروهِ ایزوله: بچه‌ها = لایه‌هایی که parent === id (به ترتیبِ فهرست)؛ جدا ترکیب می‌شوند و بعد با پیدایی/حالت/ماسکِ گروه روی بالادستی می‌نشینند */
export type GroupLayer = Common & { type: "group"; collapsed: boolean };

/** قرمزیِ چشم: چند چشم (x,y کسری از W,H؛ r کسری از W)؛ فرمول در SPEC §3 (هم‌سانِ سرور و GLSL) */
export type RedeyeEye = { x: number; y: number; r: number };
export type RedeyeLayer = Common & { type: "redeye"; eyes: RedeyeEye[]; amount: number; darken: number };

export type Layer = BaseLayer | ImageLayer | TextLayer | ShapeLayer | AdjustLayer | RetouchLayer | GroupLayer | RedeyeLayer;

export type Quad = { tl: Pt2; tr: Pt2; br: Pt2; bl: Pt2 };

/** نسخهٔ مدلِ مختصات: ۲ = لایه‌ها نسبت به بومِ نهایی (قاب‌اول). نبودنش در داده‌ی ذخیره‌شده = نسخهٔ ۱ (لایه‌ها نسبت به عکس) */
export const FRAME_VERSION = 2;

export type ProState = EditState & {
  fv: number;
  layers: Layer[];
  persp: Quad | null;
  /** مایع‌سازی (Liquify): نشانِ نقشهٔ جابه‌جاییِ پروژه روی سرور — null/نبود = بی‌نقشه (بقیه را ابزارِ مایع‌سازی پر می‌کند) */
  liquify?: { rev: number } | null;
};

/** پایه + کارهای مشترک */
export const nid = (): string => Math.random().toString(36).slice(2, 10);

const common = (type: LayerType, name: string): Common => ({
  id: type === "base" ? "base" : nid(), name, visible: true, locked: false, opacity: 1, blend: "normal", mask: null,
});

export const makeBase = (): BaseLayer => ({ ...common("base", "عکس"), type: "base" });

export const makeText = (cx = 0.5, cy = 0.5, text = "متن شما"): TextLayer => ({
  ...common("text", "متن"), type: "text", text, font: "vazirmatn", weight: 700, size: 0.05, color: "#ffffff",
  align: "center", dir: "auto", line_height: 1.3, letter_spacing: 0, width: 0, cx, cy, rot: 0, stroke: null,
  shadow: { color: "#000000", opacity: 0.5, blur: 0.08, dx: 0.03, dy: 0.03 }, box: null, tile: null,
});

export const makeImage = (src: ImageLayer["src"], name = "تصویر"): ImageLayer => ({
  ...common("image", name), type: "image", src, cx: 0.5, cy: 0.5, w: 0.4, rot: 0, flip_h: false, flip_v: false,
});

export type PaintLayer = ImageLayer & { src: { kind: "paint"; id: string; rev: number } };
export const isPaintLayer = (l: Layer | null | undefined): l is PaintLayer => !!l && l.type === "image" && l.src.kind === "paint";
export const makePaintLayer = (paintId: string, name = "نقاشی"): PaintLayer => ({
  ...common("image", name), type: "image", src: { kind: "paint", id: paintId, rev: 0 }, cx: 0.5, cy: 0.5, w: 1, rot: 0, flip_h: false, flip_v: false,
}) as PaintLayer;

export const makeShape = (shape: ShapeLayer["shape"] = "rect"): ShapeLayer => ({
  ...common("shape", shape === "rect" ? "مستطیل" : shape === "ellipse" ? "بیضی" : "خط"), type: "shape", shape,
  cx: 0.5, cy: 0.5, w: shape === "line" ? 0.4 : 0.3, h: shape === "line" ? 0 : shape === "ellipse" ? 0.3 : 0.18, rot: 0,
  fill: shape === "line" ? null : { type: "solid", color: "#ffffff", opacity: 1 },
  stroke: shape === "line" ? { color: "#ffffff", w: 0.006 } : null, radius: 0,
});

export const makeAdjust = (name = "تنظیم", adjust: Adjust = {}): AdjustLayer => ({
  ...common("adjust", name), type: "adjust", adjust, curve: {},
});

export const makeRetouch = (): RetouchLayer => ({ ...common("retouch", "روتوش"), type: "retouch", strokes: [] });

export const makeGroup = (name = "گروه"): GroupLayer => ({ ...common("group", name), type: "group", collapsed: false });

export const makeRedeye = (eyes: RedeyeEye[] = []): RedeyeLayer => ({
  ...common("redeye", "قرمزیِ چشم"), type: "redeye", eyes, amount: 1, darken: 0.6,
});

/** لایهٔ شکلِ مسیر (قلم): مسیر در جعبهٔ w×h؛ cx,cy مرکزِ جعبه روی بوم */
export const makePathShape = (path: ShapePath, box: { cx: number; cy: number; w: number; h: number }): ShapeLayer => ({
  ...common("shape", "مسیر"), type: "shape", shape: "path", cx: box.cx, cy: box.cy, w: box.w, h: box.h, rot: 0,
  fill: { type: "solid", color: "#ffffff", opacity: 1 }, stroke: null, radius: 0, path,
});

export const LAYER_ICON: Record<LayerType, string> = {
  base: "🖼", image: "▣", text: "T", shape: "◼", adjust: "◐", retouch: "✎", group: "▤", redeye: "◉",
};

export const isTransformable = (l: Layer): l is ImageLayer | TextLayer | ShapeLayer =>
  l.type === "image" || l.type === "text" || l.type === "shape";

export const defaultProState = (): ProState => ({ ...defaultState(), fv: FRAME_VERSION, layers: [makeBase()], persp: null });

export const withBase = (s: ProState): ProState =>
  s.layers.some((l) => l.type === "base") ? s : { ...s, layers: [makeBase(), ...s.layers] };

// ───────────────────────────── از کارهای قدیمیِ یک نسخه (خودکار / نیمه‌خودکار) به لایه

const POS_Y: Record<string, number> = { top: 0.12, center: 0.5, bottom: 0.88 };
const CORNER: Record<string, [number, number]> = {
  br: [0.86, 0.88], bl: [0.14, 0.88], tr: [0.86, 0.12], tl: [0.14, 0.12], center: [0.5, 0.5],
};

/** text / logo / watermark ِ قدیمی ⇒ لایه‌های قابل‌ویرایش */
export function legacyOverlaysToLayers(tools: Record<string, Params>): Layer[] {
  const out: Layer[] = [];
  const t = tools.text;
  if (t && (t.text || t.subtext)) {
    const band = String(t.band ?? "gradient");
    const y = POS_Y[String(t.position ?? "bottom")] ?? 0.88;
    const size = (Number(t.size) || 6) / 100;
    if (t.text) {
      const l = makeText(0.5, y, String(t.text));
      l.size = size;
      l.color = String(t.color ?? "#ffffff");
      l.box = band === "box" ? { color: "#000000", opacity: 0.6, pad: 0.5, radius: 0.4 }
        : band === "light" ? { color: "#ffffff", opacity: 0.8, pad: 0.5, radius: 0.4 } : null;
      l.shadow = band === "none" || band === "gradient" ? l.shadow : null;
      l.width = 0.88;
      l.name = "متن";
      out.push(l);
    }
    if (t.subtext) {
      const l = makeText(0.5, Math.min(0.96, y + (t.text ? size * 1.6 : 0)), String(t.subtext));
      l.size = size * 0.62;
      l.weight = 400;
      l.color = String(t.color ?? "#ffffff");
      l.width = 0.88;
      l.name = "خطِ دوم";
      out.push(l);
    }
  }
  const lg = tools.logo;
  if (lg) {
    const [cx, cy] = CORNER[String(lg.position ?? "br")] ?? CORNER.br;
    const l = makeImage(lg.source === "asset" && Number(lg.asset) ? { kind: "asset", asset: Number(lg.asset) } : { kind: "logo" }, "لوگو");
    l.w = (Number(lg.size) || 18) / 100;
    l.opacity = (Number(lg.opacity) || 90) / 100;
    l.cx = cx;
    l.cy = cy;
    out.push(l);
  }
  const wm = tools.watermark;
  if (wm) {
    const tiled = wm.mode === "tiled";
    const [cx, cy] = CORNER[String(wm.position ?? "bl")] ?? CORNER.bl;
    const l = makeText(cx, cy, String(wm.text || "NMarketing"));
    l.name = "واترمارک";
    l.size = (Number(wm.size) || 4) / 100;
    l.opacity = (Number(wm.opacity) || 40) / 100;
    l.color = String(wm.color ?? "#ffffff");
    l.tile = tiled ? { angle: 28, gap: 1.6 } : null;
    out.push(l);
  }
  return out;
}

const LEGACY = new Set(["text", "logo", "watermark"]);

/** کارهای یک نسخهٔ قبلی ⇒ حالتِ حرفه‌ای (متن/لوگو/واترمارک ⇒ لایه؛ compose ⇒ لایه‌های خودش؛ develop ⇒ لغزنده‌ها) */
export function proStateFromOperations(ops: { tool: string; params: Params }[]): ProState {
  const base = stateFromOperations(ops.filter((o) => o.tool !== "compose" && o.tool !== "develop" && o.tool !== "perspective" && o.tool !== "liquify"));
  const s: ProState = { ...base, fv: FRAME_VERSION, layers: [makeBase()], persp: null };
  for (const o of ops) {
    const p = o.params ?? {};
    if (o.tool === "develop") {
      s.adjust = { ...s.adjust, ...((p.adjust as Adjust) ?? {}) };
      s.curve = { ...s.curve, ...((p.curve as Curve) ?? {}) };
      if (Array.isArray(p.spots) && p.spots.length) s.spots = [...(p.spots as EditState["spots"])];
    } else if (o.tool === "perspective") {
      const q = p as unknown as Quad;
      if (q?.tl && q?.tr && q?.br && q?.bl) s.persp = q;
    } else if (o.tool === "liquify") {
      // نقشهٔ مایع‌سازی روی سرور به پروژه بسته است (نه به این کار)؛ نشانش را نگه می‌داریم تا کارِ بعدی هم آن را بخواهد
      s.liquify = { rev: 0 };
    } else if (o.tool === "compose" && Array.isArray(p.layers)) {
      const ls = (p.layers as Layer[]).filter((l) => l && l.type);
      if (ls.length) s.layers = ls.some((l) => l.type === "base") ? ls : [makeBase(), ...ls];
    }
  }
  // «قابِ مربعِ فروشگاه» (kit_square، گرهٔ پیش از لایه‌ها) در ادیتورِ حرفه‌ای = «قابِ شبکه‌ها: مربعِ دلخواه، جا دادن، سفید»
  const ks = s.tools.kit_square;
  if (ks) {
    delete s.tools.kit_square;
    if (!s.tools.crop_format) {
      const cf = effectiveCropFormat({ kit_square: ks });
      if (cf) s.tools.crop_format = cropFormatOpParams(cf);
    }
  }
  const legacy: Record<string, Params> = {};
  for (const k of LEGACY) if (s.tools[k]) legacy[k] = s.tools[k];
  if (Object.keys(legacy).length) {
    s.layers = [...s.layers, ...legacyOverlaysToLayers(legacy)];
    for (const k of LEGACY) delete s.tools[k];
  }
  return s;
}

// ───────────────────────────── از حالت به کارهای ادیتور (قراردادِ API)

// kit_square در ادیتورِ حرفه‌ای نیست (قابِ مربع = crop_format ِ custom/contain/white)؛ برای حالتِ خودکار هنوز ابزارِ گره است
const NODE_KEYS = ["kit_preset", "kit_background", "kit_upscale", "kit_denoise", "kit_sharpen"];
const TONE_KEYS = ["auto_tone", "look", "color"];

export const hasOverlayLayers = (s: ProState) => s.layers.some((l) => l.type !== "base");
export const isDefaultQuad = (q: Quad | null) =>
  !q || (q.tl[0] === 0 && q.tl[1] === 0 && q.tr[0] === 1 && q.tr[1] === 0 && q.br[0] === 1 && q.br[1] === 1 && q.bl[0] === 0 && q.bl[1] === 1);

/**
 * ترتیبِ کارها (نسخهٔ ۲، همان `catalog.SERVER_ORDER_V2`): کارهای کیت (سرورِ پردازش) ⇐ develop (فقط ساختِ سریع) ⇐ liquify ⇐
 * perspective ⇐ rotate ⇐ crop_rect ⇐ crop_format (با `window` ِ «سوژه (خودکار)» که مرورگر حساب کرده) ⇐ ابزارهای رنگ
 * (auto_tone، look، color) ⇐ compose (لایه‌ها نسبت به بومِ نهایی) ⇐ resize ⇐ export. `opts.window` = پنجرهٔ برشِ مرورگر.
 */
export function buildProOperations(s: ProState, opts: { quick?: boolean; projectId?: number; window?: number[] | null }): Operation[] {
  const ops: Operation[] = [];
  const add = (tool: string, params: Params) => ops.push({ tool, params, on: true });
  const hasCurve = !!(s.curve.rgb || s.curve.red || s.curve.green || s.curve.blue);
  const adjustCount = Object.keys(s.adjust).length;
  // ── کارهای سرورِ پردازش (گره) — همیشه اول
  if (!opts.quick) {
    if (s.kitAuto) add("kit_auto", {});
    if (adjustCount || hasCurve) add("kit_adjust", { adjust: s.adjust, curve: s.curve });
    if (s.spots.length) add("kit_heal", { spots: s.spots });
    for (const k of NODE_KEYS) if (s.tools[k]) add(k, s.tools[k]);
  } else if (adjustCount || hasCurve || s.spots.length) {
    add("develop", { adjust: s.adjust, curve: s.curve, spots: s.spots });
  }
  // ── سرورِ سایت: قاب (هندسه ⇒ قابِ شبکه) ⇒ رنگ ⇒ لایه‌ها ⇒ اندازه ⇒ خروجی
  if (s.liquify) add("liquify", { project: opts.projectId ?? 0 });
  if (!isDefaultQuad(s.persp)) add("perspective", s.persp as unknown as Params);
  if (s.turn || s.straighten || s.flipH || s.flipV) {
    add("rotate", { turn: String(s.turn), straighten: s.straighten, flip_h: s.flipH, flip_v: s.flipV });
  }
  const c = s.crop;
  if (!(c.x <= 0.0005 && c.y <= 0.0005 && c.w >= 0.9995 && c.h >= 0.9995)) {
    const r = (v: number) => Math.round(v * 1000) / 10;
    add("crop_rect", { x: r(c.x), y: r(c.y), w: r(c.w), h: r(c.h) });
  }
  const cf = effectiveCropFormat(s.tools);
  if (cf) {
    // خودکار = پنجرهٔ «سوژه (خودکار)» (cover) یا جای دوربینِ «کالا وسطِ قاب» (contain)؛ مرورگر حساب می‌کند و همان به خروجی می‌رود
    const smart = (cf.fit === "cover" && cf.focus === "smart" && cf.window.length !== 4) || (cf.fit === "contain" && cf.subject === "auto" && cf.view.length !== 3);
    add("crop_format", cropFormatOpParams(cf, smart ? opts.window : null));
  }
  for (const k of TONE_KEYS) if (s.tools[k]) add(k, s.tools[k]);
  if (hasOverlayLayers(s) || s.layers.some((l) => l.type === "base" && (l.mask || l.opacity < 1 || l.blend !== "normal" || !l.visible))) {
    add("compose", { project: opts.projectId ?? 0, layers: s.layers });
  }
  if (s.out.long_edge > 0) add("resize", { long_edge: s.out.long_edge });
  add("export", { format: s.out.format, quality: s.out.quality, max_kb: s.out.max_kb });
  return ops;
}

export const developKeys = (s: ProState) =>
  JSON.stringify([s.adjust, s.curve, s.kitAuto, s.spots, s.tools.kit_denoise ?? null, s.tools.kit_sharpen ?? null]);

/** JSON ِ پروژه برای ذخیره — همیشه `fv: 2` می‌خورد (بی آن، سرور پروژه را «قدیمی» می‌پندارد و لایه‌ها را دوباره جابه‌جا می‌کند) */
export const serializeProject = (s: ProState): ProState => ({ ...(JSON.parse(JSON.stringify(s)) as ProState), fv: FRAME_VERSION });
