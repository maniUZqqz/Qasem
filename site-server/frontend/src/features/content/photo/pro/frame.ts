import type { Params } from "../api";
import type { Rect } from "../manual/model";
import { innerRect } from "../manual/model";
import { M3, apply, inv, mul, sc, tr } from "./geo";
import type { Quad } from "./types";

/**
 * «قاب‌اول» (frame-first) در مرورگر — بازتولیدِ عینِ هندسهٔ سرور:
 *   ops.py: crop_format_target / crop_format_geometry / _inner_rect، frames.py: geometry_stage / social_stage / frame_stages.
 * مختصاتِ پیوسته با لبهٔ بالا-چپِ پیکسل = صفر؛ H همیشه «پیکسلِ عکسِ اصل ⇒ پیکسلِ بومِ نهایی» است (ماتریس سطری ۳×۳).
 * هر عددی که سرور با round() پایتون گرد می‌کند (نیمه به زوج) اینجا با pyRound گرد می‌شود تا اندازهٔ بوم یکی باشد.
 */

export const SOCIAL_FORMATS: Record<string, [number, number]> = {
  square: [1080, 1080], portrait: [1080, 1350], story: [1080, 1920], landscape: [1200, 630], wide: [1920, 1080], store: [2000, 2000],
};
export const FOCUS_KEYS = ["smart", "center", "top", "bottom", "left", "right"] as const;
export const FILL_KEYS = ["blur", "white", "black", "color", "transparent"] as const;

/** round() ِ پایتون: نیمه به نزدیک‌ترین زوج */
export function pyRound(x: number): number {
  const f = Math.floor(x);
  const d = x - f;
  if (d < 0.5) return f;
  if (d > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const num = (v: unknown, d: number): number => {
  const x = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(x) ? x : d;
};
const r3 = (x: number) => Math.round(x * 1000) / 1000;
const r5 = (x: number) => Math.round(x * 1e5) / 1e5;
const r6 = (x: number) => Math.round(x * 1e6) / 1e6;

// ───────────────────────────── پارامترهای crop_format (همان catalog.normalize_params)

export type CropFormat = {
  format: string;
  size: number;
  fit: "cover" | "contain";
  focus: (typeof FOCUS_KEYS)[number];
  fill: (typeof FILL_KEYS)[number];
  fill_color: string;
  padding: number;
  /** [x, y, w, h] به کسری از تصویرِ ورودیِ مرحله (پس از هندسه)؛ [] = بی‌پنجره */
  window: number[];
  /** فقط «جا دادن»: "auto" = «کالا وسطِ قاب» (کالا کامل و با حاشیه وسطِ قاب)؛ "" = کلِ عکس (رفتارِ قدیم و پیش‌فرضِ پروژه‌های قدیمی) */
  subject: "" | "auto";
  /** جای دوربین [zoom, cx, cy] (cx/cy = کسری از عکسی که وسطِ قاب می‌افتد)؛ [] = خودکار (مرورگر حساب می‌کند). با کشیدنِ عکس در قاب ثبت می‌شود */
  view: number[];
};

export const CF_DEFAULT: CropFormat = {
  format: "square", size: 2000, fit: "cover", focus: "smart", fill: "blur", fill_color: "#f3f4f6", padding: 0, window: [], subject: "", view: [],
};

export const VIEW_ZOOM_MAX = 8;
export const VIEW_CENTER: [number, number] = [-1, 2];

/** جای دوربین ⇐ [zoom، cx، cy] (zoom ۴ رقم در [۱، ۸]؛ مرکز ۵ رقم در [−۱، ۲]) یا [] — مثلِ catalog.normalize_view */
export function normalizeView(v: unknown): number[] {
  if (!Array.isArray(v) || v.length !== 3) return [];
  const nums: number[] = [];
  for (const item of v) {
    if (typeof item === "boolean") return [];
    const x = num(item, NaN);
    if (!Number.isFinite(x)) return [];
    nums.push(x);
  }
  const zoom = Math.min(VIEW_ZOOM_MAX, Math.max(1, nums[0]));
  const cx = Math.min(VIEW_CENTER[1], Math.max(VIEW_CENTER[0], nums[1]));
  const cy = Math.min(VIEW_CENTER[1], Math.max(VIEW_CENTER[0], nums[2]));
  return [Math.round(zoom * 1e4) / 1e4, r5(cx), r5(cy)];
}

/** پنجرهٔ برش ⇐ ۴ عدد (۶ رقم اعشار) یا [] — مثلِ catalog.normalize_window */
export function normalizeWindow(v: unknown): number[] {
  if (!Array.isArray(v) || v.length !== 4) return [];
  const nums: number[] = [];
  for (const item of v) {
    if (typeof item === "boolean") return [];
    const x = num(item, NaN);
    if (!Number.isFinite(x)) return [];
    nums.push(clamp(x, 0, 1));
  }
  const [x, y] = nums;
  let [, , w, h] = nums;
  if (w < 0.02 || h < 0.02) return [];
  if (x + w > 1.001 || y + h > 1.001) return [];
  w = Math.min(w, 1 - x);
  h = Math.min(h, 1 - y);
  if (w < 0.02 || h < 0.02) return [];
  return [r6(x), r6(y), r6(w), r6(h)];
}

export function normalizeCropFormat(raw: Params | null | undefined): CropFormat {
  const p = raw ?? {};
  const fmt = String(p.format ?? CF_DEFAULT.format);
  const pick = <T extends string>(v: unknown, allowed: readonly T[], d: T): T => (allowed.includes(String(v) as T) ? (String(v) as T) : d);
  const col = typeof p.fill_color === "string" && /^#[0-9a-fA-F]{6}$/.test(p.fill_color) ? p.fill_color : CF_DEFAULT.fill_color;
  return {
    format: fmt === "custom" || fmt in SOCIAL_FORMATS ? fmt : CF_DEFAULT.format,
    size: pyRound(clamp(num(p.size, 2000), 200, 4000)),
    fit: p.fit === "contain" ? "contain" : "cover",
    focus: pick(p.focus, FOCUS_KEYS, "smart"),
    fill: pick(p.fill, FILL_KEYS, "blur"),
    fill_color: col,
    padding: pyRound(clamp(num(p.padding, 0), 0, 40)),
    window: normalizeWindow(p.window),
    subject: p.subject === "auto" ? "auto" : "",
    view: normalizeView(p.view),
  };
}

/** `tools.crop_format` (یا kit_square ِ قدیمی که به همان تبدیل می‌شود) ⇒ پارامترهای وارسی‌شده، یا null */
export function effectiveCropFormat(tools: Record<string, Params> | undefined): CropFormat | null {
  const raw = tools?.crop_format;
  if (raw && typeof raw === "object") return normalizeCropFormat(raw);
  const ks = tools?.kit_square;
  if (ks && typeof ks === "object") {
    return normalizeCropFormat({
      format: "custom", size: pyRound(clamp(num(ks.long_edge, 2000), 500, 4000)), fit: "contain", focus: "center", fill: "white",
      padding: pyRound(clamp(num(ks.padding, 6), 0, 40)),
    });
  }
  return null;
}

/**
 * پارامترهای کار (برای operations): هر کلیدی که سرور می‌شناسد. `auto` = آنچه مرورگر خودکار حساب کرده: چهارتایی ⇒ پنجرهٔ «سوژه
 * (خودکار)» ِ cover؛ سه‌تایی ⇒ جای دوربینِ «کالا وسطِ قاب» (فقط contain با subject=auto؛ view ِ صریحِ پروژه بر آن می‌چربد).
 */
export function cropFormatOpParams(cf: CropFormat, auto?: number[] | null): Params {
  const w = auto && auto.length === 4 ? normalizeWindow(auto) : cf.window;
  const v = cf.subject === "auto" ? (cf.view.length === 3 ? cf.view : auto && auto.length === 3 ? normalizeView(auto) : []) : [];
  return { format: cf.format, size: cf.size, fit: cf.fit, focus: cf.focus, fill: cf.fill, fill_color: cf.fill_color, padding: cf.padding, window: w, subject: cf.subject, view: v };
}

export function cropFormatTarget(p: CropFormat): [number, number] {
  if (p.format === "custom") {
    const side = Math.max(200, Math.min(4000, Math.trunc(p.size || 2000)));
    return [side, side];
  }
  return SOCIAL_FORMATS[p.format] ?? SOCIAL_FORMATS.square;
}

/** «کالا وسطِ قاب»: جای اعشاریِ عکس در بوم (پیکسلِ بوم؛ ممکن است از بوم بیرون بزند) و دوربینِ سازندهٔ آن */
export type CfView = { scale: number; left: number; top: number; zoom: number; cx: number; cy: number };

export type CfGeo =
  | { mode: "cover"; size: [number, number]; box: [number, number, number, number]; exact: boolean; upscale: number; approx: boolean }
  | { mode: "contain"; size: [number, number]; fg: [number, number]; pos: [number, number]; view?: CfView; approx?: boolean };

/**
 * ops.crop_format_geometry — `energy(cw, ch)` فقط برای cover/smart بی‌پنجره؛ نبودنش ⇒ وسط و approx=true.
 * `subject()` ⇒ [zoom, cx, cy] | null فقط برای contain با subject=auto و بی view؛ نبودنش ⇒ کلِ عکس و approx=true.
 */
export function cropFormatGeometry(
  p: CropFormat,
  w: number,
  h: number,
  energy?: (cw: number, ch: number) => [number, number],
  subject?: () => number[] | null,
): CfGeo {
  const [tw, th] = cropFormatTarget(p);
  if (p.fit === "cover") {
    if (p.window.length === 4) {
      const [wx, wy, ww, wh] = p.window;
      let box: [number, number, number, number] = [
        Math.max(0, Math.min(w - 1, wx * w)), Math.max(0, Math.min(h - 1, wy * h)),
        Math.max(1, Math.min(w, (wx + ww) * w)), Math.max(1, Math.min(h, (wy + wh) * h)),
      ];
      if (box[2] - box[0] < 1 || box[3] - box[1] < 1) box = [0, 0, w, h];
      const up = Math.max(tw / Math.max(1e-9, box[2] - box[0]), th / Math.max(1e-9, box[3] - box[1]));
      return { mode: "cover", size: [tw, th], box, exact: true, upscale: up, approx: false };
    }
    const scale = Math.max(tw / w, th / h);
    const cw = Math.min(w, pyRound(tw / scale));
    const ch = Math.min(h, pyRound(th / scale));
    let x: number;
    let y: number;
    let approx = false;
    if (p.focus === "smart") {
      if (energy) [x, y] = energy(cw, ch);
      else {
        x = Math.floor((w - cw) / 2);
        y = Math.floor((h - ch) / 2);
        approx = true;
      }
    } else {
      x = p.focus === "left" ? 0 : p.focus === "right" ? w - cw : Math.floor((w - cw) / 2);
      y = p.focus === "top" ? 0 : p.focus === "bottom" ? h - ch : Math.floor((h - ch) / 2);
    }
    x = Math.max(0, Math.min(w - cw, x));
    y = Math.max(0, Math.min(h - ch, y));
    return { mode: "cover", size: [tw, th], box: [x, y, x + cw, y + ch], exact: false, upscale: scale, approx };
  }
  const pad = clamp(p.padding, 0, 40) / 100;
  const scale = Math.min(tw / w, th / h) * (1 - 2 * pad);
  let view: number[] | null = null;
  let approx = false;
  if (p.subject === "auto") {
    if (p.view.length === 3) view = p.view;
    else if (subject) view = subject();
    else approx = true;
  }
  if (view && (view[0] > 1 + 1e-9 || Math.abs(view[1] - 0.5) > 1e-9 || Math.abs(view[2] - 0.5) > 1e-9)) {
    const [zoom, cx, cy] = view;
    const s2 = scale * zoom;
    const fw = w * s2;
    const fh = h * s2;
    const left = tw / 2 - cx * fw;
    const top = th / 2 - cy * fh;
    return {
      mode: "contain", size: [tw, th], fg: [Math.max(1, pyRound(fw)), Math.max(1, pyRound(fh))], pos: [Math.floor(left), Math.floor(top)],
      view: { scale: s2, left, top, zoom, cx, cy },
    };
  }
  const nw = Math.max(1, pyRound(w * scale));
  const nh = Math.max(1, pyRound(h * scale));
  const geo: CfGeo = { mode: "contain", size: [tw, th], fg: [nw, nh], pos: [Math.floor((tw - nw) / 2), Math.floor((th - nh) / 2)] };
  if (approx) geo.approx = true;
  return geo;
}

// ───────────────────────────── مرحلهٔ هندسه: پرسپکتیو ⇐ چرخش/قرینه ⇐ برش

export type GeomInput = {
  turn: number;
  straighten: number;
  flipH: boolean;
  flipV: boolean;
  crop: Rect;
  persp: Quad | null;
};

/** چهارضلعیِ پرسپکتیو وارسی‌شده (point: ۵ رقم، −۱..۲)؛ تمام‌مربع ⇒ null */
function perspParams(q: Quad | null): Quad | null {
  if (!q) return null;
  const pt = (p: [number, number]): [number, number] => [r5(clamp(num(p[0], 0), -1, 2)), r5(clamp(num(p[1], 0), -1, 2))];
  const out: Quad = { tl: pt(q.tl), tr: pt(q.tr), br: pt(q.br), bl: pt(q.bl) };
  const full: Quad = { tl: [0, 0], tr: [1, 0], br: [1, 1], bl: [0, 1] };
  const trivial = (["tl", "tr", "br", "bl"] as const).every((k) => Math.abs(out[k][0] - full[k][0]) < 1e-4 && Math.abs(out[k][1] - full[k][1]) < 1e-4);
  return trivial ? null : out;
}

function rotateParams(g: GeomInput): { turn: number; straighten: number; flipH: boolean; flipV: boolean } | null {
  const t = ((pyRound(num(g.turn, 0)) % 360) + 360) % 360;
  const turn = t === 0 || t === 90 || t === 180 || t === 270 ? t : 0;
  const straighten = r3(clamp(num(g.straighten, 0), -15, 15));
  if (turn === 0 && !straighten && !g.flipH && !g.flipV) return null;
  return { turn, straighten, flipH: !!g.flipH, flipV: !!g.flipV };
}

/** همان قراردادِ مرورگر/سرور: برشِ کامل ⇒ null؛ وگرنه درصد با یک رقم اعشار و حدِ catalog */
function cropParams(c: Rect): { x: number; y: number; w: number; h: number } | null {
  const x = num(c?.x, 0);
  const y = num(c?.y, 0);
  const w = num(c?.w, 1);
  const h = num(c?.h, 1);
  if (x <= 0.0005 && y <= 0.0005 && w >= 0.9995 && h >= 0.9995) return null;
  const r = (v: number) => Math.floor(v * 1000 + 0.5) / 10;
  return { x: r3(clamp(r(x), 0, 95)), y: r3(clamp(r(y), 0, 95)), w: r3(clamp(r(w), 5, 100)), h: r3(clamp(r(h), 5, 100)) };
}

/** چهار نقطه ⇒ هموگرافی (حذفِ گاوس با محورگیری؛ مثلِ frames._homography) */
function homography(src: [number, number][], dst: [number, number][]): M3 {
  const A: number[][] = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i];
    const [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
  }
  for (let c = 0; c < 8; c++) {
    let piv = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[piv][c])) piv = r;
    if (Math.abs(A[piv][c]) < 1e-12) return [1, 0, 0, 0, 1, 0, 0, 0, 1];
    [A[c], A[piv]] = [A[piv], A[c]];
    for (let r = 0; r < 8; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      if (f) for (let k = c; k < 9; k++) A[r][k] -= f * A[c][k];
    }
  }
  const h = A.map((row, i) => row[8] / row[i]);
  return [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1];
}

/** perspective ⇐ rotate/flip ⇐ crop_rect ⇒ H (عکس ⇒ پس از برش) و اندازهٔ صحیحِ آن؛ مثلِ frames.geometry_stage */
export function geometryStage(Wo: number, Ho: number, g: GeomInput): { H: M3; size: [number, number] } {
  let w = Math.round(Wo);
  let h = Math.round(Ho);
  let H: M3 = [1, 0, 0, 0, 1, 0, 0, 0, 1];
  const pp = perspParams(g.persp);
  if (pp) {
    const pts = [pp.tl, pp.tr, pp.br, pp.bl];
    const src = pts.map(([x, y]) => [x * w, y * h] as [number, number]);
    const dist = (a: [number, number], b: [number, number]) => Math.hypot((a[0] - b[0]) * w, (a[1] - b[1]) * h);
    let ow = (dist(pts[0], pts[1]) + dist(pts[3], pts[2])) / 2;
    let oh = (dist(pts[0], pts[3]) + dist(pts[1], pts[2])) / 2;
    const k = Math.min(1, 8000 / Math.max(ow, oh, 1));
    ow = Math.max(8, pyRound(ow * k));
    oh = Math.max(8, pyRound(oh * k));
    H = mul(homography(src, [[0, 0], [ow, 0], [ow, oh], [0, oh]]), H);
    w = ow;
    h = oh;
  }
  const rp = rotateParams(g);
  if (rp) {
    if (rp.turn === 90) {
      // PIL ROTATE_90 = پادساعتگرد: (x, y) ⇒ (y, w − x)
      H = mul([0, 1, 0, -1, 0, w, 0, 0, 1], H);
      [w, h] = [h, w];
    } else if (rp.turn === 270) {
      H = mul([0, -1, h, 1, 0, 0, 0, 0, 1], H);
      [w, h] = [h, w];
    } else if (rp.turn === 180) {
      H = mul([-1, 0, w, 0, -1, h, 0, 0, 1], H);
    }
    if (rp.straighten) {
      const a = (rp.straighten * Math.PI) / 180;
      const c = Math.cos(a);
      const s = Math.sin(a);
      const [iw, ih] = innerRect(w, h, rp.straighten);
      const left = Math.floor((w - iw) / 2);
      const top = Math.floor((h - ih) / 2);
      // Image.rotate(angle) پادساعتگرد حولِ مرکز، سپس برشِ مرکزیِ iw×ih
      const R = mul(tr(w / 2, h / 2), mul([c, s, 0, -s, c, 0, 0, 0, 1], tr(-w / 2, -h / 2)));
      H = mul(tr(-left, -top), mul(R, H));
      w = iw;
      h = ih;
    }
    if (rp.flipH) H = mul([-1, 0, w, 0, 1, 0, 0, 0, 1], H);
    if (rp.flipV) H = mul([1, 0, 0, 0, -1, h, 0, 0, 1], H);
  }
  const cp = cropParams(g.crop);
  if (cp) {
    const x0 = Math.max(0, Math.min(w - 8, pyRound((w * cp.x) / 100)));
    const y0 = Math.max(0, Math.min(h - 8, pyRound((h * cp.y) / 100)));
    const x1 = Math.max(x0 + 8, Math.min(w, x0 + pyRound((w * cp.w) / 100)));
    const y1 = Math.max(y0 + 8, Math.min(h, y0 + pyRound((h * cp.h) / 100)));
    if (x0 !== 0 || y0 !== 0 || x1 !== w || y1 !== h) {
      H = mul(tr(-x0, -y0), H);
      w = x1 - x0;
      h = y1 - y0;
    }
  }
  return { H, size: [w, h] };
}

/** crop_format روی ورودیِ w×h ⇒ H، اندازهٔ بوم و هندسه؛ مثلِ frames.social_stage */
export function socialStage(
  w: number,
  h: number,
  cf: CropFormat,
  energy?: (cw: number, ch: number) => [number, number],
  subject?: () => number[] | null,
): { H: M3; size: [number, number]; geo: CfGeo } {
  const geo = cropFormatGeometry(cf, w, h, energy, subject);
  const [tw, th] = geo.size;
  if (geo.mode === "cover") {
    const [x0, y0, x1, y1] = geo.box;
    return { H: mul(sc(tw / (x1 - x0), th / (y1 - y0)), tr(-x0, -y0)), size: [tw, th], geo };
  }
  if (geo.view) return { H: mul(tr(geo.view.left, geo.view.top), sc(geo.view.scale, geo.view.scale)), size: [tw, th], geo };
  const [nw, nh] = geo.fg;
  const [left, top] = geo.pos;
  return { H: mul(tr(left, top), sc(nw / w, nh / h)), size: [tw, th], geo };
}

// ───────────────────────────── مشخصاتِ کاملِ قاب (برای موتور)

export type FrameInput = GeomInput & { tools: Record<string, Params> };

export type FrameSpec = {
  /** امضای محتوا (تغییرش ⇒ بافتِ قاب و انتخاب باطل می‌شوند) */
  key: string;
  Wo: number;
  Ho: number;
  /** اندازهٔ واقعیِ بومِ نهایی (همان که سرور می‌سازد) */
  Wf: number;
  Hf: number;
  /** پیکسلِ عکسِ اصل ⇒ پیکسلِ بومِ نهایی */
  H: M3;
  /** پیکسلِ عکسِ اصل ⇒ تصویرِ پس از هندسه (پیش از قابِ شبکه) و اندازهٔ آن */
  geoH: M3;
  gw: number;
  gh: number;
  cf: CropFormat | null;
  social: CfGeo | null;
  /** بی‌هندسه و بی‌قاب: بوم = خودِ عکس (بی پاسِ قاب) */
  trivial: boolean;
  /** قابِ cover با «سوژه (خودکار)» بی پنجره، یا قابِ «جا دادن» با «کالا وسطِ قاب» بی view ⇒ جایِ وسط جایگزین است تا مرورگر حساب کند */
  smartPending: boolean;
};

export function geometrySig(g: GeomInput): string {
  return JSON.stringify([g.turn, g.straighten, g.flipH, g.flipV, g.crop, g.persp]);
}

/**
 * هندسهٔ کاملِ قاب. `window` = آنچه مرورگر خودکار حساب کرده: چهارتایی (پنجرهٔ «سوژه (خودکار)») جایگزینِ `cf.window` در cover/smart؛
 * سه‌تایی (جای دوربینِ «کالا وسطِ قاب») جایگزینِ `cf.view` در contain با subject=auto.
 */
export function makeFrameSpec(Wo: number, Ho: number, input: FrameInput, window?: number[] | null): FrameSpec {
  const g = geometryStage(Wo, Ho, input);
  const [gw, gh] = g.size;
  let cf = effectiveCropFormat(input.tools);
  const wantsSmart = !!cf && cf.fit === "cover" && cf.focus === "smart" && cf.window.length !== 4;
  const wantsSubject = !!cf && cf.fit === "contain" && cf.subject === "auto" && cf.view.length !== 3;
  if (cf && wantsSmart && window && window.length === 4) {
    const w = normalizeWindow(window);
    if (w.length === 4) cf = { ...cf, window: w };
  }
  if (cf && wantsSubject && window && window.length === 3) {
    const v = normalizeView(window);
    if (v.length === 3) cf = { ...cf, view: v };
  }
  const trivial = !cf && g.H.every((v, i) => Math.abs(v - [1, 0, 0, 0, 1, 0, 0, 0, 1][i]) < 1e-12) && gw === Math.round(Wo) && gh === Math.round(Ho);
  let H = g.H;
  let size = g.size;
  let social: CfGeo | null = null;
  if (cf) {
    const s = socialStage(gw, gh, cf);
    H = mul(s.H, g.H);
    size = s.size;
    social = s.geo;
  }
  const smartPending = !!cf && ((cf.fit === "cover" && cf.focus === "smart" && cf.window.length !== 4) || (cf.fit === "contain" && cf.subject === "auto" && cf.view.length !== 3));
  const key = JSON.stringify([Math.round(Wo), Math.round(Ho), geometrySig(input), cf]);
  return { key, Wo, Ho, Wf: size[0], Hf: size[1], H, geoH: g.H, gw, gh, cf, social, trivial, smartPending };
}

/** نقطهٔ بوم (کسری ۰..۱) ⇒ نقطهٔ عکسِ اصل (کسری)؛ بیرون از عکس (مثلاً حاشیهٔ «جا دادن») ⇒ null */
export function canvasToPhoto(spec: FrameSpec, nx: number, ny: number): [number, number] | null {
  const [x, y] = apply(inv(spec.H), nx * spec.Wf, ny * spec.Hf);
  const u = x / spec.Wo;
  const v = y / spec.Ho;
  if (!(u >= 0 && u <= 1 && v >= 0 && v <= 1)) return null;
  return [u, v];
}

/** یکنواخت‌های پاسِ قاب (GLSL): همه در مختصاتِ نرمال؛ همان H ِ بالا، معکوس */
export type FrameUniforms = {
  /** uv بومِ نهایی ⇒ uv عکس */
  inv: M3;
  contain: boolean;
  /** مستطیلِ محتوا در پیکسلِ واقعیِ بوم: چپ، بالا، پهنا، ارتفاع */
  fg: [number, number, number, number];
  /** ۰ سفید، ۱ سیاه، ۲ رنگ، ۳ محو، ۴ شفاف */
  fill: number;
  color: [number, number, number];
  /** محو: اندازهٔ بافتِ کوچک (۱/۸ بوم) و uv آن ⇒ uv عکس (پس از cover-scale و برش، مثلِ ops.op_crop_format) */
  bgSize: [number, number];
  bgInv: M3;
};

const hex3 = (c: string): [number, number, number] => [parseInt(c.slice(1, 3), 16) / 255, parseInt(c.slice(3, 5), 16) / 255, parseInt(c.slice(5, 7), 16) / 255];

export function frameUniforms(spec: FrameSpec): FrameUniforms {
  const { Wo, Ho, Wf, Hf } = spec;
  const photoUv = sc(1 / Wo, 1 / Ho);
  const inverse = mul(photoUv, mul(inv(spec.H), sc(Wf, Hf)));
  const cf = spec.cf;
  const geo = spec.social;
  const base: FrameUniforms = {
    inv: inverse, contain: false, fg: [0, 0, Wf, Hf], fill: 0, color: [1, 1, 1], bgSize: [1, 1], bgInv: inverse,
  };
  if (!cf || !geo || geo.mode !== "contain") return base;
  const [tw, th] = geo.size;
  // «کالا وسطِ قاب»: مستطیلِ عکس اعشاری است و ممکن است از بوم بیرون بزند (شیدر هر دو را درست می‌پوشاند)
  const fgRect: [number, number, number, number] = geo.view
    ? [geo.view.left, geo.view.top, spec.gw * geo.view.scale, spec.gh * geo.view.scale]
    : [geo.pos[0], geo.pos[1], geo.fg[0], geo.fg[1]];
  const fill = { white: 0, black: 1, color: 2, blur: 3, transparent: 4 }[cf.fill];
  // پس‌زمینهٔ «محو»: تصویرِ پس از هندسه (gw×gh) cover-scale ⇒ برشِ مرکزی tw×th ⇒ ۱/۸ ⇒ گاوس ۶ ⇒ ×۰٫۸۲
  const cover = Math.max(tw / spec.gw, th / spec.gh);
  const cw = Math.max(tw, Math.floor(spec.gw * cover));
  const ch = Math.max(th, Math.floor(spec.gh * cover));
  const l0 = Math.floor((cw - tw) / 2);
  const t0 = Math.floor((ch - th) / 2);
  const bgInv = mul(photoUv, mul(inv(spec.geoH), mul(sc(spec.gw / cw, spec.gh / ch), mul(tr(l0, t0), sc(tw, th)))));
  return {
    inv: inverse, contain: true, fg: fgRect, fill, color: hex3(cf.fill_color),
    bgSize: [Math.max(1, Math.floor(tw / 8)), Math.max(1, Math.floor(th / 8))], bgInv,
  };
}
