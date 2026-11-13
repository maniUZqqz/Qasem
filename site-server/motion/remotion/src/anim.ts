import type { CSSProperties } from "react";
import { Easing, interpolate, spring } from "remotion";
import type { Ctx } from "./ctx";
import { clamp, R } from "./util";

/** 0..~1.2 spring progress for an element that starts at `delay` frames (uses the style's spring + stagger) */
export function enterProgress(ctx: Ctx, qf: number, delay = 0): number {
  const [damping, stiffness, mass] = ctx.style.motion.spring;
  const k = ctx.intensity;
  return spring({
    frame: qf - delay,
    fps: ctx.fps,
    config: { damping: damping / Math.sqrt(k), stiffness: stiffness * k, mass },
  });
}

export type EnterOpts = { u: number; rtl: boolean; i: number; qf: number; fps: number };

/** CSS of an element while it enters. p: spring progress (overshoots), kind: style.motion.enter */
export function enterCss(kind: string, p: number, o: EnterOpts): CSSProperties {
  const c = clamp(p);
  const op = (k: number) => clamp(p * k);
  const dir = o.rtl ? -1 : 1;
  const u = o.u;
  switch (kind) {
    case "pop":
      return { transform: `scale(${Math.max(0.001, p)})`, opacity: op(2.5) };
    case "rise":
      return { transform: `translateY(${(1 - p) * 70 * u}px)`, opacity: op(2) };
    case "drop":
      return { transform: `translateY(${-(1 - p) * 150 * u}px)`, opacity: op(4) };
    case "slide":
      return { transform: `translateX(${(1 - p) * 220 * u * dir}px)`, opacity: op(2.2) };
    case "wipe":
    case "type": {
      const cut = (1 - c) * 100;
      return { clipPath: o.rtl ? `inset(-10% -4% -10% ${cut}%)` : `inset(-10% ${cut}% -10% -4%)`, opacity: c > 0 ? 1 : 0 };
    }
    case "scan":
      return { clipPath: `inset(0 0 ${(1 - c) * 100}% 0)`, opacity: c > 0 ? 1 : 0 };
    case "flip":
      return { transform: `perspective(900px) rotateX(${(1 - p) * 88}deg)`, opacity: op(3), transformOrigin: "50% 100%" };
    case "unfold":
      return { transform: `perspective(900px) rotateX(${(1 - c) * -80}deg) scaleY(${0.2 + 0.8 * c})`, transformOrigin: "50% 0%", opacity: op(3) };
    case "spin":
      return { transform: `rotate(${(1 - p) * -200}deg) scale(${Math.max(0.001, p)})`, opacity: op(3) };
    case "blur":
      return { filter: `blur(${(1 - c) * 26 * u}px)`, transform: `scale(${1.08 - 0.08 * c})`, opacity: op(2) };
    case "bloom":
      return { filter: `blur(${(1 - c) * 34 * u}px)`, transform: `scale(${0.92 + 0.08 * c})`, opacity: op(1.6) };
    case "stamp":
      return { transform: `scale(${1 + (1 - c) * 2.4}) rotate(${(1 - c) * -9}deg)`, opacity: op(6) };
    case "swing":
      return { transform: `rotate(${(1 - p) * 38}deg)`, transformOrigin: "50% -20%", opacity: op(4) };
    case "build":
      return { transform: `translateY(${-(1 - p) * 520 * u}px)`, opacity: p > 0.001 ? 1 : 0 };
    case "glitch": {
      if (c >= 1) return {};
      const j = (R(`g${o.qf}${o.i}`) - 0.5) * 70 * u * (1 - c);
      return { transform: `translateX(${j}px) skewX(${j * 0.2}deg)`, opacity: R(`go${o.qf}${o.i}`) > 0.25 ? 1 : 0.15 };
    }
    case "sweep":
      return { transform: `translateX(${(1 - p) * 320 * u * dir}px) skewX(${(1 - c) * -18 * dir}deg)`, opacity: op(3) };
    case "squash": {
      const sy = Math.max(0.001, p);
      const sx = 1 + (1 - p) * 0.35;
      return { transform: `scale(${sx}, ${sy})`, transformOrigin: "50% 100%", opacity: op(3) };
    }
    case "zoompunch":
      return { transform: `scale(${1 + (1 - c) * 0.9})`, opacity: op(3.5), filter: `blur(${(1 - c) * 8 * u}px)` };
    case "float":
      return { transform: `translateY(${(1 - p) * 46 * u}px) rotate(${(1 - c) * 2.2 * dir}deg)`, opacity: op(1.8) };
    case "slam":
      return { transform: `scale(${1 + (1 - c) * 3.2})`, opacity: op(8) };
    case "lightup":
      return { opacity: op(2), filter: `brightness(${1 + (1 - c) * 1.6})` };
    case "grow":
      return { transform: `scaleY(${Math.max(0.001, p)})`, transformOrigin: "50% 100%", opacity: c > 0 ? 1 : 0 };
    case "fade":
    default:
      return { opacity: c };
  }
}

/** slow virtual camera of a scene (zoom / pan / roll over its length) */
export function cameraCss(ctx: Ctx, f: number, frames: number): CSSProperties {
  const cam = ctx.style.motion.cam;
  if (!cam) return {};
  const t = clamp(f / Math.max(1, frames));
  const e = Easing.inOut(Easing.quad)(t);
  const k = ctx.intensity;
  const z = 1 + (cam.zoom ?? 0) * (cam.zoomIn === false ? 1 - e : e) * k;
  const [px, py] = cam.pan ?? [0, 0];
  const sway = cam.sway ? Math.sin((f / ctx.fps) * (cam.swayHz ?? 0.6)) * cam.sway * ctx.u : 0;
  const rot = (cam.rot ?? 0) * (t - 0.5) * k;
  return { transform: `translate(${(px * (t - 0.5) * 2 * ctx.u + sway) * k}px, ${py * (t - 0.5) * 2 * ctx.u * k}px) scale(${z}) rotate(${rot}deg)` };
}

// ───────────────────────────────────────────── transitions between scenes

export type TransOpts = { W: number; H: number; rtl: boolean; seed: number };

export function transitionCss(kind: string, t: number, role: "in" | "out", o: TransOpts): CSSProperties {
  const c = clamp(t);
  const dir = o.rtl ? -1 : 1;
  switch (kind) {
    case "fade":
      return role === "in" ? { opacity: c } : { opacity: 1 - c * 0.0 };
    case "dip":
      return role === "in" ? { opacity: c < 0.5 ? 0 : (c - 0.5) * 2 } : { opacity: c < 0.5 ? 1 - c * 2 : 0 };
    case "slide":
      return role === "in"
        ? { transform: `translateX(${(1 - c) * 100 * dir}%)` }
        : { transform: `translateX(${-c * 100 * dir}%)` };
    case "push":
      return role === "in"
        ? { transform: `translateY(${(1 - c) * 100}%)` }
        : { transform: `translateY(${-c * 100}%)` };
    case "cover":
      return role === "in" ? { transform: `translateX(${(1 - c) * 100 * dir}%)` } : { transform: `translateX(${-c * 18 * dir}%)`, filter: `brightness(${1 - c * 0.5})` };
    case "wipe":
      return role === "in" ? { clipPath: dir === 1 ? `inset(0 ${(1 - c) * 100}% 0 0)` : `inset(0 0 0 ${(1 - c) * 100}%)` } : {};
    case "wipe-diag":
      return role === "in" ? { clipPath: `polygon(0 0, ${c * 220 - 60}% 0, ${c * 220 - 120}% 100%, 0 100%)` } : {};
    case "zoom":
      return role === "in"
        ? { transform: `scale(${0.7 + 0.3 * c})`, opacity: c }
        : { transform: `scale(${1 + 0.35 * c})`, opacity: 1 - c };
    case "iris":
      return role === "in" ? { clipPath: `circle(${c * 78}% at 50% 50%)` } : {};
    case "curtain":
      return role === "in" ? { clipPath: `inset(0 ${(1 - c) * 50}% 0 ${(1 - c) * 50}%)` } : {};
    case "flip":
      return role === "in"
        ? { transform: `perspective(1400px) rotateY(${(1 - c) * 90 * dir}deg)`, opacity: c > 0.02 ? 1 : 0 }
        : { transform: `perspective(1400px) rotateY(${-c * 90 * dir}deg)`, opacity: c < 0.98 ? 1 : 0 };
    case "spin":
      return role === "in"
        ? { transform: `rotate(${(1 - c) * 120}deg) scale(${c})`, opacity: c }
        : { transform: `rotate(${-c * 60}deg) scale(${1 - c * 0.5})`, opacity: 1 - c };
    case "whip":
      return role === "in"
        ? { transform: `translateX(${(1 - c) * 100 * dir}%)`, filter: `blur(${(1 - c) * 40}px)` }
        : { transform: `translateX(${-c * 100 * dir}%)`, filter: `blur(${c * 40}px)` };
    case "glitch": {
      const j = (R(`tg${o.seed}${Math.floor(c * 18)}`) - 0.5) * 120 * Math.sin(c * Math.PI);
      const vis = role === "in" ? (c > 0.5 ? 1 : 0) : c < 0.5 ? 1 : 0;
      return { opacity: vis, transform: `translateX(${j}px)`, filter: `hue-rotate(${Math.sin(c * 40) * 70}deg) saturate(1.6)` };
    }
    case "roll":
      return role === "in"
        ? { transform: `translateY(${(1 - c) * -100}%)`, filter: "brightness(1.4) contrast(1.2)" }
        : { transform: `translateY(${c * 100}%)` };
    case "blocks":
    case "flash":
      return role === "in" ? { opacity: c >= 0.5 ? 1 : 0 } : { opacity: c < 0.5 ? 1 : 0 };
    case "cut":
    default:
      return role === "in" ? { opacity: c > 0 ? 1 : 0 } : {};
  }
}

/** kinds where the incoming scene must NOT sit on top while it is invisible (cover & reveal) */
export const OVERLAY_KINDS = new Set(["blocks", "glitch", "flash"]);

export const ease = {
  out: Easing.out(Easing.cubic),
  inOut: Easing.inOut(Easing.cubic),
  back: Easing.out(Easing.back(1.6)),
};

export function pulse(frame: number, fps: number, hz = 1, amp = 1): number {
  return Math.sin((frame / fps) * Math.PI * 2 * hz) * amp;
}

export { interpolate };
