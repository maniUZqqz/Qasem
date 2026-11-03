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
export function energyMap(rgba: Uint8ClampedArray, w: number, h: number, useAlpha: boolean): EnergyMap {
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
