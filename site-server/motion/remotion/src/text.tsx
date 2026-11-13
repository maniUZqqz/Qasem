import React, { createContext, useContext } from "react";
import type { CSSProperties } from "react";
import { cameraCss, enterCss, enterProgress } from "./anim";
import { fontStack, useCtx, useQF } from "./ctx";
import type { Pal } from "./types";
import { R, bestText, clamp, col, contrast, hasArabic, lum, mix, onColor, rgba, shade, toEnDigits, toFaDigits } from "./util";

/** a plain small text (kicker, author ...) on the style's background: when its colour would nearly vanish, darken/lighten it, else fall back to the best of ink / white / black */
export function readableOn(c: string, bg: string, ink: string): string {
  if (!/^#|^rgb/.test(c) || contrast(c, bg) >= 3) return c;
  const d = shade(c, lum(bg) > 0.4 ? -0.55 : 0.55);
  return contrast(d, bg) >= 3 ? d : bestText(bg, [ink, "#ffffff", "#111111"]);
}

/** text colour a card puts on its children (contrast with its fill) */
export const TONE = createContext<string | null>(null);

export function useTone(): string | null {
  return useContext(TONE);
}

type FxOpts = { size: number; u: number; color: string; pal: Pal; qf: number; fps: number; text: any; fa: boolean; wi: number; role: string };

const longShadow = (c: string, n: number, dx: number, dy: number): string =>
  Array.from({ length: n }).map((_, i) => `${(i + 1) * dx}px ${(i + 1) * dy}px 0 ${mix(c, "#000000", (i / n) * 0.35)}`).join(", ");

/** CSS of one word for a text effect. Never splits Persian words into letters (that would break the joining of the script). */
export function fxCss(fx: string, o: FxOpts): CSSProperties {
  const { size, u, color, pal, qf, text } = o;
  const sh = col(pal, text.shadow ?? "accent2");
  const hi = col(pal, text.hi ?? "accent");
  const sw = (text.stroke ?? 0) * u;
  switch (fx) {
    case "outline":
      return { color: text.fill ? col(pal, text.fill) : color, WebkitTextStroke: `${Math.max(2, (text.sw ?? 5) * u)}px ${col(pal, text.stroke_c ?? "ink")}`, paintOrder: "stroke fill" as any };
    case "hard": {
      const d = (text.depth ?? 6) * u;
      return { color, textShadow: `${d}px ${d}px 0 ${sh}` };
    }
    case "outline-hard": {
      const d = (text.depth ?? 8) * u;
      return { color, WebkitTextStroke: `${(text.sw ?? 6) * u}px ${col(pal, text.stroke_c ?? "ink")}`, paintOrder: "stroke fill" as any, textShadow: `${d}px ${d}px 0 ${col(pal, text.stroke_c ?? "ink")}` };
    }
    case "long":
      return { color, textShadow: longShadow(sh, text.depth ?? 26, 1.4 * u, 1.4 * u) };
    case "extrude": {
      const n = text.depth ?? 14;
      const base = sh;
      const layers = Array.from({ length: n }).map((_, i) => `${(i + 1) * 1.3 * u}px ${(i + 1) * 1.6 * u}px 0 ${mix(base, "#000000", (i / n) * 0.45)}`);
      layers.push(`${(n + 4) * 1.3 * u}px ${(n + 6) * 1.6 * u}px ${18 * u}px rgba(0,0,0,0.4)`);
      return { color, textShadow: layers.join(", ") };
    }
    case "neon": {
      const g = col(pal, text.glow ?? "accent");
      return { color: text.core ? col(pal, text.core) : "#ffffff", textShadow: `0 0 ${size * 0.04}px #fff, 0 0 ${size * 0.1}px ${g}, 0 0 ${size * 0.22}px ${g}, 0 0 ${size * 0.5}px ${g}` };
    }
    case "neon-outline": {
      const g = col(pal, text.glow ?? "accent");
      return { color: "transparent", WebkitTextStroke: `${Math.max(2, 3.5 * u)}px ${g}`, textShadow: `0 0 ${size * 0.12}px ${g}, 0 0 ${size * 0.3}px ${g}` };
    }
    case "neon-tube": {
      const g = col(pal, text.glow ?? "accent");
      const flick = R(`nt${Math.floor(qf / 2)}${o.wi}`) > 0.93 ? 0.35 : 1;
      return { color: mix(g, "#ffffff", 0.82), opacity: flick, textShadow: `0 0 ${size * 0.05}px ${g}, 0 0 ${size * 0.14}px ${g}, 0 0 ${size * 0.34}px ${g}, 0 ${size * 0.05}px 0 ${rgba(g, 0.4)}` };
    }
    case "chrome": {
      const shine = ((qf * 2.2) % 220) - 20;
      return {
        backgroundImage: `linear-gradient(105deg, transparent ${shine - 12}%, rgba(255,255,255,0.95) ${shine}%, transparent ${shine + 12}%), linear-gradient(180deg, #ffffff 0%, #c9d4e3 26%, #566277 49%, #f5f9ff 51%, #a6b4c8 74%, #ffffff 100%)`,
        WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent", color: "transparent",
        WebkitTextStroke: `${Math.max(1, 2 * u)}px ${rgba(col(pal, text.edge ?? "bg"), 0.8)}`,
        filter: `drop-shadow(0 ${6 * u}px ${8 * u}px rgba(0,0,0,0.5))`,
      } as CSSProperties;
    }
    case "gold": {
      const shine = ((qf * 1.6) % 240) - 30;
      return {
        backgroundImage: `linear-gradient(105deg, transparent ${shine - 10}%, rgba(255,255,255,0.9) ${shine}%, transparent ${shine + 10}%), linear-gradient(180deg, #fff3b0 0%, #e8b63a 38%, #8a5a10 52%, #f6d777 70%, #b8801f 100%)`,
        WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent", color: "transparent",
        filter: `drop-shadow(0 ${3 * u}px 0 rgba(60,30,0,0.6))`,
      } as CSSProperties;
    }
    case "gradient":
      return { backgroundImage: `linear-gradient(${text.angle ?? 100}deg, ${col(pal, text.a ?? "accent")}, ${col(pal, text.b ?? "accent2")})`, WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent", color: "transparent" } as CSSProperties;
    case "emboss":
      return { color, textShadow: `0 ${-2 * u}px 0 rgba(255,255,255,0.7), 0 ${2 * u}px 0 rgba(0,0,0,0.18), 0 ${10 * u}px ${16 * u}px rgba(0,0,0,0.3)` };
    case "clay":
      return { color, textShadow: `0 ${-3 * u}px 0 ${shade(color, 0.35)}, 0 ${4 * u}px 0 ${shade(color, -0.3)}, 0 ${8 * u}px 0 ${shade(color, -0.42)}, 0 ${16 * u}px ${14 * u}px rgba(0,0,0,0.3)` };
    case "chalk":
      return { color, filter: "url(#nm-chalk)", textShadow: `0 0 ${3 * u}px ${rgba(color, 0.6)}` };
    case "hand":
      return { color, filter: "url(#nm-rough)" };
    case "pencil":
      return { color: rgba(color, 0.88), filter: "url(#nm-rough)", textShadow: `0 0 ${1.5 * u}px ${rgba(color, 0.9)}` };
    case "ink":
      return { color, filter: "url(#nm-ink)", mixBlendMode: "multiply" };
    case "glitch": {
      const j = (R(`gl${qf}${o.wi}`) - 0.5) * 2 * (text.amp ?? 9) * u * (R(`gk${Math.floor(qf / 3)}`) > 0.55 ? 2.4 : 0.6);
      return { color, textShadow: `${j}px 0 ${col(pal, text.a ?? "accent")}, ${-j}px 0 ${col(pal, text.b ?? "accent2")}`, transform: R(`gs${qf}${o.wi}`) > 0.9 ? `skewX(${(R(`gx${qf}`) - 0.5) * 24}deg)` : undefined };
    }
    case "misregister": {
      const d = (text.depth ?? 6) * u;
      return { color, textShadow: `${d}px ${d * 0.7}px 0 ${rgba(sh, 0.85)}`, mixBlendMode: "multiply" };
    }
    case "stamp":
      return { color: hi, border: `${5 * u}px solid ${hi}`, padding: `${0.05 * size}px ${0.22 * size}px`, borderRadius: 10 * u, transform: `rotate(${text.rot ?? -4}deg)`, filter: "url(#nm-ink)", opacity: 0.92, letterSpacing: o.fa ? undefined : "0.06em" };
    case "sticker":
      return { color, WebkitTextStroke: `${Math.max(8, 0.16 * size)}px ${col(pal, text.sticker ?? "paper")}`, paintOrder: "stroke fill" as any, filter: `drop-shadow(0 ${6 * u}px 0 rgba(0,0,0,0.28))` };
    case "pixel":
      return { color, filter: "url(#nm-pixel)", textShadow: `${6 * u}px ${6 * u}px 0 ${sh}` };
    case "fold":
      return { backgroundImage: `linear-gradient(180deg, ${color} 0 50%, ${shade(color, -0.22)} 50% 100%)`, WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent", color: "transparent" } as CSSProperties;
    case "cel":
      return { backgroundImage: `linear-gradient(180deg, ${shade(color, 0.12)} 0 45%, ${color} 45% 75%, ${shade(color, -0.3)} 75% 100%)`, WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent", color: "transparent", filter: `drop-shadow(${4 * u}px ${5 * u}px 0 ${col(pal, text.stroke_c ?? "ink")}) drop-shadow(0 0 ${2 * u}px ${col(pal, text.stroke_c ?? "ink")})` } as CSSProperties;
    case "retro": {
      const d = (text.depth ?? 5) * u;
      const c2 = col(pal, text.c2 ?? "accent2"), c3 = col(pal, text.c3 ?? "accent3"), c4 = col(pal, text.c4 ?? "ink");
      return { color, textShadow: `${d}px ${d}px 0 ${c2}, ${d * 2}px ${d * 2}px 0 ${c3}, ${d * 3}px ${d * 3}px 0 ${c4}` };
    }
    case "engrave":
      return { backgroundImage: "linear-gradient(180deg, #f3d28a, #b5792e 55%, #7a4a14)", WebkitBackgroundClip: "text", backgroundClip: "text", WebkitTextFillColor: "transparent", color: "transparent", filter: `drop-shadow(${1.5 * u}px ${2 * u}px 0 rgba(30,10,0,0.7))` } as CSSProperties;
    case "phosphor": {
      const fl = 0.9 + 0.1 * Math.sin(qf * 1.3) + (R(`ph${qf}`) > 0.94 ? -0.2 : 0);
      return { color, opacity: fl, textShadow: `0 0 ${size * 0.05}px ${color}, 0 0 ${size * 0.18}px ${rgba(color, 0.7)}` };
    }
    case "vhs":
      return { color, textShadow: `${-3.5 * u}px 0 rgba(255,40,80,0.75), ${3.5 * u}px 0 rgba(40,220,255,0.75)`, filter: `blur(${0.5 * u}px)` };
    case "marker": {
      const hh = col(pal, text.hi ?? "accent");
      return { color, backgroundImage: `linear-gradient(transparent 52%, ${hh} 52% 92%, transparent 92%)`, padding: "0 0.12em", WebkitBoxDecorationBreak: "clone" as any } as CSSProperties;
    }
    case "cutout": {
      const cols = [col(pal, "paper"), col(pal, "accent"), col(pal, "accent2"), col(pal, "accent3"), col(pal, "bg2")];
      const bg = cols[(o.wi + (text.off ?? 0)) % cols.length];
      return { color: onColor(bg), background: bg, padding: `${0.04 * size}px ${0.16 * size}px`, margin: `${0.03 * size}px ${0.04 * size}px`, transform: `rotate(${(R(`co${o.wi}`) - 0.5) * 9}deg)`, boxShadow: `${2 * u}px ${4 * u}px ${6 * u}px rgba(0,0,0,0.3)`, clipPath: R(`cc${o.wi}`) > 0.6 ? "polygon(1% 6%, 99% 0, 100% 94%, 0 100%)" : undefined };
    }
    case "felt":
      return { color, WebkitTextStroke: `${Math.max(1, 1.5 * u)}px ${rgba("#000000", 0.35)}`, textShadow: `${2 * u}px ${3 * u}px 0 ${rgba("#000000", 0.35)}`, filter: "url(#nm-ink)" };
    case "glass":
      return { color, background: "rgba(255,255,255,0.14)", border: `${2 * u}px solid rgba(255,255,255,0.4)`, backdropFilter: `blur(${14 * u}px)`, padding: `${0.06 * size}px ${0.24 * size}px`, borderRadius: size, boxShadow: `0 ${10 * u}px ${30 * u}px rgba(0,0,0,0.18)`, margin: `${0.04 * size}px` };
    case "brick": {
      const c = col(pal, text.brick ?? "accent");
      return { color: onColor(c), background: c, padding: `${0.03 * size}px ${0.2 * size}px`, margin: `${0.05 * size}px ${0.03 * size}px`, borderRadius: 0.14 * size, boxShadow: `0 ${0.09 * size}px 0 ${shade(c, -0.32)}, inset 0 ${-0.05 * size}px 0 ${rgba("#000000", 0.12)}, inset 0 ${0.04 * size}px 0 ${rgba("#ffffff", 0.3)}` };
    }
    case "softglow":
      return { color, textShadow: `0 0 ${size * 0.1}px ${rgba(col(pal, text.glow ?? "accent"), 0.9)}, 0 0 ${size * 0.35}px ${rgba(col(pal, text.glow ?? "accent"), 0.5)}` };
    case "spray": {
      const g = col(pal, text.glow ?? "accent");
      return { color, WebkitTextStroke: `${Math.max(5, 0.07 * size)}px ${col(pal, text.stroke_c ?? "ink")}`, paintOrder: "stroke fill" as any, textShadow: `0 0 ${size * 0.08}px ${g}, ${size * 0.04}px ${size * 0.05}px 0 ${g}`, filter: "url(#nm-chalk)" };
    }
    case "plain":
    default:
      return { color };
  }
}

const fixDigits = (s: string, fa: boolean, en: boolean): string => (fa ? toFaDigits(s) : en ? toEnDigits(s) : s);

export type TProps = {
  children: string;
  role?: "display" | "body" | "label";
  size: number;
  delay?: number;
  color?: string;
  align?: "center" | "start" | "end";
  weight?: number;
  fx?: string;
  noAnim?: boolean;
  style?: CSSProperties;
  i?: number;
  maxWidth?: number;
  lh?: number;
  upper?: boolean;
};

export const T: React.FC<TProps> = (p) => {
  const ctx = useCtx();
  const qf = useQF();
  const tone = useContext(TONE);
  const { style, pal, u, fps } = ctx;
  const role = p.role ?? "display";
  const raw = fixDigits(String(p.children ?? ""), ctx.faDigits, ctx.spec.digits === "en");
  const fa = hasArabic(raw);
  const f = style.font;
  const latin = role === "display" ? f.latin : f.body_latin ?? "vazirmatn";
  const faKey = role === "display" ? f.fa : f.body_fa ?? "vazirmatn";
  const size = p.size * u;
  const baseColor = col(pal, p.color ?? (role === "body" || role === "label" ? style.text.body_color ?? "ink" : style.text.color ?? "ink"));
  const fx = p.fx ?? (role === "display" ? style.text.fx : style.text.body_fx ?? "plain");
  const color = tone && !p.color ? tone : role === "label" && !tone && fx === "plain" ? readableOn(baseColor, pal.bg, col(pal, "ink")) : baseColor;
  const kind = style.motion.enter;
  const stag = Math.max(1, Math.round(style.motion.stagger * 0.5));
  const align = p.align ?? "center";
  const lines = raw.split(/\n+/);
  let wi = 0;
  const upper = (p.upper ?? (f.case === "upper" && role !== "body")) && !fa;
  const css: CSSProperties = {
    fontFamily: fontStack(latin, faKey),
    fontWeight: p.weight ?? (role === "display" ? f.weight : role === "label" ? 700 : 500),
    fontSize: size,
    lineHeight: p.lh ?? (role === "display" ? f.lh ?? 1.3 : 1.55),
    direction: fa ? "rtl" : ctx.rtl && !hasArabic(raw) && /^[\s\d.,٬٫+\-%$€٪]*$/.test(raw) ? "rtl" : fa ? "rtl" : "ltr",
    textAlign: align === "start" ? (fa ? "right" : "left") : align === "end" ? (fa ? "left" : "right") : "center",
    textTransform: upper ? "uppercase" : undefined,
    letterSpacing: !fa && f.track ? `${f.track}em` : undefined,
    fontStyle: !fa && f.italic ? "italic" : undefined,
    maxWidth: p.maxWidth ? p.maxWidth * u : undefined,
    textWrap: "balance" as any,
    margin: 0,
    ...p.style,
  };

  // typewriter reveal for Latin text; everything else animates word by word
  if (kind === "type" && !fa && role !== "body" && !p.noAnim) {
    const speed = 0.7;
    const n = Math.floor(Math.max(0, qf - (p.delay ?? 0)) * speed);
    const full = raw.replace(/\n/g, " ");
    return (
      <div style={css}>
        <span style={fxCss(fx, { size, u, color, pal, qf, fps, text: style.text, fa, wi: 0, role })}>{full.slice(0, n)}</span>
        <span style={{ visibility: "hidden" }}>{full.slice(n)}</span>
        {n < full.length && <span style={{ color, opacity: Math.floor(qf / 6) % 2 ? 0 : 1 }}>▌</span>}
      </div>
    );
  }

  return (
    <div style={css}>
      {lines.map((line, li) => (
        <div key={li}>
          {line.split(/[ \t]+/).filter(Boolean).map((w, k, arr) => {
            const i = wi++;
            const prog = p.noAnim ? 1 : enterProgress(ctx, qf, (p.delay ?? 0) + i * stag);
            const anim = p.noAnim ? {} : enterCss(role === "body" && kind === "slam" ? "rise" : kind, prog, { u, rtl: ctx.rtl, i, qf, fps });
            const fxs = fxCss(fx, { size, u, color, pal, qf, fps, text: style.text, fa, wi: i, role });
            const merged: CSSProperties = { display: "inline-block", whiteSpace: "nowrap", ...fxs, ...anim };
            if (fxs.transform && anim.transform) merged.transform = `${fxs.transform} ${anim.transform}`;
            if (fxs.filter && anim.filter) merged.filter = `${fxs.filter} ${anim.filter}`;
            if (typeof fxs.opacity === "number" && typeof anim.opacity === "number") merged.opacity = (fxs.opacity as number) * (anim.opacity as number);
            return (
              <React.Fragment key={k}>
                <span style={merged}>{w}</span>
                {k < arr.length - 1 ? " " : ""}
              </React.Fragment>
            );
          })}
        </div>
      ))}
    </div>
  );
};

// ───────────────────────────────────────────── cards

export type CardProps = {
  children?: React.ReactNode;
  delay?: number;
  i?: number;
  pad?: number;           // px at 1080
  fill?: string;          // override style.shape.fill
  style?: CSSProperties;
  noAnim?: boolean;
  enter?: string;
};

export const Card: React.FC<CardProps> = (p) => {
  const ctx = useCtx();
  const qf = useQF();
  const { style, pal, u } = ctx;
  const sh = style.shape;
  const fillName = p.fill ?? sh.fill ?? "paper";
  let bg: string;
  switch (fillName) {
    case "glass": bg = "rgba(255,255,255,0.16)"; break;
    case "none": bg = "transparent"; break;
    default: bg = col(pal, fillName);
  }
  const tone = fillName === "glass" ? (sh.glassTone ? col(pal, sh.glassTone) : "#ffffff") : fillName === "none" ? col(pal, style.text.color ?? "ink") : bestText(bg, [col(pal, "ink"), col(pal, "paper"), "#ffffff", "#16161a"]);
  const toneFinal = sh.tone ? col(pal, sh.tone) : tone;
  const bw = (sh.border ?? 0) * u;
  const bc = col(pal, sh.bc ?? "ink");
  const off = (sh.offset ?? 8) * u;
  let shadow = "none";
  switch (sh.shadow) {
    case "soft": shadow = `0 ${14 * u}px ${34 * u}px rgba(0,0,0,0.25)`; break;
    case "hard": shadow = `${off}px ${off}px 0 ${col(pal, sh.sc ?? sh.bc ?? "ink")}`; break;
    case "long": shadow = longShadow(col(pal, sh.sc ?? "accent2"), 20, 1.3 * u, 1.3 * u); break;
    case "glow": shadow = `0 0 ${24 * u}px ${col(pal, sh.sc ?? "accent")}, inset 0 0 ${18 * u}px ${rgba(col(pal, sh.sc ?? "accent"), 0.25)}`; break;
    case "float": shadow = `0 ${26 * u}px ${40 * u}px rgba(0,0,0,0.3), 0 ${6 * u}px ${10 * u}px rgba(0,0,0,0.18)`; break;
    case "inner": shadow = `inset 0 ${-6 * u}px 0 rgba(0,0,0,0.18), inset 0 ${5 * u}px 0 rgba(255,255,255,0.35), 0 ${12 * u}px ${18 * u}px rgba(0,0,0,0.22)`; break;
    default: break;
  }
  const tilt = (sh.tilt ?? 0) * (((p.i ?? 0) % 2) ? -1 : 1);
  const prog = p.noAnim ? 1 : enterProgress(ctx, qf, p.delay ?? 0);
  const ek = p.enter ?? (style.motion.enter === "type" ? "wipe" : style.motion.enter);
  const anim = p.noAnim ? {} : enterCss(ek, prog, { u, rtl: ctx.rtl, i: p.i ?? 0, qf, fps: ctx.fps });
  const css: CSSProperties = {
    position: "relative",
    background: sh.fillGradient ? `linear-gradient(${sh.fillGradient}deg, ${bg}, ${shade(bg, -0.15)})` : bg,
    borderRadius: (sh.radius ?? 0) * u,
    border: bw ? `${bw}px ${sh.dash ? "dashed" : "solid"} ${bc}` : undefined,
    boxShadow: shadow,
    padding: (p.pad ?? 28) * u,
    backdropFilter: fillName === "glass" ? `blur(${22 * u}px) saturate(1.4)` : undefined,
    WebkitBackdropFilter: fillName === "glass" ? `blur(${22 * u}px) saturate(1.4)` : undefined,
    clipPath: sh.clip === "notch" ? `polygon(${10 * u}px 0, calc(100% - ${10 * u}px) 0, calc(100% - ${10 * u}px) ${10 * u}px, 100% ${10 * u}px, 100% calc(100% - ${10 * u}px), calc(100% - ${10 * u}px) calc(100% - ${10 * u}px), calc(100% - ${10 * u}px) 100%, ${10 * u}px 100%, ${10 * u}px calc(100% - ${10 * u}px), 0 calc(100% - ${10 * u}px), 0 ${10 * u}px, ${10 * u}px ${10 * u}px)` : sh.clip === "torn" ? "polygon(0 2%, 8% 0, 22% 3%, 40% 0, 58% 2%, 76% 0, 100% 3%, 99% 40%, 100% 70%, 98% 100%, 80% 98%, 60% 100%, 38% 97%, 20% 100%, 0 98%, 2% 60%)" : undefined,
    transform: tilt ? `rotate(${tilt}deg)` : undefined,
    ...anim,
    ...p.style,
  };
  if (anim.transform && tilt) css.transform = `rotate(${tilt}deg) ${anim.transform}`;
  const extra = sh.extra as string | undefined;
  return (
    <div style={css}>
      {extra === "studs" && (
        <div style={{ position: "absolute", left: 0, right: 0, top: -14 * u, height: 16 * u, display: "flex", justifyContent: "space-around", padding: `0 ${16 * u}px` }}>
          {[0, 1, 2].map((k) => <div key={k} style={{ width: 30 * u, height: 16 * u, borderRadius: `${8 * u}px ${8 * u}px 0 0`, background: shade(bg, 0.12), boxShadow: `inset 0 ${-3 * u}px 0 ${rgba("#000000", 0.18)}` }} />)}
        </div>
      )}
      {extra === "rivets" && [[8, 8], [92, 8], [8, 92], [92, 92]].map(([x, y], k) => <div key={k} style={{ position: "absolute", left: `${x}%`, top: `${y}%`, width: 14 * u, height: 14 * u, marginLeft: -7 * u, marginTop: -7 * u, borderRadius: "50%", background: "radial-gradient(circle at 35% 30%, #ffe3a8, #8a5a1c)", boxShadow: `0 ${2 * u}px 0 rgba(0,0,0,0.5)` }} />)}
      {extra === "titlebar" && (
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 44 * u, background: col(pal, sh.bar ?? "accent2"), borderBottom: `${3 * u}px solid ${bc}`, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8 * u, padding: `0 ${14 * u}px` }}>
          {[0, 1, 2].map((k) => <div key={k} style={{ width: 20 * u, height: 20 * u, background: col(pal, "paper"), border: `${2 * u}px solid ${bc}` }} />)}
        </div>
      )}
      {extra === "tape" && <div style={{ position: "absolute", left: "50%", top: -18 * u, width: 150 * u, height: 40 * u, marginLeft: -75 * u, background: rgba(col(pal, "accent3"), 0.7), transform: `rotate(${(R(`tp${p.i ?? 0}`) - 0.5) * 8}deg)`, boxShadow: `0 ${2 * u}px ${4 * u}px rgba(0,0,0,0.2)` }} />}
      {extra === "band" && <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 14 * u, background: col(pal, sh.bandColor ?? "accent"), borderRadius: `${(sh.radius ?? 0) * u}px ${(sh.radius ?? 0) * u}px 0 0` }} />}
      {extra === "corner" && [[0, 0], [1, 0], [0, 1], [1, 1]].map(([x, y], k) => <div key={k} style={{ position: "absolute", [x ? "right" : "left"]: 10 * u, [y ? "bottom" : "top"]: 10 * u, width: 22 * u, height: 22 * u, [`border${y ? "Bottom" : "Top"}`]: `${3 * u}px solid ${bc}`, [`border${x ? "Right" : "Left"}`]: `${3 * u}px solid ${bc}` }} />)}
      <TONE.Provider value={toneFinal}>{p.children}</TONE.Provider>
    </div>
  );
};

// ───────────────────────────────────────────── SVG filters used by the styles (one hidden <svg> per video)

export const SvgDefs: React.FC = () => {
  const ctx = useCtx();
  const f = useQF();
  const { style, u, fps } = ctx;
  const boilSeed = (Math.floor(f / Math.max(1, fps / 8)) % 8) + 1;
  const wob = (style.motion.wobble ?? 0) * u;
  // Pixelation: the sampling dot of the filter must cover at least ONE DEVICE pixel, or the browser rounds it to nothing and the text vanishes.
  // A render at "scale" < 1 (540p / 360p, thumbnails) is a page with devicePixelRatio < 1, so the dot grows by 1 / ratio.
  const dpr = Math.max(0.2, Number((globalThis as any).devicePixelRatio) || 1);
  const dot = Math.max(1, Math.ceil(1 / dpr));
  const px = Math.max(2 * dot, (style.fx?.pixel ?? 5) * u);
  const chroma = (style.fx?.chroma ?? 0) * u;
  const levels = style.fx?.posterize ?? 5;
  const table = Array.from({ length: levels }).map((_, i) => (i / (levels - 1)).toFixed(3)).join(" ");
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden>
      <defs>
        <filter id="nm-rough" x="-5%" y="-10%" width="110%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed={boilSeed} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={Math.max(1.5 * u, wob)} xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <filter id="nm-chalk" x="-5%" y="-10%" width="110%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves="3" seed={boilSeed} result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={Math.max(2.5 * u, wob * 0.8)} xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <filter id="nm-ink" x="-5%" y="-10%" width="110%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.5" numOctaves="2" seed="3" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={2.2 * u} xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <filter id="nm-wash" x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.012" numOctaves="4" seed="5" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale={46 * u} xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <filter id="nm-pixel" x="0" y="0" width="100%" height="100%">
          <feFlood x={(px - dot) / 2} y={(px - dot) / 2} width={dot} height={dot} />
          <feComposite width={px} height={px} />
          <feTile result="a" />
          <feComposite in="SourceGraphic" in2="a" operator="in" />
          <feMorphology operator="dilate" radius={px / 2} />
        </filter>
        <filter id="nm-chroma" x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
          <feColorMatrix in="SourceGraphic" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r" />
          <feOffset in="r" dx={chroma} dy="0" result="ro" />
          <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="g" />
          <feColorMatrix in="SourceGraphic" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="b" />
          <feOffset in="b" dx={-chroma} dy="0" result="bo" />
          <feBlend in="ro" in2="g" mode="screen" result="rg" />
          <feBlend in="rg" in2="bo" mode="screen" />
        </filter>
        <filter id="nm-posterize" colorInterpolationFilters="sRGB">
          <feComponentTransfer>
            <feFuncR type="discrete" tableValues={table} />
            <feFuncG type="discrete" tableValues={table} />
            <feFuncB type="discrete" tableValues={table} />
          </feComponentTransfer>
        </filter>
      </defs>
    </svg>
  );
};

export { cameraCss, clamp };
