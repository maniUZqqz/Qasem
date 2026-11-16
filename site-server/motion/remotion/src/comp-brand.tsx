// Brand character component («شخصیتِ برند»): the owner's cartoon character enters, waves / points / gives a thumbs-up, and a speech bubble shows the
// words of the narration exactly when they are spoken (word timings = ctx.cues). The pictures are two transparent PNG stickers of the SAME character
// (image_a = standing, image_b = the action pose) made by apps.brandchar (refs "photo:<id>" are resolved to assets by the server like every other image).
// As an overlay it sits in a corner of another scene; as a scene it is the hero. No new dependency: only Remotion's Img / interpolate.
import React from "react";
import { Img, interpolate } from "remotion";
import { useAsset, useCtx, useQF } from "./ctx";
import type { Ctx } from "./ctx";
import { area } from "./kit";
import type { Scene } from "./types";
import { clamp, col, onColor } from "./util";

type SC = React.FC<{ sc: Scene }>;

const ACTIONS = ["wave", "point", "thumbs", "explain", "think"];

/** seconds when each word of `words` appears: from the narration cues when they roughly match, else spread over the first 70 % of the scene */
export function wordTimes(words: string[], cues: Ctx["cues"], seconds: number, startAt: number): number[] {
  if (cues.length && Math.abs(cues.length - words.length) <= Math.max(1, Math.round(words.length * 0.3))) {
    return words.map((_, i) => Math.max(startAt, cues[Math.min(cues.length - 1, Math.round((i * (cues.length - 1)) / Math.max(1, words.length - 1)))].s - 0.05));
  }
  const span = Math.max(0.6, seconds * 0.7 - startAt);
  return words.map((_, i) => startAt + (span * i) / Math.max(1, words.length));
}

const Bubble: React.FC<{ text: string; width: number; t: number; seconds: number; cues: Ctx["cues"]; accent: string; ink: string; paper: string; rtl: boolean; u: number }> = ({ text, width, t, seconds, cues, accent, ink, paper, rtl, u }) => {
  const words = text.split(/\s+/).filter(Boolean).slice(0, 24);
  const times = wordTimes(words, cues, seconds, 0.55);
  const size = Math.max(30, Math.min(64, (width * 0.92) / Math.max(7, Math.sqrt(words.join(" ").length) * 3.1)));
  const pop = clamp((t - 0.35) / 0.35);
  return (
    <div data-nm="box" style={{ position: "relative", width, maxWidth: "100%", boxSizing: "border-box", padding: `${22 * u}px ${28 * u}px`, borderRadius: 34 * u, background: paper, border: `${5 * u}px solid ${ink}`, color: ink,
      direction: rtl ? "rtl" : "ltr", textAlign: "center", transform: `scale(${0.6 + 0.4 * pop})`, opacity: pop, transformOrigin: "bottom center", boxShadow: `0 ${12 * u}px ${30 * u}px rgba(0,0,0,0.25)` }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `${8 * u}px ${14 * u}px`, lineHeight: 1.35 }}>
        {words.map((w, i) => {
          const k = clamp((t - times[i]) / 0.18);
          const current = t >= times[i] && (i === words.length - 1 || t < times[i + 1]);
          return (
            <span key={i} style={{ fontSize: size * u, fontWeight: 800, opacity: 0.15 + 0.85 * k, transform: `translateY(${(1 - k) * 12 * u}px) scale(${1 + (current ? 0.08 : 0)})`, color: current ? accent : ink, display: "inline-block" }}>
              {w}
            </span>
          );
        })}
      </div>
      <div style={{ position: "absolute", bottom: -22 * u, [rtl ? "right" : "left"]: 70 * u, width: 0, height: 0, borderLeft: `${18 * u}px solid transparent`, borderRight: `${18 * u}px solid transparent`, borderTop: `${26 * u}px solid ${ink}` }} />
      <div style={{ position: "absolute", bottom: -13 * u, [rtl ? "right" : "left"]: 74 * u, width: 0, height: 0, borderLeft: `${14 * u}px solid transparent`, borderRight: `${14 * u}px solid transparent`, borderTop: `${20 * u}px solid ${paper}` }} />
    </div>
  );
};

const BrandCharacter: React.FC<{ sc: Scene; hero: boolean }> = ({ sc, hero }) => {
  const ctx = useCtx();
  const { fps, W, H, u, pal, rtl, cues } = ctx;
  const qf = useQF();
  const t = qf / fps;
  const a = area(ctx);
  const imgA = useAsset(sc.image_a as string | undefined);
  const imgB = useAsset(sc.image_b as string | undefined) || imgA;
  const action = ACTIONS.includes(String(sc.action)) ? String(sc.action) : "wave";
  const enter = ["left", "right", "bottom"].includes(String(sc.arrive)) ? String(sc.arrive) : "left";
  const side = String(sc.side) === "left" ? "left" : "right";
  const text = String(sc.text ?? "").trim();
  const showBubble = sc.bubble !== false && !!text;
  const seconds = Math.max(2, Number((sc as any).duration ?? 6));
  const h = Math.min(a.h * (hero ? 0.66 : 0.42), H * (hero ? 0.6 : 0.36));
  // enter: a spring-like slide over ~0.7 s (overshoot then settle)
  const e = clamp(t / 0.7);
  const ease = 1 - Math.pow(1 - e, 3) + Math.sin(e * Math.PI) * 0.06;
  const dist = enter === "bottom" ? h * 1.1 : Math.min(W * 0.6, h * 1.2);
  const dx = enter === "bottom" ? 0 : (enter === "left" ? -1 : 1) * (1 - ease) * dist;
  const dy = enter === "bottom" ? (1 - ease) * dist : 0;
  const bob = Math.sin(t * 2.4) * 0.012 * h;
  // which picture: alternate for "wave" (two frames, ~3 swaps per second), switch once for the others
  const act = t > 0.75;
  const waving = action === "wave" && act && Math.floor(t * 3.2) % 2 === 0;
  const useB = action === "wave" ? waving : act && t < seconds - 0.4;
  const src = useB ? imgB : imgA;
  const pulse = action !== "wave" && act ? 1 + Math.max(0, 0.06 - (t - 0.75) * 0.08) : 1;
  const accent = col(pal, "accent");
  const ink = col(pal, "ink");
  const paper = col(pal, "paper") || "#ffffff";
  const bw = Math.min(a.w * 0.9, hero ? a.w * 0.88 : a.w * 0.62);
  const physicalRight = side === "right";
  return (
    <div data-nm="box" style={{ width: a.w, display: "flex", flexDirection: "column", alignItems: physicalRight ? "flex-end" : "flex-start", gap: 14 * u, direction: "ltr", position: "relative" }}>
      {showBubble ? (
        <div style={{ alignSelf: physicalRight ? "flex-end" : "flex-start", maxWidth: "100%" }}>
          <Bubble text={text} width={bw} t={t} seconds={seconds} cues={cues} accent={accent} ink={ink} paper={paper} rtl={rtl} u={u} />
        </div>
      ) : null}
      {src ? (
        <Img src={src} style={{ height: h, width: "auto", objectFit: "contain", transform: `translate(${dx}px, ${dy + bob}px) scale(${pulse}) ${physicalRight ? "" : "scaleX(1)"}`, transformOrigin: "50% 100%", filter: "drop-shadow(0 10px 14px rgba(0,0,0,0.28))" }} />
      ) : (
        <div style={{ height: h * 0.8, width: h * 0.5, borderRadius: 24 * u, background: accent, color: onColor(accent), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 34 * u, fontWeight: 800, opacity: interpolate(e, [0, 1], [0, 1]) }}>
          {String(sc.name || "★")}
        </div>
      )}
    </div>
  );
};

/** as an overlay (placed by the overlay layer; bottom corner by default) */
export const BrandCharacterOverlay: SC = ({ sc }) => <BrandCharacter sc={sc} hero={false} />;

/** as a whole scene: the character is the hero, centred at the bottom of the safe area */
export const BrandCharacterScene: SC = ({ sc }) => {
  const ctx = useCtx();
  const a = area(ctx);
  return (
    <div style={{ position: "absolute", left: a.x, top: a.y, width: a.w, height: a.h, display: "flex", alignItems: "flex-end", justifyContent: "center" }}>
      <BrandCharacter sc={sc} hero />
    </div>
  );
};
