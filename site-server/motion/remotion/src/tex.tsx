import React from "react";
import { Fill, noiseTile } from "./bg";
import { useCtx, useQF } from "./ctx";
import type { Any } from "./types";
import { R, col, rgba } from "./util";

type TProps = { t: Any };

function useT() {
  const c = useCtx();
  const f = useQF();
  return { ...c, f, P: (n?: string, d?: string) => col(c.pal, n, d) };
}

const TEX: { [k: string]: React.FC<TProps> } = {
  grain: ({ t }) => {
    const { f } = useT();
    return <Fill style={{ backgroundImage: noiseTile({ freq: String(t.freq ?? "0.85"), oct: 2, a: 1.2, off: -0.1, rgb: t.rgb ?? [0, 0, 0], seed: 1 + (f % 5) }), opacity: t.opacity ?? 0.12, mixBlendMode: (t.blend ?? "multiply") as any }} />;
  },
  halftone: ({ t }) => {
    const { P, u } = useT();
    const s = (t.size ?? 22) * u;
    return <Fill style={{ backgroundImage: `radial-gradient(circle, ${P(t.color ?? "ink")} ${s * 0.22}px, transparent ${s * 0.23}px)`, backgroundSize: `${s}px ${s}px`, opacity: t.opacity ?? 0.12, mixBlendMode: "multiply", WebkitMaskImage: "linear-gradient(160deg, rgba(0,0,0,0.1), rgba(0,0,0,1))" }} />;
  },
  scanlines: ({ t }) => {
    const { u, f, fps } = useT();
    const gap = (t.gap ?? 4) * u;
    return <Fill style={{ backgroundImage: `repeating-linear-gradient(0deg, rgba(0,0,0,${t.opacity ?? 0.2}) 0 ${gap / 2}px, transparent ${gap / 2}px ${gap}px)`, backgroundPosition: `0 ${t.roll ? ((f / fps) * 40 * u) % gap : 0}px` }} />;
  },
  crosshatch: ({ t }) => {
    const { P, u } = useT();
    const c = rgba(P(t.color ?? "ink"), t.opacity ?? 0.08);
    return <Fill style={{ backgroundImage: `repeating-linear-gradient(45deg, ${c} 0 ${1.5 * u}px, transparent ${1.5 * u}px ${9 * u}px), repeating-linear-gradient(-45deg, ${c} 0 ${1.5 * u}px, transparent ${1.5 * u}px ${12 * u}px)` }} />;
  },
  paper: ({ t }) => <Fill style={{ backgroundImage: noiseTile({ freq: "0.04 0.7", oct: 3, a: 0.8, off: -0.15, rgb: [100, 80, 50], seed: 4, size: 300 }), opacity: t.opacity ?? 0.3, mixBlendMode: "multiply" }} />,
  dither: ({ t }) => {
    const { P, u } = useT();
    const s = (t.size ?? 4) * u;
    return <Fill style={{ background: `repeating-conic-gradient(${rgba(P(t.color ?? "ink"), t.opacity ?? 0.1)} 0% 25%, transparent 0% 50%) 0 0 / ${s * 2}px ${s * 2}px` }} />;
  },
  vignette: ({ t }) => <Fill style={{ background: `radial-gradient(ellipse at 50% 46%, rgba(0,0,0,0) ${t.from ?? 52}%, rgba(0,0,0,${t.opacity ?? 0.45}) 100%)` }} />,
  bloom: ({ t }) => {
    const { P, f, fps } = useT();
    const pulse = 0.85 + 0.15 * Math.sin((f / fps) * 1.6);
    return <Fill style={{ background: `radial-gradient(ellipse at ${t.at ?? "50% 40%"}, ${rgba(P(t.color ?? "paper"), (t.opacity ?? 0.2) * pulse)}, transparent 65%)`, mixBlendMode: "screen" }} />;
  },
  chalkdust: ({ t }) => <Fill style={{ backgroundImage: noiseTile({ freq: "0.6", oct: 3, a: 0.9, off: -0.3, rgb: [255, 255, 255], seed: 7, size: 300 }), opacity: t.opacity ?? 0.22, mixBlendMode: "screen" }} />,
  flicker: ({ t }) => {
    const { f } = useT();
    return <Fill style={{ background: `rgba(0,0,0,${R(`fl${f}`) * (t.opacity ?? 0.1)})` }} />;
  },
  scratches: ({ t }) => {
    const { f, W, H, u } = useT();
    return (
      <Fill>
        {Array.from({ length: 5 }).map((_, i) => R(`sc${f}${i}`) > 0.45 ? <div key={i} style={{ position: "absolute", left: R(`sx${f}${i}`) * W, top: R(`sy${f}${i}`) * H * 0.4, width: Math.max(1, 1.5 * u), height: H * (0.2 + R(`sh${f}${i}`) * 0.6), background: `rgba(255,255,255,${t.opacity ?? 0.35})` }} /> : null)}
      </Fill>
    );
  },
  vhs: ({ t }) => {
    const { f, fps, H, W, u } = useT();
    const y = ((f / fps) * 0.35 * H) % (H * 1.2) - H * 0.1;
    return (
      <Fill>
        <div style={{ position: "absolute", left: 0, right: 0, top: y, height: H * 0.05, background: "linear-gradient(180deg, transparent, rgba(255,255,255,0.14), transparent)" }} />
        <div style={{ position: "absolute", left: 0, right: 0, top: H * (0.82 + 0.03 * Math.sin(f / 5)), height: 5 * u, background: "rgba(255,255,255,0.3)", transform: `translateX(${(R(`vh${f}`) - 0.5) * 40 * u}px)` }} />
        <Fill style={{ backgroundImage: noiseTile({ freq: "0.9 0.03", oct: 1, a: 1.4, off: -0.45, rgb: [255, 255, 255], seed: 1 + (f % 6) }), opacity: t.opacity ?? 0.35 }} />
        <Fill style={{ boxShadow: `inset ${4 * u}px 0 ${10 * u}px rgba(255,0,80,0.18), inset ${-4 * u}px 0 ${10 * u}px rgba(0,200,255,0.18)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, width: W }} />
      </Fill>
    );
  },
  crt: ({ t }) => {
    const { u } = useT();
    return (
      <Fill>
        <Fill style={{ backgroundImage: `repeating-linear-gradient(0deg, rgba(0,0,0,0.3) 0 ${2 * u}px, transparent ${2 * u}px ${4 * u}px)` }} />
        <Fill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.6) 100%)", opacity: t.opacity ?? 1 }} />
      </Fill>
    );
  },
  stitch: ({ t }) => {
    const { P, u } = useT();
    return <Fill style={{ margin: 22 * u, border: `${3 * u}px dashed ${rgba(P(t.color ?? "paper"), 0.75)}`, borderRadius: 18 * u }} />;
  },
};

export const Textures: React.FC<{ layers: Any[] }> = ({ layers }) => (
  <>
    {layers.map((t, i) => {
      const C = TEX[t.kind];
      return C ? <C key={i} t={t} /> : null;
    })}
  </>
);
