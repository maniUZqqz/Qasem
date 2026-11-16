import React from "react";
import { AbsoluteFill, Img, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { OVERLAY_KINDS, cameraCss, exitCss, transitionCss } from "./anim";
import { Background } from "./bg";
import { Decor } from "./decor";
import { CtxC, buildCtx, fontKeysOf, sceneCtx, useAsset, useCtx, useFonts } from "./ctx";
import type { Ctx } from "./ctx";
import { area } from "./kit";
import { computeTimeline } from "./timeline";
import type { Timeline } from "./timeline";
import { QaProbe } from "./qa";
import { COMPONENTS, OVERLAYS } from "./registry";
import { CaptionsLine } from "./comp-text";
import { SvgDefs } from "./text";
import { Textures } from "./tex";
import { ASPECTS } from "./types";
import type { Overlay, Scene, Spec, StyleDef } from "./types";
import { R, clamp, col, rgba } from "./util";
import CATALOG from "./styles.generated.json";

export const STYLES: StyleDef[] = (CATALOG as any).styles as StyleDef[];
export function getStyle(id: string): StyleDef {
  return STYLES.find((s) => s.id === id) ?? STYLES[0];
}

// ───────────────────────────────────────────── timeline: scene lengths, overlaps (transitions, one per JOIN), total

export type { Timeline };
export { computeTimeline };

export function calcMetadata(spec: Spec) {
  const [width, height] = ASPECTS[spec.aspect] ?? ASPECTS["9:16"];
  const fps = Math.max(10, Math.min(60, Number(spec.fps) || 30));
  const tl = computeTimeline(spec, getStyle(spec.style), fps);
  return { width, height, fps, durationInFrames: tl.total };
}

// ───────────────────────────────────────────── one scene

const BrandBadge: React.FC = () => {
  const { spec, u, W, pal, safe } = useCtx();
  const logo = useAsset(spec.brand?.logo);
  if (!logo || spec.brand?.show_logo === false) return null;
  const size = Math.min(W, 1080) * 0.13;
  return (
    <div style={{ position: "absolute", top: Math.max(40 * u, safe.top * 0.4), left: Math.max(40 * u, safe.left), width: size, height: size, borderRadius: size * 0.22, background: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 ${6 * u}px ${18 * u}px rgba(0,0,0,0.25)`, border: `${2 * u}px solid ${rgba(col(pal, "ink"), 0.12)}` }}>
      <Img src={logo} style={{ width: "76%", height: "76%", objectFit: "contain" }} />
    </div>
  );
};

/** where an overlay sits inside the safe area (anchor + offsets as fractions of the area) */
function overlayBox(ctx: Ctx, ov: Overlay): React.CSSProperties {
  const a = area(ctx, ov.type === "captions");            // the captions track sits in its own band below / above the content area
  const { W, H, rtl, safe } = ctx;
  let anchor = String(ov.anchor || (ov.type === "lower_third" ? "lower" : ov.type === "captions" ? "lower" : ov.type === "ticker" ? "bottom" : ov.type === "sticker" ? "top-end" : ov.type === "brand_character" ? "bottom" : "lower"));
  if (ov.type === "captions") anchor = anchor === "lower" ? "bottom" : anchor === "upper" ? "top" : anchor;
  const dx = (Number(ov.dx) || 0) * a.w, dy = (Number(ov.dy) || 0) * a.h;
  const full = ov.type === "ticker";
  const h = anchor.startsWith("top") ? "start" : anchor.startsWith("bottom") ? "start" : "center";
  void h;
  const side = anchor.endsWith("-start") ? (rtl ? "flex-end" : "flex-start") : anchor.endsWith("-end") ? (rtl ? "flex-start" : "flex-end") : "center";
  const base: React.CSSProperties = { position: "absolute", left: full ? 0 : a.x + dx, width: full ? W : a.w, display: "flex", justifyContent: side };
  if (anchor === "top" || anchor.startsWith("top")) return { ...base, top: (full ? safe.top : a.y) + dy };
  if (anchor === "upper") return { ...base, top: a.y + a.h * 0.2 + dy };
  if (anchor === "center") return { ...base, top: a.y + a.h * 0.5 + dy, transform: "translateY(-50%)" };
  if (anchor === "bottom" || anchor.startsWith("bottom")) return { ...base, bottom: H - (full ? H - safe.bottom : a.y + a.h) - dy };
  return { ...base, bottom: H - (a.y + a.h * 0.86) - dy };       // lower (the lower third of the safe area)
}

const OverlayLayer: React.FC<{ overlays: Overlay[]; sc: Scene }> = ({ overlays, sc }) => {
  const ctx = useCtx();
  const { fps } = ctx;
  return (
    <>
      {overlays.map((ov, k) => {
        const Body = OVERLAYS[ov.type];
        if (!Body) return null;
        const from = Math.max(0, Math.round((Number(ov.at) || 0) * fps));
        const len = ov.dur ? Math.max(1, Math.round(Number(ov.dur) * fps)) : Math.max(1, ctx.scene.frames - from);
        return (
          <Sequence key={k} from={from} durationInFrames={len} layout="none">
            <div data-nm-overlay={ov.type} style={overlayBox(ctx, ov)}>
              <Body sc={{ ...(ov as any), duration: sc.duration } as Scene} />
            </div>
          </Sequence>
        );
      })}
    </>
  );
};

const SceneView: React.FC<{ sc: Scene; i: number; base: Omit<Ctx, "scene">; tl: Timeline; fonts: boolean }> = ({ sc, i, base, tl, fonts }) => {
  const f = useCurrentFrame();
  const style = base.style;
  const count = tl.frames.length;
  const ctx: Ctx = sceneCtx(base, sc, tl.frames[i], i, count, fonts);
  const Body = COMPONENTS[sc.type] ?? COMPONENTS.title;
  const seed = i * 7 + 1;
  let wrap: React.CSSProperties = {};
  const inTf = i > 0 ? tl.tfs[i - 1] : 0, outTf = i < count - 1 ? tl.tfs[i] : 0;
  if (inTf > 0 && f < inTf) wrap = { ...wrap, ...transitionCss(tl.kinds[i - 1], f / inTf, "in", { W: base.W, H: base.H, rtl: base.rtl, seed }) };
  const outStart = tl.frames[i] - outTf;
  if (outTf > 0 && f >= outStart) wrap = { ...wrap, ...transitionCss(tl.kinds[i], (f - outStart) / outTf, "out", { W: base.W, H: base.H, rtl: base.rtl, seed: seed + 1 }) };
  // the scene's own exit (only where nothing covers the cut)
  const exitKind = typeof sc.exit === "string" ? sc.exit : "none";
  const EX = Math.max(6, Math.round(base.fps * 0.3));
  const exiting = exitKind !== "none" && outTf === 0 && f >= tl.frames[i] - EX;
  const exit = exiting ? exitCss(exitKind, (f - (tl.frames[i] - EX)) / EX, base.rtl ? -1 : 1) : {};
  const grade = style.fx?.grade as string | undefined;
  const filters: string[] = [];
  if (grade) filters.push(grade);
  if (style.fx?.chroma) filters.push("url(#nm-chroma)");
  if (style.fx?.posterize) filters.push("url(#nm-posterize)");
  const use2 = i % 2 === 1 && style.bg2 ? style.bg2 : style.bg;
  const par = sc.camera?.move === "parallax";
  const cam = (layer: "bg" | "mid" | "fg") => cameraCss(ctx, f, tl.frames[i], sc.camera, par ? layer : "all");
  const overlays: Overlay[] = (Array.isArray(sc.overlays) ? sc.overlays : []).filter((o) => o && OVERLAYS[o.type]);
  const globalCaptions = !!base.spec.captions?.on && ctx.cues.length > 0 && !overlays.some((o) => o.type === "captions");
  return (
    <CtxC.Provider value={ctx}>
      <AbsoluteFill style={{ ...wrap }} data-nm-scene={i}>
        <AbsoluteFill style={{ filter: filters.length ? filters.join(" ") : undefined }}>
          <AbsoluteFill style={cam("bg")}>
            {base.spec.bare ? null : <Background spec={use2} variant={i} />}
            {base.spec.bare || sc.tokens?.calm ? null : <Decor layers={style.decor} />}
          </AbsoluteFill>
          <AbsoluteFill style={{ ...cam("mid"), ...exit }}>
            <Body sc={sc} />
            {overlays.length ? <OverlayLayer overlays={overlays} sc={sc} /> : null}
            {globalCaptions ? (
              <div data-nm-overlay="captions" style={overlayBox(ctx, { type: "captions", anchor: base.spec.captions?.position || "lower" })}>
                <CaptionsLine words={ctx.cues} />
              </div>
            ) : null}
          </AbsoluteFill>
          <AbsoluteFill style={cam("fg")}>
            {base.spec.bare || sc.tokens?.calm ? null : <Decor layers={style.decor} over />}
          </AbsoluteFill>
        </AbsoluteFill>
        {sc.type !== "logo" && sc.type !== "image_hero" && !base.spec.bare ? <BrandBadge /> : null}
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
  const fonts = useFonts(fontKeysOf(style));
  const rootCtx: Ctx = { ...base, fonts, scene: { index: 0, frames: tl.total, count: tl.frames.length } };
  const dip = tl.kinds.includes("dip");
  return (
    <CtxC.Provider value={rootCtx}>
      <AbsoluteFill style={{ background: dip || spec.bare ? "#000000" : base.pal.bg }}>
        <SvgDefs />
        {spec.scenes.map((sc, i) => (
          <Sequence key={i} from={tl.starts[i]} durationInFrames={tl.frames[i]} layout="none">
            <SceneView sc={sc} i={i} base={base} tl={tl} fonts={fonts} />
          </Sequence>
        ))}
        {tl.kinds.map((kind, j) =>
          tl.tfs[j] > 0 && (kind === "blocks" || kind === "flash") ? (
            <Sequence key={`o${j}`} from={tl.starts[j + 1]} durationInFrames={Math.max(1, tl.tfs[j])} layout="none">
              <CutOverlay kind={kind} base={base} />
            </Sequence>
          ) : null,
        )}
        <AbsoluteFill style={{ pointerEvents: "none" }}>
          {spec.bare ? null : <Textures layers={style.tex} />}
        </AbsoluteFill>
        {spec.qa ? <QaProbe /> : null}
      </AbsoluteFill>
    </CtxC.Provider>
  );
};

export { OVERLAY_KINDS };
