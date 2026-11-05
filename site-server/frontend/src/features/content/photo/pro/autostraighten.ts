/**
 * تشخیصِ خودکارِ کجیِ افق (بی مدل و بی سرور): جهتِ غالبِ لبه‌ها با «تانسورِ ساختار» (گرادیانِ Sobel، میانگین‌گیری در یک همسایگیِ
 * بلندتر از یک پلهٔ لبهٔ کج) خوانده می‌شود؛ لبه‌های نزدیک به افقی یا عمودی در یک هیستوگرامِ زاویه (±۱۵ درجه) وزن‌دهی می‌شوند و قله‌اش
 * کجیِ صحنه است. (زاویهٔ هر پیکسلِ لبه به‌تنهایی کافی نیست: روی لبهٔ پله‌پلهٔ کج بیشترِ پیکسل‌ها «صفر درجه» می‌خوانند.)
 * خروجی ``angle`` = کجیِ ساعتگردِ صحنه (درجه)؛ برای صاف کردن همان عدد به «صاف کردن» (straighten) داده می‌شود (همان قراردادِ سرور:
 * ``img.rotate(+angle)`` پادساعتگرد می‌چرخاند). ``confidence`` ۰..۱: سهمِ وزنِ لبه‌هایی که در ±۱° قله‌اند؛ زیرِ ۰٫۱۸ یعنی «مطمئن نیستم».
 */
export type Tilt = { angle: number; confidence: number; edges: number };

const RANGE = 15;
const BIN = 0.25;
const WORK = 320;
const RADIUS = 8;

/** میانگینِ جعبه‌ایِ جداپذیر با شعاعِ r (لبه‌ها تکرار می‌شوند) */
function boxBlur(src: Float32Array, w: number, h: number, r: number): Float32Array {
  const tmp = new Float32Array(w * h);
  const out = new Float32Array(w * h);
  const n = 2 * r + 1;
  for (let y = 0; y < h; y++) {
    let acc = 0;
    for (let k = -r; k <= r; k++) acc += src[y * w + Math.min(w - 1, Math.max(0, k))];
    for (let x = 0; x < w; x++) {
      tmp[y * w + x] = acc / n;
      acc += src[y * w + Math.min(w - 1, x + r + 1)] - src[y * w + Math.max(0, x - r)];
    }
  }
  for (let x = 0; x < w; x++) {
    let acc = 0;
    for (let k = -r; k <= r; k++) acc += tmp[Math.min(h - 1, Math.max(0, k)) * w + x];
    for (let y = 0; y < h; y++) {
      out[y * w + x] = acc / n;
      acc += tmp[Math.min(h - 1, y + r + 1) * w + x] - tmp[Math.max(0, y - r) * w + x];
    }
  }
  return out;
}

export function detectTilt(img: { data: Uint8ClampedArray | Uint8Array; width: number; height: number }): Tilt {
  const { data, width: w0, height: h0 } = img;
  const k = Math.max(1, Math.round(Math.max(w0, h0) / WORK));
  const w = Math.floor(w0 / k);
  const h = Math.floor(h0 / k);
  if (w < 24 || h < 24) return { angle: 0, confidence: 0, edges: 0 };
  // کوچک‌کردن با میانگینِ کاملِ k×k (ضدِ پله)
  const g = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let s = 0;
      for (let dy = 0; dy < k; dy++) {
        for (let dx = 0; dx < k; dx++) {
          const i = ((y * k + dy) * w0 + (x * k + dx)) * 4;
          s += data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
        }
      }
      g[y * w + x] = s / (k * k);
    }
  }
  // محوِ سبکِ پیش از گرادیان: لبهٔ پله‌پله (بی‌ضدِ پله) صاف می‌شود تا جهتِ گرادیان همان شیبِ واقعی را بدهد
  const g2 = boxBlur(boxBlur(g, w, h, 1), w, h, 1);
  g.set(g2);
  // گرادیان (Sobel) و تانسورِ ساختار
  const jxx = new Float32Array(w * h);
  const jyy = new Float32Array(w * h);
  const jxy = new Float32Array(w * h);
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x;
      const gx = g[i - w + 1] + 2 * g[i + 1] + g[i + w + 1] - g[i - w - 1] - 2 * g[i - 1] - g[i + w - 1];
      const gy = g[i + w - 1] + 2 * g[i + w] + g[i + w + 1] - g[i - w - 1] - 2 * g[i - w] - g[i - w + 1];
      jxx[i] = gx * gx;
      jyy[i] = gy * gy;
      jxy[i] = gx * gy;
    }
  }
  const Axx = boxBlur(jxx, w, h, RADIUS);
  const Ayy = boxBlur(jyy, w, h, RADIUS);
  const Axy = boxBlur(jxy, w, h, RADIUS);
  let maxE = 0;
  for (let i = 0; i < Axx.length; i++) maxE = Math.max(maxE, Axx[i] + Ayy[i]);
  if (maxE < 1e-6) return { angle: 0, confidence: 0, edges: 0 };
  const thr = maxE * 0.04;
  const nb = Math.round((2 * RANGE) / BIN) + 1;
  const hist = new Float32Array(nb);
  let total = 0;
  let edges = 0;
  for (let y = RADIUS; y < h - RADIUS; y++) {
    for (let x = RADIUS; x < w - RADIUS; x++) {
      const i = y * w + x;
      const e = Axx[i] + Ayy[i];
      if (e < thr) continue;
      const coh = Math.hypot(Axx[i] - Ayy[i], 2 * Axy[i]) / e;
      if (coh < 0.8) continue; // گوشه/بافت: جهتِ مشخصی ندارد (فقط خط‌های بلندِ مطمئن)
      edges++;
      const thetaN = 0.5 * Math.atan2(2 * Axy[i], Axx[i] - Ayy[i]); // جهتِ گرادیان
      let tl = (thetaN * 180) / Math.PI + 90; // جهتِ خط
      while (tl > 90) tl -= 180;
      while (tl <= -90) tl += 180;
      let d: number;
      if (Math.abs(tl) <= RANGE) d = tl;
      else if (tl >= 90 - RANGE) d = tl - 90;
      else if (tl <= -90 + RANGE) d = tl + 90;
      else continue;
      const b = Math.round((d + RANGE) / BIN);
      if (b < 0 || b >= nb) continue;
      const wgt = Math.sqrt(e) * coh;
      hist[b] += wgt;
      total += wgt;
    }
  }
  if (total <= 0) return { angle: 0, confidence: 0, edges };
  // قله با هموارسازیِ جعبه‌ای (±۰٫۵°)
  let best = 0;
  let bestV = -1;
  for (let b = 0; b < nb; b++) {
    let s = 0;
    for (let j = -2; j <= 2; j++) s += hist[Math.min(nb - 1, Math.max(0, b + j))];
    if (s > bestV) {
      bestV = s;
      best = b;
    }
  }
  // میانگینِ وزنیِ نزدیکِ قله برای دقتِ زیرِ بین
  let num = 0;
  let den = 0;
  for (let j = -3; j <= 3; j++) {
    const b = Math.min(nb - 1, Math.max(0, best + j));
    num += (b * BIN - RANGE) * hist[b];
    den += hist[b];
  }
  const angle = den > 0 ? num / den : best * BIN - RANGE;
  const near = Math.round(1 / BIN);
  let mass = 0;
  for (let b = Math.max(0, best - near); b <= Math.min(nb - 1, best + near); b++) mass += hist[b];
  return { angle: Math.round(angle * 10) / 10, confidence: Math.min(1, mass / total), edges };
}
