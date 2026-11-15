// New background / decoration kinds that came over with the «سبک‌های تازه از InstAI» port (docs/motion/looks-from-instai-fa.md).
//
// SOURCE: ported from InstAI:remotion/src/kit/Look.tsx @ 2f8aa90 (the "look" makers mosaic, ornament, waves, holo, doubleExp, miniLook (tilt-shift),
// stitch and kawaii), adapted for NMarketing: InstAI paints them over a family backdrop with a 6-role palette in pixels of the video;
// here each one is a background / decoration KIND of the style engine (a catalog row picks it and tunes it with parameters), written for NM's
// 1080-short-side unit `u`, its 8-colour palette (names like "accent" or literal colours) and its stop-motion clock (useQF).
//
// Rules every kind here follows (tests_looks.py checks what can be checked from the source):
//   - plain SVG / CSS, no pictures, no downloads, no fonts: a kind NEVER paints text (the scene text is the engine's);
//   - deterministic: the same frame always renders the same (R(seed) = Remotion's random, no Math.random / Date);
//   - quiet behind the text: the busy ones take the style's `veil` (Background draws it), and tiles / lines are pulled toward the base colour;
//   - cheap per frame: repeating art is an SVG <pattern> (one rect), not hundreds of nodes.
import React from "react";
import type { CSSProperties } from "react";
import { useCtx, useQF } from "./ctx";
import type { Any } from "./types";
import { R, col, mix, rgba, shade } from "./util";

type BgProps = { s: Any; v: number };
type DProps = { d: Any };

const Fill: React.FC<{ style?: CSSProperties; children?: React.ReactNode }> = ({ style, children }) => (
  <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, overflow: "hidden", ...style }}>{children}</div>
);

function useLook() {
  const c = useCtx();
  const f = useQF();
  return { ...c, f, t: f / c.fps, P: (n?: string, d?: string) => col(c.pal, n, d) };
}

const STAR = "M0,-1 L0.24,-0.24 L1,0 L0.24,0.24 L0,1 L-0.24,0.24 L-1,0 L-0.24,-0.24 Z";

// ───────────────────────────────────────────────────────────────────────────────────────────── backgrounds

/** تکه‌های موزاییک/کاشی با بندکشی (InstAI: mosaic). params: base, grout, colors[], size, gap, soft (0..1, how far a tile is pulled toward `base`), tilt (deg) */
const Mosaic: React.FC<BgProps> = ({ s, v }) => {
  const { P, W, H, u, t } = useLook();
  const cell = (s.size ?? 72) * u;
  const gap = (s.gap ?? 5) * u;
  const cols = Math.ceil(W / cell) + 1, rows = Math.ceil(H / cell) + 1;
  const base = P(s.base ?? "bg");
  const tones: string[] = (s.colors ?? ["accent", "accent2", "accent3", "bg2"]).map((c: string) => P(c));
  const soft = s.soft ?? 0.55;
  const tilt = s.tilt ?? 3;
  const tiles: React.ReactNode[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const tone = mix(tones[Math.floor(R(`mo${v}-${r}-${c}`) * tones.length) % tones.length], base, Math.min(0.92, soft + R(`ms${r}-${c}`) * 0.22));
      const glint = Math.sin(t * 0.9 + R(`mg${r}-${c}`) * 6.28) * 0.035;
      const x = c * cell, y = r * cell;
      tiles.push(
        <rect key={`${r}-${c}`} x={x + gap / 2} y={y + gap / 2} width={cell - gap} height={cell - gap} rx={3 * u} fill={shade(tone, glint)}
          transform={`rotate(${((R(`mr${r}-${c}`) - 0.5) * 2 * tilt).toFixed(2)} ${x + cell / 2} ${y + cell / 2})`} />,
      );
    }
  }
  const sweep = ((t * (s.sweep ?? 0.22)) % 1.6 - 0.3) * W * 1.4;
  return (
    <Fill style={{ background: P(s.grout ?? "ink") }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>{tiles}</svg>
      <Fill style={{ mixBlendMode: "overlay" }}>
        <div style={{ position: "absolute", top: "-10%", bottom: "-10%", left: sweep, width: W * 0.18, background: "linear-gradient(100deg, transparent, rgba(255,255,255,0.5), transparent)", transform: "skewX(-18deg)" }} />
      </Fill>
      <Fill style={{ background: `radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 45%, ${rgba(P(s.grout ?? "ink"), 0.4)} 100%)` }} />
    </Fill>
  );
};

const FLORET = (r: number): string => {
  // a six-petal flower as one path (petals are ellipses around the centre)
  const out: string[] = [];
  for (let k = 0; k < 6; k++) {
    const a = (k / 6) * Math.PI * 2;
    const cx = Math.cos(a) * r * 0.55, cy = Math.sin(a) * r * 0.55;
    out.push(`M${cx - r * 0.34},${cy} a${r * 0.34},${r * 0.34} 0 1,0 ${r * 0.68},0 a${r * 0.34},${r * 0.34} 0 1,0 ${-r * 0.68},0`);
  }
  return out.join(" ");
};

/** پنل آراسته (InstAI: ornament). mode "vine" = آرنوو: ساقه و برگ و گلِ پیچان کنارِ قاب؛ mode "frame" = صفحهٔ تذهیب‌شده: حاشیهٔ زرین با لوزی و ترنج‌های گوشه.
 *  params: base, line (قاب)، a (برگ/لاجورد)، b (گل/زر)، sway */
const Ornament: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, t } = useLook();
  const base = P(s.base ?? "bg");
  const line = P(s.line ?? "accent");
  const a = P(s.a ?? "accent2"), b = P(s.b ?? "accent3");
  const wide = W > H * 1.2;
  const layers: React.ReactNode[] = [];
  if ((s.mode ?? "vine") === "frame") {
    // illuminated page: a lapis band between two gold rules, gold diamonds along it, a medallion in every corner
    const m = 38 * u, bw = 46 * u;
    const band = (inset: number) => ({ x: inset, y: inset, w: W - inset * 2, h: H - inset * 2 });
    const o = band(m), i = band(m + bw);
    const diamonds: React.ReactNode[] = [];
    const step = 66 * u;
    for (let x = o.x + step; x < o.x + o.w - step * 0.5; x += step) {
      for (const y of [o.y + bw / 2, o.y + o.h - bw / 2]) diamonds.push(<path key={`h${x}-${y}`} d={`M${x},${y - 13 * u} l${11 * u},${13 * u} l${-11 * u},${13 * u} l${-11 * u},${-13 * u} z`} fill={b} />);
    }
    for (let y = o.y + step; y < o.y + o.h - step * 0.5; y += step) {
      for (const x of [o.x + bw / 2, o.x + o.w - bw / 2]) diamonds.push(<path key={`v${x}-${y}`} d={`M${x},${y - 13 * u} l${11 * u},${13 * u} l${-11 * u},${13 * u} l${-11 * u},${-13 * u} z`} fill={b} />);
    }
    const pulse = 0.82 + 0.18 * Math.sin(t * 1.3);
    const medal = ([x, y]: number[], k: number) => (
      <g key={k} transform={`translate(${x} ${y})`}>
        <circle r={bw * 0.95} fill={a} stroke={line} strokeWidth={5 * u} />
        <circle r={bw * 0.7} fill="none" stroke={b} strokeWidth={3 * u} />
        <path d={FLORET(bw * 0.62)} fill={b} opacity={0.9 * pulse} />
        <circle r={bw * 0.13} fill={line} />
      </g>
    );
    layers.push(
      <svg key="fr" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <rect x={o.x} y={o.y} width={o.w} height={o.h} fill={a} stroke={line} strokeWidth={6 * u} />
        <rect x={i.x} y={i.y} width={i.w} height={i.h} fill={base} stroke={line} strokeWidth={4 * u} />
        <rect x={i.x + 12 * u} y={i.y + 12 * u} width={i.w - 24 * u} height={i.h - 24 * u} fill="none" stroke={rgba(line, 0.55)} strokeWidth={2 * u} strokeDasharray={`${10 * u} ${9 * u}`} />
        {diamonds}
        {[[o.x, o.y], [o.x + o.w, o.y], [o.x, o.y + o.h], [o.x + o.w, o.y + o.h]].map(medal)}
      </svg>,
    );
  } else {
    // art-nouveau vines: two sinuous stems rise along the left and right edge, leaves alternate along them, a flower opens near the top
    const edge = (wide ? 0.07 : 0.09) * W;
    const amp = (wide ? 0.035 : 0.05) * W;
    const sway = (s.sway ?? 0.35) * t;
    const stem = (side: number, k: number) => {
      const pts: [number, number][] = [];
      const n = 40;
      for (let q = 0; q <= n; q++) {
        const y = H * (1.04 - (q / n) * 1.08);
        const x = (side ? W - edge : edge) + (side ? -1 : 1) * (Math.sin((q / n) * Math.PI * 3.2 + k + sway) * amp + (q / n) * amp * 0.6);
        pts.push([x, y]);
      }
      const d = pts.map((p, q) => `${q ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      const kids: React.ReactNode[] = [];
      for (let q = 3; q < n - 2; q += 3) {
        const [x, y] = pts[q];
        const dir = q % 6 === 0 ? 1 : -1;
        const ang = (dir * 38 + (side ? 180 : 0) + (R(`ov${side}${q}`) - 0.5) * 22) * (side ? -1 : 1);
        const ln = (60 + R(`ol${side}${q}`) * 36) * u;
        kids.push(
          <g key={`l${q}`} transform={`translate(${x} ${y}) rotate(${ang})`}>
            <path d={`M0,0 C${ln * 0.3},${-ln * 0.34} ${ln * 0.82},${-ln * 0.3} ${ln},0 C${ln * 0.82},${ln * 0.3} ${ln * 0.3},${ln * 0.34} 0,0 Z`} fill={a} opacity={0.9} />
            <path d={`M0,0 L${ln * 0.9},0`} stroke={rgba(base, 0.55)} strokeWidth={2 * u} />
          </g>,
        );
      }
      const top = pts[Math.round(n * 0.78)];
      kids.push(
        <g key="fl" transform={`translate(${top[0]} ${top[1]})`}>
          <path d={FLORET(34 * u)} fill={b} />
          <circle r={9 * u} fill={line} />
        </g>,
      );
      return (
        <g key={`${side}${k}`}>
          <path d={d} stroke={line} strokeWidth={6 * u} fill="none" strokeLinecap="round" />
          {kids}
        </g>
      );
    };
    const m = 30 * u;
    layers.push(
      <svg key="vn" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {stem(0, 0)}{stem(1, 2.4)}
        <rect x={m} y={m} width={W - m * 2} height={H - m * 2} rx={26 * u} fill="none" stroke={line} strokeWidth={4 * u} />
        <rect x={m * 1.55} y={m * 1.55} width={W - m * 3.1} height={H - m * 3.1} rx={18 * u} fill="none" stroke={rgba(line, 0.5)} strokeWidth={2 * u} />
      </svg>,
    );
  }
  return (
    <Fill style={{ background: `radial-gradient(ellipse at 50% 45%, ${shade(base, 0.1)} 0%, ${base} 60%, ${shade(base, -0.1)} 100%)` }}>
      {layers}
    </Fill>
  );
};

/** موج‌های هم‌پوشانِ سیگایها (InstAI: waves، چاپ چوب/لینولئوم). یک الگوی SVG که به‌آرامی می‌لغزد. params: base, colors[], line, size, op, speed, soft (0..1: چقدر به رنگِ زمینه نزدیک شود) */
const Waves: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, t, scene } = useLook();
  const pid = `nm-seigaiha-${scene.index}`;        // one id per scene: two scenes overlap during a transition and their patterns differ by the frame
  const r = (s.size ?? 64) * u;
  const base = P(s.base ?? "bg");
  const tones: string[] = (s.colors ?? ["accent2", "bg2", "accent"]).map((c: string) => P(c));
  const line = P(s.line ?? "ink");
  const circles: React.ReactNode[] = [];
  // rows every r/2 (top to bottom, so the lower row covers the lower half of the one above); odd rows are shifted by r
  for (let k = -2; k <= 4; k++) {
    const y = (k * r) / 2;
    const xs = k % 2 === 0 ? [0, 2 * r] : [-r, r, 3 * r];
    xs.forEach((x) => {
      // two alternating tones by row parity: the tile repeats every two rows, so a colour must not depend on a longer cycle
      const tone = mix(tones[(((k % 2) + 2) % 2) % tones.length], base, s.soft ?? 0.5);        // pulled toward the base colour: the text must stay readable on it
      circles.push(
        <g key={`${k}-${x}`}>
          <circle cx={x} cy={y} r={r} fill={tone} stroke={line} strokeWidth={2.2 * u} />
          {[0.76, 0.54, 0.32].map((q, i) => <circle key={i} cx={x} cy={y} r={r * q} fill={i % 2 ? tone : mix(tone, base, 0.35)} stroke={line} strokeWidth={2 * u} />)}
        </g>,
      );
    });
  }
  const dx = (t * (s.speed ?? 16) * u) % (2 * r);
  return (
    <Fill style={{ background: base }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ opacity: s.op ?? 0.85 }}>
        <defs>
          <pattern id={pid} width={2 * r} height={r * 1} patternUnits="userSpaceOnUse" patternTransform={`translate(${dx} ${H * 0.0}) `}>
            {circles}
          </pattern>
        </defs>
        <rect width={W} height={H} fill={`url(#${pid})`} />
      </svg>
      <Fill style={{ background: `linear-gradient(180deg, ${rgba(base, 0.94)} 0%, ${rgba(base, 0.6)} 42%, ${rgba(base, 0)} 100%)` }} />
    </Fill>
  );
};

/** فویلِ هولوگرافیک (InstAI: holo): رنگین‌کمانِ در حالِ چرخش + نوارِ درخشان + جرقه. params: base, stops[], angle, sparkles, op */
const Holo: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, t } = useLook();
  const base = P(s.base ?? "bg");
  const stops: string[] = (s.stops ?? ["accent", "accent2", "accent3", "paper"]).map((c: string) => P(c));
  const ang = (s.angle ?? 115) + Math.sin(t * 0.5) * 22;
  const ring = [...stops, stops[0]].map((c, i, arr) => `${rgba(c, 0.8)} ${Math.round((i / (arr.length - 1)) * 100)}%`).join(", ");
  const sweep = ((t * 0.28) % 1.7 - 0.35) * W * 1.5;
  const n = s.sparkles ?? 16;
  return (
    <Fill style={{ background: base }}>
      <Fill style={{ background: `linear-gradient(${ang}deg, ${ring})`, opacity: s.op ?? 0.55 }} />
      <Fill style={{ background: `conic-gradient(from ${t * 14}deg at 62% 42%, ${rgba(stops[0], 0.5)}, ${rgba(stops[1 % stops.length], 0.5)}, ${rgba(stops[2 % stops.length], 0.5)}, ${rgba(stops[0], 0.5)})`, mixBlendMode: "soft-light", opacity: 0.7 }} />
      <Fill style={{ backgroundImage: `repeating-linear-gradient(${ang + 90}deg, rgba(255,255,255,0.16) 0 ${2 * u}px, transparent ${2 * u}px ${18 * u}px)`, mixBlendMode: "overlay" }} />
      <Fill style={{ mixBlendMode: "screen" }}>
        <div style={{ position: "absolute", top: "-10%", bottom: "-10%", left: sweep, width: W * 0.2, background: "linear-gradient(100deg, transparent, rgba(255,255,255,0.7), transparent)", transform: "skewX(-20deg)" }} />
      </Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0 }}>
        {Array.from({ length: n }).map((_, i) => {
          const tw = Math.max(0, Math.sin(t * (1.1 + R(`hs${i}`) * 2) + i * 2));
          const sz = (12 + R(`hz${i}`) * 26) * u * (0.3 + tw * 0.7);
          return <path key={i} d={STAR} transform={`translate(${R(`hx${i}`) * W} ${R(`hy${i}`) * H}) scale(${sz})`} fill="#ffffff" opacity={0.25 + tw * 0.65} />;
        })}
      </svg>
    </Fill>
  );
};

/** نوردهیِ دوگانه (InstAI: doubleexp): دو «نوردهی» روی هم، هر کدام آرام در جهتِ مخالف. params: base, a (تپه‌ها)، b (خورشید/تنه‌ها)، blend */
const DoubleExp: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, t } = useLook();
  const base = P(s.base ?? "bg");
  const a = P(s.a ?? "accent"), b = P(s.b ?? "accent2");
  const hills = (seed: number, y0: number, amp: number, sh: number) => {
    const pts: string[] = [];
    for (let i = 0; i <= 40; i++) {
      const x = (i / 40) * W;
      const y = y0 + Math.sin((x / W) * 5.2 + seed + sh) * amp + Math.sin((x / W) * 11.3 + seed * 1.7 + sh * 1.4) * amp * 0.35;
      pts.push(`${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return `${pts.join(" ")} L${W},${H} L0,${H} Z`;
  };
  const sh = t * 0.18;
  const trunks = Array.from({ length: 11 }).map((_, i) => {
    const x = W * (0.06 + R(`dt${i}`) * 0.9) - Math.sin(t * 0.25) * 18 * u;
    const top = H * (0.12 + R(`dh${i}`) * 0.3);
    return <path key={i} d={`M${x},${H} L${x + Math.sin(i) * 12 * u},${top}`} stroke={b} strokeWidth={(5 + R(`dw${i}`) * 9) * u} strokeLinecap="round" />;
  });
  return (
    <Fill style={{ background: `linear-gradient(180deg, ${shade(base, 0.08)}, ${base} 70%, ${shade(base, -0.06)})` }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0, opacity: s.opA ?? 0.55 }}>
        <path d={hills(1.2, H * 0.62, H * 0.07, sh)} fill={a} opacity={0.55} />
        <path d={hills(3.4, H * 0.72, H * 0.06, -sh * 1.3)} fill={a} opacity={0.8} />
      </svg>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0, opacity: s.opB ?? 0.5, mixBlendMode: (s.blend ?? "multiply") as any }}>
        <circle cx={W * (0.64 + Math.sin(t * 0.2) * 0.03)} cy={H * 0.3} r={Math.min(W, H) * 0.3} fill={b} opacity={0.75} />
        {trunks}
      </svg>
      <Fill style={{ backgroundImage: `repeating-linear-gradient(0deg, ${rgba(P("paper"), 0.1)} 0 1px, transparent 1px ${14 * u}px)` }} />
    </Fill>
  );
};

/** مینیاتورِ تیلت‌شیفت (InstAI: tiltshift): شهرِ اسباب‌بازی که بالا و پایینش محو است. params: sky[2], ground, colors[], n, blur (px), band (0..1: ارتفاعِ نوارِ شفاف) */
const TiltShift: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, t } = useLook();
  const sky0 = P(s.sky?.[0] ?? "bg"), sky1 = P(s.sky?.[1] ?? "bg2");
  const ground = P(s.ground ?? "accent3");
  const tones: string[] = (s.colors ?? ["accent", "accent2", "accent3", "paper"]).map((c: string) => P(c));
  const roof = P(s.roof ?? "ink");
  const n = s.n ?? 14;
  const speed = (s.speed ?? 12) * u;
  const Town: React.FC = () => {
    const kids: React.ReactNode[] = [];
    // three rows of toy houses (far, middle, near): each row scrolls at its own speed (parallax) and wraps
    [0.52, 0.66, 0.84].forEach((y, row) => {
      const sc = 0.55 + row * 0.38;
      const period = W * 1.25;
      const off = ((t * speed * (row + 1)) % period);
      for (let i = 0; i < n; i++) {
        const w = (70 + R(`tw${row}${i}`) * 70) * u * sc, h = (60 + R(`th${row}${i}`) * 70) * u * sc;
        const x = ((R(`tx${row}${i}`) * period - off) % period + period) % period - W * 0.12;
        const yy = H * y;
        const tone = tones[Math.floor(R(`tc${row}${i}`) * tones.length) % tones.length];
        if (R(`tt${row}${i}`) > 0.72) {
          kids.push(<g key={`t${row}${i}`}><rect x={x + w * 0.45} y={yy - h * 0.3} width={w * 0.1} height={h * 0.3} fill={shade(ground, -0.45)} /><circle cx={x + w / 2} cy={yy - h * 0.55} r={w * 0.42} fill={mix(ground, "#2f7d3a", 0.55)} /></g>);
          continue;
        }
        kids.push(
          <g key={`h${row}${i}`}>
            <rect x={x} y={yy - h} width={w} height={h} fill={tone} />
            <rect x={x + w * 0.62} y={yy - h} width={w * 0.38} height={h} fill={shade(tone, -0.16)} />
            <polygon points={`${x - w * 0.08},${yy - h} ${x + w / 2},${yy - h - h * 0.45} ${x + w * 1.08},${yy - h}`} fill={roof} opacity={0.88} />
            <rect x={x + w * 0.16} y={yy - h * 0.62} width={w * 0.2} height={h * 0.26} fill={P("paper")} opacity={0.9} />
          </g>,
        );
      }
      kids.push(<rect key={`g${row}`} x={0} y={H * y} width={W} height={H * 0.045 * (row + 1)} fill={shade(ground, -0.08 * row)} />);
    });
    return (
      <>
        <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${sky0} 0%, ${sky1} 46%, ${mix(ground, sky1, 0.3)} 100%)` }} />
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0 }}>{kids}</svg>
      </>
    );
  };
  const band = Math.max(0.12, Math.min(0.6, s.band ?? 0.34));
  const edge = (1 - band) / 2 * 100;
  const blur = (s.blur ?? 11) * u;
  const top = `linear-gradient(to bottom, #000 0%, #000 ${edge * 0.55}%, transparent ${edge + 6}%)`;
  const bottom = `linear-gradient(to top, #000 0%, #000 ${edge * 0.55}%, transparent ${edge + 6}%)`;
  return (
    <Fill style={{ filter: `saturate(${s.saturate ?? 1.3}) contrast(1.04)` }}>
      <Fill><Town /></Fill>
      <Fill style={{ filter: `blur(${blur}px)`, WebkitMaskImage: top, maskImage: top }}><Town /></Fill>
      <Fill style={{ filter: `blur(${blur}px)`, WebkitMaskImage: bottom, maskImage: bottom }}><Town /></Fill>
      <Fill style={{ background: "radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 55%, rgba(0,0,0,0.28) 100%)" }} />
    </Fill>
  );
};

/** پارچهٔ گلدوزی‌شده (InstAI: stitch): تار و پود، نوارهای دوخت‌ضربدری و درزِ خط‌چین. params: base, thread, thread2, size */
const Cloth: React.FC<BgProps> = ({ s }) => {
  const { P, W, H, u, t, scene } = useLook();
  const sid = scene.index;
  const base = P(s.base ?? "bg");
  const t1 = P(s.thread ?? "accent"), t2 = P(s.thread2 ?? "accent2"), t3 = P(s.thread3 ?? "accent3");
  const wv = (s.weave ?? 9) * u;
  const x = (s.size ?? 18) * u;
  const bandH = (s.band ?? 0.085) * H;
  const cross = (c: string, id: string) => (
    <pattern id={id} width={x * 1.6} height={x * 1.6} patternUnits="userSpaceOnUse">
      <path d={`M${x * 0.3},${x * 0.3} L${x * 1.3},${x * 1.3} M${x * 1.3},${x * 0.3} L${x * 0.3},${x * 1.3}`} stroke={c} strokeWidth={x * 0.2} strokeLinecap="round" />
    </pattern>
  );
  const pulse = 0.88 + 0.12 * Math.sin(t * 1.4);
  const m = 42 * u;
  return (
    <Fill style={{ background: base }}>
      <Fill style={{ backgroundImage: `repeating-linear-gradient(0deg, ${rgba(P("ink"), 0.07)} 0 1px, transparent 1px ${wv}px), repeating-linear-gradient(90deg, ${rgba(P("ink"), 0.07)} 0 1px, transparent 1px ${wv}px)` }} />
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ position: "absolute", left: 0, top: 0 }}>
        <defs>{cross(t1, `nm-x1-${sid}`)}{cross(t2, `nm-x2-${sid}`)}{cross(t3, `nm-x3-${sid}`)}</defs>
        <rect x={m} y={m} width={W - m * 2} height={bandH} fill={`url(#nm-x1-${sid})`} opacity={pulse} />
        <rect x={m} y={m + bandH + 14 * u} width={W - m * 2} height={bandH * 0.5} fill={`url(#nm-x3-${sid})`} opacity={0.85} />
        <rect x={m} y={H - m - bandH} width={W - m * 2} height={bandH} fill={`url(#nm-x2-${sid})`} opacity={pulse} />
        <rect x={m} y={H - m - bandH * 1.5 - 14 * u} width={W - m * 2} height={bandH * 0.5} fill={`url(#nm-x3-${sid})`} opacity={0.85} />
        <rect x={m * 0.55} y={m * 0.55} width={W - m * 1.1} height={H - m * 1.1} rx={20 * u} fill="none" stroke={rgba(t1, 0.8)} strokeWidth={4 * u} strokeDasharray={`${14 * u} ${10 * u}`} strokeLinecap="round" />
      </svg>
    </Fill>
  );
};

export const LOOK_BG: { [k: string]: React.FC<BgProps> } = {
  mosaic: Mosaic, ornament: Ornament, waves: Waves, holo: Holo, doubleexp: DoubleExp, tiltshift: TiltShift, cloth: Cloth,
};

// ───────────────────────────────────────────────────────────────────────────────────────────── decoration

/** moves a floating decoration out of the middle of the frame (where the text sits) */
function avoid(x: number, y: number, W: number, H: number, on: boolean): [number, number] {
  if (!on) return [x, y];
  const dx = (x - W / 2) / (W / 2), dy = (y - H / 2) / (H / 2);
  const r = Math.hypot(dx / 0.88, dy / 0.5);
  if (r >= 1) return [x, y];
  const k = 1.12 / Math.max(r, 0.25);
  return [Math.max(0, Math.min(W, W / 2 + dx * k * (W / 2))), Math.max(0, Math.min(H, H / 2 + dy * k * (H / 2)))];
}

const HEART = "M0,0.9 C-1.1,0.1 -0.95,-0.85 -0.45,-0.85 C-0.15,-0.85 0,-0.62 0,-0.45 C0,-0.62 0.15,-0.85 0.45,-0.85 C0.95,-0.85 1.1,0.1 0,0.9 Z";

/** کاوایی (InstAI: kawaii): قلب، ستاره و ابرِ گونه‌صورتی که آرام بالا می‌روند. params: n, colors[], size, avoid */
const Kawaii: React.FC<DProps> = ({ d }) => {
  const { P, W, H, u, t } = useLook();
  const cols: string[] = (d.colors ?? ["accent", "accent2", "accent3", "paper"]).map((c: string) => P(c));
  const n = d.n ?? 14;
  const ink = P(d.ink ?? "ink");
  return (
    <Fill>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {Array.from({ length: n }).map((_, i) => {
          const sz = (34 + R(`kz${i}`) * 52) * u * (d.size ?? 1);
          const y0 = (R(`ky${i}`) * (H + sz * 2) - t * (16 + R(`kv${i}`) * 26) * u) % (H + sz * 2);
          const y = (y0 + (H + sz * 2)) % (H + sz * 2) - sz;
          const x0 = R(`kx${i}`) * W + Math.sin(t * (0.8 + R(`kw${i}`)) + i) * 18 * u;
          const [x, yy] = avoid(x0, y, W, H, d.avoid !== false);
          const c = cols[i % cols.length];
          const kind = i % 3;
          const rot = Math.sin(t * 1.1 + i) * 10;
          return (
            <g key={i} transform={`translate(${x} ${yy}) rotate(${rot})`} opacity={0.92}>
              {kind === 0 && <path d={HEART} transform={`scale(${sz * 0.62})`} fill={c} />}
              {kind === 1 && <path d={STAR} transform={`scale(${sz * 0.7})`} fill={c} />}
              {kind === 2 && (
                <g>
                  <path d={`M${-sz * 0.7},${sz * 0.3} a${sz * 0.32},${sz * 0.32} 0 0 1 ${sz * 0.1},${-sz * 0.5} a${sz * 0.42},${sz * 0.42} 0 0 1 ${sz * 0.78},${-sz * 0.12} a${sz * 0.34},${sz * 0.34} 0 0 1 ${sz * 0.52},${sz * 0.62} z`} fill={c} />
                  <circle cx={-sz * 0.2} cy={sz * 0.02} r={sz * 0.045} fill={ink} />
                  <circle cx={sz * 0.28} cy={sz * 0.02} r={sz * 0.045} fill={ink} />
                  <path d={`M${-sz * 0.02},${sz * 0.1} q${sz * 0.06},${sz * 0.08} ${sz * 0.12},0`} stroke={ink} strokeWidth={Math.max(2, sz * 0.04)} fill="none" strokeLinecap="round" />
                  <ellipse cx={-sz * 0.4} cy={sz * 0.12} rx={sz * 0.09} ry={sz * 0.055} fill={P("accent")} opacity={0.4} />
                  <ellipse cx={sz * 0.5} cy={sz * 0.12} rx={sz * 0.09} ry={sz * 0.055} fill={P("accent")} opacity={0.4} />
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </Fill>
  );
};

export const LOOK_DECOR: { [k: string]: React.FC<DProps> } = { kawaii: Kawaii };
