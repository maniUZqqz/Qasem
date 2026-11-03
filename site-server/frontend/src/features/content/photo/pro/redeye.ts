/**
 * برآوردِ خودکارِ چشمِ قرمز از یک کلیک: لکهٔ قرمزِ دورِ نقطه را روی پیکسل‌های بومِ کاری (RGBA خام) پیدا می‌کند
 * (فلودفیلِ ۴-همسایه با همان معیارِ «قرمزی» ِ فرمولِ redeye.py: R/(میانگینِ G,B + 0.04) و روشنیِ R) و مرکز و شعاع را می‌دهد.
 * شعاعِ فرمول r طوری است که لکه داخلِ ۰٫۷۵·r (اثرِ کامل) بنشیند: r ≈ ۱٫۴۵ × شعاعِ لکه.
 * پیدا نشد ⇒ null (فراخواننده از لغزندهٔ اندازه استفاده می‌کند).
 */
export type EyeEstimate = { x: number; y: number; r: number };

const isRed = (d: Uint8ClampedArray, i: number): boolean => {
  const R = d[i] / 255;
  const neutral = (d[i + 1] + d[i + 2]) / 510;
  return R >= 0.3 && R / Math.max(1e-4, neutral + 0.04) >= 1.7;
};

/** data: RGBA ِ w×h؛ (px, py) = نقطهٔ کلیک به پیکسل؛ fallbackR = شعاعِ پیش‌فرض به پیکسل */
export function estimateEye(data: Uint8ClampedArray, w: number, h: number, px: number, py: number, fallbackR: number): EyeEstimate | null {
  const half = Math.max(20, Math.min(140, Math.round(w * 0.05)));
  const x0 = Math.max(0, Math.floor(px) - half);
  const x1 = Math.min(w - 1, Math.floor(px) + half);
  const y0 = Math.max(0, Math.floor(py) - half);
  const y1 = Math.min(h - 1, Math.floor(py) + half);
  const ww = x1 - x0 + 1;
  const hh = y1 - y0 + 1;
  if (ww < 3 || hh < 3) return null;
  // نزدیک‌ترین پیکسلِ قرمز به کلیک (تا شعاعِ جست‌وجو)
  const reach = Math.max(6, Math.round(fallbackR * 1.6));
  let sx = -1;
  let sy = -1;
  let best = Infinity;
  for (let y = Math.max(y0, Math.floor(py) - reach); y <= Math.min(y1, Math.floor(py) + reach); y++) {
    for (let x = Math.max(x0, Math.floor(px) - reach); x <= Math.min(x1, Math.floor(px) + reach); x++) {
      if (!isRed(data, (y * w + x) * 4)) continue;
      const dd = (x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2;
      if (dd < best) {
        best = dd;
        sx = x;
        sy = y;
      }
    }
  }
  if (sx < 0) return null;
  const seen = new Uint8Array(ww * hh);
  const stack: number[] = [(sy - y0) * ww + (sx - x0)];
  seen[stack[0]] = 1;
  let n = 0;
  let sumX = 0;
  let sumY = 0;
  let bx0 = sx;
  let bx1 = sx;
  let by0 = sy;
  let by1 = sy;
  let touchesEdge = false;
  while (stack.length) {
    const k = stack.pop()!;
    const x = (k % ww) + x0;
    const y = ((k / ww) | 0) + y0;
    n++;
    sumX += x;
    sumY += y;
    if (x < bx0) bx0 = x;
    if (x > bx1) bx1 = x;
    if (y < by0) by0 = y;
    if (y > by1) by1 = y;
    if (x === x0 || x === x1 || y === y0 || y === y1) touchesEdge = true;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = x + dx;
      const ny = y + dy;
      if (nx < x0 || nx > x1 || ny < y0 || ny > y1) continue;
      const nk = (ny - y0) * ww + (nx - x0);
      if (seen[nk]) continue;
      seen[nk] = 1;
      if (isRed(data, (ny * w + nx) * 4)) stack.push(nk);
    }
  }
  // لکهٔ پنجره‌پُرکن = چیزِ قرمزِ بزرگ (نه مردمک)
  if (touchesEdge || n < 3) return null;
  const rb = Math.max(Math.sqrt(n / Math.PI), (bx1 - bx0 + 1 + by1 - by0 + 1) / 4);
  const r = Math.min(0.1 * w, Math.max(2, rb * 1.45));
  const r5 = (v: number) => Math.round(v * 1e5) / 1e5;
  return { x: r5(((sumX / n) + 0.5) / w), y: r5(((sumY / n) + 0.5) / h), r: r5(r / w) };
}
