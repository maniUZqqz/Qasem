/**
 * پیش‌نمایشِ زندهٔ ادیتورِ دستیِ عکس — در مرورگر، روی نسخهٔ کوچک.
 *
 * این یک «تقریب» است، نه جایگزینِ کیت: نور (نوردهی، کنتراست، روشنی‌ها/سایه‌ها، سفیدها/سیاه‌ها)، رنگ (دما، ته‌رنگ، وایبرنس،
 * اشباع، HSL)، رنگ‌دهی، سطوح، منحنی، وضوح/بافت/شارپ/نویزگیری، وینیت و دانه با فرمول‌های ساده‌شده حساب می‌شوند تا کشیدنِ
 * لغزنده فوری باشد. خروجیِ دقیق همیشه از «ساخت» روی سرورِ پردازش (PersianAiKit.Photo) می‌آید. اعوجاجِ لنز و
 * نویزگیریِ واقعی فقط در خروجیِ نهایی‌اند.
 */

export type Pt = [number, number];
export type Curve = { rgb?: Pt[]; red?: Pt[]; green?: Pt[]; blue?: Pt[] };
export type Adjust = Record<string, number>;

const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);

/** منحنیِ نرم و یکنوا (Fritsch–Carlson) از نقطه‌های [ورودی، خروجی] ⇐ جدولِ ۲۵۶تایی */
export function curveLut(points: Pt[] | undefined): Uint8Array | null {
  if (!points || points.length < 2) return null;
  const pts = [...points].sort((a, b) => a[0] - b[0]);
  if (pts.every((p) => Math.abs(p[0] - p[1]) < 1e-6)) return null;
  const n = pts.length;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const d: number[] = [];
  const m: number[] = new Array(n).fill(0);
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / Math.max(1e-6, xs[i + 1] - xs[i]));
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2;
  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(d[i]) < 1e-9) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  const lut = new Uint8Array(256);
  let seg = 0;
  for (let x = 0; x < 256; x++) {
    if (x <= xs[0]) {
      lut[x] = clamp(Math.round(ys[0]), 0, 255);
      continue;
    }
    if (x >= xs[n - 1]) {
      lut[x] = clamp(Math.round(ys[n - 1]), 0, 255);
      continue;
    }
    while (seg < n - 2 && x > xs[seg + 1]) seg++;
    const h = xs[seg + 1] - xs[seg];
    const t = (x - xs[seg]) / h;
    const t2 = t * t;
    const t3 = t2 * t;
    const v =
      (2 * t3 - 3 * t2 + 1) * ys[seg] +
      (t3 - 2 * t2 + t) * h * m[seg] +
      (-2 * t3 + 3 * t2) * ys[seg + 1] +
      (t3 - t2) * h * m[seg + 1];
    lut[x] = clamp(Math.round(v), 0, 255);
  }
  return lut;
}

/** نور: نوردهی، سیاه/سفید، سایه/روشنی، روشنیِ میانه، کنتراست، مه‌زدایی، سطوح — یک تابعِ ۰..۱ ⇐ ۰..۱ */
function toneFn(a: Adjust) {
  const ev = a.exposure ?? 0;
  const con = a.contrast ?? 0;
  const hi = a.highlights ?? 0;
  const sh = a.shadows ?? 0;
  const wh = a.whites ?? 0;
  const bl = a.blacks ?? 0;
  const br = a.brightness ?? 0;
  const dh = a.dehaze ?? 0;
  const lb = a.levelsBlack ?? 0;
  const lw = a.levelsWhite ?? 255;
  const lg = a.levelsGamma ?? 1;
  const gain = Math.pow(2, ev);
  const brExp = 1 - (br / 100) * 0.45;
  const cf = 1 + (con / 100) * (con > 0 ? 1.0 : 0.7);
  const dhk = (dh / 100) * 0.12;
  return (x0: number) => {
    let x = x0;
    if (ev) x = Math.pow(clamp(Math.pow(x, 2.2) * gain, 0, 1), 1 / 2.2);
    if (bl) x += (bl / 100) * 0.12 * Math.pow(1 - x, 3);
    if (wh) x += (wh / 100) * 0.12 * Math.pow(x, 3);
    if (sh) x += (sh / 100) * 0.3 * Math.pow(1 - x, 2) * Math.min(1, x * 5 + 0.15);
    if (hi) x += (hi / 100) * 0.3 * Math.pow(x, 2) * Math.min(1, (1 - x) * 5 + 0.15);
    x = clamp(x, 0, 1);
    if (br) x = Math.pow(x, brExp);
    if (con) x = clamp(0.5 + (x - 0.5) * cf, 0, 1);
    if (dh) x = clamp((x - dhk) / (1 - Math.abs(dhk)), 0, 1);
    if (lb > 0 || lw < 255 || lg !== 1) {
      x = clamp((x * 255 - lb) / Math.max(1, lw - lb), 0, 1);
      if (lg !== 1) x = Math.pow(x, 1 / lg);
    }
    return x;
  };
}

/** سه جدولِ ۲۵۶تایی (قرمز، سبز، آبی): دما/ته‌رنگ + نور + منحنی‌ها. null = بی‌اثر */
export function buildLuts(a: Adjust, curve: Curve): [Uint8Array, Uint8Array, Uint8Array] | null {
  const t = (a.temperature ?? 0) / 100;
  const ti = (a.tint ?? 0) / 100;
  const hasTone = ["exposure", "contrast", "highlights", "shadows", "whites", "blacks", "brightness", "dehaze"].some((k) => a[k]) ||
    (a.levelsBlack ?? 0) > 0 || (a.levelsWhite ?? 255) < 255 || (a.levelsGamma ?? 1) !== 1;
  const cr = curveLut(curve.rgb);
  const cR = curveLut(curve.red);
  const cG = curveLut(curve.green);
  const cB = curveLut(curve.blue);
  if (!hasTone && !t && !ti && !cr && !cR && !cG && !cB) return null;
  const tone = toneFn(a);
  const gains = [1 + 0.22 * t, 1 - 0.12 * ti, 1 - 0.22 * t];
  const chan = [cR, cG, cB];
  const out: Uint8Array[] = [];
  for (let c = 0; c < 3; c++) {
    const lut = new Uint8Array(256);
    for (let i = 0; i < 256; i++) {
      let x = clamp((i / 255) * gains[c], 0, 1);
      if (hasTone) x = tone(x);
      let v = Math.round(x * 255);
      if (cr) v = cr[v];
      const cc = chan[c];
      if (cc) v = cc[v];
      lut[i] = v;
    }
    out.push(lut);
  }
  return out as [Uint8Array, Uint8Array, Uint8Array];
}

const BANDS = ["red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta"] as const;
const BAND_CENTER = [0, 30, 60, 120, 180, 240, 270, 300];

/** هر درجهٔ فام ⇐ جابه‌جاییِ فام، ضریبِ اشباع، افزایشِ روشنی */
function hslTables(a: Adjust) {
  const any = BANDS.some((b) => a[`${b}Hue`] || a[`${b}Sat`] || a[`${b}Lum`]);
  if (!any) return null;
  const hue = new Float32Array(360);
  const sat = new Float32Array(360).fill(1);
  const lum = new Float32Array(360);
  for (let h = 0; h < 360; h++) {
    let dh = 0;
    let ds = 0;
    let dl = 0;
    for (let i = 0; i < 8; i++) {
      let d = Math.abs(h - BAND_CENTER[i]);
      if (d > 180) d = 360 - d;
      const w = Math.max(0, 1 - d / 45);
      if (!w) continue;
      dh += w * (a[`${BANDS[i]}Hue`] ?? 0);
      ds += w * (a[`${BANDS[i]}Sat`] ?? 0);
      dl += w * (a[`${BANDS[i]}Lum`] ?? 0);
    }
    hue[h] = (dh / 100) * 30;
    sat[h] = Math.max(0, 1 + ds / 100);
    lum[h] = (dl / 100) * 0.3;
  }
  return { hue, sat, lum };
}

function hueRgb(h: number): [number, number, number] {
  const x = h / 60;
  const f = x - Math.floor(x);
  switch (((Math.floor(x) % 6) + 6) % 6) {
    case 0: return [1, f, 0];
    case 1: return [1 - f, 1, 0];
    case 2: return [0, 1, f];
    case 3: return [0, 1 - f, 1];
    case 4: return [f, 0, 1];
    default: return [1, 0, 1 - f];
  }
}

function boxBlur(src: Float32Array, w: number, h: number, radius: number): Float32Array {
  const r = Math.max(1, Math.round(radius));
  const tmp = new Float32Array(w * h);
  const out = new Float32Array(w * h);
  const win = 2 * r + 1;
  for (let y = 0; y < h; y++) {
    let sum = 0;
    const row = y * w;
    for (let x = -r; x <= r; x++) sum += src[row + clamp(x, 0, w - 1)];
    for (let x = 0; x < w; x++) {
      tmp[row + x] = sum / win;
      sum += src[row + clamp(x + r + 1, 0, w - 1)] - src[row + clamp(x - r, 0, w - 1)];
    }
  }
  for (let x = 0; x < w; x++) {
    let sum = 0;
    for (let y = -r; y <= r; y++) sum += tmp[clamp(y, 0, h - 1) * w + x];
    for (let y = 0; y < h; y++) {
      out[y * w + x] = sum / win;
      sum += tmp[clamp(y + r + 1, 0, h - 1) * w + x] - tmp[clamp(y - r, 0, h - 1) * w + x];
    }
  }
  return out;
}

/** آیا این تنظیم‌ها چیزی را عوض می‌کنند؟ */
export function isNeutral(a: Adjust, curve: Curve): boolean {
  return Object.keys(a).length === 0 && !curve.rgb && !curve.red && !curve.green && !curve.blue;
}

/**
 * src ⇐ نسخهٔ پردازش‌شده (در `out`، اگر هم‌اندازه باشد دوباره استفاده می‌شود).
 * `draft` = هنگامِ کشیدنِ لغزنده: وضوح/بافت/نویز را کنار می‌گذارد تا فوری بماند.
 */
export function process(src: ImageData, a: Adjust, curve: Curve, out?: ImageData, draft = false): ImageData {
  const { width: w, height: h } = src;
  const dst = out && out.width === w && out.height === h ? out : new ImageData(w, h);
  const s = src.data;
  const d = dst.data;
  if (isNeutral(a, curve)) {
    d.set(s);
    return dst;
  }
  const luts = buildLuts(a, curve);
  const sat = (a.saturation ?? 0) / 100;
  const vib = (a.vibrance ?? 0) / 100;
  const dehazeSat = ((a.dehaze ?? 0) / 100) * 0.2;
  const hsl = hslTables(a);
  const sS = (a.shadowsSat ?? 0) / 100;
  const hS = (a.highlightsSat ?? 0) / 100;
  const tintS = sS > 0 ? hueRgb(a.shadowsHue ?? 220) : null;
  const tintH = hS > 0 ? hueRgb(a.highlightsHue ?? 40) : null;
  const bal = (a.gradingBalance ?? 0) / 100;
  const needColor = !!(sat || vib || dehazeSat || hsl || tintS || tintH);
  const L0 = luts?.[0];
  const L1 = luts?.[1];
  const L2 = luts?.[2];
  const kSat = 1 + sat + dehazeSat;

  for (let i = 0; i < d.length; i += 4) {
    let r = s[i];
    let g = s[i + 1];
    let b = s[i + 2];
    if (L0 && L1 && L2) {
      r = L0[r];
      g = L1[g];
      b = L2[b];
    }
    if (needColor) {
      const lum = 0.299 * r + 0.587 * g + 0.114 * b;
      if (kSat !== 1 || vib) {
        const mx = Math.max(r, g, b);
        const mn = Math.min(r, g, b);
        const sp = mx > 0 ? (mx - mn) / mx : 0;
        const k = Math.max(0, kSat + vib * (1 - sp));
        r = lum + (r - lum) * k;
        g = lum + (g - lum) * k;
        b = lum + (b - lum) * k;
      }
      if (hsl) {
        const mx = Math.max(r, g, b);
        const mn = Math.min(r, g, b);
        const delta = mx - mn;
        if (delta > 1) {
          let hh: number;
          if (mx === r) hh = ((g - b) / delta) % 6;
          else if (mx === g) hh = (b - r) / delta + 2;
          else hh = (r - g) / delta + 4;
          hh = ((hh * 60) % 360 + 360) % 360;
          const hi = Math.floor(hh) % 360;
          const nh = (((hh + hsl.hue[hi]) % 360) + 360) % 360;
          const l = (mx + mn) / 510;
          const sl = delta / 255 / (1 - Math.abs(2 * l - 1) + 1e-6);
          const ns = clamp(sl * hsl.sat[hi], 0, 1);
          const nl = clamp(l + hsl.lum[hi], 0, 1);
          const c = (1 - Math.abs(2 * nl - 1)) * ns * 255;
          const [rr, gg, bb] = hueRgb(nh);
          const m0 = nl * 255 - c / 2;
          r = m0 + c * rr;
          g = m0 + c * gg;
          b = m0 + c * bb;
        }
      }
      if (tintS || tintH) {
        const l = clamp((0.299 * r + 0.587 * g + 0.114 * b) / 255, 0, 1);
        if (tintS) {
          const w = Math.pow(1 - l, 2) * (1 - Math.max(0, bal)) * sS * 0.35;
          r += (tintS[0] * 255 - l * 255) * w;
          g += (tintS[1] * 255 - l * 255) * w;
          b += (tintS[2] * 255 - l * 255) * w;
        }
        if (tintH) {
          const w = l * l * (1 + Math.min(0, bal)) * hS * 0.35;
          r += (tintH[0] * 255 - l * 255) * w;
          g += (tintH[1] * 255 - l * 255) * w;
          b += (tintH[2] * 255 - l * 255) * w;
        }
      }
    }
    d[i] = r < 0 ? 0 : r > 255 ? 255 : r;
    d[i + 1] = g < 0 ? 0 : g > 255 ? 255 : g;
    d[i + 2] = b < 0 ? 0 : b > 255 ? 255 : b;
    d[i + 3] = s[i + 3];
  }

  // وضوح، بافت، شارپ، نویزگیری — روی روشنایی (با تارکردنِ جعبه‌ای)
  const clarity = a.clarity ?? 0;
  const texture = a.texture ?? 0;
  const sharpen = a.sharpen ?? 0;
  const noise = a.noiseLuma ?? 0;
  if (!draft && (clarity || texture || sharpen || noise)) {
    const lum = new Float32Array(w * h);
    for (let i = 0, p = 0; p < lum.length; i += 4, p++) lum[p] = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
    const big = clarity ? boxBlur(lum, w, h, Math.max(3, Math.min(w, h) / 40)) : null;
    const rad = Math.max(1, ((a.sharpenRadius ?? 1) * Math.max(w, h)) / 1600);
    const small = texture || sharpen || noise ? boxBlur(lum, w, h, rad) : null;
    for (let i = 0, p = 0; p < lum.length; i += 4, p++) {
      let delta = 0;
      if (big) delta += (lum[p] - big[p]) * (clarity / 100) * 0.9;
      if (small) {
        const dd = lum[p] - small[p];
        delta += dd * (texture / 100) * 0.8;
        if (sharpen) {
          const mask = a.sharpenMasking ? Math.min(1, Math.abs(dd) / (4 + (a.sharpenMasking ?? 0) * 0.3)) : 1;
          delta += dd * (sharpen / 100) * 1.2 * mask;
        }
        if (noise) delta -= dd * Math.min(1, noise / 100) * 0.8;
      }
      if (delta) {
        d[i] = clamp(d[i] + delta, 0, 255);
        d[i + 1] = clamp(d[i + 1] + delta, 0, 255);
        d[i + 2] = clamp(d[i + 2] + delta, 0, 255);
      }
    }
  }

  // وینیت و دانه
  const vig = a.vignette ?? 0;
  const grain = a.grain ?? 0;
  if (vig || grain) {
    const mid = (a.vignetteMidpoint ?? 50) / 100;
    const feather = (a.vignetteFeather ?? 50) / 100;
    const cx = w / 2;
    const cy = h / 2;
    const maxd = Math.hypot(cx, cy);
    const e0 = clamp(0.25 + mid * 0.5 - feather * 0.2, 0, 0.95);
    const e1 = clamp(e0 + 0.15 + feather * 0.5, e0 + 0.05, 1.4);
    let seed = 1234567;
    for (let y = 0, p = 0; y < h; y++) {
      for (let x = 0; x < w; x++, p += 4) {
        if (vig) {
          const r = Math.hypot(x - cx, y - cy) / maxd;
          let t = clamp((r - e0) / (e1 - e0), 0, 1);
          t = t * t * (3 - 2 * t);
          const k = (vig / 100) * t;
          if (k < 0) {
            const f = 1 + k;
            d[p] *= f;
            d[p + 1] *= f;
            d[p + 2] *= f;
          } else {
            d[p] += (255 - d[p]) * k;
            d[p + 1] += (255 - d[p + 1]) * k;
            d[p + 2] += (255 - d[p + 2]) * k;
          }
        }
        if (grain) {
          seed ^= seed << 13;
          seed ^= seed >>> 17;
          seed ^= seed << 5;
          const n = (((seed >>> 0) % 2000) / 1000 - 1) * (grain / 100) * 28;
          d[p] = clamp(d[p] + n, 0, 255);
          d[p + 1] = clamp(d[p + 1] + n, 0, 255);
          d[p + 2] = clamp(d[p + 2] + n, 0, 255);
        }
      }
    }
  }
  return dst;
}

/** «خودکار» ِ سریعِ مرورگر: از روی هیستوگرام نوردهی، کنتراست، سفیدها و سیاه‌ها را پیشنهاد می‌دهد (نسخهٔ دقیق = کیت). */
export function autoTone(src: ImageData): Adjust {
  const hist = new Uint32Array(256);
  const d = src.data;
  let n = 0;
  for (let i = 0; i < d.length; i += 16) {
    hist[Math.round(0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2])]++;
    n++;
  }
  const pct = (p: number) => {
    let acc = 0;
    for (let i = 0; i < 256; i++) {
      acc += hist[i];
      if (acc >= n * p) return i;
    }
    return 255;
  };
  const lo = pct(0.005);
  const hi = pct(0.995);
  const med = pct(0.5);
  const out: Adjust = {};
  const ev = clamp(Math.log2((0.46 * 255) / Math.max(20, med)) * 0.6, -1.5, 1.5);
  if (Math.abs(ev) > 0.08) out.exposure = Math.round(ev * 100) / 100;
  if (hi < 235) out.whites = clamp(Math.round((235 - hi) * 0.5), 0, 60);
  if (lo > 20) out.blacks = -clamp(Math.round((lo - 20) * 0.6), 0, 50);
  if (hi - lo < 170) out.contrast = clamp(Math.round((170 - (hi - lo)) * 0.35), 0, 40);
  return out;
}

/** ImageData ⇐ یک تصویر، با ضلعِ بلندِ حداکثر `side` */
export function imageDataFrom(img: CanvasImageSource, w0: number, h0: number, side: number): ImageData {
  const k = Math.min(1, side / Math.max(w0, h0));
  const w = Math.max(1, Math.round(w0 * k));
  const h = Math.max(1, Math.round(h0 * k));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(img, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h);
}
