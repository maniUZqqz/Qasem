/**
 * رسمِ عنوان/زیرنویس روی بومِ مانیتور — آینهٔ backend/services/editing/titles.py
 * (clean ← مقدارهای پیش‌فرض و قالب، _geometry ← جای بلوک، _apply/_state ← انیمیشن‌ها، _word_plan ← کارائوکه).
 *
 * اندازه‌ها کسری از ارتفاعِ قاب‌اند؛ پس همان تابع روی هر اندازهٔ بوم کار می‌کند. شکل‌دهیِ فارسی و ترتیبِ دوسویه را خودِ مرورگر
 * (measureText / fillText) درست می‌کند. رندرِ نهایی با libass است؛ تفاوت‌های کوچک در `textRender` ذکر شده (فاصلهٔ خط، لبه‌ها).
 */
import type { TextClip, TextWord } from "./model";

export type FontDef = { title: string; css: string; weight: number; bold: boolean; line: number };

/** کلیدِ فونت ← پشتهٔ CSS؛ `line` = ارتفاعِ خطِ libass به نسبتِ em (اندازه‌گیری‌شده روی سرور) */
export const FONT_CSS: Record<string, FontDef> = {
  vazir: { title: "وزیرمتن", css: "Vazirmatn, 'Vazir', Tahoma, sans-serif", weight: 400, bold: true, line: 1.713 },
  vazir_black: { title: "وزیرمتن سیاه", css: "Vazirmatn, 'Vazir', Tahoma, sans-serif", weight: 800, bold: false, line: 1.713 },
  vazir_light: { title: "وزیرمتن نازک", css: "Vazirmatn, 'Vazir', Tahoma, sans-serif", weight: 300, bold: false, line: 1.711 },
  lato: { title: "Lato", css: "Lato, 'Helvetica Neue', Arial, sans-serif", weight: 400, bold: true, line: 1.203 },
  dejavu: { title: "DejaVu Sans", css: "'DejaVu Sans', Verdana, sans-serif", weight: 400, bold: true, line: 1.166 },
  dejavu_serif: { title: "DejaVu Serif", css: "'DejaVu Serif', Georgia, serif", weight: 400, bold: true, line: 1.166 },
  liberation: { title: "Liberation Sans", css: "'Liberation Sans', Arial, sans-serif", weight: 400, bold: true, line: 1.119 },
  liberation_serif: { title: "Liberation Serif", css: "'Liberation Serif', 'Times New Roman', serif", weight: 400, bold: true, line: 1.11 },
  mono: { title: "DejaVu Mono", css: "'DejaVu Sans Mono', Consolas, monospace", weight: 400, bold: true, line: 1.166 },
};

export const LINE2 = 0.62;
const POS_Y: Record<string, number> = { top: 0.12, middle: 0.5, bottom: 0.86 };

type Align = "left" | "center" | "right";

type Base = {
  size: number; bold: boolean; italic: boolean; color: string; opacity: number; stroke_color: string; stroke: number; shadow: number;
  shadow_color: string; box: boolean; box_color: string; box_opacity: number; box_pad: number; align: Align | "auto"; y: number | null;
  rotation: number; scale: number; anim_in: string; anim_out: string; anim_dur: number; hl_color: string; hl_mode: string; accent: string;
  font: string; duration: number;
};

const BASE: Base = {
  font: "vazir", size: 6, bold: true, italic: false, color: "#ffffff", opacity: 1, stroke_color: "#000000", stroke: 0, shadow: 0,
  shadow_color: "#000000", box: true, box_color: "#000000", box_opacity: 0.45, box_pad: 20, align: "center", y: null, rotation: 0,
  scale: 1, anim_in: "none", anim_out: "none", anim_dur: 0.4, hl_color: "#ffd400", hl_mode: "color", accent: "#ff3d71", duration: 2.5,
};

/** همان _TEMPLATE_DEFAULTS ِ titles.py */
export const TEMPLATE_DEFAULTS: Record<string, Partial<Base>> = {
  plain: {},
  lower_bar: { size: 4.8, y: 0.8, align: "auto", box: false, shadow: 14, duration: 4, anim_out: "fade" },
  lower_box: { size: 4.6, y: 0.8, align: "auto", box: false, box_pad: 24, duration: 4, anim_out: "fade" },
  lower_line: { size: 5.0, y: 0.8, align: "auto", box: false, shadow: 18, duration: 4, anim_out: "fade" },
  title_center: { size: 9, y: 0.5, box: false, shadow: 14, anim_in: "zoom", anim_out: "fade", duration: 3.5 },
  title_big: { size: 13, y: 0.5, box: false, stroke: 10, shadow: 16, anim_in: "pop", anim_out: "fade", duration: 3 },
  quote: { size: 6, y: 0.5, box: false, italic: true, bold: false, shadow: 12, anim_in: "fade", anim_out: "fade", duration: 4 },
  sticker: { size: 7, y: 0.35, rotation: -4, box: true, box_color: "#ffd400", box_opacity: 1, color: "#111111", box_pad: 28, anim_in: "pop", anim_out: "fade", duration: 3 },
  bubble: { size: 5.4, y: 0.62, box: true, box_color: "#ffffff", box_opacity: 0.95, color: "#111111", box_pad: 34, bold: false, anim_in: "pop", anim_out: "fade", duration: 3.5 },
};

const RTL_CHAR = /[֐-ࣿיִ-﷿ﹰ-﻿]/;
const LETTER = /\p{L}/u;

/** اولین «حرفِ» قوی تعیین‌کنندهٔ جهت است (مثلِ dir=auto و is_rtl ِ سرور) */
export function isRtl(text: string): boolean {
  for (const ch of text || "") if (LETTER.test(ch)) return RTL_CHAR.test(ch);
  return false;
}

const num = (v: unknown, lo: number, hi: number, d: number): number => {
  if (v === null || v === undefined || v === "") return d;
  const x = Number(v);
  return Number.isFinite(x) ? Math.max(lo, Math.min(hi, x)) : d;
};
const hex = (v: unknown, d: string): string => {
  const s = typeof v === "string" ? v.trim() : "";
  if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
  if (/^#[0-9a-f]{3}$/i.test(s)) return "#" + [...s.slice(1)].map((c) => c + c).join("").toLowerCase();
  return d;
};

export type Resolved = {
  text: string; text2: string; template: string; at: number; duration: number; font: string; size: number; bold: boolean; italic: boolean;
  color: string; opacity: number; stroke_color: string; stroke: number; shadow: number; shadow_color: string; box: boolean; box_color: string;
  box_opacity: number; box_pad: number; align: Align; x: number; y: number; rotation: number; scale: number; anim_in: string; anim_out: string;
  anim_dur: number; words: TextWord[]; hl_color: string; hl_mode: string; accent: string;
};

const resolvedCache = new WeakMap<object, Resolved>();

/** همان `clean` ِ سرور: پیش‌فرض ← پیش‌فرضِ قالب ← کلیدهای خودِ قطعه */
export function resolveText(clip: TextClip): Resolved {
  const hit = resolvedCache.get(clip);
  if (hit) return hit;
  const raw = clip as unknown as Record<string, unknown>;
  const template = typeof raw.template === "string" && raw.template in TEMPLATE_DEFAULTS ? (raw.template as string) : "plain";
  const d: Base = { ...BASE, ...TEMPLATE_DEFAULTS[template] } as Base;
  const pick = <K extends keyof Base>(key: K): unknown => (raw[key] === null || raw[key] === undefined ? d[key] : raw[key]);
  const text = String(raw.text ?? "").replace(/\r\n?/g, "\n").slice(0, 400);
  const text2 = String(raw.text2 ?? "").replace(/\r\n?/g, "\n").slice(0, 200);
  const duration = num(pick("duration"), 0.1, 3600, 2.5);
  const alignRaw = String(pick("align"));
  const align: Align = alignRaw === "left" || alignRaw === "right" || alignRaw === "center" ? alignRaw : alignRaw === "auto" ? (isRtl(text || text2) ? "right" : "left") : "center";
  const position = typeof raw.position === "string" && raw.position in POS_Y ? (raw.position as string) : "bottom";
  let y: number;
  if (raw.y !== null && raw.y !== undefined) y = num(raw.y, 0, 1, 0.86);
  else if (typeof raw.position === "string" && raw.position in POS_Y) y = POS_Y[position];
  else y = d.y !== null ? num(d.y, 0, 1, 0.86) : POS_Y[position];
  let animIn = String(raw.anim_in ?? d.anim_in);
  if ((raw.anim_in === null || raw.anim_in === undefined) && template.startsWith("lower_")) animIn = align === "right" ? "slide_left" : align === "left" ? "slide_right" : "slide_up";
  const font = String(pick("font"));
  const words: TextWord[] = [];
  for (const w of Array.isArray(raw.words) ? (raw.words as TextWord[]).slice(0, 400) : []) {
    const wt = String(w?.w ?? "").replace(/\n/g, " ").trim();
    if (!wt || w.s === undefined || w.e === undefined) continue;
    const s = Math.min(Math.max(0, Number(w.s)), duration);
    const e = Math.max(s, Math.min(Number(w.e), duration));
    if (Number.isFinite(s) && Number.isFinite(e)) words.push({ w: wt, s, e });
  }
  words.sort((a, b) => a.s - b.s);
  const out: Resolved = {
    text, text2, template, at: num(raw.at, 0, 86400, 0), duration, font: font in FONT_CSS ? font : "vazir",
    size: num(pick("size"), 1, 30, 6), bold: !!pick("bold"), italic: !!pick("italic"), color: hex(pick("color"), "#ffffff"),
    opacity: num(pick("opacity"), 0.05, 1, 1), stroke_color: hex(pick("stroke_color"), "#000000"), stroke: num(pick("stroke"), 0, 100, 0),
    shadow: num(pick("shadow"), 0, 100, 0), shadow_color: hex(pick("shadow_color"), "#000000"), box: !!pick("box"),
    box_color: hex(pick("box_color"), "#000000"), box_opacity: num(pick("box_opacity"), 0, 1, 0.45), box_pad: num(pick("box_pad"), 0, 100, 20),
    align, x: num(raw.x, 0, 1, 0.5), y, rotation: num(pick("rotation"), -180, 180, 0), scale: num(pick("scale"), 0.1, 4, 1),
    anim_in: animIn, anim_out: String(pick("anim_out")), anim_dur: num(pick("anim_dur"), 0.1, 2, 0.4), words,
    hl_color: hex(pick("hl_color"), "#ffd400"), hl_mode: String(pick("hl_mode")), accent: hex(pick("accent"), "#ff3d71"),
  };
  resolvedCache.set(clip, out);
  return out;
}

/**
 * کلیدهای صریحی که با انتخابِ یک قالب باید روی قطعه بنشینند (پیش‌فرضِ قالب روی پیش‌فرضِ پایه).
 * قطعهٔ ویرایشگر همیشه size/color/box/position دارد و سرور کلیدِ صریح را بر پیش‌فرضِ قالب ترجیح می‌دهد؛ پس قالب باید صریح نوشته شود.
 */
export function templatePatch(template: string, clip: TextClip): Partial<TextClip> {
  const t = template in TEMPLATE_DEFAULTS ? template : "plain";
  const d = { ...BASE, ...TEMPLATE_DEFAULTS[t] } as Base;
  const rtl = isRtl(clip.text || clip.text2 || "");
  const align: Align = d.align === "auto" ? (rtl ? "right" : "left") : d.align;
  const y = d.y ?? POS_Y.bottom;
  return {
    template: t, size: d.size, bold: d.bold, italic: d.italic, color: d.color, stroke: d.stroke, stroke_color: d.stroke_color, shadow: d.shadow,
    shadow_color: d.shadow_color, box: d.box, box_color: d.box_color, box_opacity: d.box_opacity, box_pad: d.box_pad, align, y,
    position: y < 0.3 ? "top" : y < 0.65 ? "middle" : "bottom", rotation: d.rotation, scale: d.scale,
    anim_in: (t.startsWith("lower_") ? (align === "right" ? "slide_left" : "slide_right") : d.anim_in) as TextClip["anim_in"],
    anim_out: d.anim_out as TextClip["anim_out"],
  };
}

/** کلیدهای «سبک» (بدونِ متن/زمان/کلمه‌ها) — برای «اعمال روی همهٔ زیرنویس‌ها» */
export const STYLE_KEYS = [
  "template", "font", "size", "bold", "italic", "color", "opacity", "stroke_color", "stroke", "shadow", "shadow_color", "box", "box_color",
  "box_opacity", "box_pad", "align", "position", "x", "y", "rotation", "scale", "anim_in", "anim_out", "anim_dur", "hl_color", "hl_mode", "accent",
] as const;

export function styleOf(clip: TextClip): Partial<TextClip> {
  const out: Record<string, unknown> = {};
  const src = clip as unknown as Record<string, unknown>;
  for (const k of STYLE_KEYS) if (src[k] !== undefined) out[k] = src[k];
  return out as Partial<TextClip>;
}

// ───────────── اندازه‌گیری
let mctx: CanvasRenderingContext2D | null = null;
function measureCtx(): CanvasRenderingContext2D | null {
  if (mctx) return mctx;
  if (typeof document === "undefined") return null;
  mctx = document.createElement("canvas").getContext("2d");
  return mctx;
}

function fontString(r: Resolved, em: number, bold: boolean, scale = 1): string {
  const f = FONT_CSS[r.font];
  const weight = bold && f.bold ? 700 : f.weight;
  return `${r.italic ? "italic " : ""}${weight} ${(em * scale).toFixed(2)}px ${f.css}`;
}

let fontEpoch = 0;
const fontSubs = new Set<() => void>();
const warmed = new Set<string>();
/** هر بار که فونتی تازه بارگیری شد شمارنده بالا می‌رود (کشِ چیدمان باطل می‌شود) */
export const textFontEpoch = (): number => fontEpoch;
export function onTextFontsReady(cb: () => void): () => void {
  fontSubs.add(cb);
  return () => fontSubs.delete(cb);
}
function warmFont(r: Resolved): void {
  if (typeof document === "undefined" || !document.fonts) return;
  const sample = (r.text + r.text2).slice(0, 80) || "آ";
  for (const bold of [r.bold, false]) {
    const spec = fontString(r, 16, bold);
    const key = spec + "|" + (/[؀-ۿ]/.test(sample) ? "ar" : "la");
    if (warmed.has(key)) continue;
    warmed.add(key);
    void document.fonts.load(spec, sample).then(() => {
      fontEpoch++;
      fontSubs.forEach((cb) => cb());
    }).catch(() => undefined);
  }
}

// ───────────── چیدمان
type Tok = { s: string; w: number; word: number | null };
type Line = { toks: Tok[]; text: string; w: number; second: boolean; em: number; pitch: number; chars: number; top: number; rtl: boolean };
type Geo = {
  em: number; em2: number; x: number; y: number; left: number; right: number; region: number; anchorX: number; barW: number; gap: number;
  hasBar: boolean; wrap: number; pad: number; blockH: number; line: number;
};
type Layout = { key: string; r: Resolved; g: Geo; lines: Line[]; nChars: number; spans: [number, number][]; dIn: number; dOut: number };

const layoutCache = new WeakMap<object, Layout>();

function wordPlan(r: Resolved): { text: string; spans: [number, number][] } {
  let text = r.text;
  if (!r.words.length) return { text, spans: [] };
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  if (tokens.length !== r.words.length) text = r.words.map((w) => w.w).join(" ");
  const spans: [number, number][] = r.words.map((w, i) => {
    const nxt = i + 1 < r.words.length ? r.words[i + 1].s : r.duration;
    return [w.s, Math.max(w.s + 0.05, Math.min(nxt, w.e + 0.25))];
  });
  return { text, spans };
}

function buildLayout(clip: TextClip, r: Resolved, W: number, H: number): Layout {
  const ctx = measureCtx();
  const fd = FONT_CSS[r.font];
  const em = (r.size / 100) * H;
  const em2 = em * LINE2;
  const x = r.x * W;
  const region = Math.min(0.88, 2 * Math.min(r.x, 1 - r.x) * 0.96) * W;
  let left = x - region / 2;
  let right = x + region / 2;
  const barW = Math.max(3, em * 0.16);
  const gap = em * 0.5;
  const hasBar = r.template === "lower_bar";
  if (hasBar) {
    if (r.align === "right") right -= barW + gap;
    else left += barW + gap;
  }
  const anchorX = r.align === "left" ? left : r.align === "right" ? right : (left + right) / 2;
  const boxed = r.box || r.template === "lower_box";
  const pad = boxed ? (em * r.box_pad) / 100 : 0;
  const wrap = Math.max(20, right - left - 2 * pad);

  const measure = (text: string, size: number, bold: boolean): number => {
    if (!ctx) return text.length * size * 0.52;
    ctx.font = fontString(r, size, bold);
    return ctx.measureText(text).width;
  };

  const { text, spans } = wordPlan(r);
  const lines: Line[] = [];
  let nChars = 0;
  let widx = 0;
  const addBlock = (src: string, second: boolean) => {
    const size = second ? em2 : em;
    const bold = second ? false : r.bold;
    const rtl = isRtl(src);
    for (const para of src.split("\n")) {
      const words: { s: string; word: number | null }[] = [];
      if (second) {
        // الگوی سرور: خطِ دوم یک تکه با فاصله‌های یکی‌شده؛ شمارشِ حرف = طولِ خطِ خام
        const joined = para.split(/\s+/).filter(Boolean).join(" ");
        nChars += para.length;
        if (!joined) continue;
        words.push({ s: joined, word: null });
      } else {
        for (const part of para.split(/(\s+)/)) {
          if (!part) continue;
          if (/^\s+$/.test(part)) { nChars += 1; continue; }
          words.push({ s: part, word: spans.length ? widx++ : null });
          nChars += part.length;
        }
      }
      // شکستنِ خط: اول حریصانه با پهنای ناحیه؛ بعد کوچک‌ترین پهنایی که همان تعدادِ خط را می‌دهد (libass با WrapStyle 0 خط‌ها را هم‌اندازه می‌کند)
      const greedy = (limit: number): { s: string; word: number | null }[][] => {
        const out: { s: string; word: number | null }[][] = [];
        let cur: { s: string; word: number | null }[] = [];
        for (const w of words) {
          const trial = [...cur, w].map((c) => c.s).join(" ");
          if (cur.length && measure(trial, size, bold) > limit) {
            out.push(cur);
            cur = [w];
          } else cur.push(w);
        }
        if (cur.length) out.push(cur);
        return out;
      };
      let broken = greedy(wrap);
      if (broken.length > 1) {
        let lo = Math.max(...words.map((w) => measure(w.s, size, bold)));
        let hi = wrap;
        for (let i = 0; i < 12 && hi - lo > 1; i++) {
          const mid = (lo + hi) / 2;
          if (greedy(mid).length <= broken.length) hi = mid;
          else lo = mid;
        }
        broken = greedy(hi);
      }
      broken.forEach((cur, i) => {
        const textLine = cur.map((c) => c.s).join(" ");
        const toks: Tok[] = cur.map((c) => ({ s: c.s, w: measure(c.s, size, bold), word: c.word }));
        lines.push({ toks, text: textLine, w: measure(textLine, size, bold), second, em: size, pitch: size * fd.line,
          chars: textLine.length + (i < broken.length - 1 ? 1 : 0), top: 0, rtl });
      });
    }
  };
  if (text.trim()) addBlock(text, false);
  if (r.text2.trim()) addBlock(r.text2, true);
  let blockH = 0;
  for (const l of lines) {
    l.top = blockH;
    blockH += l.pitch;
  }
  const half = blockH / 2 + pad + 0.01 * H;
  const lo = half + 0.02 * H;
  const hi = H - half - 0.02 * H;
  const yRaw = r.y * H;
  const y = lo <= hi ? Math.min(Math.max(yRaw, lo), hi) : H / 2;
  // مدتِ انیمیشن‌ها
  let dIn = r.anim_in !== "none" ? r.anim_dur : 0;
  let dOut = r.anim_out !== "none" ? r.anim_dur : 0;
  if (r.anim_in === "typewriter") dIn = Math.max(dIn, 0.045 * nChars);
  if (dIn + dOut > r.duration * 0.9) {
    const k = (r.duration * 0.9) / (dIn + dOut);
    dIn *= k;
    dOut *= k;
  }
  return { key: "", r, g: { em, em2, x, y, left, right, region, anchorX, barW, gap, hasBar, wrap, pad, blockH, line: fd.line }, lines, nChars, spans, dIn, dOut };
}

function layoutFor(clip: TextClip, r: Resolved, W: number, H: number): Layout {
  const key = `${W}x${H}|${fontEpoch}`;
  const hit = layoutCache.get(clip);
  if (hit && hit.key === key) return hit;
  const lay = buildLayout(clip, r, W, H);
  lay.key = key;
  layoutCache.set(clip, lay);
  return lay;
}

// ───────────── انیمیشن (همان _apply / _state)
type St = { alpha: number; scale: number; dx: number; dy: number; blur: number; reveal: number };
const easeOut = (u: number) => 1 - (1 - u) ** 3;
const easeIn = (u: number) => u ** 3;
const backOut = (u: number) => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2;
};
const DIRS: Record<string, [number, number]> = { slide_up: [0, -1], slide_down: [0, 1], slide_left: [-1, 0], slide_right: [1, 0] };

function applyAnim(kind: string, u: number, mode: "in" | "out", W: number, H: number): St {
  const st: St = { alpha: 1, scale: 1, dx: 0, dy: 0, blur: 0, reveal: 1 };
  const entering = mode === "in";
  const p = entering ? easeOut(u) : easeIn(u);
  const gone = entering ? 1 - p : p;
  if (kind === "fade") st.alpha = 1 - gone;
  else if (kind in DIRS) {
    const [dx, dy] = DIRS[kind];
    const sign = entering ? -1 : 1;
    st.dx = sign * dx * 0.1 * W * gone;
    st.dy = sign * dy * 0.06 * H * gone;
    st.alpha = 1 - gone;
  } else if (kind === "pop") {
    if (entering) {
      st.scale = 0.45 + 0.55 * backOut(u);
      st.alpha = Math.min(1, u * 3);
    } else {
      st.scale = 1 - 0.4 * p;
      st.alpha = 1 - p;
    }
  } else if (kind === "zoom") {
    st.scale = 1 + (entering ? 0.6 * gone : 0.4 * p);
    st.alpha = 1 - gone;
  } else if (kind === "blur") {
    st.blur = gone * 0.008 * H;
    st.alpha = 1 - gone;
  } else if (kind === "typewriter") st.reveal = entering ? u : 1 - u;
  return st;
}

function stateAt(r: Resolved, t: number, dIn: number, dOut: number, W: number, H: number): St {
  const st: St = { alpha: 1, scale: 1, dx: 0, dy: 0, blur: 0, reveal: 1 };
  const parts: St[] = [];
  if (dIn > 0 && t < dIn) parts.push(applyAnim(r.anim_in, Math.max(0, t / dIn), "in", W, H));
  if (dOut > 0 && t > r.duration - dOut) parts.push(applyAnim(r.anim_out, Math.min(1, (t - (r.duration - dOut)) / dOut), "out", W, H));
  for (const p of parts) {
    st.alpha *= p.alpha;
    st.scale *= p.scale;
    st.dx += p.dx;
    st.dy += p.dy;
    st.blur = Math.max(st.blur, p.blur);
    st.reveal = Math.min(st.reveal, p.reveal);
  }
  return st;
}

// ───────────── رسم
const rgba = (color: string, a: number): string => {
  const n = parseInt(color.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
};

/**
 * عنوانِ `clip` را در لحظهٔ `t` ِ «تایم‌لاین» روی بومِ W×H می‌کشد؛ بیرون از [at, at+duration) چیزی نمی‌کشد.
 * ctx باید ماتریسِ هویت داشته باشد. هزینه: چیدمان کش می‌شود؛ هر فریم فقط چند fillText.
 */
export function drawText(ctx: CanvasRenderingContext2D, clip: TextClip, t: number, W: number, H: number): void {
  const r = resolveText(clip);
  const local = t - r.at;
  if (local < 0 || local >= r.duration || (!r.text.trim() && !r.text2.trim())) return;
  warmFont(r);
  const L = layoutFor(clip, r, W, H);
  const { g } = L;
  const st = stateAt(r, local, L.dIn, L.dOut, W, H);
  if (st.alpha <= 0.002) return;
  const textA = r.opacity * st.alpha;
  const strokePx = (g.em * r.stroke) / 100;
  const shadowPx = (g.em * r.shadow) / 100 * 0.6;
  const pad = (g.em * r.box_pad) / 100;
  const boxed = r.box || r.template === "lower_box";
  const baseScale = r.scale;

  ctx.save();
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.miterLimit = 2;

  // — تزئینات (نوار، خط): با همان حرکت و محوشدن، بی‌چرخش
  const ax = g.anchorX + st.dx;
  const ay = g.y + st.dy;
  const gx = g.x + st.dx;
  if (r.template === "lower_bar" && g.blockH) {
    const h = g.blockH * 0.82;
    const bx = (r.align === "right" ? g.right + g.gap : g.left - g.gap - g.barW) + st.dx;
    ctx.fillStyle = rgba(r.accent, st.alpha);
    ctx.fillRect(bx, g.y + st.dy - h / 2, g.barW, h);
  } else if (r.template === "lower_line" && g.blockH) {
    const lw = Math.min(g.region * 0.4, W * 0.28);
    const lh = Math.max(2, g.em * 0.09);
    const lx = (r.align === "left" ? g.left : r.align === "center" ? g.anchorX - lw / 2 : g.right - lw) + st.dx;
    ctx.fillStyle = rgba(r.accent, st.alpha);
    ctx.fillRect(lx, g.y + st.dy + g.blockH / 2 + g.em * 0.15, lw, lh);
  } else if (r.template === "quote") {
    const markEm = g.em * 2.2;
    ctx.save();
    ctx.translate(gx, g.y + st.dy - g.blockH / 2 - markEm * 0.45);
    ctx.font = fontString(r, markEm, true);
    ctx.textAlign = "center";
    ctx.fillStyle = rgba(r.accent, st.alpha);
    ctx.fillText("“", 0, 0);
    ctx.restore();
  }

  // — بلوکِ متن: مبدأ = نقطهٔ لنگر؛ چرخش و بزرگ‌نمایی دورِ آن
  ctx.translate(ax, ay);
  if (r.rotation) ctx.rotate((r.rotation * Math.PI) / 180);
  const sc = baseScale * st.scale;
  if (sc !== 1) ctx.scale(sc, sc);
  const blurOk = st.blur > 0.05 && "filter" in ctx;
  if (blurOk) (ctx as CanvasRenderingContext2D & { filter: string }).filter = `blur(${(st.blur * sc).toFixed(2)}px)`;

  const reveal = st.reveal < 0.999 ? Math.round(st.reveal * L.nChars) : null;
  let budget = reveal ?? Infinity;
  const midLocal = local;
  const active = L.spans.length ? L.spans.findIndex(([s, e]) => s <= midLocal && midLocal < e) : -1;
  const top0 = -g.blockH / 2;

  for (const line of L.lines) {
    const lx = r.align === "left" ? 0 : r.align === "center" ? -line.w / 2 : -line.w;
    // — جعبه (لبهٔ هر خط)
    if (boxed) {
      let color = r.box_color;
      let op = r.box_opacity;
      if (r.template === "lower_box") {
        if (line.second) { color = "#000000"; op = Math.max(r.box_opacity, 0.7); } else { color = r.accent; op = 1; }
      }
      ctx.fillStyle = rgba(color, op * st.alpha);
      ctx.fillRect(lx - pad, top0 + line.top - pad, line.w + 2 * pad, line.pitch + 2 * pad);
    }
  }
  for (const line of L.lines) {
    const cy = top0 + line.top + line.pitch / 2;
    const lx = r.align === "left" ? 0 : r.align === "center" ? -line.w / 2 : -line.w;
    const rx = lx + line.w;
    const bold = line.second ? false : r.bold;
    ctx.font = fontString(r, line.em, bold);
    ctx.direction = line.rtl ? "rtl" : "ltr";
    const alpha = textA * (line.second ? 0.9 : 1);

    const paint = (txt: string, x: number, align: CanvasTextAlign, fill: string, extraStroke = 0, strokeColor = r.stroke_color) => {
      ctx.textAlign = align;
      if (shadowPx > 0.4) {
        ctx.fillStyle = rgba(r.shadow_color, 0.6 * st.alpha);
        ctx.strokeStyle = ctx.fillStyle;
        const sw = strokePx + extraStroke;
        if (sw > 0) { ctx.lineWidth = 2 * sw; ctx.strokeText(txt, x + shadowPx, cy + shadowPx); }
        ctx.fillText(txt, x + shadowPx, cy + shadowPx);
      }
      const sw = strokePx + extraStroke;
      if (sw > 0) {
        ctx.strokeStyle = rgba(strokeColor, st.alpha);
        ctx.lineWidth = 2 * sw;
        ctx.strokeText(txt, x, cy);
      }
      ctx.fillStyle = fill;
      ctx.fillText(txt, x, cy);
    };

    const consumed = Math.min(line.text.length, budget);
    budget -= line.chars;
    if (consumed <= 0) continue;
    const partial = consumed < line.text.length;

    const karaoke = !line.second && L.spans.length > 0 && line.toks.some((tk) => tk.word !== null);
    if (!karaoke || partial) {
      const txt = partial ? line.text.slice(0, consumed) : line.text;
      if (line.rtl) paint(txt, rx, "right", rgba(r.color, alpha));
      else paint(txt, lx, "left", rgba(r.color, alpha));
      continue;
    }
    // — کارائوکه: هر کلمه جدا کشیده می‌شود تا کلمهٔ فعال رنگ/اندازه/کادرِ دیگری بگیرد
    const spaceW = (() => {
      const m = measureCtx();
      if (!m) return line.em * 0.25;
      m.font = fontString(r, line.em, bold);
      return m.measureText(" ").width;
    })();
    let off = 0;
    for (const tk of line.toks) {
      const isActive = tk.word !== null && tk.word === active;
      const x0 = line.rtl ? rx - off : lx + off;
      const center = line.rtl ? x0 - tk.w / 2 : x0 + tk.w / 2;
      off += tk.w + spaceW;
      if (isActive && r.hl_mode === "scale") {
        ctx.font = fontString(r, line.em, bold, 1.12);
        paint(tk.s, center, "center", rgba(r.hl_color, alpha));
        ctx.font = fontString(r, line.em, bold);
      } else if (isActive && r.hl_mode === "box") {
        paint(tk.s, center, "center", rgba("#111111", alpha), g.em * 0.16, r.hl_color);
      } else if (isActive) {
        paint(tk.s, center, "center", rgba(r.hl_color, alpha));
      } else {
        paint(tk.s, center, "center", rgba(r.color, alpha));
      }
    }
  }
  ctx.restore();
}
