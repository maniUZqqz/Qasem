// Component library, part 2: TEXT and LAYOUT pieces - kinetic title, lower third, checklist, steps / timeline, icon grid, feature cards,
// testimonial, captions track (word highlight), sticker pop, social call-to-action, tags, ticker, image hero.
import React from "react";
import type { CSSProperties } from "react";
import { Img, interpolate } from "remotion";
import { fontStackOf, useAsset, useCtx, useQF } from "./ctx";
import type { Ctx } from "./ctx";
import { FT, prepText, textWidth, useFit } from "./fit";
import { Badge, EMOJI_NAMES, Emoji, Icon, ICON_NAMES, IconTile, PLATFORM_ICON, Pop, Stage, accentAt, area, itemDelay, stagger, useGrow } from "./kit";
import { Card, T } from "./text";
import type { Scene } from "./types";
import { BrandCharacterOverlay, BrandCharacterScene } from "./comp-brand";
import { clamp, col, onColor, rgba } from "./util";

type SC = React.FC<{ sc: Scene }>;
const A = (ctx: Ctx) => {
  const a = area(ctx);
  return { w: a.w / ctx.u, h: a.h / ctx.u };
};
const rows = <T2 = any,>(v: any, max: number): T2[] => (Array.isArray(v) ? (v.slice(0, max) as T2[]) : []);
const Title: React.FC<{ text?: string; w: number; max?: number }> = ({ text, w, max = 88 }) => (text ? <FT box={[w, 150]} max={max} min={40} maxLines={2} delay={0}>{String(text)}</FT> : null);
const iconOf = (name: any, fallback = "sparkles") => (ICON_NAMES.includes(String(name)) ? String(name) : fallback);

// ───────────────────────────────────────────── kinetic title (word by word - never letter by letter in Persian)

const KineticTitle: SC = ({ sc }) => {
  const ctx = useCtx();
  const { fps, wide } = ctx;
  const a = A(ctx);
  const text = String(sc.text ?? sc.title ?? "");
  const words = text.split(/\s+/).filter(Boolean);
  const cues = ctx.cues;
  // with word timings: the i-th word appears when it is spoken (cues of the SAME words), else the words are spread over the first 60 % of the speech / a steady stagger
  let delays: number[];
  if (cues.length && Math.abs(cues.length - words.length) <= Math.max(1, Math.round(words.length * 0.25))) {
    delays = words.map((_, i) => Math.max(0, Math.round((cues[Math.min(cues.length - 1, Math.round((i * (cues.length - 1)) / Math.max(1, words.length - 1)))].s - 0.08) * fps)));
  } else {
    const start = cues.length ? Math.max(0, Math.round((cues[0].s - 0.1) * fps)) : 3;
    const span = cues.length ? Math.max(1, (cues[cues.length - 1].e - cues[0].s) * fps * 0.9) : Math.max(1, words.length) * Math.max(6, stagger(ctx, 6));
    delays = words.map((_, i) => start + Math.round((i * span) / Math.max(1, words.length)));
  }
  return (
    <Stage gap={34}>
      {sc.kicker ? <T role="label" size={46} delay={0} color="accent" upper>{String(sc.kicker)}</T> : null}
      <FT box={[a.w, a.h * (wide ? 0.7 : 0.55)]} max={wide ? 170 : 190} min={52} maxLines={6} wordDelays={delays} lh={1.25}>{text}</FT>
    </Stage>
  );
};

// ───────────────────────────────────────────── lower third

const LowerThird: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, pal, rtl, style, fps } = ctx;
  const qf = useQF();
  const a = A(ctx);
  const accent = col(pal, "accent");
  const w = Math.min(a.w, ctx.wide ? 900 : 860);
  const t = clamp(qf / (fps * 0.5));
  const slide = (1 - Math.pow(t, 0.6)) * 120 * u * (rtl ? 1 : -1);
  const bg = style.shape.fill === "glass" ? "rgba(0,0,0,0.55)" : col(pal, style.shape.fill ?? "paper");
  const fg = onColor(bg);
  return (
    <div style={{ width: w * u, display: "flex", direction: rtl ? "rtl" : "ltr", transform: `translateX(${slide}px)`, opacity: t, filter: "drop-shadow(0 8px 18px rgba(0,0,0,0.3))" }} data-nm="box">
      <div style={{ width: 16 * u, background: accent, borderRadius: `${8 * u}px 0 0 ${8 * u}px`, flex: "none" }} />
      <div style={{ flex: 1, background: bg, padding: `${18 * u}px ${30 * u}px`, borderRadius: `0 ${Math.min(24, style.shape.radius ?? 12) * u}px ${Math.min(24, style.shape.radius ?? 12) * u}px 0`, display: "flex", flexDirection: "column", gap: 4 * u }}>
        <FT box={[w - 110, 90]} max={58} min={30} maxLines={1} noAnim color={fg} fx="plain" align="start" weight={800}>{String(sc.name ?? "")}</FT>
        {sc.role ? <FT box={[w - 110, 70]} max={38} min={24} maxLines={1} role="label" noAnim color={fg} fx="plain" align="start">{String(sc.role)}</FT> : null}
      </div>
    </div>
  );
};

// ───────────────────────────────────────────── checklist

const Tick: React.FC<{ progress: number; size: number; color: string }> = ({ progress, size, color }) => {
  const { u } = useCtx();
  const len = 26;
  return (
    <svg width={size * u} height={size * u} viewBox="0 0 24 24" style={{ flex: "none" }}>
      <circle cx="12" cy="12" r="10.2" fill={rgba(color, 0.16 + 0.84 * clamp(progress * 2))} stroke={color} strokeWidth="1.6" />
      <path d="M7 12.6l3.2 3.2L17 8.8" fill="none" stroke={onColor(color)} strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={len} strokeDashoffset={len * (1 - clamp(progress * 1.6 - 0.2))} />
    </svg>
  );
};
const CheckRow: React.FC<{ i: number; text: string; delay: number; w: number }> = ({ i, text, delay, w }) => {
  const ctx = useCtx();
  const { u, fps } = ctx;
  const g = useGrow(delay + 4, Math.round(fps * 0.5));
  return (
    <Pop delay={delay} i={i}>
      <div style={{ display: "flex", alignItems: "center", gap: 22 * u, direction: ctx.rtl ? "rtl" : "ltr" }}>
        <Tick progress={g} size={70} color={accentAt(ctx, 0)} />
        <div style={{ flex: 1 }}><FT box={[w - 130, 120]} max={52} min={26} maxLines={2} role="body" noAnim weight={600} align="start">{text}</FT></div>
      </div>
    </Pop>
  );
};
const Checklist: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps } = ctx;
  const a = A(ctx);
  const items = rows<string>(sc.items, 6).map(String);
  const per = Math.min(125, (a.h - 330) / Math.max(1, items.length));
  return (
    <Stage gap={28}>
      <Title text={sc.title} w={a.w} />
      <Card pad={34} delay={3} style={{ width: a.w * u, display: "flex", flexDirection: "column", gap: Math.max(18, per * 0.3) * u }}>
        {items.map((it, i) => <CheckRow key={i} i={i} text={it} delay={itemDelay(ctx, i, items.length, Math.round(fps * 0.45), stagger(ctx, 9))} w={a.w - 68} />)}
      </Card>
    </Stage>
  );
};

// ───────────────────────────────────────────── steps / timeline

const Steps: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, rtl, wide, pal } = ctx;
  const a = A(ctx);
  const steps = rows<{ title: string; text?: string }>(sc.steps, 5).map((s) => (typeof s === "string" ? { title: s } : { title: String((s as any).title ?? ""), text: (s as any).text ? String((s as any).text) : "" }));
  const n = Math.max(1, steps.length);
  const horizontal = sc.layout === "horizontal" || (sc.layout == null && wide);
  const g = useGrow(Math.round(fps * 0.3), Math.round(fps * (0.6 + 0.5 * n)));
  const accent = col(pal, "accent");
  const colW = horizontal ? (a.w - 30 * (n - 1)) / n : a.w;
  return (
    <Stage gap={28}>
      <Title text={sc.title} w={a.w} />
      <div style={{ position: "relative", width: a.w * u, display: "flex", flexDirection: horizontal ? (rtl ? "row-reverse" : "row") : "column", gap: (horizontal ? 30 : 26) * u, direction: rtl ? "rtl" : "ltr" }}>
        {!horizontal ? (
          <div style={{ position: "absolute", top: 40 * u, bottom: 40 * u, [rtl ? "right" : "left"]: 38 * u, width: 8 * u, background: rgba(col(pal, "ink"), 0.14), borderRadius: 4 * u }}>
            <div style={{ width: "100%", height: `${clamp(g) * 100}%`, background: accent, borderRadius: 4 * u }} />
          </div>
        ) : (
          <div style={{ position: "absolute", top: 38 * u, left: 40 * u, right: 40 * u, height: 8 * u, background: rgba(col(pal, "ink"), 0.14), borderRadius: 4 * u }}>
            <div style={{ height: "100%", width: `${clamp(g) * 100}%`, background: accent, borderRadius: 4 * u, [rtl ? "marginLeft" : "marginRight"]: "auto", float: rtl ? "right" : "left" }} />
          </div>
        )}
        {steps.map((s, i) => (
          <Pop key={i} delay={itemDelay(ctx, i, n, Math.round(fps * 0.4), stagger(ctx, 10))} i={i}>
            <div style={{ width: horizontal ? colW * u : undefined, display: "flex", flexDirection: horizontal ? "column" : "row", alignItems: horizontal ? "center" : "flex-start", gap: 22 * u, position: "relative" }}>
              <Badge n={String(i + 1)} size={80} />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 * u, alignItems: horizontal ? "center" : "stretch", flex: 1, paddingTop: horizontal ? 0 : 4 * u }}>
                <FT box={[horizontal ? colW : a.w - 130, 110]} max={horizontal ? 46 : 54} min={26} maxLines={2} role="body" noAnim weight={800} align={horizontal ? "center" : "start"}>{s.title}</FT>
                {s.text ? <FT box={[horizontal ? colW : a.w - 130, 130]} max={38} min={22} maxLines={3} role="body" noAnim align={horizontal ? "center" : "start"}>{s.text}</FT> : null}
              </div>
            </div>
          </Pop>
        ))}
      </div>
    </Stage>
  );
};

// ───────────────────────────────────────────── icon grid + feature cards

const IconGrid: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, wide, rtl } = ctx;
  const a = A(ctx);
  const items = rows<{ icon?: string; label: string }>(sc.items, 6).map((x) => ({ icon: iconOf(x.icon, "sparkles"), label: String(x.label ?? "") }));
  const n = Math.max(1, items.length);
  const colsN = wide ? Math.min(n, 3) : n <= 2 ? n : n === 4 ? 2 : 3;
  const cellW = (a.w - 30 * (colsN - 1)) / colsN;
  const tile = Math.min(150, cellW * 0.52);
  return (
    <Stage gap={34}>
      <Title text={sc.title} w={a.w} />
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${colsN}, ${cellW * u}px)`, gap: `${46 * u}px ${30 * u}px`, direction: rtl ? "rtl" : "ltr" }}>
        {items.map((it, i) => (
          <Pop key={i} delay={itemDelay(ctx, i, n, Math.round(fps * 0.3), stagger(ctx, 6))} i={i}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 18 * u }}>
              <IconTile name={it.icon} size={tile} fill={accentAt(ctx, i)} />
              <FT box={[cellW, 110]} max={44} min={24} maxLines={2} role="body" noAnim weight={700}>{it.label}</FT>
            </div>
          </Pop>
        ))}
      </div>
    </Stage>
  );
};

const FeatureCards: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, rtl, wide } = ctx;
  const a = A(ctx);
  const cards = rows<{ icon?: string; title: string; text?: string }>(sc.cards, 4).map((c) => ({ icon: iconOf(c.icon, "sparkles"), title: String(c.title ?? ""), text: c.text ? String(c.text) : "" }));
  const n = Math.max(1, cards.length);
  const row = wide && n > 1;
  const cw = row ? (a.w - 28 * (n - 1)) / n : a.w;
  const per = row ? a.h * 0.55 : Math.min(300, (a.h - 330) / n);
  return (
    <Stage gap={26}>
      <Title text={sc.title} w={a.w} />
      <div style={{ display: "flex", flexDirection: row ? (rtl ? "row-reverse" : "row") : "column", gap: 24 * u, width: a.w * u, direction: rtl ? "rtl" : "ltr" }}>
        {cards.map((c, i) => (
          <Card key={i} i={i} delay={itemDelay(ctx, i, n, Math.round(fps * 0.3), stagger(ctx, 8))} pad={24} style={{ width: cw * u, height: per * u, display: "flex", flexDirection: row ? "column" : "row", alignItems: row ? "center" : "center", gap: 24 * u, boxSizing: "border-box" }}>
            <IconTile name={c.icon} size={row ? 120 : Math.min(130, per - 60)} fill={accentAt(ctx, i)} />
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 * u, alignItems: row ? "center" : "stretch", minWidth: 0 }}>
              <FT box={[row ? cw - 40 : cw - 220, 90]} max={row ? 46 : 52} min={24} maxLines={2} role="body" noAnim weight={800} align={row ? "center" : "start"}>{c.title}</FT>
              {c.text ? <FT box={[row ? cw - 40 : cw - 220, per - 150]} max={38} min={20} maxLines={3} role="body" noAnim align={row ? "center" : "start"}>{c.text}</FT> : null}
            </div>
          </Card>
        ))}
      </div>
    </Stage>
  );
};

// ───────────────────────────────────────────── testimonial

const Testimonial: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, rtl, pal } = ctx;
  const a = A(ctx);
  const img = useAsset(sc.image);
  const name = String(sc.name ?? "");
  const letter = Array.from(name.trim())[0] || "★";
  const accent = col(pal, "accent");
  const stars = Math.max(0, Math.min(5, Math.round(Number(sc.rating) || 0)));
  return (
    <Stage gap={26}>
      <Card pad={44} delay={0} enter="rise" style={{ width: a.w * u, display: "flex", flexDirection: "column", alignItems: "center", gap: 24 * u }}>
        <T noAnim fixed size={200} color="accent" fx="plain" style={{ lineHeight: 0.6, height: 100 * u }}>{"“"}</T>
        <FT box={[a.w - 100, Math.min(a.h * 0.42, 620)]} max={74} min={32} maxLines={9} role="body" lh={1.5} delay={6} weight={600}>{String(sc.quote ?? "")}</FT>
        {stars ? <div style={{ display: "flex", gap: 8 * u }}>{Array.from({ length: stars }).map((_, i) => <Icon key={i} name="star" size={54} color={col(pal, "accent3")} style={{ fill: col(pal, "accent3") }} />)}</div> : null}
        <Pop delay={Math.round(fps * 0.9)}>
          <div style={{ display: "flex", alignItems: "center", gap: 22 * u, direction: rtl ? "rtl" : "ltr" }}>
            <div style={{ width: 96 * u, height: 96 * u, borderRadius: "50%", background: accent, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", flex: "none" }}>
              {img ? <Img src={img} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <T noAnim fixed size={52} color={onColor(accent)} fx="plain">{letter}</T>}
            </div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
              <FT box={[a.w - 260, 80]} max={48} min={26} maxLines={1} noAnim role="body" weight={800} align="start">{name}</FT>
              {sc.role ? <FT box={[a.w - 260, 60]} max={36} min={22} maxLines={1} noAnim role="label" fx="plain" align="start">{String(sc.role)}</FT> : null}
            </div>
          </div>
        </Pop>
      </Card>
    </Stage>
  );
};

// ───────────────────────────────────────────── captions track with word highlight

type CapWord = { w: string; s: number; e: number };
function capPages(words: CapWord[], maxChars: number): CapWord[][] {
  const pages: CapWord[][] = [];
  let cur: CapWord[] = [], len = 0;
  for (const w of words) {
    const l = Array.from(w.w).length + 1;
    if (cur.length && (len + l > maxChars || cur.length >= 6 || /[.!؟?؛]$/.test(cur[cur.length - 1].w))) {
      pages.push(cur);
      cur = [];
      len = 0;
    }
    cur.push(w);
    len += l;
  }
  if (cur.length) pages.push(cur);
  return pages;
}

export const CaptionsLine: React.FC<{ words: CapWord[]; maxChars?: number; size?: number; width?: number }> = ({ words, maxChars = 26, size = 62, width }) => {
  const ctx = useCtx();
  const { u, fps, pal, rtl, style } = ctx;
  const qf = useQF();
  const a = A(ctx);
  const t = qf / fps;
  const pages = capPages(words, maxChars);
  const page = pages.find((p) => t >= p[0].s - 0.05 && t < p[p.length - 1].e + 0.25) ?? (t > words[words.length - 1]?.e ? undefined : undefined);
  if (!page) return null;
  const box = Math.min(width ?? a.w, a.w);
  const accent = col(pal, "accent");
  const hi = readable(accent, "#000000");
  return (
    <div data-nm="text" data-nm-role="caption" data-nm-size={size * u} style={{ maxWidth: box * u, display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `${6 * u}px ${14 * u}px`, direction: rtl ? "rtl" : "ltr", padding: `${12 * u}px ${24 * u}px`, background: "rgba(0,0,0,0.58)", borderRadius: Math.max(18, style.shape.radius ?? 0) * u, backdropFilter: "blur(2px)" }}>
      {page.map((w, i) => {
        const active = t >= w.s && t < w.e + 0.04;
        const past = t >= w.e;
        return (
          <span key={i} style={{ fontFamily: fontStackOf(ctx), fontWeight: 800, fontSize: size * u, lineHeight: 1.45, color: active ? hi : "#ffffff", opacity: past || active ? 1 : 0.62, background: active ? accent : "transparent", borderRadius: 14 * u, padding: `0 ${10 * u}px`, transform: active ? "scale(1.06)" : "none", display: "inline-block", whiteSpace: "nowrap" }}>{prepText(ctx, w.w)}</span>
        );
      })}
    </div>
  );
};
function readable(bg: string, dark: string): string {
  return onColor(bg, "#ffffff", dark);
}

const Captions: SC = ({ sc }) => {
  const ctx = useCtx();
  const { fps } = ctx;
  const text = String(sc.text ?? "");
  let words: CapWord[] = ctx.cues.map((c) => ({ w: c.w, s: c.s, e: c.e }));
  if (!words.length && text) {
    const ws = text.split(/\s+/).filter(Boolean);
    const per = Math.max(0.28, (ctx.scene.frames / fps - 0.8) / Math.max(1, ws.length));
    words = ws.map((w, i) => ({ w, s: 0.3 + i * per, e: 0.3 + (i + 1) * per }));
  }
  if (!words.length) return null;
  return <CaptionsLine words={words} size={sc.size ? Number(sc.size) : 62} />;
};
const CaptionsScene: SC = ({ sc }) => (
  <Stage justify="center">
    {sc.title ? <FT box={[760, 130]} max={64} min={32} maxLines={2} role="label" delay={0}>{String(sc.title)}</FT> : null}
    <Captions sc={sc} />
  </Stage>
);

// ───────────────────────────────────────────── sticker pop (original SVG badges + Lucide icons)

const Sticker: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, pal, fps } = ctx;
  const qf = useQF();
  const kind = String(sc.kind ?? "burst");
  const icon = iconOf(sc.icon, "sparkles");
  const emoji = EMOJI_NAMES.includes(String(sc.emoji ?? "")) ? String(sc.emoji) : "";
  const c = sc.color === "accent2" ? col(pal, "accent2") : sc.color === "accent3" ? col(pal, "accent3") : col(pal, "accent");
  const t = clamp(qf / (fps * 0.45));
  const s = 1 + Math.sin(t * Math.PI * 2.6) * 0.14 * (1 - t);
  const wob = Math.sin((qf / fps) * 3) * 4;
  const size = 230;
  const pts = Array.from({ length: 24 }).map((_, i) => {
    const ang = (i / 24) * Math.PI * 2, r = i % 2 ? 0.74 : 1;
    return `${50 + Math.cos(ang) * 50 * r},${50 + Math.sin(ang) * 50 * r}`;
  }).join(" ");
  // «emoji» kind: the picture alone pops in (bouncing), with the short text under it when there is one
  const bare = kind === "emoji" && !!emoji;
  return (
    <div data-nm="box" style={{ width: size * u, height: size * u, transform: `scale(${Math.max(0.01, t < 1 ? s * t : 1)}) rotate(${wob - (bare ? 4 : 8)}deg)`, position: "relative", filter: "drop-shadow(0 8px 14px rgba(0,0,0,0.3))" }}>
      {bare ? null : (
        <svg width={size * u} height={size * u} viewBox="0 0 100 100" style={{ position: "absolute", inset: 0 }}>
          {kind === "circle" ? <circle cx="50" cy="50" r="48" fill={c} /> : kind === "tag" ? <rect x="4" y="14" width="92" height="72" rx="20" fill={c} /> : <polygon points={pts} fill={c} />}
        </svg>
      )}
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2 * u }}>
        {emoji ? <Emoji name={emoji} size={bare ? size * 0.86 : sc.text ? size * 0.4 : size * 0.58} /> : null}
        {sc.text && (!emoji || !bare) ? <FT box={[size * 0.64, size * 0.42]} max={50} min={22} maxLines={2} noAnim color={onColor(c)} fx="plain" weight={900}>{String(sc.text)}</FT> : emoji ? null : <Icon name={icon} size={size * 0.46} color={onColor(c)} />}
      </div>
    </div>
  );
};

// ───────────────────────────────────────────── social call-to-action (handle + button)

const SocialCta: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, pal, fps, rtl, style } = ctx;
  const a = A(ctx);
  const accent = col(pal, "accent");
  const plat = String(sc.platform ?? "instagram");
  const handle = String(sc.handle ?? "");
  const w = Math.min(a.w, ctx.wide ? 1000 : 940);
  return (
    <Stage gap={30}>
      {sc.title ? <FT box={[a.w, 220]} max={104} min={44} maxLines={3} delay={0}>{String(sc.title)}</FT> : null}
      <Pop delay={10}>
        <Card pad={26} style={{ width: w * u, display: "flex", alignItems: "center", gap: 26 * u, direction: rtl ? "rtl" : "ltr", boxSizing: "border-box" }}>
          <IconTile name={PLATFORM_ICON[plat] ?? "at-sign"} size={104} fill={accent} />
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", alignItems: "stretch", gap: 4 * u }}>
            <div style={{ direction: "ltr", textAlign: rtl ? "right" : "left" }}><FT box={[w - 190, 100]} max={64} min={28} maxLines={1} role="body" noAnim weight={800} align={rtl ? "end" : "start"}>{handle}</FT></div>
            {sc.note ? <FT box={[w - 190, 70]} max={38} min={22} maxLines={1} role="label" noAnim fx="plain" align="start">{String(sc.note)}</FT> : null}
          </div>
        </Card>
      </Pop>
      {sc.button ? (
        <Pop delay={Math.round(fps * 0.8)}>
          <div style={{ background: accent, padding: `${20 * u}px ${70 * u}px`, borderRadius: Math.max(24, (style.shape.radius ?? 0) * 3) * u, border: style.shape.border ? `${style.shape.border * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined, boxShadow: style.shape.shadow === "hard" ? `${9 * u}px ${9 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : `0 ${14 * u}px ${34 * u}px rgba(0,0,0,0.3)` }}>
            <FT box={[w - 140, 110]} max={62} min={30} maxLines={1} noAnim color={onColor(accent)} fx="plain" weight={800}>{String(sc.button)}</FT>
          </div>
        </Pop>
      ) : null}
    </Stage>
  );
};

// ───────────────────────────────────────────── tags (hashtag chips)

const Tags: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, fps, rtl } = ctx;
  const a = A(ctx);
  const tags = rows<string>(sc.tags, 10).map(String);
  return (
    <Stage gap={34}>
      <Title text={sc.title} w={a.w} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 * u, justifyContent: "center", direction: rtl ? "rtl" : "ltr", width: a.w * u }}>
        {tags.map((t, i) => {
          const c = accentAt(ctx, i);
          return (
            <Pop key={i} delay={itemDelay(ctx, i, tags.length, 4, stagger(ctx, 5))} i={i}>
              <div style={{ background: rgba(c, 0.18), border: `${3 * u}px solid ${c}`, padding: `${10 * u}px ${34 * u}px`, borderRadius: 60 * u }}>
                <FT box={[a.w - 120, 90]} max={50} min={26} maxLines={1} role="body" noAnim weight={700}>{t}</FT>
              </div>
            </Pop>
          );
        })}
      </div>
    </Stage>
  );
};

// ───────────────────────────────────────────── ticker (marquee band)

const Ticker: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, W, pal, fps, rtl } = ctx;
  const qf = useQF();
  const text = prepText(ctx, String(sc.text ?? "")) + "   ✦   ";
  const size = 54 * u;
  const font = `800 ${size}px ${fontStackOf(ctx)}`;
  const one = Math.max(120 * u, textWidth(text, font, rtl)) ;
  const speed = (Number(sc.speed) || 1) * 160 * u;
  const off = ((qf / fps) * speed) % one;
  const accent = col(pal, "accent");
  const copies = Math.ceil((W * 1.4) / one) + 2;
  return (
    <div data-nm="box" style={{ width: W, overflow: "hidden", background: accent, padding: `${14 * u}px 0`, direction: "ltr", boxShadow: "0 6px 16px rgba(0,0,0,0.25)" }}>
      <div style={{ display: "flex", whiteSpace: "nowrap", width: one * copies, transform: `translateX(${rtl ? off - one : -off}px)` }}>
        {Array.from({ length: copies }).map((_, i) => <span key={i} style={{ width: one, flex: "none", fontFamily: fontStackOf(ctx), fontWeight: 800, fontSize: size, color: onColor(accent), direction: rtl ? "rtl" : "ltr" }}>{text}</span>)}
      </div>
    </div>
  );
};
const TickerScene: SC = ({ sc }) => (
  <Stage justify="center">
    <Ticker sc={sc} />
  </Stage>
);

// ───────────────────────────────────────────── image hero (Ken Burns + caption)

const ImageHero: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, W, H, fps, pal } = ctx;
  const qf = useQF();
  const img = useAsset(sc.image);
  const a = A(ctx);
  const z = interpolate(qf, [0, ctx.scene.frames], [1, 1.12], { extrapolateRight: "clamp" });
  return (
    <>
      <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
        {img ? <Img src={img} style={{ position: "absolute", inset: 0, width: W, height: H, objectFit: "cover", transform: `scale(${z})` }} /> : <div style={{ position: "absolute", inset: 0, background: `linear-gradient(135deg, ${col(pal, "accent")}, ${col(pal, "accent2")})`, transform: `scale(${z})` }} />}
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, rgba(0,0,0,0.08) 28%, rgba(0,0,0,0.80) 58%, rgba(0,0,0,0.90) 100%)" }} />
      </div>
      <Stage justify="flex-end" gap={20}>
        {sc.kicker ? <T role="label" size={44} delay={0} color="#ffffff" fx="plain">{String(sc.kicker)}</T> : null}
        <FT box={[a.w, a.h * 0.34]} max={110} min={38} maxLines={3} delay={6} color="#ffffff" fx="plain">{String(sc.caption ?? "")}</FT>
      </Stage>
    </>
  );
};

const LowerThirdScene: SC = ({ sc }) => (
  <Stage justify="flex-end">
    <LowerThird sc={sc} />
  </Stage>
);
const StickerScene: SC = ({ sc }) => (
  <Stage>
    <div style={{ transform: "scale(2.3)", transformOrigin: "center" }}>      {/* as a whole scene the sticker is the hero: ~half the frame width (as an overlay it stays small) */}
      <Sticker sc={sc} />
    </div>
  </Stage>
);

export const TEXT_COMPONENTS: { [k: string]: SC } = {
  kinetic_title: KineticTitle, lower_third: LowerThirdScene, checklist: Checklist, steps: Steps, icon_grid: IconGrid, feature_cards: FeatureCards,
  testimonial: Testimonial, captions: CaptionsScene, sticker: StickerScene, social_cta: SocialCta, tags: Tags, ticker: TickerScene, image_hero: ImageHero,
  brand_character: BrandCharacterScene,
};
/** a compact social handle (an overlay: icon + @handle) */
const SocialBug: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, pal, rtl } = ctx;
  const a = A(ctx);
  const accent = col(pal, "accent");
  return (
    <Pop delay={0}>
      <div data-nm="box" style={{ display: "flex", alignItems: "center", gap: 18 * u, direction: rtl ? "rtl" : "ltr", background: "rgba(0,0,0,0.6)", padding: `${10 * u}px ${26 * u}px ${10 * u}px ${14 * u}px`, borderRadius: 60 * u }}>
        <IconTile name={PLATFORM_ICON[String(sc.platform ?? "instagram")] ?? "at-sign"} size={70} fill={accent} />
        <div style={{ direction: "ltr" }}><FT box={[Math.min(a.w - 200, 620), 80]} max={46} min={24} maxLines={1} role="body" noAnim color="#ffffff" fx="plain" weight={800}>{String(sc.handle ?? "")}</FT></div>
      </div>
    </Pop>
  );
};

/** the overlay forms (no Stage: they are placed by the overlay layer) */
export const OVERLAY_BODIES: { [k: string]: SC } = { lower_third: LowerThird, sticker: Sticker, captions: Captions, ticker: Ticker, social_cta: SocialBug, brand_character: BrandCharacterOverlay };
void useFit;
void ({} as CSSProperties);
