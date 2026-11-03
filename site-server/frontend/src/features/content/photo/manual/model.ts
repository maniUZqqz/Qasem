import type { Operation, Params, Tool } from "../api";
import type { Adjust, Curve } from "./engine";

/**
 * حالتِ یک ویرایشِ دستی. همه‌چیز «غیرمخرب» است: اصلِ عکس دست نمی‌خورد، این شیء فقط فهرستِ کارهاست و با
 * `buildOperations` همان قراردادِ API ِ ادیتور (tool + params) می‌شود.
 */
export type Rect = { x: number; y: number; w: number; h: number };
export type Spot = { x: number; y: number; r: number };

export type EditState = {
  turn: 0 | 90 | 180 | 270;
  straighten: number;
  flipH: boolean;
  flipV: boolean;
  /** برش، به نسبتِ عکسِ چرخیده و صاف‌شده (۰ تا ۱) */
  crop: Rect;
  adjust: Adjust;
  curve: Curve;
  spots: Spot[];
  /** ابزارهای عمومی که روشن‌اند (متن، لوگو، واترمارک، حذفِ پس‌زمینه، قابِ مربع، بزرگ‌نمایی، قالبِ شبکه‌ها، فیلترِ ساده…) */
  tools: Record<string, Params>;
  /** «بهبودِ خودکارِ کیت» هنگامِ ساخت (روی سرورِ پردازش) */
  kitAuto: boolean;
  out: { format: "jpeg" | "png" | "webp"; quality: number; max_kb: number; long_edge: number };
};

export const FULL: Rect = { x: 0, y: 0, w: 1, h: 1 };

export const defaultState = (): EditState => ({
  turn: 0,
  straighten: 0,
  flipH: false,
  flipV: false,
  crop: { ...FULL },
  adjust: {},
  curve: {},
  spots: [],
  tools: {},
  kitAuto: false,
  out: { format: "jpeg", quality: 92, max_kb: 0, long_edge: 0 },
});

export const isFullCrop = (c: Rect) => c.x <= 0.0005 && c.y <= 0.0005 && c.w >= 0.9995 && c.h >= 0.9995;
export const hasCurve = (c: Curve) => !!(c.rgb || c.red || c.green || c.blue);

/** بزرگ‌ترین مستطیلِ هم‌راستا داخلِ عکسِ چرخیده — همان فرمولِ ops._inner_rect ِ سرور */
export function innerRect(w: number, h: number, angleDeg: number): [number, number] {
  const a = (Math.abs(angleDeg) * Math.PI) / 180;
  if (a < 1e-6) return [w, h];
  const long = Math.max(w, h);
  const short = Math.min(w, h);
  const sin = Math.sin(a);
  const cos = Math.cos(a);
  let wr: number;
  let hr: number;
  if (short <= 2 * sin * cos * long || Math.abs(sin - cos) < 1e-10) {
    const x = 0.5 * short;
    [wr, hr] = w >= h ? [x / sin, x / cos] : [x / cos, x / sin];
  } else {
    const c2 = cos * cos - sin * sin;
    wr = (w * cos - h * sin) / c2;
    hr = (h * cos - w * sin) / c2;
  }
  return [Math.max(1, Math.floor(wr)), Math.max(1, Math.floor(hr))];
}

/** اندازهٔ عکس بعد از چرخشِ ۹۰ درجه‌ای و صاف کردن (پیش از برش) */
export function transformedSize(w: number, h: number, s: Pick<EditState, "turn" | "straighten">): [number, number] {
  const [tw, th] = s.turn === 90 || s.turn === 270 ? [h, w] : [w, h];
  return innerRect(tw, th, s.straighten);
}

export const ASPECTS: { key: string; title: string; ratio: number | null }[] = [
  { key: "free", title: "آزاد", ratio: null },
  { key: "orig", title: "اصل", ratio: 0 },
  { key: "1:1", title: "۱:۱ مربع", ratio: 1 },
  { key: "4:5", title: "۴:۵ پستِ عمودی", ratio: 4 / 5 },
  { key: "9:16", title: "۹:۱۶ استوری", ratio: 9 / 16 },
  { key: "16:9", title: "۱۶:۹ ", ratio: 16 / 9 },
  { key: "1.91", title: "۱٫۹۱:۱ بنر", ratio: 1.91 },
  { key: "3:2", title: "۳:۲", ratio: 3 / 2 },
  { key: "4:3", title: "۴:۳", ratio: 4 / 3 },
];

/** بزرگ‌ترین قابِ هم‌نسبت (ratio = عرض/ارتفاع، روی پیکسل) داخلِ تصویر، وسط‌چین */
export function aspectRect(ratio: number, imgW: number, imgH: number): Rect {
  const cur = imgW / imgH;
  if (ratio >= cur) {
    const h = cur / ratio;
    return { x: 0, y: (1 - h) / 2, w: 1, h };
  }
  const w = ratio / cur;
  return { x: (1 - w) / 2, y: 0, w, h: 1 };
}

// ───────────────────────────── بخش‌های پنلِ راست (مثلِ Camera Raw)

export type Section = { key: string; title: string; groups: string[]; help: string };

export const SECTIONS: Section[] = [
  { key: "basic", title: "پایه (Basic)", groups: ["light", "color", "presence"], help: "نور، رنگ، وضوح و مه‌زدایی" },
  { key: "curves", title: "منحنی و سطوح (Curves)", groups: ["levels"], help: "منحنیِ تُن و سطوح" },
  { key: "hsl", title: "رنگ‌به‌رنگ (HSL / Color)", groups: ["hsl"], help: "فام، اشباع و روشنیِ هر خانوادهٔ رنگ" },
  { key: "grading", title: "رنگ‌دهی (Color Grading)", groups: ["grading"], help: "رنگِ دلخواه در سایه‌ها و روشنی‌ها" },
  { key: "detail", title: "جزئیات (Detail)", groups: ["detail"], help: "شارپ و نویزگیری" },
  { key: "optics", title: "لنز (Optics)", groups: ["geometry"], help: "اصلاحِ اعوجاج و تاریکیِ گوشهٔ لنز" },
  { key: "effects", title: "افکت (Effects)", groups: ["effects"], help: "وینیت و دانه" },
];

// ───────────────────────────── از حالت به کارهای ادیتور

const toNum = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);

/** لغزنده‌های کیت ⇐ «رنگِ سادهٔ» سرورِ سایت (Pillow) — برای ساختِ سریع وقتی سرورِ پردازش خاموش است */
export function quickColorFromAdjust(a: Adjust): Params | null {
  const brightness = Math.round(toNum(a.exposure, 0) * 28 + toNum(a.brightness, 0) * 0.5);
  const contrast = Math.round(toNum(a.contrast, 0) + toNum(a.clarity, 0) * 0.3);
  const saturation = Math.round(toNum(a.saturation, 0) + toNum(a.vibrance, 0) * 0.6);
  const warmth = Math.round(toNum(a.temperature, 0));
  const sharpness = Math.round(Math.max(0, toNum(a.sharpen, 0) * 0.7));
  const clampN = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
  const p = {
    brightness: clampN(brightness, -100, 100), contrast: clampN(contrast, -100, 100),
    saturation: clampN(saturation, -100, 100), warmth: clampN(warmth, -100, 100), sharpness: clampN(sharpness, 0, 100),
  };
  return Object.values(p).some((v) => v) ? p : null;
}

export const NODE_TOOLS = new Set([
  "kit_auto", "kit_preset", "kit_adjust", "kit_denoise", "kit_sharpen", "kit_heal", "kit_background", "kit_square",
  "kit_upscale", "kit_smart",
]);

export function buildOperations(
  s: EditState,
  opts: { quick?: boolean; tools?: Record<string, Tool> } = {},
): Operation[] {
  const ops: Operation[] = [];
  const add = (tool: string, params: Params) => ops.push({ tool, params, on: true });
  const quick = !!opts.quick;
  const adjustCount = Object.keys(s.adjust).length;

  if (!quick) {
    if (s.kitAuto) add("kit_auto", {});
    if (adjustCount || hasCurve(s.curve)) add("kit_adjust", { adjust: s.adjust, curve: s.curve });
    if (s.spots.length) add("kit_heal", { spots: s.spots });
    for (const key of ["kit_background", "kit_square", "kit_upscale", "kit_denoise", "kit_sharpen"]) {
      if (s.tools[key]) add(key, s.tools[key]);
    }
  } else {
    // سرورِ پردازش خاموش یا ساختِ سریع: لغزنده‌ها به رنگِ سادهٔ سرورِ سایت می‌روند؛ کارهای کیت کنار می‌مانند
    const qc = quickColorFromAdjust(s.adjust);
    if (qc) add("color", qc);
  }

  if (s.turn || s.straighten || s.flipH || s.flipV) {
    add("rotate", { turn: String(s.turn), straighten: s.straighten, flip_h: s.flipH, flip_v: s.flipV });
  }
  if (!isFullCrop(s.crop)) {
    const r = (v: number) => Math.round(v * 1000) / 10;
    add("crop_rect", { x: r(s.crop.x), y: r(s.crop.y), w: r(s.crop.w), h: r(s.crop.h) });
  }
  for (const key of ["crop_format", "auto_tone", "look", "color", "text", "logo", "watermark"]) {
    if (s.tools[key]) add(key, s.tools[key]);
  }
  if (s.out.long_edge > 0) add("resize", { long_edge: s.out.long_edge });
  add("export", { format: s.out.format, quality: s.out.quality, max_kb: s.out.max_kb });
  return ops;
}

/** حالت از روی کارهای یک نسخهٔ قبلی (برای «ادامه» دادنِ ویرایش) — آنچه می‌شناسیم برمی‌گردد */
export function stateFromOperations(ops: { tool: string; params: Params }[]): EditState {
  const s = defaultState();
  for (const o of ops) {
    const p = o.params ?? {};
    switch (o.tool) {
      case "kit_auto": s.kitAuto = true; break;
      case "kit_adjust":
        s.adjust = { ...s.adjust, ...((p.adjust as Adjust) ?? {}) };
        s.curve = { ...s.curve, ...((p.curve as Curve) ?? {}) };
        break;
      case "kit_heal": s.spots = [...((p.spots as Spot[]) ?? [])]; break;
      case "rotate":
        s.turn = (Number(p.turn) || 0) as EditState["turn"];
        s.straighten = Number(p.straighten) || 0;
        s.flipH = !!p.flip_h;
        s.flipV = !!p.flip_v;
        break;
      case "crop_rect":
        s.crop = { x: Number(p.x) / 100, y: Number(p.y) / 100, w: Number(p.w) / 100, h: Number(p.h) / 100 };
        break;
      case "resize": s.out.long_edge = Number(p.long_edge) || 0; break;
      case "export":
        s.out = { format: (p.format as EditState["out"]["format"]) ?? "jpeg", quality: Number(p.quality) || 92, max_kb: Number(p.max_kb) || 0, long_edge: s.out.long_edge };
        break;
      default:
        if (o.tool !== "kit_smart") s.tools[o.tool] = { ...p };
    }
  }
  return s;
}
