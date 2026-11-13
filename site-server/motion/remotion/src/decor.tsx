import React from "react";
import type { CSSProperties } from "react";
import { Fill, noiseTile } from "./bg";
import { useCtx, useQF } from "./ctx";
import type { Any } from "./types";
import { R, col, mix, rgba, shade } from "./util";

type DProps = { d: Any };

function useD() {
  const c = useCtx();
  const f = useQF();
  const t = f / c.fps;
  return { ...c, f, t, P: (n?: string, dflt?: string) => col(c.pal, n, dflt) };
}

const colorsOf = (d: Any, P: (n?: string) => string, dflt: string[]): string[] => (d.colors ?? dflt).map((c: string) => P(c));

const STAR = "M0,-1 L0.24,-0.24 L1,0 L0.24,0.24 L0,1 L-0.24,0.24 L-1,0 L-0.24,-0.24 Z";

const Confetti: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3", "paper"]);
  const n = d.n ?? 30;
  return (
    <Fill>
      {Array.from({ length: n }).map((_, i) => {
        const size = (10 + R(`cf${i}`) * 22) * u * (d.size ?? 1);
        const sp = (60 + R(`cs${i}`) * 140) * u * (d.speed ?? 1);
        const y = ((R(`cy${i}`) * (H + 120) + t * sp) % (H + 120)) - 60;
        const x = R(`cx${i}`) * W + Math.sin(t * (1 + R(`cw${i}`) * 2) + i) * 30 * u;
        const kind = i % 3;
        const st: CSSProperties = { position: "absolute", left: x, top: y, width: size, height: kind === 0 ? size * 0.5 : size, background: cols[i % cols.length], transform: `rotate(${t * (120 + R(`cr${i}`) * 200) + i * 40}deg)`, borderRadius: kind === 1 ? "50%" : 2 };
        if (kind === 2) { st.clipPath = "polygon(50% 0, 100% 100%, 0 100%)"; }
        return <div key={i} style={st} />;
      })}
    </Fill>
  );
};

const Sparkles: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "paper"]);
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={d.glow ? { filter: `drop-shadow(0 0 ${8 * u}px ${cols[0]})` } : undefined}>
        {Array.from({ length: d.n ?? 14 }).map((_, i) => {
          const tw = Math.max(0, Math.sin(t * (1.2 + R(`sp${i}`) * 2) + i * 2));
          const sz = (14 + R(`sz${i}`) * 34) * u * (d.size ?? 1) * (0.25 + tw * 0.75);
          return <path key={i} d={STAR} transform={`translate(${R(`sx${i}`) * W} ${R(`sy${i}`) * H}) scale(${sz}) rotate(${tw * 30})`} fill={cols[i % cols.length]} opacity={0.3 + tw * 0.7} />;
        })}
      </svg>
    </Fill>
  );
};

const Pixels: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3"]);
  const grid = 16 * u;
  return (
    <Fill>
      {Array.from({ length: d.n ?? 26 }).map((_, i) => {
        const size = grid * (1 + Math.floor(R(`px${i}`) * 3));
        const y = H - ((R(`py${i}`) * H + t * (30 + R(`ps${i}`) * 70) * u) % (H + size)) + size / 2;
        const x = Math.round((R(`pxx${i}`) * W) / grid) * grid;
        return <div key={i} style={{ position: "absolute", left: x, top: Math.round(y / grid) * grid, width: size, height: size, background: cols[i % cols.length], opacity: 0.55 + R(`po${i}`) * 0.45, boxShadow: `inset ${-size * 0.2}px ${-size * 0.2}px 0 ${rgba("#000000", 0.25)}` }} />;
      })}
    </Fill>
  );
};

const Corners: React.FC<DProps> = ({ d }) => {
  const { W, H, u, P, t } = useD();
  const c = P(d.color ?? "paper");
  const m = 44 * u, L = 90 * u, w = 3 * u;
  const bracket = (x: number, y: number, sx: number, sy: number, k: string) => <path key={k} d={`M${x + sx * L},${y} L${x},${y} L${x},${y + sy * L}`} stroke={c} strokeWidth={w} fill="none" />;
  const dimY = H - m * 1.8;
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} opacity={0.85}>
        {bracket(m, m, 1, 1, "a")}{bracket(W - m, m, -1, 1, "b")}{bracket(m, H - m, 1, -1, "c")}{bracket(W - m, H - m, -1, -1, "d")}
        <circle cx={m * 2.2} cy={m * 2.2} r={14 * u} stroke={c} strokeWidth={w} fill="none" />
        <line x1={m * 2.2 - 24 * u} y1={m * 2.2} x2={m * 2.2 + 24 * u} y2={m * 2.2} stroke={c} strokeWidth={w * 0.7} />
        <line x1={m * 2.2} y1={m * 2.2 - 24 * u} x2={m * 2.2} y2={m * 2.2 + 24 * u} stroke={c} strokeWidth={w * 0.7} />
        <line x1={m * 2} y1={dimY} x2={W - m * 2} y2={dimY} stroke={c} strokeWidth={w * 0.7} />
        <path d={`M${m * 2},${dimY} l${22 * u},${-9 * u} v${18 * u} z M${W - m * 2},${dimY} l${-22 * u},${-9 * u} v${18 * u} z`} fill={c} />
        <line x1={m * 2} y1={dimY - 16 * u} x2={m * 2} y2={dimY + 16 * u} stroke={c} strokeWidth={w * 0.7} />
        <line x1={W - m * 2} y1={dimY - 16 * u} x2={W - m * 2} y2={dimY + 16 * u} stroke={c} strokeWidth={w * 0.7} />
        <circle cx={W - m * 2.4} cy={H * 0.5 + Math.sin(t) * 6 * u} r={34 * u} stroke={c} strokeWidth={w * 0.7} fill="none" strokeDasharray={`${10 * u} ${8 * u}`} />
      </svg>
    </Fill>
  );
};

const Bubbles: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "paper");
  return (
    <Fill>
      {Array.from({ length: d.n ?? 16 }).map((_, i) => {
        const size = (30 + R(`bb${i}`) * 110) * u;
        const y = H - ((R(`by${i}`) * H + t * (40 + R(`bs${i}`) * 80) * u) % (H + size)) + size / 2;
        const x = R(`bx${i}`) * W + Math.sin(t * 1.3 + i) * 24 * u;
        return <div key={i} style={{ position: "absolute", left: x, top: y, width: size, height: size, borderRadius: "50%", background: `radial-gradient(circle at 32% 30%, ${rgba(c, 0.55)} 0 ${size * 0.08}px, ${rgba(c, 0.07)} ${size * 0.1}px, ${rgba(c, 0.14)} 100%)`, boxShadow: `inset 0 0 ${size * 0.15}px ${rgba(c, 0.5)}`, border: `${Math.max(1, 2 * u)}px solid ${rgba(c, 0.5)}` }} />;
      })}
    </Fill>
  );
};

const Shapes: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3", "ink"]);
  const ink = P(d.ink ?? "ink");
  const n = d.n ?? 16;
  const items = Array.from({ length: n }).map((_, i) => {
    const s = (50 + R(`ms${i}`) * 90) * u * (d.size ?? 1);
    const x = R(`mx${i}`) * W, y = R(`my${i}`) * H + Math.sin(t * 0.8 + i) * 14 * u;
    const rot = R(`mr${i}`) * 360 + t * (d.spin ?? 14) * (i % 2 ? 1 : -1);
    const c = cols[i % cols.length];
    const kind = (d.kinds ?? ["circle", "tri", "squiggle", "cross", "half", "dots", "ring"])[i % (d.kinds?.length ?? 7)];
    let body: React.ReactNode;
    const sw = Math.max(3, 6 * u);
    switch (kind) {
      case "circle": body = <circle r={s / 2} fill={c} stroke={d.outline ? ink : "none"} strokeWidth={sw} />; break;
      case "ring": body = <circle r={s / 2} fill="none" stroke={c} strokeWidth={sw * 1.6} />; break;
      case "tri": body = <polygon points={`0,${-s / 2} ${s / 2},${s / 2} ${-s / 2},${s / 2}`} fill={c} stroke={d.outline ? ink : "none"} strokeWidth={sw} strokeLinejoin="round" />; break;
      case "cross": body = <path d={`M${-s / 2},0 H${s / 2} M0,${-s / 2} V${s / 2}`} stroke={c} strokeWidth={sw * 1.6} strokeLinecap="round" />; break;
      case "half": body = <path d={`M${-s / 2},0 A${s / 2},${s / 2} 0 0 1 ${s / 2},0 Z`} fill={c} stroke={d.outline ? ink : "none"} strokeWidth={sw} />; break;
      case "dots": body = <g fill={c}>{[-1, 0, 1].flatMap((a) => [-1, 0, 1].map((b) => <circle key={`${a}${b}`} cx={a * s * 0.3} cy={b * s * 0.3} r={s * 0.07} />))}</g>; break;
      default: body = <path d={`M${-s / 2},0 l${s / 6},${-s / 5} l${s / 6},${s / 3} l${s / 6},${-s / 3} l${s / 6},${s / 3} l${s / 6},${-s / 5}`} stroke={c} strokeWidth={sw * 1.2} fill="none" strokeLinecap="round" strokeLinejoin="round" />;
    }
    return <g key={i} transform={`translate(${x} ${y}) rotate(${rot})`}>{body}</g>;
  });
  return <Fill><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{items}</svg></Fill>;
};

const Blobs: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3"]);
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: d.n ?? 5 }).map((_, i) => {
          const r = (150 + R(`bl${i}`) * 220) * u * (d.size ?? 1);
          const cx = R(`bx${i}`) * W, cy = R(`by${i}`) * H;
          const pts = Array.from({ length: 8 }).map((_, k) => {
            const a = (k / 8) * Math.PI * 2;
            const rr = r * (0.78 + 0.22 * Math.sin(t * 0.7 + k * 1.7 + i) * (0.6 + R(`bk${i}${k}`)));
            return [cx + Math.cos(a) * rr, cy + Math.sin(a) * rr];
          });
          let path = "";
          pts.forEach((p, k) => {
            const n1 = pts[(k + 1) % pts.length];
            const mx = (p[0] + n1[0]) / 2, my = (p[1] + n1[1]) / 2;
            path += k === 0 ? `M${mx},${my}` : "";
            const nx = pts[(k + 1) % pts.length];
            const nmx = (nx[0] + pts[(k + 2) % pts.length][0]) / 2, nmy = (nx[1] + pts[(k + 2) % pts.length][1]) / 2;
            path += ` Q${nx[0]},${nx[1]} ${nmx},${nmy}`;
          });
          return <path key={i} d={path + "Z"} fill={rgba(cols[i % cols.length], d.op ?? 0.9)} />;
        })}
      </svg>
    </Fill>
  );
};

const Speed: React.FC<DProps> = ({ d }) => {
  const { W, H, f, fps, u, P } = useD();
  const c = P(d.color ?? "paper");
  const tick = Math.floor((f / fps) * (d.rate ?? 14));
  const n = d.n ?? 38;
  const cx = W / 2, cy = H * (d.cy ?? 0.5);
  const lines: React.ReactNode[] = [];
  for (let i = 0; i < n; i++) {
    if (d.mode === "h") {
      const y = R(`sy${tick % 7}-${i}`) * H, len = W * (0.2 + R(`sl${tick % 5}-${i}`) * 0.5);
      const x = ((R(`sx${i}`) * W * 1.5 + tick * (90 + R(`sv${i}`) * 100) * u) % (W * 1.5)) - len / 2;
      lines.push(<rect key={i} x={x} y={y} width={len} height={(2 + R(`sh${i}`) * 5) * u} fill={rgba(c, 0.18 + R(`so${i}`) * 0.35)} />);
    } else {
      const a = R(`sa${i}`) * Math.PI * 2 + (tick % 3) * 0.02;
      const r0 = Math.hypot(W, H) * (0.22 + R(`sr${tick % 4}-${i}`) * 0.18), r1 = Math.hypot(W, H) * 0.78;
      const wdt = (0.004 + R(`sw${i}`) * 0.012);
      lines.push(<polygon key={i} points={`${cx + Math.cos(a) * r0},${cy + Math.sin(a) * r0} ${cx + Math.cos(a - wdt) * r1},${cy + Math.sin(a - wdt) * r1} ${cx + Math.cos(a + wdt) * r1},${cy + Math.sin(a + wdt) * r1}`} fill={rgba(c, 0.55)} />);
    }
  }
  return <Fill><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{lines}</svg></Fill>;
};

const Burst: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const n = d.spikes ?? 18;
  const R0 = Math.min(W, H) * (d.r ?? 0.46), R1 = R0 * 0.72;
  const pts = Array.from({ length: n * 2 }).map((_, i) => {
    const a = (i / (n * 2)) * Math.PI * 2 + t * (d.spin ?? 0.1);
    const r = i % 2 ? R1 : R0;
    return `${W / 2 + Math.cos(a) * r},${H * (d.cy ?? 0.5) + Math.sin(a) * r}`;
  }).join(" ");
  return <Fill><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}><polygon points={pts} fill={P(d.color ?? "accent3")} stroke={P(d.stroke ?? "ink")} strokeWidth={(d.sw ?? 7) * u} strokeLinejoin="round" /></svg></Fill>;
};

const Rain: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "paper");
  const ang = d.angle ?? 12;
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: d.n ?? 90 }).map((_, i) => {
          const len = (30 + R(`rl${i}`) * 60) * u;
          const sp = 900 + R(`rs${i}`) * 900;
          const y = ((R(`ry${i}`) * H + t * sp * u) % (H + len)) - len;
          const x = R(`rx${i}`) * (W + 200) - 100 + (y / H) * Math.tan((ang * Math.PI) / 180) * H * 0.3;
          return <line key={i} x1={x} y1={y} x2={x + Math.sin((ang * Math.PI) / 180) * len} y2={y + Math.cos((ang * Math.PI) / 180) * len} stroke={rgba(c, 0.25 + R(`ro${i}`) * 0.4)} strokeWidth={(1.5 + R(`rw${i}`)) * u} />;
        })}
      </svg>
    </Fill>
  );
};

const Smoke: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "paper");
  return (
    <Fill>
      {Array.from({ length: d.n ?? 7 }).map((_, i) => {
        const size = (420 + R(`sm${i}`) * 520) * u;
        const y = H - ((R(`sy${i}`) * H + t * (28 + R(`ss${i}`) * 34) * u) % (H + size)) + size / 4;
        const x = R(`sx${i}`) * W + Math.sin(t * 0.4 + i) * 110 * u;
        return <div key={i} style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: "50%", background: `radial-gradient(circle, ${rgba(c, d.op ?? 0.18)}, ${rgba(c, 0)} 68%)` }} />;
      })}
    </Fill>
  );
};

const gearPath = (r: number, teeth: number): string => {
  const pts: string[] = [];
  for (let i = 0; i < teeth * 4; i++) {
    const a = (i / (teeth * 4)) * Math.PI * 2;
    const rr = i % 4 < 2 ? r : r * 0.82;
    pts.push(`${Math.cos(a) * rr},${Math.sin(a) * rr}`);
  }
  return pts.join(" ");
};

const Gears: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "muted"]);
  const spots = [[0.08, 0.1, 190], [0.92, 0.18, 150], [0.12, 0.9, 230], [0.9, 0.86, 170], [0.5, 0.97, 130]];
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} opacity={d.op ?? 0.8}>
        {spots.slice(0, d.n ?? 5).map(([x, y, r], i) => (
          <g key={i} transform={`translate(${W * x} ${H * y}) rotate(${t * (i % 2 ? -18 : 14) * (200 / r)})`}>
            <polygon points={gearPath(r * u, 12 + (i % 3) * 2)} fill={cols[i % cols.length]} stroke={P("ink")} strokeWidth={4 * u} />
            <circle r={r * 0.32 * u} fill={P("bg")} stroke={P("ink")} strokeWidth={4 * u} />
            {Array.from({ length: 6 }).map((_, k) => <circle key={k} cx={Math.cos((k / 6) * 6.283) * r * 0.58 * u} cy={Math.sin((k / 6) * 6.283) * r * 0.58 * u} r={r * 0.07 * u} fill={P("bg")} />)}
          </g>
        ))}
      </svg>
    </Fill>
  );
};

const Splats: React.FC<DProps> = ({ d }) => {
  const { W, H, f, fps, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3"]);
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: d.n ?? 7 }).map((_, i) => {
          const born = i * 5 + 3;
          const p = Math.min(1, Math.max(0, (f - born) / 8));
          if (p <= 0) return null;
          const [cx, cy] = avoidText(R(`px${i}`) * W, R(`py${i}`) * H * 0.85, W, H, d.avoid !== false);
          const r = (60 + R(`pr${i}`) * 110) * u * p;
          const c = cols[i % cols.length];
          const drip = (40 + R(`pd${i}`) * 160) * u * Math.min(1, (f - born) / (fps * 1.2));
          return (
            <g key={i} fill={c}>
              <circle cx={cx} cy={cy} r={r} />
              {Array.from({ length: 9 }).map((_, k) => { const a = (k / 9) * 6.283 + R(`pa${i}${k}`); const dd = r * (1.2 + R(`pk${i}${k}`) * 0.9); return <circle key={k} cx={cx + Math.cos(a) * dd} cy={cy + Math.sin(a) * dd} r={r * (0.08 + R(`pq${i}${k}`) * 0.16)} />; })}
              <rect x={cx - r * 0.12} y={cy} width={r * 0.24} height={r * 0.6 + drip} rx={r * 0.12} />
            </g>
          );
        })}
      </svg>
    </Fill>
  );
};

const Bars: React.FC<DProps> = ({ d }) => {
  const { W, H, f, fps, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3", "muted"]);
  const n = d.n ?? 7;
  const bw = (W * 0.7) / n;
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: n }).map((_, i) => {
          const p = Math.min(1, Math.max(0, (f - i * 3) / (fps * 0.9)));
          const e = 1 - Math.pow(1 - p, 3);
          const h = (60 + R(`ib${i}`) * 220) * u * e;
          return <rect key={i} x={W * 0.15 + i * bw + bw * 0.12} y={H - 90 * u - h} width={bw * 0.76} height={h} rx={8 * u} fill={rgba(cols[i % cols.length], d.op ?? 0.28)} />;
        })}
      </svg>
    </Fill>
  );
};

const Birds: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "ink");
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: d.n ?? 5 }).map((_, i) => {
          const x = ((R(`ox${i}`) * W + t * (50 + R(`os${i}`) * 50) * u) % (W + 200)) - 100;
          const y = H * (0.1 + R(`oy${i}`) * 0.3) + Math.sin(t * 2 + i) * 14 * u;
          const flap = Math.sin(t * 7 + i * 2) * 10 * u, s = (14 + R(`oz${i}`) * 14) * u;
          return <path key={i} d={`M${x - s * 1.5},${y - flap} Q${x - s * 0.5},${y - s * 0.6} ${x},${y} Q${x + s * 0.5},${y - s * 0.6} ${x + s * 1.5},${y - flap}`} stroke={c} strokeWidth={3.5 * u} fill="none" strokeLinecap="round" />;
        })}
      </svg>
    </Fill>
  );
};

const Petals: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "paper"]);
  return (
    <Fill>
      {Array.from({ length: d.n ?? 18 }).map((_, i) => {
        const s = (16 + R(`pt${i}`) * 22) * u * (d.size ?? 1);
        const y = ((R(`py${i}`) * (H + 100) + t * (60 + R(`ps${i}`) * 80) * u) % (H + 100)) - 50;
        const x = R(`px${i}`) * W + Math.sin(t * (0.8 + R(`pw${i}`)) + i) * 90 * u + t * 20 * u;
        return <div key={i} style={{ position: "absolute", left: x % W, top: y, width: s, height: s * 0.62, borderRadius: "80% 0 80% 0", background: cols[i % cols.length], opacity: 0.85, transform: `rotate(${t * 90 + i * 60}deg) rotateX(${t * 120 + i * 20}deg)` }} />;
      })}
    </Fill>
  );
};

const Doodles: React.FC<DProps> = ({ d }) => {
  const { W, H, f, fps, u, P } = useD();
  const c = P(d.color ?? "ink");
  const sw = (d.sw ?? 6) * u;
  const draw = (k: number, len: number) => {
    const p = Math.min(1, Math.max(0, (f - k * 7 - 6) / (fps * 0.8)));
    return { strokeDasharray: len, strokeDashoffset: len * (1 - p) } as CSSProperties;
  };
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} fill="none" stroke={c} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" opacity={d.op ?? 0.9}>
        <path d={`M${W * 0.08},${H * 0.12} l${60 * u},${-8 * u} l${-48 * u},${40 * u} l${22 * u},${-56 * u} l${12 * u},${64 * u} z`} style={draw(0, 700 * u)} />
        <path d={`M${W * 0.78},${H * 0.1} q${60 * u},${-50 * u} ${120 * u},${10 * u} t${-30 * u},${70 * u}`} style={draw(1, 600 * u)} />
        <path d={`M${W * 0.1},${H * 0.88} q${90 * u},${-70 * u} ${190 * u},${-6 * u}`} style={draw(2, 500 * u)} />
        <path d={`M${W * 0.2},${H * 0.86} l${-32 * u},${14 * u} m${32 * u},${-14 * u} l${-4 * u},${36 * u}`} style={draw(3, 200 * u)} />
        <circle cx={W * 0.86} cy={H * 0.86} r={46 * u} style={draw(4, 320 * u)} />
        <path d={`M${W * 0.72},${H * 0.93} q${22 * u},${-22 * u} ${44 * u},0 t${44 * u},0 t${44 * u},0`} style={draw(5, 320 * u)} />
        {d.arrow && <path d={`M${W * 0.3},${H * 0.2} q${80 * u},${-60 * u} ${200 * u},${10 * u} m${-26 * u},${-20 * u} l${26 * u},${20 * u} l${-34 * u},${14 * u}`} style={draw(6, 420 * u)} />}
      </svg>
    </Fill>
  );
};

const Stickman: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "ink");
  const s = (d.size ?? 1) * 150 * u;
  const walk = d.mode !== "wave";
  const x = walk ? ((t * 90 * u + W * 0.1) % (W + s * 2)) - s : W * 0.86;
  const y = H * 0.94 - s * 1.15;
  const sw = Math.sin(t * (walk ? 6 : 5));
  const limb = (x1: number, y1: number, len: number, ang: number) => `M${x1},${y1} L${x1 + Math.sin(ang) * len},${y1 + Math.cos(ang) * len}`;
  const armUp = !walk;
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} fill="none" stroke={c} strokeWidth={7 * u} strokeLinecap="round">
        <g transform={`translate(${x} ${y})`}>
          <circle cx={0} cy={0} r={s * 0.16} />
          <path d={`M0,${s * 0.16} L0,${s * 0.66}`} />
          <path d={limb(0, s * 0.26, s * 0.4, armUp ? -2.4 + sw * 0.5 : sw * 0.7)} />
          <path d={limb(0, s * 0.26, s * 0.4, armUp ? 0.6 : -sw * 0.7)} />
          <path d={limb(0, s * 0.66, s * 0.5, walk ? sw * 0.6 : 0.2)} />
          <path d={limb(0, s * 0.66, s * 0.5, walk ? -sw * 0.6 : -0.2)} />
        </g>
      </svg>
    </Fill>
  );
};

/** moves a floating decoration out of the middle of the frame (where the text sits) to the edge of an ellipse around it */
function avoidText(x: number, y: number, W: number, H: number, on: boolean): [number, number] {
  if (!on) return [x, y];
  const dx = (x - W / 2) / (W / 2), dy = (y - H / 2) / (H / 2);
  const r = Math.hypot(dx / 0.88, dy / 0.5);
  if (r >= 1) return [x, y];
  const k = 1.12 / Math.max(r, 0.25);
  const nx = W / 2 + dx * k * (W / 2), ny = H / 2 + dy * k * (H / 2);
  return [Math.max(0, Math.min(W, nx)), Math.max(0, Math.min(H, ny))];
}

const Orbs: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2", "accent3"]);
  const mode = d.mode ?? "gloss";
  return (
    <Fill>
      {Array.from({ length: d.n ?? 5 }).map((_, i) => {
        const size = (130 + R(`ob${i}`) * 200) * u * (d.size ?? 1);
        const [x, y] = avoidText(R(`ox${i}`) * W, R(`oy${i}`) * H + Math.sin(t * (0.9 + R(`oz${i}`)) + i * 2) * 26 * u, W, H, d.avoid !== false);
        const c = cols[i % cols.length];
        let bg: string, bd = "none", sh = `0 ${size * 0.25}px ${size * 0.2}px ${rgba("#000000", 0.22)}`;
        if (mode === "cel") {
          bg = `radial-gradient(circle at 34% 30%, #ffffff 0 ${size * 0.05}px, transparent ${size * 0.06}px), linear-gradient(135deg, ${shade(c, 0.18)} 0 55%, ${c} 55% 78%, ${shade(c, -0.28)} 78%)`;
          bd = `${5 * u}px solid ${P("ink")}`; sh = `${8 * u}px ${10 * u}px 0 ${rgba("#000000", 0.3)}`;
        } else if (mode === "clay") {
          bg = `radial-gradient(circle at 36% 30%, ${shade(c, 0.4)}, ${c} 50%, ${shade(c, -0.25)} 100%)`;
        } else {
          bg = `radial-gradient(circle at 32% 26%, #ffffff 0 ${size * 0.05}px, ${rgba("#ffffff", 0.5)} ${size * 0.07}px, transparent ${size * 0.22}px), radial-gradient(circle at 40% 36%, ${shade(c, 0.35)}, ${c} 45%, ${shade(c, -0.55)} 100%)`;
        }
        return <div key={i} style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: "50%", background: bg, border: bd, boxShadow: sh }} />;
      })}
    </Fill>
  );
};

const Cubes: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const top = P(d.top ?? "accent"), left = P(d.left ?? "accent2"), right = P(d.right ?? "accent3");
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: d.n ?? 6 }).map((_, i) => {
          const e = (50 + R(`ce${i}`) * 80) * u, b = e * 0.866, a = e * 0.5;
          const [cx, cy] = avoidText(R(`cx${i}`) * W, R(`cy${i}`) * H + Math.sin(t * 1.1 + i * 1.7) * 18 * u, W, H, d.avoid !== false);
          return (
            <g key={i}>
              <polygon points={`${cx - b},${cy} ${cx},${cy + a} ${cx},${cy + a + e} ${cx - b},${cy + e}`} fill={left} />
              <polygon points={`${cx},${cy + a} ${cx + b},${cy} ${cx + b},${cy + e} ${cx},${cy + a + e}`} fill={right} />
              <polygon points={`${cx},${cy - a} ${cx + b},${cy} ${cx},${cy + a} ${cx - b},${cy}`} fill={top} />
            </g>
          );
        })}
      </svg>
    </Fill>
  );
};

const Letterbox: React.FC<DProps> = ({ d }) => {
  const { W, H } = useD();
  const bar = Math.max(0, (H - W / (d.ratio ?? 2.39)) / 2);
  const h = Math.min(bar, H * 0.2);
  return (
    <Fill>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: h, background: "#000" }} />
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: h, background: "#000" }} />
    </Fill>
  );
};

const Flare: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "accent2");
  const x = W * (0.5 + 0.4 * Math.sin(t * 0.5));
  const y = H * (d.y ?? 0.42);
  return (
    <Fill style={{ mixBlendMode: "screen" }}>
      <div style={{ position: "absolute", left: x - W * 0.6, top: y - 3 * u, width: W * 1.2, height: 6 * u, background: `linear-gradient(90deg, transparent, ${rgba(c, 0.9)}, transparent)`, filter: `blur(${2 * u}px)` }} />
      <div style={{ position: "absolute", left: x - 90 * u, top: y - 90 * u, width: 180 * u, height: 180 * u, borderRadius: "50%", background: `radial-gradient(circle, ${rgba("#ffffff", 0.7)}, ${rgba(c, 0.25)} 40%, transparent 70%)` }} />
    </Fill>
  );
};

const Dust: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const c = P(d.color ?? "paper");
  return (
    <Fill>
      {Array.from({ length: d.n ?? 40 }).map((_, i) => {
        const s = (2 + R(`du${i}`) * 5) * u;
        const x = ((R(`dx${i}`) * W + t * (8 + R(`dv${i}`) * 14) * u) % W), y = (R(`dy${i}`) * H - t * (6 + R(`dw${i}`) * 10) * u + H * 4) % H;
        return <div key={i} style={{ position: "absolute", left: x, top: y, width: s, height: s, borderRadius: "50%", background: rgba(c, 0.15 + R(`do${i}`) * 0.45), filter: R(`df${i}`) > 0.6 ? `blur(${2 * u}px)` : undefined }} />;
      })}
    </Fill>
  );
};

const Particles: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const cols = colorsOf(d, P, ["accent", "accent2"]);
  return (
    <Fill>
      {Array.from({ length: d.n ?? 50 }).map((_, i) => {
        const s = (4 + R(`pa${i}`) * 9) * u;
        const y = H - ((R(`py${i}`) * H + t * (50 + R(`pv${i}`) * 120) * u) % (H + 40)) + 20;
        const x = R(`px${i}`) * W + Math.sin(t * 1.4 + i) * 22 * u;
        const c = cols[i % cols.length];
        return <div key={i} style={{ position: "absolute", left: x, top: y, width: s, height: s, borderRadius: "50%", background: c, boxShadow: `0 0 ${s * 2.4}px ${c}`, opacity: 0.4 + R(`po${i}`) * 0.6 }} />;
      })}
    </Fill>
  );
};

const Frame: React.FC<DProps> = ({ d }) => {
  const { W, H, u, t, P } = useD();
  const c = P(d.color ?? "accent");
  if (d.mode === "film") {
    const holes = Math.ceil(H / (70 * u));
    const off = (t * 120 * u) % (70 * u);
    return (
      <Fill>
        {[0, 1].map((side) => (
          <div key={side} style={{ position: "absolute", top: 0, bottom: 0, [side ? "right" : "left"]: 0, width: 54 * u, background: "#0a0a0a" }}>
            {Array.from({ length: holes + 1 }).map((_, i) => <div key={i} style={{ position: "absolute", left: 14 * u, top: i * 70 * u - off, width: 26 * u, height: 36 * u, borderRadius: 6 * u, background: "#d8d2c0" }} />)}
          </div>
        ))}
      </Fill>
    );
  }
  const m = 36 * u;
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} fill="none" stroke={c}>
        <rect x={m} y={m} width={W - m * 2} height={H - m * 2} strokeWidth={5 * u} />
        <rect x={m * 1.6} y={m * 1.6} width={W - m * 3.2} height={H - m * 3.2} strokeWidth={2 * u} />
        {[[m, m], [W - m, m], [m, H - m], [W - m, H - m]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={14 * u} fill={c} stroke="none" />)}
      </svg>
    </Fill>
  );
};

const Bauhaus: React.FC<DProps> = ({ d }) => {
  const { W, H, t, u, P } = useD();
  const [a, b, c, ink] = [P("accent"), P("accent2"), P("accent3"), P("ink")];
  const m = Math.min(W, H);
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <circle cx={W * 0.86} cy={H * 0.12} r={m * 0.2} fill={a} />
        <rect x={-m * 0.1} y={H * 0.78 + Math.sin(t) * 6 * u} width={m * 0.42} height={m * 0.42} fill={b} transform={`rotate(${12 + Math.sin(t * 0.6) * 3} ${m * 0.1} ${H * 0.85})`} />
        <polygon points={`${W * 0.9},${H * 0.95} ${W * 1.02},${H * 0.72} ${W * 0.68},${H * 0.95}`} fill={c} />
        <rect x={W * 0.06} y={H * 0.08} width={m * 0.3} height={14 * u} fill={ink} />
        <rect x={W * 0.06} y={H * 0.08 + 30 * u} width={m * 0.18} height={14 * u} fill={ink} />
        <circle cx={W * 0.14} cy={H * 0.56} r={m * 0.055} fill="none" stroke={ink} strokeWidth={9 * u} />
      </svg>
    </Fill>
  );
};

const Shine: React.FC<DProps> = ({ d }) => {
  const { W, t } = useD();
  const x = ((t * (d.speed ?? 0.35)) % 1.6 - 0.3) * W * 1.4;
  return <Fill style={{ mixBlendMode: "overlay" }}><div style={{ position: "absolute", top: "-10%", bottom: "-10%", left: x, width: W * 0.22, background: "linear-gradient(100deg, transparent, rgba(255,255,255,0.75), transparent)", transform: "skewX(-18deg)" }} /></Fill>;
};

const Grain: React.FC<DProps> = ({ d }) => {
  const { f } = useD();
  return <Fill style={{ backgroundImage: noiseTile({ freq: "0.8", oct: 2, a: 1.1, off: -0.1, rgb: d.rgb ?? [255, 255, 255], seed: 1 + (f % 4) }), opacity: d.op ?? 0.12, mixBlendMode: d.blend ?? "overlay" }} />;
};

export const DECOR: { [k: string]: React.FC<DProps> } = {
  confetti: Confetti, sparkles: Sparkles, pixels: Pixels, corners: Corners, bubbles: Bubbles, shapes: Shapes, blobs: Blobs,
  speed: Speed, burst: Burst, rain: Rain, smoke: Smoke, gears: Gears, splats: Splats, bars: Bars, birds: Birds, petals: Petals,
  doodles: Doodles, stickman: Stickman, orbs: Orbs, cubes: Cubes, letterbox: Letterbox, flare: Flare, dust: Dust,
  particles: Particles, frame: Frame, bauhaus: Bauhaus, shine: Shine, grain: Grain,
};

export const Decor: React.FC<{ layers: Any[]; over?: boolean }> = ({ layers, over }) => (
  <>
    {layers.filter((d) => !!d.over === !!over).map((d, i) => {
      const C = DECOR[d.kind];
      return C ? <C key={i} d={d} /> : null;
    })}
  </>
);

export { mix };
