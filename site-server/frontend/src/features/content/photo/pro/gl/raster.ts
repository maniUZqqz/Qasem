import type { Adjust, Curve, Pt } from "../../manual/engine";
import type { ShapeLayer, Stroke, TextLayer } from "../types";

/** رسم‌های دوبعدیِ لایه‌ها (متن، شکل، قلم) و جدول‌های منحنی. همه با همان قراردادِ بک‌اند (layers.py / textlayer.py). */

export const FONT_FAMILY = "Vazirmatn";
const MAX_LINES = 40;
const MAX_TILE = 8192;

const mk = (w: number, h: number) => {
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  return c;
};

let measureCtx: CanvasRenderingContext2D | null = null;
const mctx = () => (measureCtx ??= mk(8, 8).getContext("2d")!);

export function isRtlText(text: string): boolean {
  for (const ch of text) {
    const c = ch.codePointAt(0)!;
    if ((c >= 0x0590 && c <= 0x08ff) || (c >= 0xfb1d && c <= 0xfdff) || (c >= 0xfe70 && c <= 0xfeff)) return true;
    if (/\p{L}/u.test(ch)) return false;
  }
  return false;
}

const hexA = (hex: string, a: number) => {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
};

export type TextRaster = {
  canvas: HTMLCanvasElement;
  /** اندازهٔ بافت به‌صورتِ کسری از پهنای بوم */
  bw: number;
  bh: number;
  /** اندازهٔ بلوکِ متن (بی حاشیه) */
  cw: number;
  ch: number;
  lines: string[];
  /** تکرارشونده: بومِ هم‌اندازهٔ سند */
  full: boolean;
};

function fontStr(weight: number, sizePx: number) {
  return `${weight} ${sizePx}px ${FONT_FAMILY}, Tahoma, sans-serif`;
}

/** پهنای یک تکه با فونتِ جاری (بی فاصلهٔ حروف) */
function len(ctx: CanvasRenderingContext2D, text: string, rtl: boolean): number {
  if (!text) return 0;
  ctx.direction = rtl ? "rtl" : "ltr";
  return ctx.measureText(text).width;
}

export function wrapLines(ctx: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const out: string[] = [];
  for (const para of text.split("\n")) {
    const words = para.split(/\s+/).filter(Boolean);
    if (!words.length) {
      out.push("");
      continue;
    }
    const rtl = isRtlText(para);
    let cur = "";
    for (const w of words) {
      const trial = (cur + " " + w).trim();
      if (!cur || len(ctx, trial, rtl) <= maxW) cur = trial;
      else {
        out.push(cur);
        cur = w;
      }
    }
    out.push(cur);
  }
  return out.slice(0, MAX_LINES);
}

type Piece = { text: string; x: number };

function linePieces(ctx: CanvasRenderingContext2D, line: string, rtl: boolean, spacing: number): { pieces: Piece[]; width: number } {
  if (!spacing || !line.trim()) return { pieces: [{ text: line, x: 0 }], width: len(ctx, line, rtl) };
  if (!rtl) {
    const pieces: Piece[] = [];
    let x = 0;
    for (const ch of Array.from(line)) {
      pieces.push({ text: ch, x });
      x += len(ctx, ch, false) + spacing;
    }
    return { pieces, width: Math.max(0, x - spacing) };
  }
  const words = line.split(" ");
  const space = len(ctx, " ", true);
  const widths = words.map((w) => len(ctx, w, true));
  const total = widths.reduce((a, b) => a + b, 0) + (words.length - 1) * (space + spacing);
  const pieces: Piece[] = [];
  let x = total;
  words.forEach((w, i) => {
    pieces.push({ text: w, x: x - widths[i] });
    x -= widths[i] + space + spacing;
  });
  return { pieces, width: total };
}

/** مثلِ textlayer.render_text ⇐ بوم + اندازه‌ها. canvasW = پهنای بومِ کاری (پیکسل) */
export function rasterText(layer: TextLayer, canvasW: number, canvasH: number): TextRaster | null {
  const text = String(layer.text ?? "");
  if (!text.trim()) return null;
  const sizePx = Math.max(4, layer.size * canvasW);
  const ctx = mctx();
  ctx.font = fontStr(layer.weight, sizePx);
  const widthPx = (layer.width || 0) * canvasW;
  let lines: string[];
  if (layer.lines && layer.lines.length) lines = layer.lines.slice(0, MAX_LINES);
  else if (widthPx > 0) lines = wrapLines(ctx, text, widthPx);
  else {
    // auto width: a line longer than 94% of the canvas width is wrapped (same as the server)
    lines = [];
    const limit = 0.94 * canvasW;
    for (const para of text.split("\n")) {
      if (len(ctx, para, isRtlText(para)) > limit) lines.push(...wrapLines(ctx, para, limit));
      else lines.push(para);
    }
    lines = lines.slice(0, MAX_LINES);
  }
  const spacing = (layer.letter_spacing || 0) * sizePx;
  const fm = ctx.measureText("Hxگ");
  const asc = Math.round(fm.fontBoundingBoxAscent ?? sizePx * 1.0);
  const desc = Math.round(fm.fontBoundingBoxDescent ?? sizePx * 0.4);
  const lh = sizePx * (layer.line_height || 1.35);
  const baseY = (lh - (asc + desc)) / 2 + asc;

  const laid = lines.map((line) => {
    const rtl = layer.dir === "rtl" || (layer.dir === "auto" && isRtlText(line));
    const { pieces, width } = linePieces(ctx, line, rtl, spacing);
    return { line, rtl, pieces, width };
  });
  const contentW = Math.max(1, ...laid.map((l) => l.width));
  const blockW = widthPx > 0 ? Math.max(widthPx, contentW) : contentW;
  const blockH = lh * laid.length;

  const stroke = layer.stroke;
  const shadow = layer.shadow;
  const box = layer.box;
  const strokePx = stroke ? Math.round(stroke.w * sizePx) : 0;
  const pad = box ? box.pad * sizePx : 0;
  const shBlur = shadow ? shadow.blur * sizePx : 0;
  const shDx = shadow ? shadow.dx * sizePx : 0;
  const shDy = shadow ? shadow.dy * sizePx : 0;
  const margin = Math.ceil(Math.max(strokePx + 2, pad + 2, Math.abs(shDx) + shBlur * 3 + 2, Math.abs(shDy) + shBlur * 3 + 2));
  const tw = Math.min(MAX_TILE, Math.ceil(blockW + 2 * margin));
  const th = Math.min(MAX_TILE, Math.ceil(blockH + 2 * margin));

  const tile = mk(tw, th);
  const t = tile.getContext("2d")!;
  const ox = margin;
  const oy = margin;
  if (box) {
    t.fillStyle = hexA(box.color, box.opacity);
    const rr = box.radius * sizePx;
    t.beginPath();
    if (t.roundRect) t.roundRect(ox - pad, oy - pad, blockW + 2 * pad, blockH + 2 * pad, rr);
    else t.rect(ox - pad, oy - pad, blockW + 2 * pad, blockH + 2 * pad);
    t.fill();
  }
  const glyphs = mk(tw, th);
  const g = glyphs.getContext("2d")!;
  g.font = fontStr(layer.weight, sizePx);
  g.textAlign = "left";
  g.textBaseline = "alphabetic";
  g.lineJoin = "round";
  g.miterLimit = 2;
  laid.forEach((l, i) => {
    if (!l.line.trim()) return;
    const x0 = layer.align === "right" ? blockW - l.width : layer.align === "left" ? 0 : (blockW - l.width) / 2;
    const y = oy + i * lh + baseY;
    g.direction = l.rtl ? "rtl" : "ltr";
    for (const p of l.pieces) {
      if (strokePx && stroke) {
        g.lineWidth = strokePx * 2;
        g.strokeStyle = stroke.color;
        g.strokeText(p.text, ox + x0 + p.x, y);
      }
      g.fillStyle = layer.color;
      g.fillText(p.text, ox + x0 + p.x, y);
    }
  });
  if (shadow) {
    const sc = mk(tw, th);
    const s = sc.getContext("2d")!;
    s.drawImage(glyphs, 0, 0);
    s.globalCompositeOperation = "source-in";
    s.fillStyle = shadow.color;
    s.fillRect(0, 0, tw, th);
    t.save();
    t.globalAlpha = shadow.opacity;
    if (shBlur > 0.3 && "filter" in t) t.filter = `blur(${shBlur}px)`;
    t.drawImage(sc, shDx, shDy);
    t.restore();
  }
  t.drawImage(glyphs, 0, 0);

  if (layer.tile) return { canvas: tilePattern(tile, canvasW, canvasH, layer.tile.angle, layer.tile.gap), bw: 1, bh: canvasH / canvasW, cw: blockW / canvasW, ch: blockH / canvasW, lines, full: true };
  return { canvas: tile, bw: tw / canvasW, bh: th / canvasW, cw: blockW / canvasW, ch: blockH / canvasW, lines, full: false };
}

/** مثلِ textlayer.tile_pattern */
function tilePattern(tile: HTMLCanvasElement, w: number, h: number, angle: number, gap: number): HTMLCanvasElement {
  const a = (angle * Math.PI) / 180;
  const rw = Math.ceil(Math.abs(tile.width * Math.cos(a)) + Math.abs(tile.height * Math.sin(a)));
  const rh = Math.ceil(Math.abs(tile.width * Math.sin(a)) + Math.abs(tile.height * Math.cos(a)));
  const rot = mk(rw, rh);
  const r = rot.getContext("2d")!;
  r.translate(rw / 2, rh / 2);
  r.rotate(a);
  r.drawImage(tile, -tile.width / 2, -tile.height / 2);
  const out = mk(w, h);
  const o = out.getContext("2d")!;
  const stepX = Math.max(8, Math.floor(rw * gap));
  const stepY = Math.max(8, Math.floor(rh * gap * 1.35));
  let n = 0;
  let row = 0;
  for (let yy = -Math.floor(rh / 2); yy < h; yy += stepY, row++) {
    for (let xx = -Math.floor(rw / 2) + Math.floor(((row % 2) * stepX) / 2); xx < w; xx += stepX) {
      o.drawImage(rot, xx, yy);
      if (++n > 4000) return out;
    }
  }
  return out;
}

export type ShapeRaster = { canvas: HTMLCanvasElement; bw: number; bh: number };

/** مثلِ layers._render_shape */
export function rasterShape(layer: ShapeLayer, W: number): ShapeRaster | null {
  const wpx = layer.w * W;
  let hpx = layer.h * W;
  const sw = layer.stroke ? layer.stroke.w * W : 0;
  if (layer.shape === "line") hpx = Math.max(hpx, 0);
  const boxH = layer.shape === "line" ? Math.max(hpx, sw) + 2 : hpx;
  const pad = Math.ceil(sw / 2) + 2;
  const tw = Math.min(MAX_TILE, Math.ceil(wpx) + 2 * pad);
  const th = Math.min(MAX_TILE, Math.ceil(boxH) + 2 * pad);
  if (tw < 2 || th < 2) return null;
  const c = mk(tw, th);
  const g = c.getContext("2d")!;
  const x0 = pad;
  const y0 = pad;
  const x1 = pad + wpx;
  const y1 = pad + boxH;
  const path = (inset: number) => {
    g.beginPath();
    if (layer.shape === "ellipse") g.ellipse((x0 + x1) / 2, (y0 + y1) / 2, Math.max(0.1, (x1 - x0) / 2 - inset), Math.max(0.1, (y1 - y0) / 2 - inset), 0, 0, Math.PI * 2);
    else {
      const rad = (layer.radius * Math.min(x1 - x0, y1 - y0)) / 2;
      if (rad > 0.5 && g.roundRect) g.roundRect(x0 + inset, y0 + inset, x1 - x0 - 2 * inset, y1 - y0 - 2 * inset, Math.max(0, rad - inset));
      else g.rect(x0 + inset, y0 + inset, x1 - x0 - 2 * inset, y1 - y0 - 2 * inset);
    }
  };
  if (layer.shape !== "line" && layer.fill) {
    path(0);
    if (layer.fill.type === "gradient") {
      const a = (layer.fill.angle * Math.PI) / 180;
      const dx = Math.cos(a);
      const dy = Math.sin(a);
      const half = Math.max(1e-6, (Math.abs(dx) * tw + Math.abs(dy) * th) / 2);
      const cx = (tw - 1) / 2;
      const cy = (th - 1) / 2;
      const gr = g.createLinearGradient(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half);
      gr.addColorStop(0, layer.fill.c0);
      gr.addColorStop(1, layer.fill.c1);
      g.fillStyle = gr;
      g.fill();
    } else {
      g.fillStyle = hexA(layer.fill.color, layer.fill.opacity);
      g.fill();
    }
  }
  if (layer.stroke && sw > 0) {
    g.strokeStyle = layer.stroke.color;
    g.lineWidth = Math.max(1, sw);
    if (layer.shape === "line") {
      g.beginPath();
      g.moveTo(x0, (y0 + y1) / 2);
      g.lineTo(x1, (y0 + y1) / 2);
      g.stroke();
    } else {
      path(sw / 2);
      g.stroke();
    }
  }
  return { canvas: c, bw: tw / W, bh: th / W };
}

// ───────────────────────────── جدولِ منحنی‌ها (مثلِ Tone.ApplyCurves)

export const LUT_N = 1024;

export function splineFn(points: Pt[]): (x: number) => number {
  const p = [...points].sort((a, b) => a[0] - b[0]).map((q) => ({ x: q[0] / 255, y: q[1] / 255 }));
  const n = p.length;
  if (n === 1) return () => p[0].y;
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((p[i + 1].y - p[i].y) / Math.max(1e-9, p[i + 1].x - p[i].x));
  const m: number[] = new Array(n).fill(0);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const h = a * a + b * b;
    if (h > 9) {
      const t = 3 / Math.sqrt(h);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  return (x: number) => {
    if (x <= p[0].x) return p[0].y;
    if (x >= p[n - 1].x) return p[n - 1].y;
    let k = 0;
    while (k < n - 2 && x > p[k + 1].x) k++;
    const h = p[k + 1].x - p[k].x;
    const t = (x - p[k].x) / h;
    const t2 = t * t;
    const t3 = t2 * t;
    return (2 * t3 - 3 * t2 + 1) * p[k].y + (t3 - 2 * t2 + t) * h * m[k] + (-2 * t3 + 3 * t2) * p[k + 1].y + (t3 - t2) * h * m[k + 1];
  };
}

const g0 = (a: Adjust, k: string, d = 0) => (typeof a[k] === "number" ? a[k] : d);

/** null = بی‌اثر. خروجی RGBA ِ (LUT_N+1)×1 */
export function buildCurveLut(a: Adjust, curve: Curve): Uint8Array | null {
  const lb0 = g0(a, "levelsBlack", 0) / 255;
  let lw = g0(a, "levelsWhite", 255) / 255;
  const gm = g0(a, "levelsGamma", 1);
  if (lw < lb0 + 0.02) lw = Math.min(1, lb0 + 0.02);
  const blacks = g0(a, "blacks") / 100;
  const whites = g0(a, "whites") / 100;
  const contrast = g0(a, "contrast") / 100;
  const bright = g0(a, "brightness") / 100;
  const identity = lb0 === 0 && lw === 1 && gm === 1 && blacks === 0 && whites === 0 && contrast === 0 && bright === 0;
  const has = (pts?: Pt[]) => !!pts && pts.length >= 2;
  if (identity && !has(curve.rgb) && !has(curve.red) && !has(curve.green) && !has(curve.blue)) return null;
  const ib = -blacks * 0.12;
  const iw = 1 - whites * 0.12;
  const ca = contrast > 0 ? contrast * 0.45 : contrast * 0.6;
  const gamma = Math.pow(2, -bright * 0.8);
  const base = new Float64Array(LUT_N + 1);
  for (let i = 0; i <= LUT_N; i++) {
    let x = i / LUT_N;
    x = Math.pow(Math.min(1, Math.max(0, (x - lb0) / (lw - lb0))), 1 / gm);
    x = Math.min(1, Math.max(0, (x - ib) / (iw - ib)));
    x += ca * 4 * (x - 0.5) * x * (1 - x);
    x = Math.pow(Math.min(1, Math.max(0, x)), gamma);
    base[i] = x;
  }
  const rgb = has(curve.rgb) ? splineFn(curve.rgb!) : null;
  const chans = [curve.red, curve.green, curve.blue].map((pts) => (has(pts) ? splineFn(pts!) : null));
  const out = new Uint8Array((LUT_N + 1) * 4);
  for (let i = 0; i <= LUT_N; i++) {
    for (let c = 0; c < 3; c++) {
      let v = base[i];
      if (rgb) v = rgb(v);
      const s = chans[c];
      if (s) v = s(v);
      out[i * 4 + c] = Math.round(Math.min(1, Math.max(0, v)) * 255);
    }
    out[i * 4 + 3] = 255;
  }
  return out;
}

// ───────────────────────────── قلم

/** آلفای یک گروه ضربهٔ روتوش (مثلِ _apply_retouch): سطحِ خاکستریِ کامل‌اندازه؛ هر ضربه max روی مهره‌ها، گروه screen */
export function rasterStrokes(strokes: Stroke[], w: number, h: number): HTMLCanvasElement {
  const out = mk(w, h);
  const o = out.getContext("2d")!;
  o.fillStyle = "#000";
  o.fillRect(0, 0, w, h);
  for (const s of strokes) {
    if (!s.pts.length) continue;
    const r = Math.max(1, s.r * w);
    const pts = s.pts.map((p) => [p[0] * w, p[1] * h]);
    const bx0 = Math.max(0, Math.floor(Math.min(...pts.map((p) => p[0])) - r - 1));
    const by0 = Math.max(0, Math.floor(Math.min(...pts.map((p) => p[1])) - r - 1));
    const bx1 = Math.min(w, Math.ceil(Math.max(...pts.map((p) => p[0])) + r + 1));
    const by1 = Math.min(h, Math.ceil(Math.max(...pts.map((p) => p[1])) + r + 1));
    if (bx1 <= bx0 || by1 <= by0) continue;
    const sc = mk(bx1 - bx0, by1 - by0);
    const c = sc.getContext("2d")!;
    c.fillStyle = "#000";
    c.fillRect(0, 0, sc.width, sc.height);
    c.globalCompositeOperation = "lighten";
    const inner = Math.min(0.999, s.hardness);
    const v = Math.round(255 * s.opacity);
    const stops: string[] = [];
    for (let k = 0; k <= 10; k++) {
      const t = k / 10;
      const u = Math.min(1, Math.max(0, (t - inner) / Math.max(1e-6, 1 - inner)));
      const g2 = Math.round(v * (1 - u * u * (3 - 2 * u)));
      stops.push(`rgb(${g2},${g2},${g2})`);
    }
    const stamp = (x: number, y: number) => {
      const gr = c.createRadialGradient(x, y, 0, x, y, r);
      stops.forEach((col, k) => gr.addColorStop(k / 10, col));
      c.fillStyle = gr;
      c.fillRect(x - r, y - r, 2 * r, 2 * r);
    };
    const step = Math.max(1, r * 0.12);
    stamp(pts[0][0] - bx0, pts[0][1] - by0);
    for (let i = 1; i < pts.length; i++) {
      const [ax, ay] = pts[i - 1];
      const [bx, by] = pts[i];
      const n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / step));
      for (let k = 1; k <= n; k++) stamp(ax + ((bx - ax) * k) / n - bx0, ay + ((by - ay) * k) / n - by0);
    }
    o.globalCompositeOperation = "screen";
    o.drawImage(sc, bx0, by0);
  }
  return out;
}

/** یک مهرِ قلم روی بومِ ماسک. paint: سفید/سیاه با شدتِ flow؛ سختی hardness */
export function maskStamp(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, hardness: number, flow: number, white: boolean): void {
  const gr = ctx.createRadialGradient(x, y, 0, x, y, r);
  const col = white ? "255,255,255" : "0,0,0";
  const inner = Math.min(0.999, hardness);
  for (let k = 0; k <= 10; k++) {
    const t = k / 10;
    const u = Math.min(1, Math.max(0, (t - inner) / Math.max(1e-6, 1 - inner)));
    const f = 1 - u * u * (3 - 2 * u);
    gr.addColorStop(t, `rgba(${col},${(f * flow).toFixed(4)})`);
  }
  ctx.fillStyle = gr;
  ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
}

export function maskLine(ctx: CanvasRenderingContext2D, ax: number, ay: number, bx: number, by: number, r: number, hardness: number, flow: number, white: boolean): void {
  const step = Math.max(1, r * 0.18);
  const dist = Math.hypot(bx - ax, by - ay);
  const n = Math.max(1, Math.ceil(dist / step));
  for (let k = 1; k <= n; k++) maskStamp(ctx, ax + ((bx - ax) * k) / n, ay + ((by - ay) * k) / n, r, hardness, flow, white);
}

export const newCanvas = mk;
