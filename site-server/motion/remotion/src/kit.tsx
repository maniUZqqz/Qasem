// Shared building blocks of the component library: the safe-area Stage, entering elements, rules, badges, icons, cue-synced delays.
import React from "react";
import type { CSSProperties } from "react";
import { enterCss, enterProgress } from "./anim";
import { useCtx, useQF } from "./ctx";
import type { Ctx } from "./ctx";
import EMOJISET from "./emoji.generated.json";
import ICONSET from "./icons.generated.json";
import { easeOf } from "./presets";
import { T } from "./text";
import { clamp, col, onColor } from "./util";

/** the content area: the frame minus the style's margins minus the platform's UI bars (px of the composition) */
export function area(ctx: Ctx, full = false): { x: number; y: number; w: number; h: number } {
  const { W, H, wide, safe, capBand } = ctx;
  const px = wide ? W * 0.09 : W * 0.085, py = wide ? H * 0.08 : H * 0.07;
  const left = Math.max(px, safe.left), right = Math.max(px, safe.right);
  const top = Math.max(py, safe.top) + (full ? 0 : capBand.top), bottom = Math.max(py, safe.bottom) + (full ? 0 : capBand.bottom);
  return { x: left, y: top, w: W - left - right, h: H - top - bottom };
}

export const Stage: React.FC<{ children?: React.ReactNode; gap?: number; row?: boolean; justify?: CSSProperties["justifyContent"] }> = ({ children, gap = 36, row, justify = "center" }) => {
  const ctx = useCtx();
  const { u, rtl } = ctx;
  const a = area(ctx);
  return (
    <div
      data-nm="stage"
      style={{ position: "absolute", left: a.x, top: a.y, width: a.w, height: a.h, display: "flex", flexDirection: row ? (rtl ? "row-reverse" : "row") : "column", justifyContent: justify, alignItems: "center", gap: gap * u, boxSizing: "border-box" }}
    >
      {children}
    </div>
  );
};

/** a small element that enters with the scene's motion (bars, badges, rings) */
export const Pop: React.FC<{ delay?: number; children?: React.ReactNode; style?: CSSProperties; i?: number; kind?: string }> = ({ delay = 0, children, style, i = 0, kind }) => {
  const ctx = useCtx();
  const qf = useQF();
  const p = enterProgress(ctx, qf, delay);
  return <div style={{ ...enterCss(kind ?? ctx.enter, p, { u: ctx.u, rtl: ctx.rtl, i, qf, fps: ctx.fps }), ...style }}>{children}</div>;
};

export const Rule: React.FC<{ delay?: number; w?: number }> = ({ delay = 8, w = 260 }) => {
  const { pal, u, style } = useCtx();
  return (
    <Pop delay={delay} kind="wipe">
      <div style={{ width: w * u, height: 14 * u, background: col(pal, style.shape.rule ?? "accent"), borderRadius: Math.min(7, style.shape.radius ?? 0) * u, boxShadow: style.shape.shadow === "hard" ? `${5 * u}px ${5 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : undefined }} />
    </Pop>
  );
};

export const Badge: React.FC<{ n: string; size?: number }> = ({ n, size = 76 }) => {
  const { pal, u, style } = useCtx();
  const bg = col(pal, style.shape.badge ?? "accent");
  return (
    <div style={{ width: size * u, height: size * u, flex: "none", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: style.shape.badgeRound === false ? (style.shape.radius ?? 0) * u : "50%", background: bg, border: style.shape.border ? `${Math.max(3, (style.shape.border ?? 0) * 0.7) * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined, boxShadow: style.shape.shadow === "hard" ? `${4 * u}px ${4 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
      <T noAnim fixed size={size * 0.55} color={onColor(bg)} fx="plain" style={{ lineHeight: 1 }}>{n}</T>
    </div>
  );
};

// ───────────────────────────────────────────── timing helpers

/** frames the i-th of n elements waits: stepped by the style's stagger, or - when the scene has word timings - the moment the matching word is spoken */
export function itemDelay(ctx: Ctx, i: number, n: number, base: number, step: number): number {
  const fallback = base + i * step;
  const cues = ctx.cues;
  if (!cues.length) return fallback;
  const idx = Math.min(cues.length - 1, Math.floor((i * cues.length) / Math.max(1, n)));
  return Math.max(0, Math.round((cues[idx].s - 0.1) * ctx.fps));
}

/** 0..1 progress of a growing thing (bar, line, ring) that starts after `delay` frames and takes `len` frames, with the scene's easing preset */
export function useGrow(delay: number, len: number): number {
  const ctx = useCtx();
  const qf = useQF();
  const e = easeOf(ctx.easeName);
  return clamp(e(clamp((qf - delay) / Math.max(1, len))), 0, 1.15);
}

export const stagger = (ctx: Ctx, min = 4) => Math.max(min, ctx.style.motion.stagger);

// ───────────────────────────────────────────── icons (Lucide, ISC licence - see ICONS-LICENSE.txt)

const ICONS = (ICONSET as any).icons as { [name: string]: string };
export const ICON_NAMES = Object.keys(ICONS);

export const Icon: React.FC<{ name: string; size: number; color?: string; stroke?: number; style?: CSSProperties }> = ({ name, size, color, stroke = 1.9, style }) => {
  const { u } = useCtx();
  const inner = ICONS[name] ?? ICONS["circle-check"] ?? "";
  return (
    <svg width={size * u} height={size * u} viewBox="0 0 24 24" fill="none" stroke={color ?? "currentColor"} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{ flex: "none", display: "block", ...style }} aria-hidden dangerouslySetInnerHTML={{ __html: inner }} />
  );
};

// ───────────────────────────────────────────── emoji (Twemoji vector art, CC-BY 4.0 - see ICONS-LICENSE.txt)

const EMOJIS = (EMOJISET as any).emoji as { [name: string]: string };
export const EMOJI_NAMES = Object.keys(EMOJIS);

/** a colour emoji drawn as vector art (identical on every machine, unlike a colour-emoji font); an unknown name draws nothing */
export const Emoji: React.FC<{ name: string; size: number; style?: CSSProperties }> = ({ name, size, style }) => {
  const { u } = useCtx();
  const inner = EMOJIS[name];
  if (!inner) return null;
  return <svg width={size * u} height={size * u} viewBox="0 0 36 36" style={{ flex: "none", display: "block", ...style }} aria-hidden dangerouslySetInnerHTML={{ __html: inner }} />;
};

/** a rounded tile with an icon: the unit of icon grids and feature cards */
export const IconTile: React.FC<{ name: string; size?: number; fill?: string }> = ({ name, size = 110, fill }) => {
  const { pal, u, style } = useCtx();
  const bg = fill ?? col(pal, "accent");
  const fg = onColor(bg);
  return (
    <div style={{ width: size * u, height: size * u, flex: "none", borderRadius: style.shape.badgeRound === false ? Math.min(28, style.shape.radius ?? 0) * u : size * 0.3 * u, background: bg, display: "flex", alignItems: "center", justifyContent: "center", border: style.shape.border ? `${Math.max(3, (style.shape.border ?? 0) * 0.6) * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined, boxShadow: style.shape.shadow === "hard" ? `${5 * u}px ${5 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
      <Icon name={name} size={size * 0.52} color={fg} />
    </div>
  );
};

/** the colour i of the style's accent cycle */
export const accentAt = (ctx: Ctx, i: number): string => col(ctx.pal, ["accent", "accent2", "accent3"][i % 3]);

export const PLATFORM_ICON: { [k: string]: string } = {
  instagram: "camera", telegram: "send", whatsapp: "message-circle", website: "globe", youtube: "play", aparat: "play", eitaa: "message-circle", rubika: "message-circle", phone: "phone", email: "mail", app: "smartphone",
};
