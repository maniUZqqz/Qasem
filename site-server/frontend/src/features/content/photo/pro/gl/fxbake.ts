import type { FxGlow, FxShadow, FxStroke, LayerFx } from "../types";
import type { GLCtx, Tex } from "./glutil";
import { SH } from "./shaders";

/**
 * جلوه‌های لایه (سایه، درخشش، دورخط) — پختن در تایلِ لایه، پیش از حالتِ ترکیب/پیدایی/ماسک. همان قراردادِ بک‌اند (fx.py):
 *  • طول‌ها کسری از پهنای بوم W؛ ترتیبِ رسم: سایه، درخشش، دورخط، پیکسل‌های لایه؛ حاشیهٔ متقارن (مرکزِ تایل = محورِ لایه).
 *  • سایه = آلفا جابه‌جا (dx,dy)·W ⇒ محوِ گاوسی σ = blur·W ⇒ × opacity؛ درخشش = دیسکِ dilate(size·W) ⇒ محو ⇒ × opacity؛
 *    دورخط = dilate(w·W) ⇒ × opacity (بیرونی، زیرِ پیکسل‌ها). نقشهٔ هر جلوه پس از opacity به ۸ بیت گرد می‌شود.
 *  • همه روی GPU (شیدرهای fx* در shaders.ts)؛ نتیجه پیش‌ضرب‌شده است.
 */

export const FX_MAX_PIXELS = 20_000_000;
const MAX_SIDE = 8192;
const STEP = 12;

export type FxEff = { shadow?: FxShadow; glow?: FxGlow; stroke?: FxStroke };

/** فقط جلوه‌هایی که واقعاً چیزی می‌کشند (opacity > 0؛ برای دورخط w > 0 هم) — مثلِ fx.effective */
export function effectiveFx(fx: LayerFx | null | undefined): FxEff {
  const out: FxEff = {};
  if (!fx) return out;
  if (fx.shadow && fx.shadow.opacity > 0) out.shadow = fx.shadow;
  if (fx.glow && fx.glow.opacity > 0) out.glow = fx.glow;
  if (fx.stroke && fx.stroke.opacity > 0 && fx.stroke.w > 0) out.stroke = fx.stroke;
  return out;
}

export const fxActive = (fx: LayerFx | null | undefined): boolean => Object.keys(effectiveFx(fx)).length > 0;

/** حاشیهٔ پیکسلی از هر چهار طرف (fx.margin) */
export function fxMargin(e: FxEff, W: number): number {
  let m = 0;
  if (e.shadow) m = Math.max(m, Math.max(Math.abs(e.shadow.dx), Math.abs(e.shadow.dy)) * W + 4 * e.shadow.blur * W + 2);
  if (e.glow) m = Math.max(m, e.glow.size * W + 4 * e.glow.blur * W + 2);
  if (e.stroke) m = Math.max(m, e.stroke.w * W + 2);
  return Math.ceil(m);
}

/** round ِ پایتون (گردکردنِ نیم به زوج) برای گام‌های متوازنِ dilate */
const pyRound = (x: number): number => {
  const f = Math.floor(x);
  const d = x - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
};

/** شعاعِ هر گامِ dilate (fx.dilate_disc): r = ⌊طول+½⌋؛ r > ۱۲ ⇒ ⌈r/۱۲⌉ گامِ متوازن */
export function dilateSteps(rPx: number): number[] {
  const r = Math.floor(rPx + 0.5);
  if (r <= 0) return [];
  const n = Math.max(1, Math.ceil(r / STEP));
  const steps: number[] = [];
  let left = r;
  for (let i = 0; i < n; i++) {
    const s = pyRound(left / (n - i));
    left -= s;
    if (s > 0) steps.push(s);
  }
  return steps;
}

const rgb = (hex: string): [number, number, number] => {
  const h = /^#[0-9a-fA-F]{6}$/.test(hex) ? hex : "#000000";
  return [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255];
};

export type BakeSrc = {
  /** تایلِ لایه (پیش‌ضرب‌شده، بافتِ ورودی؛ برای تصویر: بافتِ عکس با میپ‌مپ) */
  tex: Tex;
  /** اندازهٔ محتوا به پیکسلِ بوم (برای تصویر = اندازهٔ بومیِ لایه؛ تصویر به همین اندازه نمونه‌برداری می‌شود) */
  cw: number;
  ch: number;
  flipX?: boolean;
  flipY?: boolean;
  /** تکرارشونده (واترمارک): خروجی هم‌اندازهٔ محتوا و حاشیه بریده می‌شود */
  crop?: boolean;
};

type Own = { tex: Tex; own: boolean };

/** هر بافتِ منبع یک شناسهٔ پایدار برای کلیدِ کَش */
const texIds = new WeakMap<Tex, number>();
let texSeq = 0;
const texId = (t: Tex): number => {
  let id = texIds.get(t);
  if (!id) texIds.set(t, (id = ++texSeq));
  return id;
};

/** کَشِ نقشه‌های هر جلوه (فقط نقشهٔ آلفا: رنگ و شدت در پاسِ آخر اعمال می‌شوند؛ پس تغییرِ رنگ/شدت چیزی را دوباره نمی‌سازد) */
export type FxCache = {
  geom: string;
  pad: Tex | null;
  maps: { shadow?: { sig: string; tex: Tex }; glow?: { sig: string; tex: Tex }; stroke?: { sig: string; tex: Tex } };
};
export const newFxCache = (): FxCache => ({ geom: "", pad: null, maps: {} });
export function freeFxCache(g: GLCtx, c: FxCache): void {
  if (c.pad) g.destroy(c.pad);
  for (const m of Object.values(c.maps)) if (m) g.destroy(m.tex);
  c.pad = null;
  c.maps = {};
  c.geom = "";
}
/** تایل‌های بزرگ‌تر از این کَشِ میانی نمی‌گیرند (حافظهٔ گوشی) */
const CACHE_MAX_PIXELS = 4_000_000;

function dilate(g: GLCtx, src: Tex, rPx: number): Tex {
  let cur: Tex | null = null;
  for (const s of dilateSteps(rPx)) {
    const out = g.take(src.w, src.h);
    g.pass("fxDilate", SH.fxDilate, out, { uT: cur ?? src, uPx: [1 / src.w, 1 / src.h], uS: s });
    if (cur) g.release(cur);
    cur = out;
  }
  if (!cur) {
    cur = g.take(src.w, src.h);
    g.pass("copy", SH.copy, cur, { uT: src });
  }
  return cur;
}

/** نیمه‌کردنِ پشتِ هم (k بار) — هر گام میانگینِ ۲×۲ */
function halve(g: GLCtx, src: Tex, k: number): Own {
  let cur = src;
  let own = false;
  for (let i = 0; i < k; i++) {
    const t = g.take(Math.max(1, Math.ceil(cur.w / 2)), Math.max(1, Math.ceil(cur.h / 2)));
    g.pass("copy", SH.copy, t, { uT: cur });
    if (own) g.release(cur);
    cur = t;
    own = true;
  }
  return { tex: cur, own };
}

/** محوِ گاوسی σ پیکسل؛ σ بزرگ ⇒ روی نسخهٔ ۱/f (f توانِ ۲ و σ/f ≤ ۸) و بعد با دوخطی بالا کشیده می‌شود (مثلِ fx._blur). ورودی را آزاد می‌کند اگر own */
function blur(g: GLCtx, src: Tex, sigma: number, srcOwn: boolean): Tex {
  if (sigma <= 0.05) {
    if (srcOwn) return src;
    const c = g.take(src.w, src.h);
    g.pass("copy", SH.copy, c, { uT: src });
    return c;
  }
  let f = 1;
  let k = 0;
  while (sigma / f > 8) {
    f *= 2;
    k++;
  }
  const h = halve(g, src, k);
  if (srcOwn && h.own) g.release(src);
  const cur = h.tex;
  const s = Math.max(0.3, sigma / f);
  const a = g.take(cur.w, cur.h);
  g.pass("blur", SH.blur, a, { uT: cur, uStep: [1 / cur.w, 0], uSigma: s });
  const b = g.take(cur.w, cur.h);
  g.pass("blur", SH.blur, b, { uT: a, uStep: [0, 1 / cur.h], uSigma: s });
  g.release(a);
  if (h.own) g.release(cur);
  else if (srcOwn) g.release(src);
  return b;
}

/** ورودی بیش‌ازحد بزرگ است؟ (⇒ جلوه نادیده، مثلِ سرور) */
export function fxTooBig(cw: number, ch: number, m: number): boolean {
  return (cw + 2 * m) * (ch + 2 * m) > FX_MAX_PIXELS || cw + 2 * m > MAX_SIDE || ch + 2 * m > MAX_SIDE;
}

/**
 * تایل + جلوه ⇒ بافتِ تازه (مالکیت با فراخوان). اندازهٔ خروجی (w, h) به پیکسل.
 * cache (اختیاری): نقشهٔ هر جلوه را نگه می‌دارد تا با کشیدنِ لغزندهٔ یک جلوه فقط همان دوباره ساخته شود.
 */
export function bakeFx(g: GLCtx, s: BakeSrc, e: FxEff, W: number, cache?: FxCache): { tex: Tex; w: number; h: number } | null {
  const cw = Math.max(1, Math.round(s.cw));
  const ch = Math.max(1, Math.round(s.ch));
  const m = fxMargin(e, W);
  if (fxTooBig(cw, ch, m)) return null;
  const PW = cw + 2 * m;
  const PH = ch + 2 * m;
  const keep = !!cache && PW * PH <= CACHE_MAX_PIXELS;
  const geom = JSON.stringify([texId(s.tex), cw, ch, m, !!s.flipX, !!s.flipY, W]);
  if (cache && cache.geom !== geom) {
    freeFxCache(g, cache);
    cache.geom = geom;
  }
  let pad = keep ? cache!.pad : null;
  if (!pad) {
    pad = g.take(PW, PH);
    g.pass("fxPad", SH.fxPad, pad, { uT: s.tex, uOut: [PW, PH], uM: [m, m], uIn: [cw, ch], uFlip: [s.flipX ? -1 : 1, s.flipY ? -1 : 1] });
    if (keep) cache!.pad = pad;
  }
  const maps: Partial<Record<"shadow" | "glow" | "stroke", Tex>> = {};
  const transient: Tex[] = [];
  const got = (name: "shadow" | "glow" | "stroke", sig: string, make: () => Tex): Tex => {
    const have = keep ? cache!.maps[name] : undefined;
    if (have && have.sig === sig) return have.tex;
    if (have) g.destroy(have.tex);
    const t = make();
    if (keep) cache!.maps[name] = { sig, tex: t };
    else transient.push(t);
    return t;
  };
  if (cache && !keep) freeFxCache(g, cache);
  // نقشهٔ آلفای بی‌جابه‌جایی؛ فقط وقتی دیلیت لازم است ساخته می‌شود
  let aMap: Tex | null = null;
  const alpha = (): Tex => {
    if (!aMap) {
      aMap = g.take(PW, PH);
      g.pass("fxAlpha", SH.fxAlpha, aMap, { uT: pad!, uOff: [0, 0] });
    }
    return aMap;
  };
  // اگر نقشه‌ای کَش شده نباشد، ساخته می‌شود؛ نقشهٔ کَش‌شده بی‌هزینه است
  const dropped = (name: "shadow" | "glow" | "stroke") => {
    if (keep && cache!.maps[name] && !e[name]) {
      g.destroy(cache!.maps[name]!.tex);
      delete cache!.maps[name];
    }
  };
  (["shadow", "glow", "stroke"] as const).forEach(dropped);
  if (e.shadow) {
    const sh = e.shadow;
    maps.shadow = got("shadow", JSON.stringify([sh.dx, sh.dy, sh.blur]), () => {
      const a = g.take(PW, PH);
      g.pass("fxAlpha", SH.fxAlpha, a, { uT: pad!, uOff: [(sh.dx * W) / PW, (sh.dy * W) / PH] });
      return blur(g, a, sh.blur * W, true);
    });
  }
  if (e.glow) {
    const gl = e.glow;
    maps.glow = got("glow", JSON.stringify([gl.size, gl.blur]), () => {
      // درخشش بعدش محو می‌شود ⇒ وقتی محو روی نسخهٔ ۱/f حساب می‌شود، dilate هم همان‌جا (شعاعِ r/f) انجام شود: ده‌ها برابر سریع‌تر
      const sigma = gl.blur * W;
      const r = gl.size * W;
      let k = 0;
      while (sigma / 2 ** k > 8) k++;
      if (k > 0 && r > STEP) {
        const h = halve(g, alpha(), k);
        const d = dilate(g, h.tex, r / 2 ** k);
        if (h.own) g.release(h.tex);
        return blur(g, d, sigma / 2 ** k, true) as Tex;
      }
      const d = dilate(g, alpha(), r);
      return blur(g, d, sigma, true);
    });
  }
  if (e.stroke) {
    const st = e.stroke;
    maps.stroke = got("stroke", JSON.stringify([st.w]), () => dilate(g, alpha(), st.w * W));
  }
  const outW = s.crop ? cw : PW;
  const outH = s.crop ? ch : PH;
  const out = g.create(outW, outH, true);
  const c0: [number, number, number] = [0, 0, 0];
  g.pass("fxFinal", SH.fxFinal, out, {
    uL: pad, uSh: maps.shadow ?? pad, uGl: maps.glow ?? pad, uSt: maps.stroke ?? pad,
    uShC: e.shadow ? rgb(e.shadow.color) : c0, uGlC: e.glow ? rgb(e.glow.color) : c0, uStC: e.stroke ? rgb(e.stroke.color) : c0,
    uOp: [e.shadow ? e.shadow.opacity : 0, e.glow ? e.glow.opacity : 0, e.stroke ? e.stroke.opacity : 0],
    uOut: [outW, outH], uOff: s.crop ? [m, m] : [0, 0], uPad: [PW, PH],
  });
  if (aMap) g.release(aMap);
  for (const t of transient) g.release(t);
  if (!keep) g.release(pad);
  return { tex: out, w: outW, h: outH };
}
