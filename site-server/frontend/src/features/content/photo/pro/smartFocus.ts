/**
 * «سوژه (خودکار)» برای قابِ cover — بازتولیدِ ops._energy_offset در مرورگر (روی کوچک‌نمایِ ۳۲۰ پیکسلیِ عکسِ پس از هندسه).
 * پیش‌نمایش و خروجی یک پنجره را می‌بینند: مرورگر پنجره را حساب می‌کند و در کارِ crop_format به‌صورتِ window می‌فرستد.
 */

export const ENERGY_SIDE = 320;

export type EnergyMap = { e: Float32Array; w: number; h: number };

/** اندازهٔ کوچک‌نمای PIL.thumbnail((side, side)): فقط کوچک می‌کند، نسبت را نگه می‌دارد */
export function thumbSize(w: number, h: number, side = ENERGY_SIDE): [number, number] {
  if (w <= side && h <= side) return [w, h];
  const aspect = w / h;
  let x = side;
  let y = side;
  if (x / y >= aspect) x = Math.max(1, Math.round(y * aspect));
  else y = Math.max(1, Math.round(x / aspect));
  return [x, y];
}

/**
 * RGBA ِ کوچک‌نما ⇒ نقشهٔ «انرژی»: آلفا اگر عکس شفاف باشد (خودِ کالا)، وگرنه گرادیانِ روشنایی با سهمِ وسط.
 * روشنایی مثلِ PIL «L»: (R·19595 + G·38470 + B·7471 + 0x8000) >> 16.
 */
export function energyMap(rgba: Uint8ClampedArray, w: number, h: number, useAlpha: boolean, center = true): EnergyMap {
  const e = new Float32Array(w * h);
  if (useAlpha) {
    for (let i = 0, p = 0; p < e.length; i += 4, p++) e[p] = rgba[i + 3];
    return { e, w, h };
  }
  const g = new Float32Array(w * h);
  for (let i = 0, p = 0; p < g.length; i += 4, p++) g[p] = (rgba[i] * 19595 + rgba[i + 1] * 38470 + rgba[i + 2] * 7471 + 0x8000) >> 16;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const p = y * w + x;
      const gx = x < w - 1 ? Math.abs(g[p + 1] - g[p]) : 0;
      const gy = y < h - 1 ? Math.abs(g[p + w] - g[p]) : 0;
      e[p] = gx + gy;
    }
  }
  if (!center) return { e, w, h }; // «جعبهٔ کالا» سهمِ وسط نمی‌خواهد (مثلِ ops._energy_arrays(center=False))
  // کمی سهمِ وسط: عکاس سوژه را وسط می‌گذارد؛ لبهٔ پرجزئیاتِ پس‌زمینه نباید برنده شود
  const cy = (h - 1) / 2;
  const cx = (w - 1) / 2;
  for (let y = 0; y < h; y++) {
    const dy = (y - cy) / (0.45 * h);
    for (let x = 0; x < w; x++) {
      const dx = (x - cx) / (0.45 * w);
      e[y * w + x] *= 1 + 0.6 * Math.exp(-(dy * dy + dx * dx));
    }
  }
  return { e, w, h };
}

// ───────────── «کالا وسطِ قاب»: جعبهٔ کالا از همان نقشهٔ انرژی — بازتولیدِ عینِ ops._subject_box / subject_view_from_box
// (همان ثابت‌ها؛ سرور فقط وقتی خودش تشخیص می‌دهد که مرورگر view نفرستاده باشد)

export const SUBJECT_MIN_FRAC = 0.004; // پیکسل‌های «سوژه» کمتر از این کسرِ کوچک‌نما ⇒ نویز ⇒ کلِ عکس
export const SUBJECT_TRIM = 0.003; // از هر سو این کسرِ جرم بریده می‌شود (لکهٔ تنها دور افتد)
export const SUBJECT_ALPHA_MIN = 32; // آلفای کمتر از این «سوژه» نیست
export const SUBJECT_ENERGY_MIN = 12; // انرژیِ کمتر از این (نویزِ JPEG) هیچ‌وقت سوژه نیست
export const SUBJECT_ENERGY_REL = 0.2; // … و کمتر از این کسر از صدکِ ۹۹
export const SUBJECT_ZOOM_MAX = 6;
export const SUBJECT_ZOOM_MIN = 1.08; // کمتر از این ⇒ کلِ عکس (همان جا دادنِ قدیمی)

/** numpy.percentile (درون‌یابیِ خطی) روی آرایهٔ عددی */
export function percentile(v: Float32Array, q: number): number {
  const s = Float32Array.from(v).sort();
  const pos = (q / 100) * (s.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.min(s.length - 1, lo + 1);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

function trimmedSpan(counts: Float64Array, trim: number): [number, number] {
  let acc = 0;
  let lo = 0;
  for (let i = 0; i < counts.length; i++) {
    acc += counts[i];
    if (acc > trim) {
      lo = i;
      break;
    }
  }
  acc = 0;
  let hi = counts.length - 1;
  for (let i = counts.length - 1; i >= 0; i--) {
    acc += counts[i];
    if (acc > trim) {
      hi = i;
      break;
    }
  }
  return [lo, hi + 1];
}

/** جعبهٔ پیکسل‌های سوژه در کوچک‌نما [x0, y0, x1, y1] (x1/y1 انحصاری) یا null (تشخیص نشد) */
export function subjectBox(m: EnergyMap, alpha: boolean): [number, number, number, number] | null {
  const n = m.w * m.h;
  const thr = alpha ? SUBJECT_ALPHA_MIN : Math.max(SUBJECT_ENERGY_MIN, SUBJECT_ENERGY_REL * percentile(m.e, 99));
  const col = new Float64Array(m.w);
  const row = new Float64Array(m.h);
  let total = 0;
  for (let y = 0; y < m.h; y++) {
    for (let x = 0; x < m.w; x++) {
      const v = m.e[y * m.w + x];
      if (alpha ? v >= thr : v > thr) {
        col[x]++;
        row[y]++;
        total++;
      }
    }
  }
  if (total < SUBJECT_MIN_FRAC * n) return null;
  const trim = SUBJECT_TRIM * total;
  let [x0, x1] = trimmedSpan(col, trim);
  let [y0, y1] = trimmedSpan(row, trim);
  if (!alpha) {
    // انرژی تفاضلِ رو‌به‌جلو است: لبه‌ای بینِ پیکسلِ i و i+1 در اندیسِ i می‌افتد ⇒ مرزِ بالا/چپ یک پیکسل جلوتر است
    x0 = Math.min(x0 + 1, x1 - 1);
    y0 = Math.min(y0 + 1, y1 - 1);
  }
  return x1 > x0 && y1 > y0 ? [x0, y0, x1, y1] : null;
}

const r4 = (x: number) => Math.round(x * 1e4) / 1e4;
const r5 = (x: number) => Math.round(x * 1e5) / 1e5;

/**
 * جعبهٔ کالا (پیکسلِ عکسِ w×h) ⇒ [zoom, cx, cy] یا null (کالا تقریباً کلِ عکس است).
 * zoom نسبت به «کلِ عکس در قاب»: min(tw/bw, th/bh) / min(tw/w, th/h)؛ کالا بُعدِ بزرگ‌ترش را تا حاشیه پر می‌کند.
 */
export function subjectViewFromBox(w: number, h: number, box: [number, number, number, number], tw: number, th: number): number[] | null {
  const [x0, y0, x1, y1] = box;
  const bw = Math.max(1, x1 - x0);
  const bh = Math.max(1, y1 - y0);
  const zoom = Math.min(SUBJECT_ZOOM_MAX, Math.min(tw / bw, th / bh) / Math.min(tw / w, th / h));
  if (zoom < SUBJECT_ZOOM_MIN) return null;
  return [r4(zoom), r5((x0 + x1) / 2 / w), r5((y0 + y1) / 2 / h)];
}

/** نقشهٔ انرژیِ (بی سهمِ وسط) ⇒ جای دوربینِ «کالا وسطِ قاب» برای عکسِ imgW×imgH و قابِ tw×th؛ تشخیص نشد ⇒ null (= کلِ عکس) */
export function subjectView(m: EnergyMap, alpha: boolean, imgW: number, imgH: number, tw: number, th: number): number[] | null {
  const box = subjectBox(m, alpha);
  if (!box) return null;
  const sx = m.w / imgW;
  const sy = m.h / imgH;
  return subjectViewFromBox(imgW, imgH, [box[0] / sx, box[1] / sy, box[2] / sx, box[3] / sy], tw, th);
}

function bestWindow(sums: Float64Array, win: number): number {
  const c = new Float64Array(sums.length + 1);
  for (let i = 0; i < sums.length; i++) c[i + 1] = c[i] + sums[i];
  let best = 0;
  let bestV = -Infinity;
  for (let i = 0; i + win < c.length; i++) {
    const v = c[i + win] - c[i];
    if (v > bestV) {
      bestV = v;
      best = i;
    }
  }
  return best;
}

/**
 * بالا-چپِ بهترین پنجرهٔ cropW×cropH (پیکسلِ تصویرِ اصلِ پس از هندسه، imgW×imgH) — argmax ِ مجموعِ تجمعی.
 * همان محاسبهٔ ops._energy_offset (بر پایهٔ نسبتِ کوچک‌نما به تصویر).
 */
export function energyOffset(m: EnergyMap, imgW: number, imgH: number, cropW: number, cropH: number): [number, number] {
  const sx = m.w / imgW;
  const sy = m.h / imgH;
  const cw = Math.max(1, Math.round(cropW * sx));
  const ch = Math.max(1, Math.round(cropH * sy));
  let bx = 0;
  let by = 0;
  if (cw < m.w) {
    const col = new Float64Array(m.w);
    for (let y = 0; y < m.h; y++) for (let x = 0; x < m.w; x++) col[x] += m.e[y * m.w + x];
    bx = bestWindow(col, cw);
  }
  if (ch < m.h) {
    const row = new Float64Array(m.h);
    for (let y = 0; y < m.h; y++) {
      let s = 0;
      for (let x = 0; x < m.w; x++) s += m.e[y * m.w + x];
      row[y] = s;
    }
    by = bestWindow(row, ch);
  }
  return [Math.trunc(bx / sx), Math.trunc(by / sy)];
}
