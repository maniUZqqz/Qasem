import React from "react";
import { AbsoluteFill, Img, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { OVERLAY_KINDS, cameraCss, transitionCss } from "./anim";
import { Background } from "./bg";
import { Decor } from "./decor";
import { CtxC, buildCtx, fontKeysOf, useAsset, useCtx, useFonts } from "./ctx";
import type { Ctx } from "./ctx";
import { SCENES } from "./scenes";
import { SvgDefs } from "./text";
import { Textures } from "./tex";
import { ASPECTS } from "./types";
import type { Scene, Spec, StyleDef } from "./types";
import { R, clamp, col, rgba } from "./util";
import CATALOG from "./styles.generated.json";

export const STYLES: StyleDef[] = (CATALOG as any).styles as StyleDef[];
export function getStyle(id: string): StyleDef {
  return STYLES.find((s) => s.id === id) ?? STYLES[0];
}

// ───────────────────────────────────────────── timeline: scene lengths, overlaps (transitions), total

export type Timeline = { frames: number[]; starts: number[]; tf: number; total: number; kind: string };

export function computeTimeline(spec: Spec, style: StyleDef, fps: number): Timeline {
  const frames = (spec.scenes || []).map((s) => Math.max(fps, Math.round(Math.max(1, Math.min(60, Number(s.duration) || 4)) * fps)));
  const kind = spec.transition || style.trans.kind;
  let tf = kind === "cut" ? 0 : Math.max(0, Math.min(style.trans.frames, Math.floor(Math.min(...frames, 9999) * 0.45)));
  if (frames.length < 2) tf = 0;
  const starts: number[] = [];
  let at = 0;
  frames.forEach((f, i) => {
    starts.push(at);
    at += f - (i < frames.length - 1 ? tf : 0);
  });
  return { frames, starts, tf, total: Math.max(1, at), kind };
}

export function calcMetadata(spec: Spec) {
  const [width, height] = ASPECTS[spec.aspect] ?? ASPECTS["9:16"];
  const fps = Math.max(10, Math.min(60, Number(spec.fps) || 30));
  const tl = computeTimeline(spec, getStyle(spec.style), fps);
  return { width, height, fps, durationInFrames: tl.total };
}

// ───────────────────────────────────────────── one scene

const BrandBadge: React.FC = () => {
  const { spec, u, W, pal } = useCtx();
  const logo = useAsset(spec.brand?.logo);
  if (!logo || spec.brand?.show_logo === false) return null;
  const size = Math.min(W, 1080) * 0.13;
  return (
    <div style={{ position: "absolute", top: 40 * u, left: 40 * u, width: size, height: size, borderRadius: size * 0.22, background: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 ${6 * u}px ${18 * u}px rgba(0,0,0,0.25)`, border: `${2 * u}px solid ${rgba(col(pal, "ink"), 0.12)}` }}>
      <Img src={logo} style={{ width: "76%", height: "76%", objectFit: "contain" }} />
    </div>
  );
};

const SceneView: React.FC<{ sc: Scene; i: number; base: Omit<Ctx, "scene">; tl: Timeline }> = ({ sc, i, base, tl }) => {
  const f = useCurrentFrame();
  const style = base.style;
  const count = tl.frames.length;
  const ctx: Ctx = { ...base, scene: { index: i, frames: tl.frames[i], count } };
  const Body = SCENES[sc.type] ?? SCENES.title;
  const kind = tl.kind;
  const tf = tl.tf;
  const seed = i * 7 + 1;
  let wrap: React.CSSProperties = {};
  if (tf > 0) {
    if (i > 0 && f < tf) wrap = { ...wrap, ...transitionCss(kind, f / tf, "in", { W: base.W, H: base.H, rtl: base.rtl, seed }) };
    const outStart = tl.frames[i] - tf;
    if (i < count - 1 && f >= outStart) wrap = { ...wrap, ...transitionCss(kind, (f - outStart) / tf, "out", { W: base.W, H: base.H, rtl: base.rtl, seed: seed + 1 }) };
  }
  const grade = style.fx?.grade as string | undefined;
  const filters: string[] = [];
  if (grade) filters.push(grade);
  if (style.fx?.chroma) filters.push("url(#nm-chroma)");
  if (style.fx?.posterize) filters.push("url(#nm-posterize)");
  const use2 = i % 2 === 1 && style.bg2 ? style.bg2 : style.bg;
  return (
    <CtxC.Provider value={ctx}>
      <AbsoluteFill style={{ ...wrap }}>
        <AbsoluteFill style={{ filter: filters.length ? filters.join(" ") : undefined, ...cameraCss(ctx, f, tl.frames[i]) }}>
          <Background spec={use2} variant={i} />
          <Decor layers={style.decor} />
          <Body sc={sc} />
          <Decor layers={style.decor} over />
        </AbsoluteFill>
        {sc.type !== "logo" ? <BrandBadge /> : null}
      </AbsoluteFill>
    </CtxC.Provider>
  );
};

/** squares that cover the cut (kind "blocks") / a white flash (kind "flash") */
const CutOverlay: React.FC<{ kind: string; base: Omit<Ctx, "scene"> }> = ({ kind, base }) => {
  const f = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const t = clamp(f / Math.max(1, durationInFrames - 1));
  const e = 1 - Math.abs(2 * t - 1);
  const { W, H, pal } = base;
  if (kind === "flash") return <AbsoluteFill style={{ background: "#ffffff", opacity: Math.pow(e, 1.4) }} />;
  if (kind !== "blocks") return null;
  const n = W > H ? 12 : 7;
  const cell = W / n;
  const rows = Math.ceil(H / cell);
  const colors = [pal.accent, pal.accent2, pal.accent3, pal.ink];
  return (
    <AbsoluteFill>
      {Array.from({ length: rows * n }).map((_, k) => {
        const r = Math.floor(k / n), c = k % n;
        const th = R(`bl${r}-${c}`);
        const s = clamp((e - th * 0.5) * 2);
        return <div key={k} style={{ position: "absolute", left: c * cell, top: r * cell, width: cell + 1, height: cell + 1, background: colors[(r + c) % colors.length], transform: `scale(${s})` }} />;
      })}
    </AbsoluteFill>
  );
};

export const Template: React.FC<{ spec: Spec }> = ({ spec }) => {
  const { width, height, fps } = useVideoConfig();
  const style = getStyle(spec.style);
  const base = buildCtx(style, spec, width, height, fps);
  const tl = computeTimeline(spec, style, fps);
  useFonts(fontKeysOf(style));
  const rootCtx: Ctx = { ...base, scene: { index: 0, frames: tl.total, count: tl.frames.length } };
  const dip = tl.kind === "dip";
  return (
    <CtxC.Provider value={rootCtx}>
      <AbsoluteFill style={{ background: dip ? "#000000" : base.pal.bg }}>
        <SvgDefs />
        {spec.scenes.map((sc, i) => (
          <Sequence key={i} from={tl.starts[i]} durationInFrames={tl.frames[i]} layout="none">
            <SceneView sc={sc} i={i} base={base} tl={tl} />
          </Sequence>
        ))}
        {tl.tf > 0 && (tl.kind === "blocks" || tl.kind === "flash")
          ? spec.scenes.slice(1).map((_, j) => (
              <Sequence key={`o${j}`} from={tl.starts[j + 1]} durationInFrames={Math.max(1, tl.tf)} layout="none">
                <CutOverlay kind={tl.kind} base={base} />
              </Sequence>
            ))
          : null}
        <AbsoluteFill style={{ pointerEvents: "none" }}>
          <Textures layers={style.tex} />
        </AbsoluteFill>
      </AbsoluteFill>
    </CtxC.Provider>
  );
};

export { OVERLAY_KINDS };
