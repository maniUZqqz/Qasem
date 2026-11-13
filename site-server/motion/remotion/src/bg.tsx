import React from "react";
import type { CSSProperties } from "react";
import { useCtx, useQF } from "./ctx";
import type { Any } from "./types";
import { R, col, mix, rgba, shade } from "./util";

export const Fill: React.FC<{ style?: CSSProperties; children?: React.ReactNode }> = ({ style, children }) => (
  <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, overflow: "hidden", ...style }}>{children}</div>
);

/** a small SVG image (with feTurbulence) used as a repeating tile: rasterised once by the browser, cheap per frame */
export function noiseTile(o: { freq?: string; oct?: number; a?: number; off?: number; rgb?: [number, number, number]; size?: number; seed?: number }): string {
  const { freq = "0.9", oct = 2, a = 1.2, off = -0.1, rgb = [0, 0, 0], size = 256, seed = 1 } = o;
  const svg =
    `<svg xmlns='http://www.w3.org/2000/svg' width='${size}' height='${size}'><filter id='n' x='0' y='0' width='100%' height='100%'>` +
    `<feTurbulence type='fractalNoise' baseFrequency='${freq}' numOctaves='${oct}' seed='${seed}' stitchTiles='stitch'/>` +
    `<feColorMatrix type='matrix' values='0 0 0 0 ${rgb[0] / 255} 0 0 0 0 ${rgb[1] / 255} 0 0 0 0 ${rgb[2] / 255} 0 0 0 ${a} ${off}'/></filter>` +
    `<rect width='100%' height='100%' filter='url(#n)'/></svg>`;
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`;
}

type BgProps = { s: Any; v: number };

function useBg() {
  const c = useCtx();
  const f = useQF();
  return { ...c, f, P: (n?: string, d?: string) => col(c.pal, n, d) };
}

// helpers ---------------------------------------------------------------------------------------------------------

function wavePath(W: number, H: number, base: number, amp: number, seed: number, f: number, speed: number, ks: number[] = [1, 2, 3]): string {
  const pts: string[] = [];
  const steps = 48;
  for (let i = 0; i <= steps; i++) {
    const x = (i / steps) * W;
    let y = base;
    ks.forEach((k, j) => {
      y += Math.sin(((x / W) * k + R(`w${seed}${j}`) + (f * speed * (j + 1)) / 900) * Math.PI * 2) * (amp / (j + 1));
    });
    pts.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  return `${pts.join(" ")} L${W} ${H} L0 ${H} Z`;
}

// backgrounds -----------------------------------------------------------------------------------------------------

const Solid: React.FC<BgProps> = ({ s, v }) => {
  const { P } = useBg();
  return <Fill style={{ background: v % 2 && s.alt ? P(s.alt) : P(s.c ?? "bg") }} />;
};

const Linear: React.FC<BgProps> = ({ s, v }) => {
  const { P, f } = useBg();
  const a = (s.angle ?? 180) + Math.sin(f / 90) * (s.drift ?? 0) + (v % 2 && s.flip ? 180 : 0);
  const mid = s.mid ? `, ${P(s.mid)}` : "";
  return <Fill style={{ background: `linear-gradient(${a}deg, ${P(s.from ?? "bg")}${mid}, ${P(s.to ?? "bg2")})` }} />;
};

const Radial: React.FC<BgProps> = ({ s }) => {
  const { P } = useBg();
  return <Fill style={{ background: `radial-gradient(${s.shape ?? "circle"} at ${s.at ?? "50% 40%"}, ${P(s.from ?? "bg2")}, ${P(s.to ?? "bg")} ${s.r ?? "78%"})` }} />;
};

const Bands: React.FC<BgProps> = ({ s }) => {
  const { P } = useBg();
  const n = s.n ?? 8;
  const a = P(s.from ?? "bg2"), b = P(s.to ?? "bg");
  const stops: string[] = [];
  for (let i = 0; i < n; i++) {
    const c = mix(a, b, n === 1 ? 0 : i / (n - 1));
    stops.push(`${c} ${(i / n) * 100}% ${((i + 1) / n) * 100}%`);
  }
  return <Fill style={{ background: `linear-gradient(180deg, ${stops.join(", ")})` }} />;
};

const Grid: React.FC<BgProps> = ({ s }) => {
  const { P, u, f, fps } = useBg();
  const size = (s.size ?? 48) * u, w = Math.max(1, (s.w ?? 2) * u);
  const line = P(s.line ?? "muted");
  const drift = (s.drift ?? 0) * (f / fps) * u;
  const layers = [
    `linear-gradient(${line} ${w}px, transparent ${w}px)`, `linear-gradient(90deg, ${line} ${w}px, transparent ${w}px)`,
  ];
  const sizes = [`${size}px ${size}px`, `${size}px ${size}px`];
  if (s.major) {
    const ml = P(s.majorLine ?? s.line ?? "ink");
    layers.unshift(`linear-gradient(${ml} ${w * 1.8}px, transparent ${w * 1.8}px)`, `linear-gradient(90deg, ${ml} ${w * 1.8}px, transparent ${w * 1.8}px)`);
    sizes.unshift(`${size * s.major}px ${size * s.major}px`, `${size * s.major}px ${size * s.major}px`);
  }
  return <Fill style={{ background: P(s.base ?? "bg"), backgroundImage: layers.join(", "), backgroundSize: sizes.join(", "), backgroundPosition: `${drift}px ${drift}px` }} />;
};

const Dots: React.FC<BgProps> = ({ s }) => {
  const { P, u, f, fps } = useBg();
  const size = (s.size ?? 36) * u, r = (s.r ?? 4) * u;
  const d = (s.drift ?? 0) * (f / fps) * u;
  return (
    <Fill style={{
      background: P(s.base ?? "bg"),
      backgroundImage: `radial-gradient(circle, ${P(s.dot ?? "muted")} ${r}px, transparent ${r + 1}px)`,
      backgroundSize: `${size}px ${size}px`, backgroundPosition: `${d}px ${d}px`,
    }} />
  );
};

const Stripes: React.FC<BgProps> = ({ s, v }) => {
  const { P, u, f, fps } = useBg();
  const w = (s.w ?? 40) * u;
  const a = P(v % 2 && s.a2 ? s.a2 : s.a ?? "bg"), b = P(v % 2 && s.b2 ? s.b2 : s.b ?? "bg2");
  const move = (s.move ?? 0) * (f / fps) * u;
  return <Fill style={{ backgroundImage: `repeating-linear-gradient(${s.angle ?? 45}deg, ${a} 0 ${w}px, ${b} ${w}px ${w * 2}px)`, backgroundPosition: `${move}px 0` }} />;
};

const Checker: React.FC<BgProps> = ({ s }) => {
  const { P, u, f, fps } = useBg();
  const size = (s.size ?? 90) * u;
  const m = (s.move ?? 0) * (f / fps) * u;
  return <Fill style={{ background: `repeating-conic-gradient(${P(s.a ?? "bg")} 0% 25%, ${P(s.b ?? "bg2")} 0% 50%) ${m}px ${m}px / ${size * 2}px ${size * 2}px` }} />;
};

const Paper: React.FC<BgProps> = ({ s }) => {
  const { P } = useBg();
  const base = P(s.base ?? "paper");
  return (
    <Fill style={{ background: `radial-gradient(ellipse at 50% 40%, ${shade(base, 0.35)} 0%, ${base} 55%, ${shade(base, -0.08 - (s.edge ?? 0.06))} 100%)` }}>
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.04 0.9", oct: 3, a: 0.6, off: -0.12, rgb: [90, 70, 40], seed: 4 }), opacity: s.fiber ?? 0.55 }} />
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.9", oct: 2, a: 0.9, off: -0.2, rgb: [60, 50, 40], seed: 9 }), opacity: 0.35 }} />
    </Fill>
  );
};

const Notebook: React.FC<BgProps> = ({ s }) => {
  const { P, u, rtl, W } = useBg();
  const gap = (s.gap ?? 76) * u;
  return (
    <Fill style={{ background: P(s.base ?? "paper") }}>
      <Fill style={{ backgroundImage: `linear-gradient(${rgba(P(s.line ?? "accent2"), 0.35)} ${2 * u}px, transparent ${2 * u}px)`, backgroundSize: `100% ${gap}px`, backgroundPosition: `0 ${gap * 0.8}px` }} />
      <div style={{ position: "absolute", top: 0, bottom: 0, [rtl ? "right" : "left"]: W * 0.1, width: 3 * u, background: rgba(P(s.margin ?? "accent3"), 0.55) }} />
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.04 0.9", oct: 2, a: 0.4, off: -0.1, rgb: [90, 80, 60], seed: 2 }), opacity: 0.4 }} />
    </Fill>
  );
};

const Whiteboard: React.FC<BgProps> = ({ s }) => {
  const { P, u } = useBg();
  const fr = (s.frame ?? 26) * u;
  return (
    <Fill style={{ background: P(s.base ?? "paper") }}>
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} style={{ position: "absolute", left: `${R(`sm${i}`) * 80}%`, top: `${R(`sn${i}`) * 85}%`, width: `${30 + R(`sw${i}`) * 40}%`, height: `${8 + R(`sh${i}`) * 10}%`, background: "radial-gradient(ellipse, rgba(80,90,110,0.07), transparent 70%)", transform: `rotate(${R(`sr${i}`) * 40 - 20}deg)` }} />
      ))}
      <Fill style={{ boxShadow: `inset 0 0 0 ${fr}px #c9ccd1, inset 0 0 0 ${fr + 3 * u}px #9aa0a8, inset 0 0 ${60 * u}px rgba(0,0,0,0.12)` }} />
    </Fill>
  );
};

const Chalk: React.FC<BgProps> = ({ s }) => {
  const { P, u } = useBg();
  const fr = (s.frame ?? 30) * u;
  return (
    <Fill style={{ background: `radial-gradient(ellipse at 50% 45%, ${shade(P(s.base ?? "bg"), 0.12)}, ${P(s.base ?? "bg")} 75%)` }}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div key={i} style={{ position: "absolute", left: `${R(`cm${i}`) * 90}%`, top: `${R(`cn${i}`) * 90}%`, width: `${25 + R(`cw${i}`) * 45}%`, height: `${6 + R(`ch${i}`) * 9}%`, background: "radial-gradient(ellipse, rgba(255,255,255,0.07), transparent 70%)", transform: `rotate(${R(`cr${i}`) * 50 - 25}deg)` }} />
      ))}
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.7", oct: 2, a: 0.5, off: -0.05, rgb: [255, 255, 255], seed: 5 }), opacity: 0.16 }} />
      <Fill style={{ boxShadow: `inset 0 0 0 ${fr}px #7a5230, inset 0 0 0 ${fr + 4 * u}px #4b311b, inset 0 0 ${70 * u}px rgba(0,0,0,0.45)` }} />
    </Fill>
  );
};

const Halftone: React.FC<BgProps> = ({ s }) => {
  const { P, u } = useBg();
  const size = (s.size ?? 34) * u;
  return (
    <Fill style={{ background: P(s.base ?? "paper") }}>
      <Fill style={{
        backgroundImage: `radial-gradient(circle, ${P(s.dot ?? "accent")} ${size * 0.3}px, transparent ${size * 0.31}px)`,
        backgroundSize: `${size}px ${size}px`, backgroundPosition: `${size / 2}px ${size / 2}px`,
        WebkitMaskImage: `linear-gradient(${s.angle ?? 135}deg, rgba(0,0,0,${s.maskA ?? 1}), rgba(0,0,0,${s.maskB ?? 0.05}))`,
      }} />
    </Fill>
  );
};

const Mesh: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps } = useBg();
  const cols: string[] = (s.blobs ?? ["accent", "accent2", "accent3", "bg2"]).map((c: string) => P(c));
  const t = (f / fps) * (s.speed ?? 0.25);
  const D = Math.max(W, H) * (s.size ?? 0.75);
  return (
    <Fill style={{ background: P(s.base ?? "bg") }}>
      {cols.map((c, i) => {
        const x = W * (0.5 + 0.38 * Math.sin(t * (1 + i * 0.37) + i * 1.9));
        const y = H * (0.5 + 0.38 * Math.cos(t * (0.8 + i * 0.29) + i * 2.7));
        return <div key={i} style={{ position: "absolute", left: x - D / 2, top: y - D / 2, width: D, height: D, borderRadius: "50%", background: `radial-gradient(circle, ${rgba(c, s.op ?? 0.85)} 0%, ${rgba(c, 0)} 68%)` }} />;
      })}
    </Fill>
  );
};

const LowPoly: React.FC<BgProps> = ({ s, v }) => {
  const { P, W, H, u, f } = useBg();
  const cell = (s.cell ?? 170) * u;
  const cols = Math.ceil(W / cell) + 1, rows = Math.ceil(H / cell) + 1;
  const jit = s.jitter ?? 0.65;
  const a = P(s.a ?? "bg2"), b = P(s.b ?? "bg");
  const seed = (s.seed ?? 3) + v;
  const pt = (r: number, c: number): [number, number] => {
    let x = c * cell + (R(`lx${seed}-${r}-${c}`) - 0.5) * cell * jit;
    let y = r * cell + (R(`ly${seed}-${r}-${c}`) - 0.5) * cell * jit;
    if (c === 0) x = 0;
    if (r === 0) y = 0;
    if (c >= cols - 1) x = cols * cell;
    if (r >= rows - 1) y = rows * cell;
    const dr = (s.drift ?? 0.06) * cell;
    if (c > 0 && c < cols - 1 && r > 0 && r < rows - 1) {
      x += Math.sin(f / 70 + R(`dx${r}${c}`) * 6) * dr;
      y += Math.cos(f / 83 + R(`dy${r}${c}`) * 6) * dr;
    }
    return [x, y];
  };
  const polys: React.ReactNode[] = [];
  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const p00 = pt(r, c), p10 = pt(r, c + 1), p01 = pt(r + 1, c), p11 = pt(r + 1, c + 1);
      const tris = R(`dg${seed}${r}${c}`) > 0.5 ? [[p00, p10, p11], [p00, p11, p01]] : [[p00, p10, p01], [p10, p11, p01]];
      tris.forEach((tri, k) => {
        const cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3, cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3;
        const t = Math.min(1, Math.max(0, (cx / W) * (s.gx ?? 0.4) + (cy / H) * (s.gy ?? 0.6)));
        const base = mix(a, b, t);
        const col2 = shade(base, (R(`tc${seed}${r}${c}${k}`) - 0.5) * (s.contrast ?? 0.22));
        polys.push(<polygon key={`${r}-${c}-${k}`} points={tri.map((p) => p.join(",")).join(" ")} fill={col2} stroke={s.edge ? rgba(P(s.edge), 0.35) : col2} strokeWidth={s.edge ? 1.5 * u : 1} />);
      });
    }
  }
  return <Fill><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{polys}</svg></Fill>;
};

const Stained: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const cell = (s.cell ?? 230) * u;
  const cols = Math.ceil(W / cell) + 1, rows = Math.ceil(H / cell) + 1;
  const palette: string[] = (s.colors ?? ["accent", "accent2", "accent3", "bg2", "muted"]).map((c: string) => P(c));
  const pt = (r: number, c: number): [number, number] => {
    let x = c * cell + (R(`sx${r}-${c}`) - 0.5) * cell * 0.7;
    let y = r * cell + (R(`sy${r}-${c}`) - 0.5) * cell * 0.7;
    if (c === 0) x = 0;
    if (r === 0) y = 0;
    if (c >= cols - 1) x = cols * cell;
    if (r >= rows - 1) y = rows * cell;
    return [x, y];
  };
  const cells: React.ReactNode[] = [];
  const glow = 0.5 + 0.5 * Math.sin((f / fps) * 1.4);
  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const pts = [pt(r, c), pt(r, c + 1), pt(r + 1, c + 1), pt(r + 1, c)];
      const base = palette[Math.floor(R(`sc${r}${c}`) * palette.length)];
      const pulse = 0.82 + 0.18 * Math.sin((f / fps) * 1.2 + R(`sp${r}${c}`) * 6);
      cells.push(<polygon key={`${r}-${c}`} points={pts.map((p) => p.join(",")).join(" ")} fill={shade(base, (pulse - 1) * 0.6)} stroke={P(s.lead ?? "ink")} strokeWidth={(s.leadw ?? 11) * u} strokeLinejoin="round" />);
    }
  }
  return (
    <Fill style={{ background: P(s.base ?? "ink") }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{cells}</svg>
      <Fill style={{ background: `radial-gradient(circle at 50% 40%, rgba(255,255,255,${0.28 * glow + 0.1}), transparent 65%)`, mixBlendMode: "screen" }} />
    </Fill>
  );
};

const IsoCubes: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f } = useBg();
  const e = (s.size ?? 74) * u;
  const b = e * 0.866, a = e * 0.5;
  const top = P(s.top ?? "accent"), left = P(s.left ?? "accent2"), right = P(s.right ?? "accent3");
  const nodes: React.ReactNode[] = [];
  const maxI = Math.ceil(H / a) + 6, maxJ = Math.ceil(W / b) + 6;
  const cells: { i: number; j: number; h: number }[] = [];
  for (let sum = 0; sum < maxI + maxJ; sum++) {
    for (let i = 0; i <= sum; i++) {
      const j = sum - i;
      const cx = (i - j) * b + W / 2, cy = (i + j) * a - e * 2;
      if (cx < -b * 2 || cx > W + b * 2 || cy < -e * 3 || cy > H + e * 2) continue;
      const hgt = 0.2 + R(`ic${i}-${j}`) * 1.6 + (s.bob ? Math.sin(f / 40 + i * 0.7 + j * 1.3) * 0.18 : 0);
      cells.push({ i, j, h: hgt });
    }
  }
  cells.forEach(({ i, j, h }) => {
    const cx = (i - j) * b + W / 2, cy = (i + j) * a - e * 2 - h * e;
    const H2 = h * e + e;
    nodes.push(
      <g key={`${i}-${j}`}>
        <polygon points={`${cx - b},${cy} ${cx},${cy + a} ${cx},${cy + a + H2} ${cx - b},${cy + H2}`} fill={left} />
        <polygon points={`${cx},${cy + a} ${cx + b},${cy} ${cx + b},${cy + H2} ${cx},${cy + a + H2}`} fill={right} />
        <polygon points={`${cx},${cy - a} ${cx + b},${cy} ${cx},${cy + a} ${cx - b},${cy}`} fill={shade(top, (R(`it${i}${j}`) - 0.5) * 0.18)} />
      </g>,
    );
  });
  return <Fill style={{ background: P(s.base ?? "bg") }}><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{nodes}</svg></Fill>;
};

const IsoGrid: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const e = (s.size ?? 80) * u;
  const line = rgba(P(s.line ?? "muted"), s.lineOp ?? 0.55);
  const lines: React.ReactNode[] = [];
  const sx = e * 1.732;
  const off = ((s.drift ?? 0) * (f / fps) * u) % sx;
  for (let k = -Math.ceil(H / e); k < W / (sx / 2) + 4; k++) {
    const x = k * (sx / 2) + off;
    lines.push(<line key={`a${k}`} x1={x} y1={0} x2={x + H * 1.732} y2={H} stroke={line} strokeWidth={2 * u} />);
    lines.push(<line key={`b${k}`} x1={x} y1={0} x2={x - H * 1.732} y2={H} stroke={line} strokeWidth={2 * u} />);
  }
  return <Fill style={{ background: P(s.base ?? "bg") }}><svg width={W} height={H}>{lines}</svg></Fill>;
};

const Studs: React.FC<BgProps> = ({ s }) => {
  const { P, u } = useBg();
  const size = (s.size ?? 76) * u;
  const base = P(s.base ?? "bg");
  return (
    <Fill style={{ background: base }}>
      <Fill style={{
        backgroundImage: `radial-gradient(circle at 42% 38%, ${shade(base, 0.22)} 0 ${size * 0.12}px, transparent ${size * 0.13}px), radial-gradient(circle, ${shade(base, 0.12)} 0 ${size * 0.3}px, ${shade(base, -0.28)} ${size * 0.3}px ${size * 0.34}px, transparent ${size * 0.35}px)`,
        backgroundSize: `${size}px ${size}px`,
      }} />
    </Fill>
  );
};

const Hills: React.FC<BgProps> = ({ s, v }) => {
  const { P, W, H, f, fps, u } = useBg();
  const layers = s.layers ?? 4;
  const colors: string[] = (s.colors ?? ["bg2", "muted", "ink"]).map((c: string) => P(c));
  const sky0 = P(s.sky?.[0] ?? "accent2"), sky1 = P(s.sky?.[1] ?? "paper");
  const out: React.ReactNode[] = [];
  for (let l = 0; l < layers; l++) {
    const t = layers === 1 ? 1 : l / (layers - 1);
    const colr = colors.length > 1 ? mix(colors[0], colors[colors.length - 1], t) : colors[0];
    const base = H * (s.horizon ?? 0.52) + t * H * (s.spread ?? 0.4);
    const amp = H * (s.amp ?? 0.07) * (1 - t * 0.35);
    const shift = ((f / fps) * (s.speed ?? 10) * u * (l + 1) * (s.parallax ?? 1)) % W;
    const d = wavePath(W, H, base, amp, l + (s.seed ?? 0) + v, 0, 0, [1, 2, 3]);
    out.push(
      <g key={l} transform={`translate(${-shift},0)`}>
        <path d={d} fill={colr} />
        <path d={d} fill={colr} transform={`translate(${W},0)`} />
        <path d={d} fill={colr} transform={`translate(${-W},0)`} />
      </g>,
    );
  }
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${sky0}, ${sky1} 62%)` }}>
      {s.sun !== false && (
        <div style={{ position: "absolute", left: "62%", top: `${(s.sunY ?? 0.26) * 100}%`, width: W * 0.22, height: W * 0.22, borderRadius: "50%", background: `radial-gradient(circle, ${P(s.sunColor ?? "paper")} 30%, ${rgba(P(s.sunColor ?? "paper"), 0)} 70%)`, transform: "translate(-50%,-50%)" }} />
      )}
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0 }}>{out}</svg>
    </Fill>
  );
};

const Clouds: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps, u } = useBg();
  const n = s.n ?? 7;
  const crisp = s.crisp;
  const cloud = P(s.cloud ?? "paper");
  const shadow = P(s.shadow ?? "accent2");
  const items: React.ReactNode[] = [];
  for (let i = 0; i < n; i++) {
    const size = (160 + R(`cs${i}`) * 260) * u;
    const speed = (6 + R(`cv${i}`) * 14) * u * (s.speed ?? 1);
    const x = ((R(`cx${i}`) * (W + size * 2) + (f / fps) * speed) % (W + size * 3)) - size * 1.5;
    const y = H * (0.06 + R(`cy${i}`) * (s.band ?? 0.55));
    const puffs = [[0, 0, 1], [0.55, 0.12, 0.8], [-0.55, 0.14, 0.75], [0.2, -0.28, 0.75], [-0.25, -0.2, 0.65]];
    items.push(
      <div key={i} style={{ position: "absolute", left: x, top: y, width: size, height: size * 0.6 }}>
        {puffs.map((p, k) => {
          const d = size * 0.62 * p[2];
          const st: CSSProperties = crisp
            ? { background: cloud, boxShadow: `inset 0 ${-d * 0.22}px 0 ${shadow}` }
            : { background: `radial-gradient(circle, ${rgba(cloud, 0.95)} 38%, ${rgba(cloud, 0)} 70%)` };
          return <div key={k} style={{ position: "absolute", left: size * (0.5 + p[0] * 0.5) - d / 2, top: size * (0.3 + p[1] * 0.5) - d / 2, width: d, height: d, borderRadius: "50%", ...st }} />;
        })}
      </div>,
    );
  }
  return <Fill style={{ background: `linear-gradient(180deg, ${P(s.sky?.[0] ?? "accent2")}, ${P(s.sky?.[1] ?? "paper")})` }}>{items}</Fill>;
};

const NightSky: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps, u } = useBg();
  const stars: React.ReactNode[] = [];
  for (let i = 0; i < (s.stars ?? 90); i++) {
    const tw = 0.5 + 0.5 * Math.sin((f / fps) * (1 + R(`ns${i}`) * 3) + i);
    stars.push(<circle key={i} cx={R(`nx${i}`) * W} cy={R(`ny${i}`) * H * 0.75} r={(1 + R(`nr${i}`) * 2.4) * u} fill={P(s.star ?? "paper")} opacity={0.35 + tw * 0.65} />);
  }
  const castle = (() => {
    if (!s.castle) return null;
    const base = H * 0.86, cw = W * 0.42, cx = W * 0.5;
    const tower = (x: number, w: number, h: number, roof: number, k: string) => (
      <g key={k}>
        <rect x={x - w / 2} y={base - h} width={w} height={h + H * 0.2} fill={P(s.bld ?? "ink")} />
        <polygon points={`${x - w * 0.62},${base - h} ${x + w * 0.62},${base - h} ${x},${base - h - roof}`} fill={P(s.bld ?? "ink")} />
        {[0.3, 0.6].map((q, i) => <rect key={i} x={x - w * 0.12} y={base - h * q - h * 0.05} width={w * 0.24} height={w * 0.34} rx={w * 0.12} fill={rgba(P(s.win ?? "accent"), 0.85)} />)}
      </g>
    );
    return (
      <g>
        <rect x={cx - cw / 2} y={base - H * 0.07} width={cw} height={H * 0.4} fill={P(s.bld ?? "ink")} />
        {tower(cx, cw * 0.22, H * 0.2, H * 0.1, "t0")}
        {tower(cx - cw * 0.36, cw * 0.14, H * 0.12, H * 0.07, "t1")}
        {tower(cx + cw * 0.36, cw * 0.14, H * 0.14, H * 0.08, "t2")}
        {tower(cx - cw * 0.18, cw * 0.1, H * 0.09, H * 0.05, "t3")}
        {tower(cx + cw * 0.18, cw * 0.1, H * 0.1, H * 0.06, "t4")}
      </g>
    );
  })();
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${P(s.from ?? "bg")}, ${P(s.to ?? "bg2")})` }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {stars}
        {s.moon && <circle cx={W * 0.78} cy={H * 0.14} r={W * 0.07} fill={P(s.moonColor ?? "paper")} opacity={0.92} />}
        {castle}
      </svg>
    </Fill>
  );
};

const Skyline: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps, u } = useBg();
  const layers = s.layers ?? 3;
  const sky0 = P(s.sky?.[0] ?? "bg"), sky1 = P(s.sky?.[1] ?? "bg2");
  const out: React.ReactNode[] = [];
  for (let l = 0; l < layers; l++) {
    const t = l / Math.max(1, layers - 1);
    const fill = mix(P(s.bld ?? "ink"), sky1, (1 - t) * 0.55);
    const shift = ((f / fps) * (s.speed ?? 8) * u * (l + 1)) % (W + 400 * u);
    let x = -200 * u - shift;
    let k = 0;
    while (x < W + 220 * u) {
      const w = (70 + R(`bw${l}${k}`) * 120) * u;
      const h = H * (0.16 + l * 0.05 + R(`bh${l}${k}`) * 0.2);
      const y = H * (s.base ?? 0.92) - h;
      out.push(<rect key={`b${l}${k}`} x={x} y={y} width={w} height={h + H * 0.2} fill={fill} />);
      if (l >= layers - 2) {
        const cols = Math.floor(w / (24 * u)), rows = Math.floor(h / (34 * u));
        for (let r = 0; r < rows; r++) {
          for (let c = 0; c < cols; c++) {
            if (R(`wn${l}${k}${r}${c}`) > 0.55) {
              const wc = s.neon ? (R(`wc${l}${k}${r}${c}`) > 0.5 ? P("accent") : P("accent2")) : P(s.win ?? "accent");
              out.push(<rect key={`w${l}${k}${r}${c}`} x={x + 8 * u + c * 24 * u} y={y + 12 * u + r * 34 * u} width={12 * u} height={16 * u} fill={wc} opacity={s.neon ? 0.95 : 0.8} />);
            }
          }
        }
      }
      x += w + (4 + R(`bg${l}${k}`) * 8) * u;
      k++;
    }
  }
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${sky0}, ${sky1})` }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={s.neon ? { filter: `drop-shadow(0 0 ${6 * u}px ${rgba(P("accent"), 0.7)})` } : undefined}>{out}</svg>
    </Fill>
  );
};

const Sunset: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const horizon = H * (s.horizon ?? 0.6);
  const sunR = W * 0.3;
  const sky = [P(s.sky?.[0] ?? "bg"), P(s.sky?.[1] ?? "bg2"), P(s.sky?.[2] ?? "accent3")];
  const move = ((f / fps) * (s.speed ?? 80) * u) % (s.cell ?? 120) * u;
  const cellSize = (s.cell ?? 120) * u;
  const stripes: React.ReactNode[] = [];
  for (let i = 0; i < 7; i++) {
    const y = horizon - sunR * 0.1 - i * (sunR * 0.13);
    stripes.push(<rect key={i} x={W / 2 - sunR} y={y - (1 + i * 0.5) * u * 2} width={sunR * 2} height={(2 + i * 3.2) * u} fill={sky[2]} />);
  }
  const line = P(s.line ?? "accent");
  const floorStyle: CSSProperties =
    s.floor === "checker"
      ? { background: `repeating-conic-gradient(${P(s.fa ?? "accent")} 0% 25%, ${P(s.fb ?? "accent2")} 0% 50%) 0 ${move}px / ${cellSize * 2}px ${cellSize * 2}px` }
      : {
          background: P(s.floorBase ?? "bg"),
          backgroundImage: `linear-gradient(${line} ${3 * u}px, transparent ${3 * u}px), linear-gradient(90deg, ${line} ${3 * u}px, transparent ${3 * u}px)`,
          backgroundSize: `${cellSize}px ${cellSize}px`, backgroundPosition: `0 ${move}px`,
        };
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${sky[0]}, ${sky[1]} ${(s.horizon ?? 0.6) * 100}%, ${sky[2]})` }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs>
          <linearGradient id="nm-sun" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={P(s.sun?.[0] ?? "accent")} />
            <stop offset="1" stopColor={P(s.sun?.[1] ?? "accent2")} />
          </linearGradient>
        </defs>
        {Array.from({ length: 50 }).map((_, i) => (
          <circle key={i} cx={R(`ss${i}`) * W} cy={R(`st${i}`) * horizon * 0.8} r={(1 + R(`sr${i}`) * 2) * u} fill="#fff" opacity={0.3 + 0.6 * R(`so${i}`)} />
        ))}
        <circle cx={W / 2} cy={horizon - sunR * 0.28} r={sunR} fill="url(#nm-sun)" />
        {stripes}
      </svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: horizon, bottom: 0, overflow: "hidden", perspective: `${H * 0.5}px`, perspectiveOrigin: "50% 0%" }}>
        <div style={{ position: "absolute", left: "-100%", right: "-100%", top: 0, height: H * 1.6, transform: "rotateX(72deg)", transformOrigin: "50% 0%", ...floorStyle }} />
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: H * 0.12, background: `linear-gradient(180deg, ${sky[2]}, transparent)` }} />
      </div>
    </Fill>
  );
};

const Wood: React.FC<BgProps> = ({ s }) => {
  const { P, u } = useBg();
  const base = P(s.base ?? "#8a5a2b");
  const plank = (s.plank ?? 220) * u;
  return (
    <Fill style={{ background: base }}>
      <Fill style={{ backgroundImage: `repeating-linear-gradient(90deg, transparent 0 ${plank - 5 * u}px, ${shade(base, -0.45)} ${plank - 5 * u}px ${plank}px)` }} />
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.012 0.28", oct: 3, a: 1.4, off: -0.3, rgb: [60, 30, 10], seed: 6, size: 320 }), opacity: 0.75 }} />
      <Fill style={{ background: "radial-gradient(ellipse at 50% 45%, rgba(255,255,255,0.1), rgba(0,0,0,0.35))" }} />
    </Fill>
  );
};

const Bricks: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u } = useBg();
  const w = (s.w ?? 150) * u, h = (s.h ?? 62) * u, m = (s.m ?? 7) * u;
  const brick = P(s.brick ?? "bg2"), mortar = P(s.mortar ?? "bg");
  const rects: React.ReactNode[] = [];
  const rows = Math.ceil(H / h) + 1, cols = Math.ceil(W / w) + 2;
  for (let r = 0; r < rows; r++) {
    for (let c = -1; c < cols; c++) {
      const x = c * w + (r % 2 ? w / 2 : 0);
      rects.push(<rect key={`${r}-${c}`} x={x + m / 2} y={r * h + m / 2} width={w - m} height={h - m} rx={2 * u} fill={shade(brick, (R(`br${r}${c}`) - 0.5) * (s.jitter ?? 0.2))} />);
    }
  }
  return <Fill style={{ background: mortar }}><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{rects}</svg>{s.dark && <Fill style={{ background: `radial-gradient(ellipse at 50% 40%, rgba(0,0,0,0), rgba(0,0,0,${s.dark}))` }} />}</Fill>;
};

const Blinds: React.FC<BgProps> = ({ s }) => {
  const { P, u, f, fps, W } = useBg();
  const w = (s.w ?? 78) * u;
  const drift = (f / fps) * (s.speed ?? 6) * u;
  return (
    <Fill style={{ background: P(s.base ?? "bg") }}>
      <Fill style={{ left: -W * 0.3, right: -W * 0.3, backgroundImage: `repeating-linear-gradient(0deg, ${rgba(P(s.light ?? "paper"), s.op ?? 0.5)} 0 ${w * 0.42}px, transparent ${w * 0.42}px ${w}px)`, backgroundPosition: `0 ${drift}px`, transform: `skewX(${s.skew ?? -22}deg)`, WebkitMaskImage: "linear-gradient(115deg, rgba(0,0,0,0.9), rgba(0,0,0,0.05) 70%)" }} />
    </Fill>
  );
};

const Parchment: React.FC<BgProps> = ({ s }) => {
  const { P } = useBg();
  const base = P(s.base ?? "paper");
  return (
    <Fill style={{ background: `radial-gradient(ellipse at 50% 45%, ${shade(base, 0.12)} 0%, ${base} 55%, ${shade(base, -0.35)} 100%)` }}>
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.012", oct: 4, a: 1.1, off: -0.25, rgb: [110, 70, 20], seed: 8, size: 400 }), opacity: 0.55 }} />
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.9", oct: 2, a: 0.8, off: -0.15, rgb: [70, 50, 20], seed: 3 }), opacity: 0.3 }} />
    </Fill>
  );
};

const Wash: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps } = useBg();
  const colors: string[] = (s.colors ?? ["accent", "accent2", "accent3"]).map((c: string) => P(c));
  const base = P(s.base ?? "paper");
  const t = (f / fps) * 0.18;
  return (
    <Fill style={{ background: base }}>
      <div style={{ position: "absolute", inset: 0, filter: "url(#nm-wash)" }}>
        {Array.from({ length: s.n ?? 7 }).map((_, i) => {
          const c = colors[i % colors.length];
          const w = W * (0.5 + R(`ww${i}`) * 0.5), h = w * (0.6 + R(`wh${i}`) * 0.5);
          const x = W * R(`wx${i}`) + Math.sin(t + i) * W * 0.03, y = H * R(`wy${i}`) + Math.cos(t + i * 1.3) * H * 0.02;
          return <div key={i} style={{ position: "absolute", left: x - w / 2, top: y - h / 2, width: w, height: h, borderRadius: "50%", background: rgba(c, s.op ?? 0.42), mixBlendMode: "multiply" }} />;
        })}
      </div>
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.05 0.5", oct: 3, a: 0.7, off: -0.1, rgb: [120, 110, 90], seed: 11 }), opacity: 0.45 }} />
    </Fill>
  );
};

const Newsprint: React.FC<BgProps> = ({ s }) => {
  const { P, u, W } = useBg();
  const base = P(s.base ?? "paper");
  const cols = s.cols ?? 3;
  return (
    <Fill style={{ background: base }}>
      <Fill style={{ backgroundImage: `repeating-linear-gradient(0deg, ${rgba(P("ink"), 0.1)} 0 ${3 * u}px, transparent ${3 * u}px ${9 * u}px)`, WebkitMaskImage: `repeating-linear-gradient(90deg, #000 0 ${W / cols - 30 * u}px, transparent ${W / cols - 30 * u}px ${W / cols}px)` }} />
      {Array.from({ length: cols - 1 }).map((_, i) => <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: `${((i + 1) / cols) * 100}%`, width: 2 * u, background: rgba(P("ink"), 0.35) }} />)}
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.8", oct: 2, a: 1, off: -0.18, rgb: [40, 40, 40], seed: 14 }), opacity: 0.45 }} />
      <Fill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0), rgba(60,40,10,0.25))" }} />
    </Fill>
  );
};

const Arcs: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps } = useBg();
  const colors: string[] = (s.colors ?? ["accent", "accent2", "accent3", "paper"]).map((c: string) => P(c));
  const cx = W * 0.5, cy = H * (s.cy ?? 0.82);
  const maxR = Math.hypot(W, H) * 0.8;
  const n = s.n ?? 9;
  const pulse = 1 + Math.sin((f / fps) * 0.9) * 0.012;
  return (
    <Fill style={{ background: P(s.base ?? "bg") }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: n }).map((_, i) => <circle key={i} cx={cx} cy={cy} r={maxR * (1 - i / n) * pulse} fill={colors[i % colors.length]} />)}
      </svg>
    </Fill>
  );
};

const Fans: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const line = P(s.line ?? "accent");
  const cx = W / 2, cy = H * 0.9;
  const rays: React.ReactNode[] = [];
  const n = s.n ?? 24;
  for (let i = 0; i <= n; i++) {
    const a = Math.PI + (i / n) * Math.PI;
    rays.push(<line key={i} x1={cx} y1={cy} x2={cx + Math.cos(a) * H * 1.3} y2={cy + Math.sin(a) * H * 1.3} stroke={rgba(line, 0.5)} strokeWidth={2.4 * u} />);
  }
  const rings = Array.from({ length: 7 }).map((_, i) => (
    <circle key={`r${i}`} cx={cx} cy={cy} r={(110 + i * 120) * u + Math.sin((f / fps) * 1.2 + i) * 4 * u} fill="none" stroke={rgba(line, 0.6)} strokeWidth={(i % 2 ? 2 : 5) * u} />
  ));
  return <Fill style={{ background: `radial-gradient(ellipse at 50% 90%, ${P(s.bg2 ?? "bg2")}, ${P(s.base ?? "bg")} 70%)` }}><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{rays}{rings}</svg></Fill>;
};

const Girih: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const size = (s.size ?? 170) * u;
  const a = P(s.a ?? "accent"), b = P(s.b ?? "accent2"), gold = P(s.gold ?? "accent3");
  const move = ((f / fps) * (s.speed ?? 6) * u) % size;
  const star = (cx: number, cy: number, r: number, fill: string, key: string) => {
    const pts = (rot: number) => Array.from({ length: 4 }).map((_, i) => { const t = ((i * 90 + rot) * Math.PI) / 180; return `${cx + Math.cos(t) * r},${cy + Math.sin(t) * r}`; }).join(" ");
    return (
      <g key={key}>
        <polygon points={pts(0)} fill={fill} stroke={gold} strokeWidth={3 * u} />
        <polygon points={pts(45)} fill={fill} stroke={gold} strokeWidth={3 * u} />
        <circle cx={cx} cy={cy} r={r * 0.34} fill={mix(fill, "#ffffff", 0.18)} stroke={gold} strokeWidth={2 * u} />
      </g>
    );
  };
  const nodes: React.ReactNode[] = [];
  const cols = Math.ceil(W / size) + 2, rows = Math.ceil(H / size) + 2;
  for (let r = -1; r < rows; r++) {
    for (let c = -1; c < cols; c++) {
      const cx = c * size + move, cy = r * size + move;
      nodes.push(star(cx, cy, size * 0.46, (r + c) % 2 ? a : b, `s${r}-${c}`));
      nodes.push(<rect key={`d${r}-${c}`} x={cx + size / 2 - size * 0.1} y={cy + size / 2 - size * 0.1} width={size * 0.2} height={size * 0.2} transform={`rotate(45 ${cx + size / 2} ${cy + size / 2})`} fill={gold} opacity={0.85} />);
    }
  }
  return <Fill style={{ background: P(s.base ?? "bg") }}><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{nodes}</svg></Fill>;
};

const Constellation: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const n = s.n ?? 64;
  const t = (f / fps) * (s.speed ?? 0.35);
  const pts = Array.from({ length: n }).map((_, i) => ({
    x: W * (0.5 + 0.52 * Math.sin(t * (0.4 + R(`kx${i}`)) + R(`ka${i}`) * 6.28)),
    y: H * (0.5 + 0.52 * Math.cos(t * (0.4 + R(`ky${i}`)) + R(`kb${i}`) * 6.28)),
  }));
  const link = (s.link ?? 230) * u;
  const lines: React.ReactNode[] = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
      if (d < link) lines.push(<line key={`${i}-${j}`} x1={pts[i].x} y1={pts[i].y} x2={pts[j].x} y2={pts[j].y} stroke={rgba(P(s.line ?? "accent2"), (1 - d / link) * 0.7)} strokeWidth={2 * u} />);
    }
  }
  return (
    <Fill style={{ background: `radial-gradient(ellipse at 50% 40%, ${P(s.bg2 ?? "bg2")}, ${P(s.base ?? "bg")} 80%)` }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {lines}
        {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={(2.5 + R(`kr${i}`) * 4) * u} fill={P(s.dot ?? "accent")} />)}
      </svg>
    </Fill>
  );
};

const Hud: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, f, fps } = useBg();
  const line = P(s.line ?? "accent");
  const cx = W / 2, cy = H * 0.46;
  const t = f / fps;
  const rings = [0.2, 0.3, 0.42, 0.56].map((k, i) => {
    const r = Math.min(W, H) * k;
    const circ = 2 * Math.PI * r;
    return <circle key={i} cx={cx} cy={cy} r={r} fill="none" stroke={rgba(line, 0.55)} strokeWidth={(i % 2 ? 2 : 4) * u} strokeDasharray={i % 2 ? `${circ / 40} ${circ / 40}` : `${circ / 3} ${circ / 12}`} transform={`rotate(${t * (i % 2 ? -14 : 9) * (i + 1)} ${cx} ${cy})`} />;
  });
  return (
    <Fill style={{ background: `radial-gradient(ellipse at 50% 46%, ${P(s.bg2 ?? "bg2")}, ${P(s.base ?? "bg")} 75%)` }}>
      <Fill style={{ backgroundImage: `linear-gradient(${rgba(line, 0.1)} ${2 * u}px, transparent ${2 * u}px), linear-gradient(90deg, ${rgba(line, 0.1)} ${2 * u}px, transparent ${2 * u}px)`, backgroundSize: `${60 * u}px ${60 * u}px` }} />
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {rings}
        <line x1={0} y1={cy} x2={W} y2={cy} stroke={rgba(line, 0.35)} strokeWidth={2 * u} />
        <line x1={cx} y1={0} x2={cx} y2={H} stroke={rgba(line, 0.35)} strokeWidth={2 * u} />
        <line x1={cx} y1={cy} x2={cx + Math.cos(t * 1.6) * Math.min(W, H) * 0.56} y2={cy + Math.sin(t * 1.6) * Math.min(W, H) * 0.56} stroke={rgba(P(s.sweep ?? "accent2"), 0.8)} strokeWidth={4 * u} />
      </svg>
    </Fill>
  );
};

const Towers: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps } = useBg();
  const n = s.n ?? 14;
  const t = f / fps;
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${P(s.base ?? "bg")}, ${P(s.bg2 ?? "bg2")})` }}>
      {Array.from({ length: n }).map((_, i) => {
        const w = W * (0.04 + R(`tw${i}`) * 0.06);
        const h = H * (0.25 + R(`th${i}`) * 0.55) * (0.9 + 0.1 * Math.sin(t * 0.5 + i));
        const x = ((R(`tx${i}`) * W * 1.2 + t * (6 + R(`ts${i}`) * 10)) % (W * 1.2)) - W * 0.1;
        return <div key={i} style={{ position: "absolute", left: x, bottom: H * (R(`tb${i}`) * 0.3 - 0.1), width: w, height: h, background: `linear-gradient(180deg, ${rgba(P(s.color ?? "accent"), 0)}, ${rgba(P(s.color ?? "accent"), s.op ?? 0.28)})`, borderTop: `2px solid ${rgba(P(s.color ?? "accent"), 0.55)}` }} />;
      })}
    </Fill>
  );
};

const Studio: React.FC<BgProps> = ({ s }) => {
  const { P, H } = useBg();
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${P(s.from ?? "paper")} 0%, ${P(s.to ?? "bg2")} ${(s.horizon ?? 0.68) * 100}%, ${shade(P(s.to ?? "bg2"), -0.2)} 100%)` }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: H * (s.horizon ?? 0.68), height: 2, background: "rgba(255,255,255,0.35)" }} />
      <div style={{ position: "absolute", left: 0, right: 0, top: H * (s.horizon ?? 0.68), bottom: 0, background: "linear-gradient(180deg, rgba(255,255,255,0.22), rgba(255,255,255,0))" }} />
    </Fill>
  );
};

const Spotlight: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps, u } = useBg();
  const t = f / fps;
  return (
    <Fill style={{ background: P(s.base ?? "bg") }}>
      <Fill style={{ background: `radial-gradient(ellipse at ${s.at ?? "50% 22%"}, ${rgba(P(s.light ?? "paper"), s.op ?? 0.55)}, rgba(0,0,0,0) 62%)` }} />
      <Fill style={{ background: `linear-gradient(180deg, rgba(0,0,0,0) 62%, ${rgba(P(s.light ?? "paper"), 0.08)} 100%)` }} />
      {s.bokeh !== false && Array.from({ length: 12 }).map((_, i) => {
        const d = (60 + R(`bk${i}`) * 140) * u;
        const x = ((R(`bx${i}`) * W + t * (6 + R(`bs${i}`) * 9)) % (W + d)) - d / 2, y = H * (0.1 + R(`by${i}`) * 0.8);
        return <div key={i} style={{ position: "absolute", left: x, top: y, width: d, height: d, borderRadius: "50%", background: `radial-gradient(circle, ${rgba(P(s.bokehColor ?? "accent"), 0.25)}, ${rgba(P(s.bokehColor ?? "accent"), 0)} 70%)` }} />;
      })}
    </Fill>
  );
};

const Layers: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, u } = useBg();
  const colors: string[] = (s.colors ?? ["accent", "accent2", "accent3", "bg2"]).map((c: string) => P(c));
  const n = s.n ?? 5;
  return (
    <Fill style={{ background: P(s.base ?? "bg") }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ overflow: "visible" }}>
        {Array.from({ length: n }).map((_, i) => (
          <path key={i} d={wavePath(W, H, H * (0.28 + i * (0.64 / n)), H * 0.05, i + 1, f, 0.8 + i * 0.2)} fill={colors[i % colors.length]} style={{ filter: `drop-shadow(0 ${-6 * u}px ${12 * u}px rgba(0,0,0,0.28))` }} />
        ))}
      </svg>
    </Fill>
  );
};

const Rays: React.FC<BgProps> = ({ s, v }) => {
  const { P, f, fps } = useBg();
  const w = 360 / ((s.n ?? 16) * 2);
  const a = P(v % 2 && s.a2 ? s.a2 : s.a ?? "bg"), b = P(v % 2 && s.b2 ? s.b2 : s.b ?? "bg2");
  return <Fill style={{ background: `repeating-conic-gradient(from ${(f / fps) * (s.speed ?? 6)}deg at 50% ${s.cy ?? 50}%, ${a} 0deg ${w}deg, ${b} ${w}deg ${w * 2}deg)` }} />;
};

const Noise: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, f, fps } = useBg();
  const tick = Math.floor((f / fps) * (s.rate ?? 12));
  const colors: string[] = (s.colors ?? ["accent", "accent2", "paper"]).map((c: string) => P(c));
  return (
    <Fill style={{ background: P(s.base ?? "bg") }}>
      {Array.from({ length: s.bars ?? 16 }).map((_, i) => {
        const on = R(`nb${tick}-${i}`) > 0.55;
        if (!on) return null;
        return <div key={i} style={{ position: "absolute", left: R(`nl${tick}${i}`) * W * 0.5, width: W * (0.2 + R(`nw${tick}${i}`) * 0.8), top: R(`nt${tick}${i}`) * H, height: H * (0.004 + R(`nh${tick}${i}`) * 0.035), background: rgba(colors[i % colors.length], 0.55 + R(`na${tick}${i}`) * 0.4) }} />;
      })}
      <Fill style={{ backgroundImage: noiseTile({ freq: "0.8", oct: 1, a: 1.3, off: -0.15, rgb: [255, 255, 255], seed: 1 + (tick % 5) }), opacity: s.grain ?? 0.18 }} />
    </Fill>
  );
};

export const BG: { [k: string]: React.FC<BgProps> } = {
  solid: Solid, linear: Linear, radial: Radial, bands: Bands, grid: Grid, dots: Dots, stripes: Stripes, checker: Checker,
  paper: Paper, notebook: Notebook, whiteboard: Whiteboard, chalk: Chalk, halftone: Halftone, mesh: Mesh,
  lowpoly: LowPoly, stained: Stained, isocubes: IsoCubes, isogrid: IsoGrid, studs: Studs, hills: Hills, clouds: Clouds,
  nightsky: NightSky, skyline: Skyline, sunset: Sunset, wood: Wood, bricks: Bricks, blinds: Blinds, parchment: Parchment,
  wash: Wash, newsprint: Newsprint, arcs: Arcs, fans: Fans, girih: Girih, constellation: Constellation, hud: Hud,
  towers: Towers, studio: Studio, spotlight: Spotlight, layers: Layers, rays: Rays, noise: Noise,
};

/** an optional soft scrim (spec.veil 0..1, colour spec.veilColor) behind the text of a busy background: the middle calms down, the edges keep the pattern */
const Veil: React.FC<{ s: Any }> = ({ s }) => {
  const { P } = useBg();
  const k = Math.max(0, Math.min(1, Number(s.veil) || 0));
  const c = P(s.veilColor ?? "bg");
  return <Fill style={{ background: `radial-gradient(ellipse 78% 60% at 50% 50%, ${rgba(c, k)} 0%, ${rgba(c, k * 0.85)} 55%, ${rgba(c, 0)} 100%)` }} />;
};

export const Background: React.FC<{ spec: Any; variant?: number }> = ({ spec, variant = 0 }) => {
  const C = BG[spec.kind] ?? Solid;
  return (
    <>
      <C s={spec} v={variant} />
      {spec.veil ? <Veil s={spec} /> : null}
    </>
  );
};
