// Component library, part 1: DATA pieces - growing bar chart, drawing line chart, donut, counters, progress ring / bars, price card,
// comparison table, before/after split, rating, countdown. Every text is auto-fit (FT) and every layout sits inside the safe area.
import React from "react";
import { Img } from "remotion";
import { useAsset, useCtx, useQF } from "./ctx";
import type { Ctx } from "./ctx";
import { FT } from "./fit";
import { Icon, IconTile, Pop, Stage, Rule, accentAt, area, itemDelay, stagger, useGrow } from "./kit";
import { easeOf } from "./presets";
import { Card, T } from "./text";
import type { Scene } from "./types";
import { clamp, col, fmtNumber, onColor, rgba, toEnDigits } from "./util";

type SC = React.FC<{ sc: Scene }>;

/** area in px at 1080 */
const A = (ctx: Ctx) => {
  const a = area(ctx);
  return { w: a.w / ctx.u, h: a.h / ctx.u };
};
const num = (v: any): number => {
  const n = Number(toEnDigits(String(v ?? "0")).replace(/[,٬\s]/g, "").replace(/٫/g, ".").replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(n) ? n : 0;
};
const rows = <T2 = any,>(v: any, max: number): T2[] => (Array.isArray(v) ? (v.slice(0, max) as T2[]) : []);
const Title: React.FC<{ text?: string; w: number; max?: number }> = ({ text, w, max = 88 }) => (text ? <FT box={[w, 150]} max={max} min={40} maxLines={2} delay={0}>{String(text)}</FT> : null);

// ───────────────────────────────────────────── bar chart

const BarCol: React.FC<{ i: number; n: number; label: string; value: number; max: number; unit: string; colW: number; h: number; delay: number; show: boolean }> = ({ i, n, label, value, max, unit, colW, h, delay, show }) => {
  const ctx = useCtx();
  const { u, faDigits, fps } = ctx;
  const g = useGrow(delay, Math.round(fps * 1.1));
  const bh = Math.max(6 * u, (value / max) * h * clamp(g, 0, 1.08));
  const c = accentAt(ctx, i);
  return (
    <div style={{ width: colW * u, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: (h + 190) * u, gap: 10 * u }}>
      {show ? <T noAnim fixed role="label" size={44} fx="plain">{fmtNumber(value * clamp(g), faDigits, value % 1 ? 1 : 0) + (unit ? " " + unit : "")}</T> : null}
      <div style={{ width: colW * 0.62 * u, height: bh, background: c, borderRadius: `${14 * u}px ${14 * u}px ${4 * u}px ${4 * u}px`, boxShadow: `0 ${8 * u}px ${18 * u}px ${rgba(c, 0.35)}` }} />
      <FT box={[colW, 88]} max={42} min={24} maxLines={2} role="body" noAnim weight={700}>{label}</FT>
    </div>
  );
};

const HBar: React.FC<{ i: number; label: string; value: number; max: number; unit: string; w: number; delay: number; show: boolean }> = ({ i, label, value, max, unit, w, delay, show }) => {
  const ctx = useCtx();
  const { u, faDigits, fps, rtl } = ctx;
  const g = useGrow(delay, Math.round(fps * 1.1));
  const c = accentAt(ctx, i);
  const labelW = Math.min(360, w * 0.34);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 * u, width: "100%", direction: rtl ? "rtl" : "ltr" }}>
      <div style={{ width: labelW * u, flex: "none" }}><FT box={[labelW, 90]} max={44} min={26} maxLines={2} role="body" noAnim weight={700} align="start">{label}</FT></div>
      <div style={{ flex: 1, height: 52 * u, background: rgba(col(ctx.pal, "ink"), 0.1), borderRadius: 26 * u, overflow: "hidden" }}>
        <div style={{ width: `${(value / max) * 100 * clamp(g)}%`, height: "100%", background: c, borderRadius: 26 * u }} />
      </div>
      {show ? <div style={{ width: 170 * u, flex: "none" }}><T noAnim fixed role="label" size={42} fx="plain" align="start">{fmtNumber(value * clamp(g), faDigits, value % 1 ? 1 : 0) + (unit ? " " + unit : "")}</T></div> : null}
    </div>
  );
};

const BarChart: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps } = ctx;
  const a = A(ctx);
  const bars = rows<{ label: string; value: number }>(sc.bars, 6).map((b) => ({ label: String(b.label ?? ""), value: Math.max(0, num(b.value)) }));
  const max = Math.max(1, ...bars.map((b) => b.value)) * 1.08;
  const unit = String(sc.unit ?? "");
  const show = sc.show_values !== false;
  const horizontal = sc.horizontal === true || (sc.horizontal == null && (bars.length > 4 || Math.max(0, ...bars.map((b) => Array.from(b.label).length)) > 12));
  const st = stagger(ctx, 5);
  const cardW = a.w;
  return (
    <Stage gap={30}>
      <Title text={sc.title} w={a.w} />
      <Card pad={34} delay={4} style={{ width: cardW * u, display: "flex", flexDirection: horizontal ? "column" : "row", gap: (horizontal ? 24 : 18) * u, justifyContent: "space-around", alignItems: horizontal ? "stretch" : "flex-end", direction: ctx.rtl ? "rtl" : "ltr" }}>
        {bars.map((b, i) =>
          horizontal ? (
            <HBar key={i} i={i} label={b.label} value={b.value} max={max} unit={unit} w={cardW - 70} delay={itemDelay(ctx, i, bars.length, Math.round(fps * 0.5), st)} show={show} />
          ) : (
            <BarCol key={i} i={i} n={bars.length} label={b.label} value={b.value} max={max} unit={unit} colW={Math.min(230, (cardW - 70 - 18 * bars.length) / Math.max(1, bars.length))} h={Math.min(a.h * 0.42, 620)} delay={itemDelay(ctx, i, bars.length, Math.round(fps * 0.5), st)} show={show} />
          ),
        )}
      </Card>
      {sc.note ? <FT box={[a.w, 110]} max={44} min={26} maxLines={2} role="body" delay={Math.round(fps * 1.2)}>{String(sc.note)}</FT> : null}
    </Stage>
  );
};

// ───────────────────────────────────────────── line chart

const LineChart: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, rtl, faDigits } = ctx;
  const qf = useQF();
  const a = A(ctx);
  const pts = rows<{ label: string; value: number }>(sc.points, 8).map((p) => ({ label: String(p.label ?? ""), value: num(p.value) }));
  const unit = String(sc.unit ?? "");
  const w = a.w - 70, h = Math.min(a.h * 0.38, 560);
  const vals = pts.map((p) => p.value);
  const lo = Math.min(0, ...vals), hi = Math.max(1, ...vals) * 1.12;
  const px = (i: number) => (pts.length < 2 ? 0.5 : rtl ? 1 - i / (pts.length - 1) : i / (pts.length - 1)) * w;
  const py = (v: number) => h - ((v - lo) / (hi - lo || 1)) * h;
  const g = useGrow(Math.round(fps * 0.5), Math.round(fps * 1.6));
  const d = pts.map((p, i) => `${i ? "L" : "M"}${px(i).toFixed(1)} ${py(p.value).toFixed(1)}`).join(" ");
  const area2 = pts.length ? `${d} L${px(pts.length - 1).toFixed(1)} ${h} L${px(0).toFixed(1)} ${h} Z` : "";
  const c = col(ctx.pal, "accent");
  const pad = 22;
  return (
    <Stage gap={26}>
      <Title text={sc.title} w={a.w} />
      <Card pad={34} delay={4} style={{ width: a.w * u }}>
        <div style={{ position: "relative", width: w * u, height: (h + 190) * u, direction: "ltr" }}>
          <svg width={w * u} height={h * u} viewBox={`${-pad} ${-pad} ${w + pad * 2} ${h + pad * 2}`} style={{ overflow: "visible", position: "absolute", left: 0, top: 20 * u }}>
            <defs>
              <linearGradient id="nm-line-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={c} stopOpacity="0.35" /><stop offset="1" stopColor={c} stopOpacity="0" /></linearGradient>
              <clipPath id="nm-line-clip"><rect x={rtl ? w - w * clamp(g) : 0} y={-pad} width={w * clamp(g)} height={h + pad * 2} /></clipPath>
            </defs>
            {[0, 0.5, 1].map((t) => <line key={t} x1={0} x2={w} y1={h * t} y2={h * t} stroke={rgba(col(ctx.pal, "ink"), 0.12)} strokeWidth={3} />)}
            <g clipPath="url(#nm-line-clip)">
              <path d={area2} fill="url(#nm-line-fill)" />
              <path d={d} fill="none" stroke={c} strokeWidth={9} strokeLinecap="round" strokeLinejoin="round" />
            </g>
            {pts.map((p, i) => {
              const shown = clamp((clamp(g) * (pts.length - 1) - i) * 3 + 1);
              const x = px(i), y = py(p.value);
              return <circle key={i} cx={x} cy={y} r={13 * shown} fill={col(ctx.pal, "paper")} stroke={c} strokeWidth={7} />;
            })}
          </svg>
          {pts.map((p, i) => {
            const shown = clamp((clamp(g) * (pts.length - 1) - i) * 3 + 1);
            const last = i === pts.length - 1 || i === 0;
            return (
              <React.Fragment key={i}>
                <div style={{ position: "absolute", left: Math.max(0, Math.min(w - 180, px(i) - 90)) * u, top: Math.max(0, py(p.value) - 78) * u + 20 * u, width: 180 * u, textAlign: "center", opacity: last ? shown : 0 }}>
                  <T noAnim fixed role="label" size={40} fx="plain">{fmtNumber(p.value, faDigits, p.value % 1 ? 1 : 0) + (unit ? " " + unit : "")}</T>
                </div>
                <div style={{ position: "absolute", left: Math.max(0, Math.min(w - Math.min(190, w / Math.max(2, pts.length)), px(i) - Math.min(190, w / Math.max(2, pts.length)) / 2)) * u, top: (h + 70) * u, width: Math.min(190, w / Math.max(2, pts.length)) * u, display: "flex", justifyContent: "center", opacity: shown }}>
                  <FT box={[Math.min(190, w / Math.max(2, pts.length)), 90]} max={38} min={22} maxLines={2} role="body" noAnim weight={600}>{p.label}</FT>
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </Card>
      {sc.note ? <FT box={[a.w, 110]} max={44} min={26} maxLines={2} role="body" delay={Math.round(fps * 1.6)}>{String(sc.note)}</FT> : null}
    </Stage>
  );
};

// ───────────────────────────────────────────── donut / pie

const Donut: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, faDigits, rtl } = ctx;
  const a = A(ctx);
  const slices = rows<{ label: string; value: number }>(sc.slices, 5).map((s) => ({ label: String(s.label ?? ""), value: Math.max(0, num(s.value)) }));
  const total = Math.max(1e-9, slices.reduce((t, s) => t + s.value, 0));
  const size = Math.min(a.w * 0.8, a.h * 0.4, 640);
  const r = size * 0.38, sw = size * 0.2, C = 2 * Math.PI * r;
  const g = useGrow(Math.round(fps * 0.4), Math.round(fps * 1.5));
  let acc = 0;
  const wide = ctx.wide;
  return (
    <Stage gap={28} row={wide}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 24 * u }}>
        {!wide ? <Title text={sc.title} w={a.w} /> : null}
        <Pop delay={2}>
          <div style={{ position: "relative", width: size * u, height: size * u }}>
            <svg width={size * u} height={size * u} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
              <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={rgba(col(ctx.pal, "ink"), 0.1)} strokeWidth={sw} />
              {slices.map((s, i) => {
                const frac = s.value / total;
                const start = acc;
                acc += frac;
                const vis = clamp(clamp(g) * 1 - start) ;
                const len = Math.min(frac, vis) * C;
                return <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={accentAt(ctx, i)} strokeWidth={sw} strokeDasharray={`${Math.max(0, len - 3)} ${C}`} strokeDashoffset={-start * C} />;
              })}
            </svg>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column" }}>
              <FT box={[size * 0.5, size * 0.3]} max={size * 0.16} min={26} maxLines={2} noAnim fx="plain" role="display">{String(sc.center_label ?? "")}</FT>
            </div>
          </div>
        </Pop>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 * u, alignItems: "stretch", direction: rtl ? "rtl" : "ltr", width: wide ? "46%" : "100%" }}>
        {wide ? <Title text={sc.title} w={a.w * 0.46} max={72} /> : null}
        {slices.map((s, i) => (
          <Card key={i} i={i} delay={itemDelay(ctx, i, slices.length, Math.round(fps * 0.7), stagger(ctx))} pad={16} style={{ display: "flex", alignItems: "center", gap: 18 * u }}>
            <div style={{ width: 30 * u, height: 30 * u, borderRadius: 9 * u, background: accentAt(ctx, i), flex: "none" }} />
            <div style={{ flex: 1 }}><FT box={[wide ? a.w * 0.3 : a.w - 330, 80]} max={44} min={24} maxLines={2} role="body" noAnim weight={600} align="start">{s.label}</FT></div>
            <T noAnim fixed role="label" size={44} fx="plain">{fmtNumber((s.value / total) * 100, faDigits, 0) + "٪"}</T>
          </Card>
        ))}
      </div>
    </Stage>
  );
};

// ───────────────────────────────────────────── counters (count-up numbers with a unit)

const CounterItem: React.FC<{ value: number; decimals: number; unit: string; label: string; delay: number; big: number; w: number; i: number }> = ({ value, decimals, unit, label, delay, big, w, i }) => {
  const ctx = useCtx();
  const { u, fps, faDigits } = ctx;
  const g = useGrow(delay + 4, Math.round(fps * 1.5));
  const shown = fmtNumber(value * clamp(g), faDigits, decimals);
  return (
    <Pop delay={delay} i={i}>
      <div style={{ width: w * u, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 * u }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 12 * u, direction: "ltr" }}>
          <FT box={[w * 0.74, big * 1.25]} max={big} min={50} maxLines={1} noAnim>{shown}</FT>
          {unit ? <FT box={[w * 0.3, big * 0.5]} max={big * 0.42} min={30} maxLines={1} noAnim color="accent">{unit}</FT> : null}
        </div>
        <FT box={[w, 110]} max={46} min={26} maxLines={2} role="body" noAnim>{label}</FT>
      </div>
    </Pop>
  );
};

const Counter: SC = ({ sc }) => {
  const ctx = useCtx();
  const { fps, wide, u } = ctx;
  const a = A(ctx);
  const items = rows<{ value: any; unit?: string; label?: string; decimals?: number }>(sc.items, 3);
  const n = Math.max(1, items.length);
  const row = wide || n === 1 ? n : 1;
  const w = row > 1 ? Math.min(560, (a.w - 40 * (row - 1)) / row) : a.w;
  const big = n === 1 ? (wide ? 280 : 300) : row > 1 ? 190 : 200;
  return (
    <Stage gap={32}>
      {sc.kicker ? <T role="label" size={46} delay={0} color="accent" upper>{String(sc.kicker)}</T> : null}
      <div style={{ display: "flex", flexDirection: row > 1 ? (ctx.rtl ? "row-reverse" : "row") : "column", gap: 40 * u, alignItems: "center", justifyContent: "center" }}>
        {items.map((it, i) => (
          <CounterItem key={i} i={i} value={num(it.value)} decimals={Number(it.decimals ?? (String(it.value ?? "").match(/[.٫]/) ? 1 : 0))} unit={String(it.unit ?? "")} label={String(it.label ?? "")} delay={itemDelay(ctx, i, n, 4, stagger(ctx, 8))} big={big} w={w} />
        ))}
      </div>
      <Rule delay={Math.round(fps * 0.8)} w={200} />
      {sc.note ? <FT box={[a.w, 110]} max={48} min={26} maxLines={2} role="body" delay={Math.round(fps * 1.1)}>{String(sc.note)}</FT> : null}
    </Stage>
  );
};

// ───────────────────────────────────────────── progress ring

const ProgressRing: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, faDigits } = ctx;
  const a = A(ctx);
  const value = clamp(num(sc.value) / 100) * 100;
  const size = Math.min(a.w * 0.78, a.h * 0.44, 640);
  const r = size * 0.4, sw = size * 0.11, C = 2 * Math.PI * r;
  const g = useGrow(Math.round(fps * 0.4), Math.round(fps * 1.7));
  const c = col(ctx.pal, "accent");
  return (
    <Stage gap={30}>
      <Title text={sc.title} w={a.w} />
      <Pop delay={2}>
        <div style={{ position: "relative", width: size * u, height: size * u }}>
          <svg width={size * u} height={size * u} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={rgba(col(ctx.pal, "ink"), 0.12)} strokeWidth={sw} />
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={c} strokeWidth={sw} strokeLinecap="round" strokeDasharray={`${(value / 100) * C * clamp(g)} ${C}`} />
          </svg>
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", direction: "ltr" }}>
            <FT box={[size * 0.62, size * 0.4]} max={size * 0.3} min={40} maxLines={1} noAnim>{fmtNumber(value * clamp(g), faDigits, 0) + (sc.unit === undefined || sc.unit === "" ? "٪" : String(sc.unit))}</FT>
          </div>
        </div>
      </Pop>
      {sc.label ? <FT box={[a.w, 150]} max={56} min={28} maxLines={2} role="body" delay={Math.round(fps * 0.9)}>{String(sc.label)}</FT> : null}
    </Stage>
  );
};

// ───────────────────────────────────────────── progress bars

const ProgressBars: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, faDigits, rtl } = ctx;
  const a = A(ctx);
  const items = rows<{ label: string; value: number }>(sc.items, 5).map((x) => ({ label: String(x.label ?? ""), value: clamp(num(x.value) / 100) * 100 }));
  return (
    <Stage gap={28}>
      <Title text={sc.title} w={a.w} />
      <Card pad={34} delay={4} style={{ width: a.w * u, display: "flex", flexDirection: "column", gap: 34 * u, direction: rtl ? "rtl" : "ltr" }}>
        {items.map((it, i) => (
          <ProgressRow key={i} i={i} label={it.label} value={it.value} delay={itemDelay(ctx, i, items.length, Math.round(fps * 0.5), stagger(ctx, 8))} w={a.w - 70} faDigits={faDigits} />
        ))}
      </Card>
    </Stage>
  );
};
const ProgressRow: React.FC<{ i: number; label: string; value: number; delay: number; w: number; faDigits: boolean }> = ({ i, label, value, delay, w, faDigits }) => {
  const ctx = useCtx();
  const { u, fps } = ctx;
  const g = useGrow(delay, Math.round(fps * 1.2));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 * u }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 20 * u }}>
        <FT box={[w - 190, 70]} max={46} min={26} maxLines={1} role="body" noAnim weight={700} align="start">{label}</FT>
        <T noAnim fixed role="label" size={44} fx="plain">{fmtNumber(value * clamp(g), faDigits, 0) + "٪"}</T>
      </div>
      <div style={{ height: 34 * u, borderRadius: 17 * u, background: rgba(col(ctx.pal, "ink"), 0.12), overflow: "hidden" }}>
        <div style={{ width: `${value * clamp(g)}%`, height: "100%", borderRadius: 17 * u, background: accentAt(ctx, i) }} />
      </div>
    </div>
  );
};

// ───────────────────────────────────────────── price card

const PriceCard: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, pal, style, rtl } = ctx;
  const a = A(ctx);
  const feats = rows<string>(sc.features, 5).map(String);
  const w = Math.min(a.w, ctx.wide ? 900 : 940);
  const accent = col(pal, "accent");
  return (
    <Stage gap={26}>
      <Card pad={44} delay={0} enter="rise" style={{ width: w * u, display: "flex", flexDirection: "column", alignItems: "center", gap: 22 * u }}>
        {sc.badge ? (
          <div style={{ position: "absolute", top: -26 * u, [rtl ? "left" : "right"]: 28 * u, background: col(pal, "accent3"), padding: `${8 * u}px ${26 * u}px`, borderRadius: 60 * u, transform: "rotate(-4deg)", border: style.shape.border ? `${style.shape.border * 0.6 * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
            <T noAnim fixed role="label" size={40} color={onColor(col(pal, "accent3"))} fx="plain">{String(sc.badge)}</T>
          </div>
        ) : null}
        <FT box={[w - 90, 130]} max={74} min={36} maxLines={2} delay={4}>{String(sc.name ?? "")}</FT>
        <Pop delay={14}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 18 * u, direction: rtl ? "rtl" : "ltr", flexWrap: "wrap", justifyContent: "center" }}>
            <div style={{ background: accent, padding: `${8 * u}px ${34 * u}px`, borderRadius: Math.max(16, (style.shape.radius ?? 0) * 2) * u, border: style.shape.border ? `${style.shape.border * 0.7 * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
              <FT box={[w - 200, 150]} max={110} min={44} maxLines={1} noAnim color={onColor(accent)} fx="plain" weight={900}>{String(sc.price ?? "")}</FT>
            </div>
            {sc.unit ? <T noAnim fixed role="label" size={44} fx="plain">{String(sc.unit)}</T> : null}
          </div>
        </Pop>
        {sc.old_price ? <Pop delay={20}><div style={{ textDecoration: "line-through", opacity: 0.65 }}><T noAnim fixed role="body" size={48} fx="plain">{String(sc.old_price)}</T></div></Pop> : null}
        <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 14 * u, direction: rtl ? "rtl" : "ltr" }}>
          {feats.map((f, i) => (
            <Pop key={i} delay={itemDelay(ctx, i, feats.length, 26, stagger(ctx, 5))} i={i}>
              <div style={{ display: "flex", alignItems: "center", gap: 16 * u }}>
                <Icon name="circle-check" size={46} color={accent} />
                <div style={{ flex: 1 }}><FT box={[w - 180, 70]} max={42} min={24} maxLines={2} role="body" noAnim weight={600} align="start">{f}</FT></div>
              </div>
            </Pop>
          ))}
        </div>
        {sc.button ? (
          <Pop delay={Math.round(fps * 1.1)}>
            <div style={{ marginTop: 8 * u, background: accent, padding: `${16 * u}px ${56 * u}px`, borderRadius: Math.max(24, (style.shape.radius ?? 0) * 3) * u, border: style.shape.border ? `${style.shape.border * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
              <FT box={[w - 220, 100]} max={58} min={30} maxLines={1} noAnim color={onColor(accent)} fx="plain" weight={800}>{String(sc.button)}</FT>
            </div>
          </Pop>
        ) : null}
      </Card>
    </Stage>
  );
};

// ───────────────────────────────────────────── comparison table

const Mark: React.FC<{ v: string; size: number; color: string }> = ({ v, size, color }) => {
  const s = v.trim().toLowerCase();
  const yes = ["✓", "✔", "yes", "بله", "دارد", "true", "+"].includes(s);
  const no = ["✗", "✘", "✕", "no", "خیر", "ندارد", "false", "-", "–"].includes(s);
  if (yes) return <Icon name="circle-check" size={size} color={color} />;
  if (no) return <Icon name="circle-x" size={size} color={rgba(color, 0.55)} />;
  return null;
};

const ComparisonTable: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, pal, rtl } = ctx;
  const a = A(ctx);
  const cols = rows<string>(sc.columns, 3).map(String);
  const body = rows<{ label: string; values: any[] }>(sc.rows, 6);
  const hl = Math.max(0, Math.min(cols.length - 1, Number(sc.highlight ?? cols.length - 1)));
  const labelW = Math.min(a.w * 0.34, 340), cellW = (a.w - 60 - labelW) / Math.max(1, cols.length);
  const accent = col(pal, "accent");
  return (
    <Stage gap={26}>
      <Title text={sc.title} w={a.w} />
      <Card pad={26} delay={4} style={{ width: a.w * u, display: "flex", flexDirection: "column", gap: 12 * u, direction: rtl ? "rtl" : "ltr" }}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ width: labelW * u }} />
          {cols.map((c, i) => (
            <div key={i} style={{ width: cellW * u, display: "flex", justifyContent: "center", padding: `${10 * u}px 0`, background: i === hl ? rgba(accent, 0.22) : undefined, borderRadius: `${16 * u}px ${16 * u}px 0 0` }}>
              <FT box={[cellW - 12, 90]} max={44} min={24} maxLines={2} role="label" noAnim weight={800}>{c}</FT>
            </div>
          ))}
        </div>
        {body.map((r, ri) => (
          <Pop key={ri} delay={itemDelay(ctx, ri, body.length, Math.round(fps * 0.5), stagger(ctx, 6))} i={ri}>
            <div style={{ display: "flex", alignItems: "center", borderTop: `${2 * u}px solid ${rgba(col(pal, "ink"), 0.12)}` }}>
              <div style={{ width: labelW * u, padding: `${12 * u}px 0` }}><FT box={[labelW - 10, 100]} max={42} min={24} maxLines={2} role="body" noAnim weight={700} align="start">{String(r.label ?? "")}</FT></div>
              {cols.map((_, ci) => {
                const v = String((r.values || [])[ci] ?? "");
                return (
                  <div key={ci} style={{ width: cellW * u, display: "flex", justifyContent: "center", alignItems: "center", padding: `${12 * u}px 0`, background: ci === hl ? rgba(accent, 0.22) : undefined, minHeight: 84 * u }}>
                    <Mark v={v} size={54} color={ci === hl ? accent : col(pal, "ink")} />
                    {!["✓", "✔", "yes", "بله", "دارد", "true", "+", "✗", "✘", "✕", "no", "خیر", "ندارد", "false", "-", "–"].includes(v.trim().toLowerCase()) ? <FT box={[cellW - 12, 100]} max={40} min={22} maxLines={2} role="body" noAnim weight={600}>{v}</FT> : null}
                  </div>
                );
              })}
            </div>
          </Pop>
        ))}
      </Card>
    </Stage>
  );
};

// ───────────────────────────────────────────── before / after split

const BeforeAfter: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, pal, rtl, style } = ctx;
  const qf = useQF();
  const a = A(ctx);
  const bi = useAsset(sc.before_image), ai = useAsset(sc.after_image);
  const w = Math.min(a.w, ctx.wide ? a.h * 1.4 : a.w), h = Math.min(a.h * 0.58, ctx.wide ? a.h * 0.72 : 880);
  const t = easeOf("smooth")(clamp((qf - fps * 0.8) / (fps * 1.8)));
  const split = t * 100;
  const bl = String(sc.before_label ?? (rtl ? "قبل" : "Before")), al = String(sc.after_label ?? (rtl ? "بعد" : "After"));
  const accent = col(pal, "accent");
  const panel = (txt: string, img: string | null, bg: string, fg: string) => (
    <div data-nm-excl="before-after" style={{ position: "absolute", inset: 0, background: bg, display: "flex", alignItems: "center", justifyContent: "center", padding: `${60 * u}px`, boxSizing: "border-box" }}>
      {img ? <Img src={img} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} /> : null}
      {!img ? <FT box={[w - 200, h - 220]} max={92} min={34} maxLines={5} noAnim color={fg} fx="plain" weight={800}>{txt}</FT> : null}
    </div>
  );
  const clipStart = rtl ? `inset(0 0 0 ${100 - split}%)` : `inset(0 ${100 - split}% 0 0)`;     // the BEFORE panel is what the divider uncovers from the start edge
  return (
    <Stage gap={28}>
      <Title text={sc.title} w={a.w} max={80} />
      <Pop delay={4}>
        <div style={{ position: "relative", width: w * u, height: h * u, borderRadius: Math.max(18, style.shape.radius ?? 0) * u, overflow: "hidden", boxShadow: `0 ${20 * u}px ${44 * u}px rgba(0,0,0,0.3)` }}>
          {panel(String(sc.after ?? ""), ai, accent, onColor(accent))}
          <div style={{ position: "absolute", inset: 0, clipPath: clipStart }}>{panel(String(sc.before ?? ""), bi, col(pal, "paper"), col(pal, "ink"))}</div>
          <div style={{ position: "absolute", top: 0, bottom: 0, [rtl ? "right" : "left"]: `${split}%`, width: 8 * u, marginLeft: rtl ? 0 : -4 * u, marginRight: rtl ? -4 * u : 0, background: "#ffffff", boxShadow: "0 0 18px rgba(0,0,0,0.45)" }} />
          <div style={{ position: "absolute", top: 22 * u, [rtl ? "right" : "left"]: 22 * u, background: "rgba(0,0,0,0.6)", padding: `${6 * u}px ${22 * u}px`, borderRadius: 40 * u }}><T noAnim fixed role="label" size={40} color="#ffffff" fx="plain">{bl}</T></div>
          <div style={{ position: "absolute", top: 22 * u, [rtl ? "left" : "right"]: 22 * u, background: "#ffffff", padding: `${6 * u}px ${22 * u}px`, borderRadius: 40 * u }}><T noAnim fixed role="label" size={40} color="#111111" fx="plain">{al}</T></div>
        </div>
      </Pop>
    </Stage>
  );
};

// ───────────────────────────────────────────── rating (stars)

const Star: React.FC<{ fill: number; size: number; color: string }> = ({ fill, size, color }) => {
  const { u } = useCtx();
  const id = `nm-star-${Math.round(fill * 100)}-${size}`;
  const d = "M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6L2.5 9.4l6.6-.8z";
  return (
    <svg width={size * u} height={size * u} viewBox="0 0 24 24">
      <defs><clipPath id={id}><rect x="0" y="0" width={24 * clamp(fill)} height="24" /></clipPath></defs>
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" opacity="0.5" />
      <path d={d} fill={color} clipPath={`url(#${id})`} />
    </svg>
  );
};

const Rating: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, faDigits } = ctx;
  const a = A(ctx);
  const score = Math.max(0, Math.min(5, num(sc.score)));
  const g = useGrow(Math.round(fps * 0.4), Math.round(fps * 1.4));
  const gold = col(ctx.pal, "accent3");
  const size = Math.min(150, (a.w - 80) / 5);
  return (
    <Stage gap={26}>
      <Title text={sc.title} w={a.w} />
      <FT box={[a.w, 330]} max={250} min={90} maxLines={1} delay={2}>{fmtNumber(score * clamp(g), faDigits, score % 1 ? 1 : 0)}</FT>
      <div style={{ display: "flex", gap: 10 * u, direction: "ltr" }}>
        {[0, 1, 2, 3, 4].map((i) => <Star key={i} size={size} color={gold} fill={clamp(score * clamp(g) - i)} />)}
      </div>
      {sc.count_label ? <FT box={[a.w, 130]} max={52} min={28} maxLines={2} role="body" delay={Math.round(fps * 0.9)}>{String(sc.count_label)}</FT> : null}
    </Stage>
  );
};

// ───────────────────────────────────────────── countdown

const Countdown: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, faDigits, scene } = ctx;
  const qf = useQF();
  const a = A(ctx);
  const from = Math.max(1, Math.min(10, Math.round(num(sc.from) || 3)));
  const sec = qf / fps;
  const step = Math.min(from, Math.floor(sec / 1.0));
  const cur = from - step;
  const done = step >= from;
  const frac = sec - step;
  const size = Math.min(a.w * 0.7, a.h * 0.42, 620);
  const c = col(ctx.pal, "accent");
  const r = size * 0.44, C = 2 * Math.PI * r;
  const pop = 1 + Math.max(0, 0.18 - frac * 0.5);
  return (
    <Stage gap={30}>
      {sc.label ? <FT box={[a.w, 150]} max={70} min={34} maxLines={2} delay={0}>{String(sc.label)}</FT> : null}
      <div style={{ position: "relative", width: size * u, height: size * u }}>
        <svg width={size * u} height={size * u} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={rgba(col(ctx.pal, "ink"), 0.12)} strokeWidth={size * 0.06} />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={c} strokeWidth={size * 0.06} strokeLinecap="round" strokeDasharray={`${done ? C : (1 - frac) * C} ${C}`} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${pop})`, direction: "ltr" }}>
          {done && sc.finish_text ? <FT box={[size * 0.7, size * 0.5]} max={size * 0.2} min={30} maxLines={2} noAnim>{String(sc.finish_text)}</FT> : <FT box={[size * 0.6, size * 0.6]} max={size * 0.5} min={60} maxLines={1} noAnim>{fmtNumber(done ? 0 : cur, faDigits, 0)}</FT>}
        </div>
      </div>
      {scene.count < 0 ? null : null}
    </Stage>
  );
};

export const DATA_COMPONENTS: { [k: string]: SC } = {
  bar_chart: BarChart, line_chart: LineChart, donut: Donut, counter: Counter, progress_ring: ProgressRing, progress_bars: ProgressBars,
  price_card: PriceCard, comparison_table: ComparisonTable, before_after: BeforeAfter, rating: Rating, countdown: Countdown,
};
void IconTile;
