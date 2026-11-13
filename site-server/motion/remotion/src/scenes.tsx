import React from "react";
import type { CSSProperties } from "react";
import { Img, interpolate, Easing } from "remotion";
import { enterCss, enterProgress } from "./anim";
import { useAsset, useCtx, useQF } from "./ctx";
import { Card, T, TONE } from "./text";
import type { Scene } from "./types";
import { clamp, col, fitSize, fmtNumber, hasArabic, onColor, rgba, shade, toEnDigits, toFaDigits } from "./util";

type SC = React.FC<{ sc: Scene }>;

const Stage: React.FC<{ children?: React.ReactNode; gap?: number; row?: boolean; justify?: CSSProperties["justifyContent"] }> = ({ children, gap = 36, row, justify = "center" }) => {
  const { W, H, u, wide, rtl } = useCtx();
  return (
    <div style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0, display: "flex", flexDirection: row ? (rtl ? "row-reverse" : "row") : "column", justifyContent: justify, alignItems: "center", padding: wide ? `${H * 0.08}px ${W * 0.09}px` : `${H * 0.07}px ${W * 0.085}px`, gap: gap * u, boxSizing: "border-box" }}>
      {children}
    </div>
  );
};

/** a small element that enters with the style's motion (bars, badges, rings) */
const Pop: React.FC<{ delay?: number; children?: React.ReactNode; style?: CSSProperties; i?: number; kind?: string }> = ({ delay = 0, children, style, i = 0, kind }) => {
  const ctx = useCtx();
  const qf = useQF();
  const p = enterProgress(ctx, qf, delay);
  return <div style={{ ...enterCss(kind ?? ctx.style.motion.enter, p, { u: ctx.u, rtl: ctx.rtl, i, qf, fps: ctx.fps }), ...style }}>{children}</div>;
};

const Rule: React.FC<{ delay?: number; w?: number }> = ({ delay = 8, w = 260 }) => {
  const { pal, u, style } = useCtx();
  return (
    <Pop delay={delay} kind="wipe">
      <div style={{ width: w * u, height: 14 * u, background: col(pal, style.shape.rule ?? "accent"), borderRadius: Math.min(7, style.shape.radius ?? 0) * u, boxShadow: style.shape.shadow === "hard" ? `${5 * u}px ${5 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : undefined }} />
    </Pop>
  );
};

const Badge: React.FC<{ n: string; size?: number }> = ({ n, size = 76 }) => {
  const { pal, u, style } = useCtx();
  const bg = col(pal, style.shape.badge ?? "accent");
  return (
    <div style={{ width: size * u, height: size * u, flex: "none", display: "flex", alignItems: "center", justifyContent: "center", borderRadius: style.shape.badgeRound === false ? (style.shape.radius ?? 0) * u : "50%", background: bg, border: style.shape.border ? `${Math.max(3, (style.shape.border ?? 0) * 0.7) * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined, boxShadow: style.shape.shadow === "hard" ? `${4 * u}px ${4 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
      <T noAnim size={size * 0.55} color={onColor(bg)} fx="plain" style={{ lineHeight: 1 }}>{n}</T>
    </div>
  );
};

// ───────────────────────────────────────────── scene templates

const Title: SC = ({ sc }) => {
  const { wide } = useCtx();
  return (
    <Stage gap={34}>
      {sc.kicker ? <T role="label" size={46} delay={0} color="accent" upper>{sc.kicker}</T> : null}
      <T size={fitSize(String(sc.title || ""), wide ? 124 : 138, 16)} delay={3} maxWidth={wide ? 1500 : 940}>{String(sc.title || "")}</T>
      <Rule delay={10} />
      {sc.subtitle ? <T role="body" size={wide ? 52 : 56} delay={16} maxWidth={wide ? 1200 : 900}>{String(sc.subtitle)}</T> : null}
    </Stage>
  );
};

const List: SC = ({ sc }) => {
  const { u, wide, style, rtl, fps, pal } = useCtx();
  const items: string[] = (sc.items || []).map(String).slice(0, 6);
  const numbered = sc.numbered !== false;
  const bodySize = items.length > 4 ? 46 : 54;
  const two = wide && items.length > 3;
  const stag = Math.max(4, style.motion.stagger);
  return (
    <Stage gap={30}>
      {sc.title ? <T size={fitSize(String(sc.title), wide ? 92 : 100, 20)} delay={0} maxWidth={wide ? 1500 : 940}>{String(sc.title)}</T> : null}
      <div style={{ width: "100%", display: "grid", gridTemplateColumns: two ? "1fr 1fr" : "1fr", gap: 22 * u, direction: rtl ? "rtl" : "ltr" }}>
        {items.map((it, i) => (
          <Card key={i} i={i} delay={Math.round(fps * 0.35) + i * stag} pad={22} style={{ display: "flex", alignItems: "center", gap: 22 * u }}>
            {numbered ? <Badge n={String(i + 1)} size={bodySize * 1.45} /> : <div style={{ width: 14 * u, height: 14 * u, background: col(pal, "accent"), borderRadius: "50%" }} />}
            <T noAnim role="body" align="start" size={bodySize} weight={600} style={{ flex: 1 }}>{it}</T>
          </Card>
        ))}
      </div>
    </Stage>
  );
};

const Quote: SC = ({ sc }) => {
  const { wide, u } = useCtx();
  const text = String(sc.text || "");
  return (
    <Stage gap={22}>
      <T size={wide ? 220 : 280} delay={0} color="accent" fx="plain" style={{ lineHeight: 0.7, height: (wide ? 120 : 170) * u }}>{"“"}</T>
      <T size={fitSize(text, wide ? 76 : 84, 60, 0.5)} delay={6} lh={1.4} maxWidth={wide ? 1500 : 920}>{text}</T>
      {sc.author ? <T role="label" size={46} delay={30} color="accent" fx="plain">{`— ${sc.author}`}</T> : null}
    </Stage>
  );
};

const Stat: SC = ({ sc }) => {
  const ctx = useCtx();
  const { fps, u, faDigits, wide } = ctx;
  const qf = useQF();
  const target = Number(toEnDigits(String(sc.value ?? 0)).replace(/[^0-9.\-]/g, "")) || 0;
  const dec = Number(sc.decimals ?? (String(sc.value ?? "").includes(".") ? 1 : 0));
  const prog = sc.count_up === false ? 1 : Easing.out(Easing.cubic)(clamp((qf - 6) / (fps * 1.5)));
  const shown = fmtNumber(target * prog, faDigits, dec);
  const base = fitSize(shown + String(sc.suffix || "") + String(sc.prefix || ""), wide ? 300 : 340, 6, 0.4);
  return (
    <Stage gap={26}>
      {sc.kicker ? <T role="label" size={46} delay={0} color="accent" upper>{String(sc.kicker)}</T> : null}
      <Pop delay={2}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 10 * u, direction: "ltr" }}>
          {sc.prefix ? <T noAnim size={base * 0.4}>{String(sc.prefix)}</T> : null}
          <T noAnim size={base}>{shown}</T>
          {sc.suffix ? <T noAnim size={base * 0.5} color="accent">{String(sc.suffix)}</T> : null}
        </div>
      </Pop>
      <Rule delay={14} w={200} />
      {sc.label ? <T role="body" size={wide ? 54 : 60} delay={18} maxWidth={wide ? 1300 : 900}>{String(sc.label)}</T> : null}
    </Stage>
  );
};

const Compare: SC = ({ sc }) => {
  const ctx = useCtx();
  const { W, H, u, wide, rtl, fps, pal } = ctx;
  const qf = useQF();
  const bl = String(sc.before_label ?? (rtl ? "قبل" : "Before"));
  const al = String(sc.after_label ?? (rtl ? "بعد" : "After"));
  const bi = useAsset(sc.before_image), ai = useAsset(sc.after_image);
  if (bi && ai) {
    const w = wide ? H * 0.78 : W * 0.84, h = wide ? H * 0.7 : H * 0.46;
    const t = Easing.inOut(Easing.cubic)(clamp((qf - fps * 0.6) / (fps * 1.8)));
    const split = t * 100;
    return (
      <Stage gap={30}>
        {sc.title ? <T size={wide ? 84 : 92} delay={0}>{String(sc.title)}</T> : null}
        <Pop delay={4}>
          <div style={{ position: "relative", width: w, height: h, borderRadius: (ctx.style.shape.radius ?? 0) * u, overflow: "hidden", boxShadow: `0 ${20 * u}px ${40 * u}px rgba(0,0,0,0.35)`, border: ctx.style.shape.border ? `${ctx.style.shape.border * u}px solid ${col(pal, ctx.style.shape.bc ?? "ink")}` : undefined }}>
            <Img src={ai} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
            <div style={{ position: "absolute", inset: 0, clipPath: `inset(0 ${100 - split}% 0 0)` }}>
              <Img src={bi} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }} />
            </div>
            <div style={{ position: "absolute", top: 0, bottom: 0, left: `${split}%`, width: 6 * u, marginLeft: -3 * u, background: col(pal, "paper") }} />
            <div style={{ position: "absolute", top: 20 * u, left: 20 * u, padding: `${6 * u}px ${18 * u}px`, background: "rgba(0,0,0,0.55)", borderRadius: 40 * u }}><T noAnim role="label" size={38} color="#ffffff" fx="plain">{bl}</T></div>
            <div style={{ position: "absolute", top: 20 * u, right: 20 * u, padding: `${6 * u}px ${18 * u}px`, background: col(pal, "accent"), borderRadius: 40 * u }}><T noAnim role="label" size={38} color={onColor(col(pal, "accent"))} fx="plain">{al}</T></div>
          </div>
        </Pop>
      </Stage>
    );
  }
  const side = (label: string, text: string, imgSrc: string | null, accent: boolean, delay: number, i: number) => (
    <Card i={i} delay={delay} pad={30} fill={accent ? "accent" : undefined} style={{ width: wide ? "100%" : "100%", display: "flex", flexDirection: "column", alignItems: "center", gap: 16 * u, flex: 1 }}>
      <T noAnim role="label" size={40} upper fx="plain" style={{ opacity: 0.8 }}>{label}</T>
      {imgSrc ? <Img src={imgSrc} style={{ width: "100%", height: (wide ? H * 0.34 : H * 0.17), objectFit: "cover", borderRadius: 10 * u }} /> : null}
      <T noAnim role="display" size={fitSize(text, wide ? 66 : 70, 24, 0.6)} fx="plain" weight={800}>{text}</T>
    </Card>
  );
  return (
    <Stage gap={26}>
      {sc.title ? <T size={wide ? 84 : 92} delay={0}>{String(sc.title)}</T> : null}
      <div style={{ width: "100%", display: "flex", flexDirection: wide ? (rtl ? "row-reverse" : "row") : "column", alignItems: "stretch", gap: 26 * u }}>
        {side(bl, String(sc.before ?? ""), bi, false, 8, 0)}
        <Pop delay={20} style={{ alignSelf: "center" }}><T noAnim size={wide ? 90 : 80} color="accent" fx="plain">{wide ? (rtl ? "←" : "→") : "↓"}</T></Pop>
        {side(al, String(sc.after ?? ""), ai, true, 30, 1)}
      </div>
    </Stage>
  );
};

const Placeholder: React.FC<{ label: string; w: number; h: number; round?: number }> = ({ label, w, h, round = 0 }) => {
  const { pal, u } = useCtx();
  const letter = Array.from(label.trim())[0] || "★";
  return (
    <div style={{ width: w, height: h, borderRadius: round * u, background: `linear-gradient(135deg, ${col(pal, "accent")}, ${col(pal, "accent2")})`, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", position: "relative" }}>
      <div style={{ position: "absolute", width: w * 0.7, height: w * 0.7, borderRadius: "50%", background: "rgba(255,255,255,0.16)", top: -w * 0.2, left: -w * 0.1 }} />
      <div style={{ position: "absolute", width: w * 0.5, height: w * 0.5, borderRadius: "50%", background: "rgba(0,0,0,0.12)", bottom: -w * 0.18, right: -w * 0.08 }} />
      <T noAnim size={Math.min(w, h) / (u * 2.6)} color="#ffffff" fx="plain">{letter}</T>
    </div>
  );
};

const Product: SC = ({ sc }) => {
  const ctx = useCtx();
  const { W, H, u, wide, rtl, pal, style } = ctx;
  const img = useAsset(sc.image);
  const feats: string[] = (sc.features || []).map(String).slice(0, 4);
  const imgW = wide ? H * 0.62 : W * 0.62;
  const media = (
    <Card pad={14} delay={0} enter="rise" style={{ width: imgW, height: imgW, padding: 14 * u, flex: "none" }}>
      {img ? <Img src={img} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: Math.max(0, (style.shape.radius ?? 0) - 4) * u }} /> : <Placeholder label={String(sc.name || "")} w={imgW - 28 * u} h={imgW - 28 * u} round={Math.max(0, (style.shape.radius ?? 0) - 4)} />}
      {sc.badge ? (
        <div style={{ position: "absolute", top: -26 * u, [rtl ? "left" : "right"]: -22 * u, background: col(pal, "accent3"), padding: `${8 * u}px ${24 * u}px`, borderRadius: 60 * u, transform: "rotate(-6deg)", border: style.shape.border ? `${style.shape.border * 0.6 * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
          <T noAnim role="label" size={40} color={onColor(col(pal, "accent3"))} fx="plain">{String(sc.badge)}</T>
        </div>
      ) : null}
    </Card>
  );
  const info = (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 * u, flex: wide ? 1 : undefined }}>
      <T size={fitSize(String(sc.name || ""), wide ? 92 : 100, 16)} delay={10} maxWidth={wide ? 900 : 940}>{String(sc.name || "")}</T>
      {sc.price ? (
        <Pop delay={22}>
          <div style={{ background: col(pal, "accent"), padding: `${10 * u}px ${36 * u}px`, borderRadius: Math.max(14, (style.shape.radius ?? 0) * 2) * u, transform: "rotate(-3deg)", border: style.shape.border ? `${style.shape.border * 0.7 * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined, boxShadow: style.shape.shadow === "hard" ? `${6 * u}px ${6 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : undefined }}>
            <T noAnim size={72} color={onColor(col(pal, "accent"))} fx="plain">{String(sc.price)}</T>
          </div>
        </Pop>
      ) : null}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14 * u, justifyContent: "center", direction: rtl ? "rtl" : "ltr" }}>
        {feats.map((f, i) => (
          <Card key={i} i={i} delay={30 + i * Math.max(5, style.motion.stagger)} pad={12} style={{ padding: `${10 * u}px ${24 * u}px` }}>
            <T noAnim role="body" size={40} fx="plain" weight={600}>{f}</T>
          </Card>
        ))}
      </div>
    </div>
  );
  return <Stage gap={34} row={wide}>{media}{info}</Stage>;
};

const LogoSting: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, W, H, pal, spec, fps } = ctx;
  const qf = useQF();
  const logo = useAsset(spec.brand?.logo);
  const name = String(sc.title || spec.brand?.name || "");
  const rings = [0, 1, 2].map((i) => {
    const t = ((qf / fps) * 0.8 + i / 3) % 1;
    return <div key={i} style={{ position: "absolute", left: "50%", top: "50%", width: Math.min(W, H) * (0.3 + t * 0.9), height: Math.min(W, H) * (0.3 + t * 0.9), marginLeft: -Math.min(W, H) * (0.3 + t * 0.9) / 2, marginTop: -Math.min(W, H) * (0.3 + t * 0.9) / 2, borderRadius: "50%", border: `${5 * u}px solid ${rgba(col(pal, "accent"), (1 - t) * 0.7)}` }} />;
  });
  return (
    <>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, transform: "translateY(-6%)" }}>{rings}</div>
      <Stage gap={30}>
        <Pop delay={2}>{logo ? <Img src={logo} style={{ height: Math.min(W, H) * 0.34, maxWidth: W * 0.7, objectFit: "contain" }} /> : <T noAnim size={fitSize(name, 170, 10)}>{name}</T>}</Pop>
        {logo && name ? <T size={78} delay={14}>{name}</T> : null}
        {sc.tagline ? <T role="body" size={52} delay={22} maxWidth={W * 0.8 / u}>{String(sc.tagline)}</T> : null}
      </Stage>
    </>
  );
};

const Phone: React.FC<{ src: string | null; h: number; label?: string }> = ({ src, h, label }) => {
  const ctx = useCtx();
  const { u, pal, fps } = ctx;
  const qf = useQF();
  const w = h * 0.49;
  const swing = Math.sin((qf / fps) * 1.1) * 7;
  return (
    <div style={{ width: w, height: h, borderRadius: w * 0.15, background: "#0c0c12", padding: w * 0.04, boxShadow: `0 ${30 * u}px ${50 * u}px rgba(0,0,0,0.45), inset 0 0 0 ${3 * u}px #2b2b36`, transform: `perspective(1400px) rotateY(${swing}deg) rotateX(${-2}deg)`, position: "relative", flex: "none" }}>
      <div style={{ width: "100%", height: "100%", borderRadius: w * 0.115, overflow: "hidden", position: "relative", background: col(pal, "paper") }}>
        {src ? <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : (
          <div style={{ position: "absolute", inset: 0, background: `linear-gradient(180deg, ${col(pal, "accent")} 0 17%, ${col(pal, "paper")} 17%)`, display: "flex", flexDirection: "column", gap: w * 0.05, padding: `${w * 0.28}px ${w * 0.07}px ${w * 0.07}px` }}>
            {[0.9, 0.6, 0.75, 0.5, 0.8].map((k, i) => <div key={i} style={{ height: w * 0.17, borderRadius: w * 0.04, background: rgba(col(pal, i % 2 ? "accent2" : "accent"), 0.18), width: `${k * 100}%`, alignSelf: i % 2 ? "flex-start" : "stretch" }} />)}
            {label ? <div style={{ position: "absolute", top: w * 0.07, left: 0, right: 0, textAlign: "center" }}><T noAnim role="label" size={w / u * 0.1} color="#fff" fx="plain">{label}</T></div> : null}
          </div>
        )}
        <div style={{ position: "absolute", top: w * 0.03, left: "50%", width: w * 0.3, height: w * 0.07, marginLeft: -w * 0.15, borderRadius: w, background: "#0c0c12" }} />
      </div>
    </div>
  );
};

const App: SC = ({ sc }) => {
  const ctx = useCtx();
  const { W, H, u, wide, style, rtl, spec } = ctx;
  const shot = useAsset(sc.screenshot);
  const bullets: string[] = (sc.bullets || []).map(String).slice(0, 4);
  const phoneH = wide ? H * 0.8 : H * 0.5;
  return (
    <Stage gap={34} row={wide}>
      <Pop delay={0} kind="rise"><Phone src={shot} h={phoneH} label={spec.brand?.name} /></Pop>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 * u, flex: wide ? 1 : undefined }}>
        {sc.caption ? <T size={fitSize(String(sc.caption), wide ? 80 : 88, 22)} delay={8} maxWidth={wide ? 900 : 940}>{String(sc.caption)}</T> : null}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 * u, direction: rtl ? "rtl" : "ltr", alignItems: "stretch", width: wide ? "100%" : undefined }}>
          {bullets.map((b, i) => (
            <Card key={i} i={i} delay={20 + i * Math.max(5, style.motion.stagger)} pad={12} style={{ padding: `${10 * u}px ${24 * u}px`, display: "flex", alignItems: "center", gap: 16 * u }}>
              <div style={{ width: 16 * u, height: 16 * u, borderRadius: "50%", background: col(ctx.pal, "accent"), flex: "none" }} />
              <T noAnim role="body" align="start" size={42} fx="plain" weight={600}>{b}</T>
            </Card>
          ))}
        </div>
      </div>
    </Stage>
  );
};

const Cta: SC = ({ sc }) => {
  const ctx = useCtx();
  const { u, pal, fps, wide, style } = ctx;
  const qf = useQF();
  const pulse = 1 + Math.sin((qf / fps) * 4) * 0.035;
  const bg = col(pal, "accent");
  return (
    <Stage gap={40}>
      <T size={fitSize(String(sc.title || ""), wide ? 120 : 130, 16)} delay={0} maxWidth={wide ? 1500 : 940}>{String(sc.title || "")}</T>
      {sc.button ? (
        <Pop delay={16}>
          <div style={{ transform: `scale(${pulse})`, background: bg, padding: `${22 * u}px ${72 * u}px`, borderRadius: Math.max(24, (style.shape.radius ?? 0) * 3) * u, border: style.shape.border ? `${style.shape.border * u}px solid ${col(pal, style.shape.bc ?? "ink")}` : undefined, boxShadow: style.shape.shadow === "hard" ? `${9 * u}px ${9 * u}px 0 ${col(pal, style.shape.bc ?? "ink")}` : `0 ${14 * u}px ${34 * u}px rgba(0,0,0,0.3)` }}>
            <T noAnim size={64} color={onColor(bg)} fx="plain" weight={800}>{String(sc.button)}</T>
          </div>
        </Pop>
      ) : null}
      {sc.note ? <T role="label" size={44} delay={26} fx="plain">{String(sc.note)}</T> : null}
    </Stage>
  );
};

export const SCENES: { [k: string]: SC } = {
  title: Title, list: List, quote: Quote, stat: Stat, compare: Compare, product: Product, logo: LogoSting, app: App, cta: Cta,
};

export const SCENE_LABELS: { [k: string]: string } = {
  title: "کارتِ عنوان", list: "فهرست / مراحل", quote: "نقل‌قول", stat: "عددِ بزرگ", compare: "قبل و بعد",
  product: "معرفیِ محصول", logo: "لوگو (استینگ)", app: "نمایشِ اپ در قابِ گوشی", cta: "دعوت به اقدام",
};

export { interpolate, shade, toFaDigits, hasArabic, TONE };
