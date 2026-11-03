import { useEffect, useRef, useState } from "react";

import "./scopes.css";

/**
 * اسکوپ‌ها (Waveform / Vectorscope / Histogram / RGB Parade) از روی فریمِ زیرِ سرِ پخش.
 * خودش ≤ ۶۰ هزار پیکسل نمونه می‌گیرد؛ هر بار `version` عوض شد دوباره می‌کشد.
 */
export type ScopeMode = "wave" | "vector" | "hist" | "parade";

const MODES: { key: ScopeMode; title: string }[] = [
  { key: "wave", title: "موج (Waveform)" },
  { key: "vector", title: "برداری (Vectorscope)" },
  { key: "hist", title: "هیستوگرام" },
  { key: "parade", title: "پریدِ RGB" },
];

export const SCOPE_W = 320;
export const SCOPE_H = 180;
const MAX_SAMPLES = 60000;
const BG: [number, number, number] = [10, 13, 20];
const FA = "۰۱۲۳۴۵۶۷۸۹";
const fa = (n: number) => String(n).replace(/\d/g, (d) => FA[Number(d)]);

type Sample = { w: number; h: number; stride: number; d: Uint8ClampedArray };
const sampleOf = (img: ImageData): Sample => ({ w: img.width, h: img.height, stride: Math.max(1, Math.floor(Math.sqrt((img.width * img.height) / MAX_SAMPLES))), d: img.data });

function frameBase(ctx: CanvasRenderingContext2D): ImageData {
  const out = ctx.createImageData(SCOPE_W, SCOPE_H);
  for (let i = 0; i < out.data.length; i += 4) {
    out.data[i] = BG[0];
    out.data[i + 1] = BG[1];
    out.data[i + 2] = BG[2];
    out.data[i + 3] = 255;
  }
  return out;
}

/** چگالی (تعداد) ⇒ روشنایی ۰..۱ */
const glow = (count: number, ref: number) => {
  const v = count / ref;
  return v <= 0 ? 0 : Math.min(1, Math.pow(v, 0.65));
};

function addPixel(out: ImageData, x: number, y: number, r: number, g: number, b: number, v: number) {
  if (v <= 0 || x < 0 || y < 0 || x >= SCOPE_W || y >= SCOPE_H) return;
  const i = (y * SCOPE_W + x) * 4;
  out.data[i] = Math.min(255, out.data[i] + r * v);
  out.data[i + 1] = Math.min(255, out.data[i + 1] + g * v);
  out.data[i + 2] = Math.min(255, out.data[i + 2] + b * v);
}

type Plot = { x0: number; y0: number; w: number; h: number };
const WAVE_PLOT: Plot = { x0: 26, y0: 8, w: SCOPE_W - 26 - 6, h: SCOPE_H - 16 };

/** یک موج برای کانالِ `pick` (لوما یا یکی از R/G/B) در بازهٔ افقیِ `plot` */
function waveInto(out: ImageData, s: Sample, plot: Plot, color: [number, number, number], pick: (r: number, g: number, b: number) => number) {
  const grid = new Float32Array(plot.w * plot.h);
  for (let y = 0; y < s.h; y += s.stride) {
    for (let x = 0; x < s.w; x += s.stride) {
      const i = (y * s.w + x) * 4;
      const v = pick(s.d[i], s.d[i + 1], s.d[i + 2]);
      const col = Math.min(plot.w - 1, Math.floor((x / s.w) * plot.w));
      const row = Math.min(plot.h - 1, Math.max(0, Math.round((1 - v / 255) * (plot.h - 1))));
      grid[row * plot.w + col] += 1;
    }
  }
  const perCol = Math.max(1, (s.h / s.stride) * (s.w / s.stride) / plot.w);
  const ref = Math.max(2, perCol * 0.09);
  for (let row = 0; row < plot.h; row++) {
    for (let col = 0; col < plot.w; col++) {
      const c = grid[row * plot.w + col];
      if (c) addPixel(out, plot.x0 + col, plot.y0 + row, color[0], color[1], color[2], glow(c, ref));
    }
  }
}

function waveGraticule(ctx: CanvasRenderingContext2D, plot: Plot, x1 = plot.x0 + plot.w) {
  ctx.save();
  ctx.font = "9px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.lineWidth = 1;
  for (const pct of [0, 25, 50, 75, 100]) {
    const y = plot.y0 + (1 - pct / 100) * (plot.h - 1) + 0.5;
    ctx.strokeStyle = pct === 0 || pct === 100 ? "rgba(255,255,255,.35)" : "rgba(255,255,255,.16)";
    ctx.beginPath();
    ctx.moveTo(plot.x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,.6)";
    ctx.fillText(fa(pct), plot.x0 - 4, y);
  }
  ctx.restore();
}

function drawWave(ctx: CanvasRenderingContext2D, s: Sample) {
  const out = frameBase(ctx);
  waveInto(out, s, WAVE_PLOT, [90, 255, 140], (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b);
  ctx.putImageData(out, 0, 0);
  waveGraticule(ctx, WAVE_PLOT);
}

function drawParade(ctx: CanvasRenderingContext2D, s: Sample) {
  const out = frameBase(ctx);
  const gap = 4;
  const each = Math.floor((WAVE_PLOT.w - gap * 2) / 3);
  const chans: { c: [number, number, number]; pick: (r: number, g: number, b: number) => number }[] = [
    { c: [255, 80, 80], pick: (r) => r },
    { c: [80, 255, 100], pick: (_r, g) => g },
    { c: [90, 140, 255], pick: (_r, _g, b) => b },
  ];
  chans.forEach((ch, i) => waveInto(out, s, { x0: WAVE_PLOT.x0 + i * (each + gap), y0: WAVE_PLOT.y0, w: each, h: WAVE_PLOT.h }, ch.c, ch.pick));
  ctx.putImageData(out, 0, 0);
  waveGraticule(ctx, WAVE_PLOT);
  ctx.save();
  ctx.fillStyle = "rgba(255,255,255,.55)";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "center";
  ["R", "G", "B"].forEach((t, i) => ctx.fillText(t, WAVE_PLOT.x0 + i * (each + gap) + each / 2, SCOPE_H - 1));
  ctx.restore();
}

/** BT.709: Cb/Cr در بازهٔ ±۰٫۵ */
function cbcr(r: number, g: number, b: number): [number, number] {
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return [(b - y) / 1.8556 / 255, (r - y) / 1.5748 / 255];
}

function drawVector(ctx: CanvasRenderingContext2D, s: Sample) {
  const out = frameBase(ctx);
  const R = Math.floor(Math.min(SCOPE_W, SCOPE_H) / 2) - 6;
  const cx = SCOPE_W / 2;
  const cy = SCOPE_H / 2;
  const grid = new Float32Array(SCOPE_W * SCOPE_H);
  for (let y = 0; y < s.h; y += s.stride) {
    for (let x = 0; x < s.w; x += s.stride) {
      const i = (y * s.w + x) * 4;
      const [cb, cr] = cbcr(s.d[i], s.d[i + 1], s.d[i + 2]);
      const px = Math.round(cx + (cb / 0.5) * R);
      const py = Math.round(cy - (cr / 0.5) * R);
      if (px >= 0 && py >= 0 && px < SCOPE_W && py < SCOPE_H) grid[py * SCOPE_W + px] += 1;
    }
  }
  const total = (s.w / s.stride) * (s.h / s.stride);
  const ref = Math.max(2, total / 700);
  for (let p = 0; p < grid.length; p++) {
    if (grid[p]) {
      const v = glow(grid[p], ref);
      // dilate by one pixel to the right/down so sparse dots stay visible
      const x = p % SCOPE_W;
      const y = (p / SCOPE_W) | 0;
      addPixel(out, x, y, 90, 255, 140, v);
      addPixel(out, x + 1, y, 90, 255, 140, v * 0.5);
      addPixel(out, x, y + 1, 90, 255, 140, v * 0.5);
    }
  }
  ctx.putImageData(out, 0, 0);
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,.22)";
  ctx.lineWidth = 1;
  for (const k of [1, 0.5]) {
    ctx.beginPath();
    ctx.arc(cx, cy, R * k, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.moveTo(cx - R, cy);
  ctx.lineTo(cx + R, cy);
  ctx.moveTo(cx, cy - R);
  ctx.lineTo(cx, cy + R);
  ctx.stroke();
  // خطِ رنگِ پوست (۱۲۳°) و هدف‌های ۷۵٪ رنگ‌ها
  const a = (123 * Math.PI) / 180;
  ctx.strokeStyle = "rgba(255,190,120,.75)";
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(a) * R, cy - Math.sin(a) * R);
  ctx.stroke();
  ctx.font = "9px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const targets: [string, number, number, number][] = [["R", 191, 0, 0], ["Mg", 191, 0, 191], ["B", 0, 0, 191], ["Cy", 0, 191, 191], ["G", 0, 191, 0], ["Yl", 191, 191, 0]];
  for (const [label, r, g, b] of targets) {
    const [cb, cr] = cbcr(r, g, b);
    const x = cx + (cb / 0.5) * R;
    const y = cy - (cr / 0.5) * R;
    ctx.strokeStyle = `rgba(${r + 64},${g + 64},${b + 64},.9)`;
    ctx.strokeRect(x - 4.5, y - 4.5, 9, 9);
    ctx.fillStyle = "rgba(255,255,255,.55)";
    ctx.fillText(label, x + (x > cx ? 13 : -13), y);
  }
  ctx.restore();
}

function drawHist(ctx: CanvasRenderingContext2D, s: Sample) {
  const bins = [new Float32Array(256), new Float32Array(256), new Float32Array(256), new Float32Array(256)];
  let count = 0;
  for (let y = 0; y < s.h; y += s.stride) {
    for (let x = 0; x < s.w; x += s.stride) {
      const i = (y * s.w + x) * 4;
      const r = s.d[i], g = s.d[i + 1], b = s.d[i + 2];
      bins[0][r]++;
      bins[1][g]++;
      bins[2][b]++;
      bins[3][Math.round(0.2126 * r + 0.7152 * g + 0.0722 * b)]++;
      count++;
    }
  }
  ctx.fillStyle = `rgb(${BG[0]},${BG[1]},${BG[2]})`;
  ctx.fillRect(0, 0, SCOPE_W, SCOPE_H);
  const plot = { x0: 6, y0: 8, w: SCOPE_W - 12, h: SCOPE_H - 26 };
  let peak = 1;
  for (const b of bins) for (let i = 2; i < 254; i++) peak = Math.max(peak, b[i]);
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,.14)";
  ctx.lineWidth = 1;
  for (let q = 0; q <= 4; q++) {
    const x = plot.x0 + (q / 4) * plot.w + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, plot.y0);
    ctx.lineTo(x, plot.y0 + plot.h);
    ctx.stroke();
  }
  ctx.globalCompositeOperation = "lighter";
  const colors = ["rgba(255,60,60,.55)", "rgba(60,255,90,.55)", "rgba(70,120,255,.55)"];
  for (let c = 0; c < 3; c++) {
    ctx.fillStyle = colors[c];
    ctx.beginPath();
    ctx.moveTo(plot.x0, plot.y0 + plot.h);
    for (let i = 0; i < 256; i++) {
      const v = Math.min(1, Math.sqrt(bins[c][i] / (peak * 1.1)));
      ctx.lineTo(plot.x0 + (i / 255) * plot.w, plot.y0 + plot.h - v * plot.h);
    }
    ctx.lineTo(plot.x0 + plot.w, plot.y0 + plot.h);
    ctx.closePath();
    ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";
  ctx.strokeStyle = "rgba(255,255,255,.85)";
  ctx.beginPath();
  for (let i = 0; i < 256; i++) {
    const v = Math.min(1, Math.sqrt(bins[3][i] / (peak * 1.1)));
    const x = plot.x0 + (i / 255) * plot.w;
    const y = plot.y0 + plot.h - v * plot.h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  // اخطارِ بُریدگی (سیاهِ له‌شده / سفیدِ سوخته)
  const clipLo = (bins[3][0] + bins[3][1]) / Math.max(1, count);
  const clipHi = (bins[3][254] + bins[3][255]) / Math.max(1, count);
  ctx.font = "10px sans-serif";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "rgba(255,255,255,.55)";
  ctx.textAlign = "left";
  ctx.fillText(fa(0), plot.x0, SCOPE_H - 6);
  ctx.textAlign = "right";
  ctx.fillText(fa(255), plot.x0 + plot.w, SCOPE_H - 6);
  ctx.textAlign = "center";
  ctx.fillText(fa(128), plot.x0 + plot.w / 2, SCOPE_H - 6);
  if (clipLo > 0.02) {
    ctx.fillStyle = "#ef4444";
    ctx.fillRect(plot.x0, plot.y0, 4, plot.h);
  }
  if (clipHi > 0.02) {
    ctx.fillStyle = "#ef4444";
    ctx.fillRect(plot.x0 + plot.w - 4, plot.y0, 4, plot.h);
  }
  ctx.restore();
}

/** اسکوپِ `mode` را از روی `img` روی ctx می‌کشد (ctx باید SCOPE_W×SCOPE_H باشد) */
export function drawScope(ctx: CanvasRenderingContext2D, mode: ScopeMode, img: ImageData): void {
  const s = sampleOf(img);
  if (mode === "wave") drawWave(ctx, s);
  else if (mode === "parade") drawParade(ctx, s);
  else if (mode === "vector") drawVector(ctx, s);
  else drawHist(ctx, s);
}

export default function Scopes({ getFrame, version }: { getFrame: () => ImageData | null; version: number }) {
  const [mode, setMode] = useState<ScopeMode>("wave");
  const [empty, setEmpty] = useState(true);
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const img = getFrame();
    if (!img || img.width < 2 || img.height < 2) {
      ctx.fillStyle = `rgb(${BG[0]},${BG[1]},${BG[2]})`;
      ctx.fillRect(0, 0, SCOPE_W, SCOPE_H);
      setEmpty(true);
      return;
    }
    setEmpty(false);
    drawScope(ctx, mode, img);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, mode]);

  return (
    <div className="sc-wrap" dir="rtl" data-testid="scopes">
      <div className="ws-tabs sc-tabs" role="tablist">
        {MODES.map((m) => (
          <button key={m.key} type="button" role="tab" aria-selected={mode === m.key} className={mode === m.key ? "is-on" : ""} onClick={() => setMode(m.key)} data-scope={m.key}>
            {m.title}
          </button>
        ))}
      </div>
      <canvas ref={ref} className="sc-canvas" width={SCOPE_W} height={SCOPE_H} aria-label={MODES.find((m) => m.key === mode)?.title} />
      {empty && <p className="ws-hint sc-empty">اسکوپ‌ها از فریمِ زیرِ سرِ پخش ساخته می‌شوند؛ سرِ پخش را روی یک قطعهٔ تصویر بگذارید.</p>}
    </div>
  );
}
