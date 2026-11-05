import { useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import type { Catalogue, MediaItem } from "../api";
import AutoReframe from "./AutoReframe";
import { defaultBezier } from "./bezier";
import { transitionIsApproximate } from "./Compositor";
import { Chips, ColorField, Num, Section, Slider, Toggle } from "./controls";
import { KfChannel, RAMP_STEPS, RampKey, keyNear, rampSpeeds, removeKey, setKey, valueAt } from "./keyframes";
import {
  ATTR_GROUPS, AttrGroup, Blend, Chroma, Mask, MediaClip, Project, ShapeSpec, Track, clipLength, propAt, timecode, updateClip,
} from "./model";
import { fitToBoxWindow, hasReframeKeys, reframeWindow } from "./reframe";
import { SHAPES } from "./shapes";
import "./clipinspector.css";

type Edit = {
  live: (fn: (p: Project) => Project) => void;
  end: (label: string) => void;
  apply: (label: string, fn: (p: Project) => Project) => void;
};

type Props = {
  clip: MediaClip;
  track: Track;
  ids: string[];
  playhead: number;
  item: MediaItem | undefined;
  cat: Catalogue | null;
  edit: Edit;
  hasClipboard: boolean;
  onCopyAttrs: (groups: AttrGroup[]) => void;
  onPasteAttrs: () => void;
  onExtractAudio: () => void;
  onUnlink: () => void;
  onFreeze: () => void;
  onJLCut: (kind: "J" | "L") => void;
  linked: boolean;
  /** ویرایشِ نقطه‌های ماسکِ آزاد روی تصویرِ مانیتور */
  onEditMask?: (on: boolean) => void;
  editingMask?: boolean;
  /** «برشِ قاب»: بازتنظیمِ خودکار (سرور) و باز/بستنِ حالتِ برش روی مانیتور */
  storeId?: string;
  format?: { width: number; height: number };
  onCropMode?: (on: boolean) => void;
  cropOn?: boolean;
};

const BLENDS_FALLBACK = [{ key: "normal", title: "عادی" }];
const DEFAULT_CHROMA: Chroma = { on: true, color: "#00ff00", similarity: 0.18, blend: 0.08, spill: 0.5 };
const DEFAULT_MASK: Mask = { shape: "ellipse", cx: 0.5, cy: 0.5, w: 0.6, h: 0.6, feather: 0.05, invert: false };

/** نمودارِ منحنیِ سرعت: محورِ افقی = بخشِ بازهٔ منبع، عمودی = سرعت (لگاریتمی ۰٫۱ تا ۸) */
function RampEditor({ ramp, onLive, onEnd }: { ramp: RampKey[]; onLive: (r: RampKey[]) => void; onEnd: () => void }) {
  const W = 280, H = 90;
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<number | null>(null);
  const lo = Math.log(0.1), hi = Math.log(8);
  const X = (p: number) => 6 + p * (W - 12);
  const Y = (v: number) => H - 6 - ((Math.log(Math.max(0.1, Math.min(8, v))) - lo) / (hi - lo)) * (H - 12);
  const toP = (x: number) => Math.max(0, Math.min(1, (x - 6) / (W - 12)));
  const toV = (y: number) => Math.exp(lo + (1 - (y - 6) / (H - 12)) * (hi - lo));
  const pos = (e: React.MouseEvent | React.PointerEvent) => {
    const r = svg.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * W, y: ((e.clientY - r.top) / r.height) * H };
  };
  const sorted = [...ramp].sort((a, b) => a.p - b.p);
  const path = sorted.map((k, i) => `${i ? "L" : "M"}${X(k.p)},${Y(k.v)}`).join(" ");
  return (
    <svg ref={svg} viewBox={`0 0 ${W} ${H}`} className="ramp-svg" data-testid="ramp-editor"
      onPointerMove={(e) => {
        if (drag.current === null) return;
        const { x, y } = pos(e);
        const next = sorted.map((k, i) => (i === drag.current ? { p: i === 0 ? 0 : i === sorted.length - 1 ? 1 : toP(x), v: Math.round(toV(y) * 100) / 100 } : k));
        onLive(next);
      }}
      onPointerUp={() => { if (drag.current !== null) { drag.current = null; onEnd(); } }}
      onDoubleClick={(e) => {
        const { x, y } = pos(e);
        const hit = sorted.findIndex((k) => Math.hypot(X(k.p) - x, Y(k.v) - y) < 9);
        if (hit > 0 && hit < sorted.length - 1) { onLive(sorted.filter((_k, i) => i !== hit)); onEnd(); }
        else if (hit < 0) { onLive([...sorted, { p: toP(x), v: Math.round(toV(y) * 100) / 100 }]); onEnd(); }
      }}
    >
      {[0.25, 0.5, 1, 2, 4].map((v) => <g key={v}><line x1={6} x2={W - 6} y1={Y(v)} y2={Y(v)} className="g" /><text x={W - 4} y={Y(v) - 2} textAnchor="end">{v}×</text></g>)}
      <path d={path} className="curve" />
      {sorted.map((k, i) => (
        <circle key={i} cx={X(k.p)} cy={Y(k.v)} r={6} className="pt" data-ramp-point={i}
          onPointerDown={(e) => { e.stopPropagation(); (e.currentTarget as SVGCircleElement).setPointerCapture(e.pointerId); drag.current = i; }} />
      ))}
    </svg>
  );
}

/** زیربلوکِ تاشوی «برشِ لبه‌ها»؛ اگر قطعه از قبل برشِ لبه دارد باز شروع می‌شود (با key = شناسهٔ قطعه برای هر قطعه از نو) */
function EdgesBlock({ initialOpen, children }: { initialOpen: boolean; children: React.ReactNode }) {
  const [open] = useState(initialOpen);
  return (
    <details className="cr-edges" open={open} data-testid="crop-edges">
      <summary>برشِ لبه‌ها (افکتِ شفاف‌شدنِ لبه)</summary>
      <p className="ws-hint">این چهار لغزنده لبه‌های قطعه را شفاف می‌کنند و تصویر جابه‌جا نمی‌شود. برای اینکه «کدام بخشِ تصویر» دیده شود از «برشِ قاب» (بالا) استفاده کنید.</p>
      {children}
    </details>
  );
}

export default function ClipInspector({ clip, track, ids, playhead, item, cat, edit, hasClipboard, onCopyAttrs, onPasteAttrs, onExtractAudio, onUnlink, onFreeze, onJLCut, linked, onEditMask, editingMask, storeId, format, onCropMode, cropOn }: Props) {
  const id = clip.id;
  const audioOnly = track.kind === "audio";
  const len = clipLength(clip);
  const rel = playhead - clip.at;
  const inside = rel >= -0.001 && rel <= len + 0.001;
  const [attrGroups, setAttrGroups] = useState<AttrGroup[]>(["transform", "color", "effects"]);

  // کلیدفریم‌ها فقط روی قطعهٔ اصلی می‌نشینند (مقدارِ هر قطعه با دیگری فرق دارد)؛ بقیهٔ تنظیم‌ها روی همهٔ انتخاب‌شده‌ها
  const upd = (patch: Partial<MediaClip>) => (pr: Project): Project => {
    const targets = "kf" in patch || "shape" in patch || "matte" in patch || "lut" in patch ? [id] : ids.length ? ids : [id];
    return { ...pr, tracks: pr.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (targets.includes(c.id) ? ({ ...c, ...patch } as typeof c) : c)) })) };
  };
  const live = (patch: Partial<MediaClip>) => edit.live(upd(patch));
  const set = (label: string, patch: Partial<MediaClip>) => edit.apply(label, upd(patch));

  /** مقدارِ یک ویژگیِ قابل‌انیمیشن؛ اگر کلیدفریم دارد در سرِ پخش کلید می‌گذارد، وگرنه مقدارِ ثابت */
  const prop = (ch: KfChannel, label: string, min: number, max: number, step: number, opts: { unit?: string; def: number; scale?: number; staticPatch: (v: number) => Partial<MediaClip>; digits?: number }) => {
    const keys = clip.kf?.[ch];
    const has = !!keys?.length;
    const here = !!keyNear(keys, rel);
    const k = opts.scale ?? 1;
    const value = propAt(clip, ch, playhead);
    const writeKey = (v: number): Partial<MediaClip> => ({ kf: { ...(clip.kf ?? {}), [ch]: setKey(keys, rel, v, ch) } });
    const write = (v: number) => (has ? writeKey(v) : opts.staticPatch(v));
    return (
      <Slider
        label={label} value={value * k} min={min} max={max} step={step} unit={opts.unit} def={opts.def * k} digits={opts.digits ?? 2}
        onLive={(v) => live(write(v / k))} onEnd={() => edit.end(label)}
        kf={{
          has, here,
          onToggle: () => {
            if (here) {
              const left = removeKey(keys, rel);
              const kf = { ...(clip.kf ?? {}) } as NonNullable<MediaClip["kf"]>;
              if (left.length) kf[ch] = left; else delete kf[ch];
              // آخرین کلید برداشته شد ⇒ مقدارِ همان لحظه ثابت می‌ماند
              set(`برداشتنِ کلیدفریمِ ${label}`, { kf, ...(left.length ? {} : opts.staticPatch(value)) });
            } else {
              if (!inside) return;
              set(`کلیدفریمِ ${label}`, writeKey(value));
            }
          },
        }}
      />
    );
  };

  const cropSet = (side: "l" | "r" | "t" | "b", v: number) => ({ crop: { ...(clip.crop ?? {}), [side]: v } });
  const eqBlend = cat?.blends ?? BLENDS_FALLBACK;
  const trKinds = cat?.transitions.kinds ?? [];
  const trGroups = cat?.transitions.groups ?? [];
  const [trGroup, setTrGroup] = useState<string>("dissolve");
  const ramp = clip.ramp && clip.ramp.length >= 2 ? clip.ramp : null;
  const rampLen = ramp ? (clip.end - clip.start) * (rampSpeeds(ramp).reduce((s, v) => s + 1 / v, 0) / RAMP_STEPS) : 0;
  const mask = clip.mask && clip.mask.shape !== "none" ? clip.mask : null;
  const chroma = clip.chroma?.on ? clip.chroma : null;

  // ---- برشِ قاب (reframe): پنجره‌ای در خودِ منبع
  const rf = clip.reframe;
  const srcAsp = item?.width && item?.height ? item.width / item.height : 0;
  const frameAsp = format && format.height ? format.width / format.height : 0;
  const boxAsp = frameAsp && clip.height > 0 ? (clip.width * frameAsp) / clip.height : 0;
  const reframable = track.kind === "video" && clip.kind !== "audio" && !clip.shape && !clip.ref.startsWith("seq:");
  const rfWin = reframeWindow(clip, playhead, 1, 1);
  const rfKeys = Math.max(rf?.kx?.length ?? 0, rf?.ky?.length ?? 0);
  const hasEdgeCrop = !!(clip.crop && (clip.crop.l || clip.crop.r || clip.crop.t || clip.crop.b)) || !!(clip.kf?.crop_l?.length || clip.kf?.crop_r?.length || clip.kf?.crop_t?.length || clip.kf?.crop_b?.length);
  const setReframe = (label: string, next: MediaClip["reframe"]) => edit.apply(label, (pr) => updateClip(pr, id, { reframe: next }));
  const pctOf = (v: number) => fa(Math.round(v * 1000) / 10);

  return (
    <div data-testid="clip-media">
      <div className="ws-card-title">{clip.label}{ids.length > 1 ? ` (+${fa(ids.length - 1)} قطعهٔ دیگر)` : ""}</div>
      <p className="ws-hint" dir="ltr">{timecode(clip.at)} → {timecode(clip.at + len)} ({fa(Math.round(len * 100) / 100)}s){item?.height ? ` · ${item.width}×${item.height}` : ""}</p>
      <div className="grid grid-cols-3 gap-2">
        <Num label="جا (ثانیه)" value={clip.at} onChange={(v) => set("جابه‌جایی", { at: Math.max(0, v) })} />
        <Num label={clip.kind === "image" ? "—" : "از منبع"} value={clip.start} onChange={(v) => clip.kind !== "image" && set("نقطهٔ شروع", { start: Math.max(0, Math.min(clip.end - 0.1, v)) })} />
        <Num label={clip.kind === "image" ? "مدت" : "تا منبع"} value={clip.end} onChange={(v) => set("نقطهٔ پایان", { end: Math.max(clip.start + 0.1, clip.src ? Math.min(clip.src, v) : v) })} />
      </div>

      {!audioOnly && (
        <Section title="جابه‌جایی، اندازه و چرخش" defaultOpen testId="sec-transform">
          {prop("px", "جابه‌جاییِ افقی", -100, 100, 0.5, { unit: "٪", def: 0, scale: 100, staticPatch: (v) => ({ px: v }), digits: 1 })}
          {prop("py", "جابه‌جاییِ عمودی", -100, 100, 0.5, { unit: "٪", def: 0, scale: 100, staticPatch: (v) => ({ py: v }), digits: 1 })}
          {prop("scale", "اندازه", 5, 400, 1, { unit: "٪", def: 1, scale: 100, staticPatch: (v) => ({ scale: v }), digits: 0 })}
          {prop("rot", "چرخش", -360, 360, 1, { unit: "°", def: 0, staticPatch: (v) => ({ rot: v }), digits: 0 })}
          {prop("opacity", "شفافیت", 0, 100, 1, { unit: "٪", def: 1, scale: 100, staticPatch: (v) => ({ opacity: v }), digits: 0 })}
          <div className="flex flex-wrap gap-3">
            <Toggle label="وارونهٔ افقی" checked={!!clip.flip_h} onChange={(v) => set("وارونهٔ افقی", { flip_h: v })} />
            <Toggle label="وارونهٔ عمودی" checked={!!clip.flip_v} onChange={(v) => set("وارونهٔ عمودی", { flip_v: v })} />
          </div>
          <p className="ws-hint">با لوزی (◆) کنارِ هر ویژگی انیمیشن شروع می‌شود؛ بعد از آن هر تغییری در سرِ پخش کلیدِ تازه می‌گذارد.</p>
          <label className="ws-field"><span>جا دادن در کادر</span>
            <select className="u-input" value={clip.fit} onChange={(e) => set("جا دادن", { fit: e.target.value as MediaClip["fit"] })} data-testid="fit">
              <option value="cover">پر کردنِ کادر (برش)</option><option value="contain">کاملِ تصویر (نوارِ سیاه)</option><option value="stretch">کشیده</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-x-3">
            <Slider label="چپ ٪" value={clip.x * 100} min={0} max={95} step={1} digits={0} onLive={(v) => live({ x: v / 100, width: Math.min(clip.width, 1 - v / 100) })} onEnd={() => edit.end("جا")} />
            <Slider label="بالا ٪" value={clip.y * 100} min={0} max={95} step={1} digits={0} onLive={(v) => live({ y: v / 100, height: Math.min(clip.height, 1 - v / 100) })} onEnd={() => edit.end("جا")} />
            <Slider label="پهنا ٪" value={clip.width * 100} min={5} max={100} step={1} digits={0} onLive={(v) => live({ width: Math.min(v / 100, 1 - clip.x) })} onEnd={() => edit.end("اندازه")} />
            <Slider label="ارتفاع ٪" value={clip.height * 100} min={5} max={100} step={1} digits={0} onLive={(v) => live({ height: Math.min(v / 100, 1 - clip.y) })} onEnd={() => edit.end("اندازه")} />
          </div>
          <button type="button" className="ws-link" onClick={() => set("تمام‌قاب", { x: 0, y: 0, width: 1, height: 1 })}>تمام‌قابِ جعبه (تصویر-در-تصویر: کوچکش کنید)</button>
        </Section>
      )}

      {!audioOnly && (
        <Section title="برش و ماسک" testId="sec-crop" badge={rf || hasEdgeCrop || mask ? <span className="ws-dot" /> : undefined}>
          {reframable && (
            <div data-testid="reframe-block">
              <div className="ws-group-title">برشِ قاب (کدام بخشِ تصویر دیده شود)</div>
              <p className="ws-hint">پنجره‌ای روی خودِ تصویر انتخاب می‌کنید و فقط همان بخش در قاب می‌آید؛ کیفیت از فایلِ اصلی است (برای ۹:۱۶ کردنِ ویدیوی افقی).</p>
              <AutoReframe
                storeId={storeId} clip={clip}
                onApply={(next) => setReframe("بازتنظیمِ خودکارِ قاب", next)}
              />
              <div className="flex flex-wrap gap-2 mb-1">
                <button type="button" className={`ws-btn ${cropOn ? "is-on" : ""}`} onClick={() => onCropMode?.(!cropOn)} disabled={!onCropMode} data-testid="open-crop-mode"
                  title="روی مانیتور کلِ تصویر را می‌بینید و پنجرهٔ برش را می‌کشید">{cropOn ? "بستنِ برشِ قاب" : "برشِ قاب روی تصویر…"}</button>
                <button type="button" className="ws-btn" onClick={() => setReframe("جا دادنِ خودکار در قاب", fitToBoxWindow(boxAsp, srcAsp))} disabled={!(srcAsp > 0) || !(boxAsp > 0)} data-testid="reframe-fit-frame"
                  title={srcAsp > 0 && boxAsp > 0 ? "وسطِ تصویر را هم‌نسبتِ قابِ پروژه می‌برد (بدونِ نوارِ سیاه، بدونِ اینترنت)" : "اندازهٔ تصویر یا قاب معلوم نیست"}>
                  جا دادنِ خودکار در قابِ پروژه
                </button>
                {rf && <button type="button" className="ws-btn" onClick={() => setReframe("برداشتنِ برشِ قاب", undefined)} data-testid="reframe-clear" title="برش برداشته شود و کلِ تصویر دیده شود">بازنشانی</button>}
              </div>
              <div className="cr-nums-ro" data-testid="reframe-readout" aria-label="اندازهٔ پنجرهٔ برش">
                <span><b>چپ</b>{pctOf(rfWin.x)}٪</span>
                <span><b>بالا</b>{pctOf(rfWin.y)}٪</span>
                <span><b>پهنا</b>{pctOf(rfWin.w)}٪</span>
                <span><b>ارتفاع</b>{pctOf(rfWin.h)}٪</span>
              </div>
              <p className="ws-hint">
                {rf ? "پنجرهٔ برش فعال است" : "هنوز برشِ قاب ندارد (کلِ تصویر دیده می‌شود)"}
                {rf && hasReframeKeys(rf) ? ` · ${fa(rfKeys)} کلیدِ حرکت` : ""}
                {rf && clip.fit !== "cover" ? " · اگر نوارِ سیاه می‌بینید «جا دادن در کادر» را روی «پر کردنِ کادر» بگذارید." : ""}
              </p>
            </div>
          )}
          <EdgesBlock key={id} initialOpen={hasEdgeCrop}>
            {prop("crop_l", "برشِ چپ", 0, 90, 1, { unit: "٪", def: 0, scale: 100, staticPatch: (v) => cropSet("l", v), digits: 0 })}
            {prop("crop_r", "برشِ راست", 0, 90, 1, { unit: "٪", def: 0, scale: 100, staticPatch: (v) => cropSet("r", v), digits: 0 })}
            {prop("crop_t", "برشِ بالا", 0, 90, 1, { unit: "٪", def: 0, scale: 100, staticPatch: (v) => cropSet("t", v), digits: 0 })}
            {prop("crop_b", "برشِ پایین", 0, 90, 1, { unit: "٪", def: 0, scale: 100, staticPatch: (v) => cropSet("b", v), digits: 0 })}
          </EdgesBlock>
          <div className="ws-group-title">ماسک</div>
          <Chips value={(mask?.shape ?? "none") as string} options={[{ key: "none", title: "بدون" }, { key: "rect", title: "مستطیل" }, { key: "ellipse", title: "بیضی" }, { key: "bezier", title: "آزاد (Bézier)" }]}
            onPick={(k) => set("ماسک", { mask: k === "none" ? undefined : { ...DEFAULT_MASK, ...(mask ?? {}), shape: k as Mask["shape"], ...(k === "bezier" && !(mask?.points?.length) ? { points: defaultBezier() } : {}) } })} />
          {mask?.shape === "bezier" && (
            <div className="flex flex-wrap gap-2 items-center">
              <button type="button" className={`ws-btn ${editingMask ? "is-on" : ""}`} onClick={() => onEditMask?.(!editingMask)} data-testid="bezier-edit">
                {editingMask ? "پایانِ ویرایشِ نقطه‌ها" : "ویرایشِ نقطه‌ها روی تصویر"}
              </button>
              <span className="ws-hint">{timecode(playhead) && `${mask.points?.length ?? 0} نقطه`} — دوبار کلیک روی خط نقطهٔ تازه می‌گذارد.</span>
            </div>
          )}
          {mask && (
            <>
              {mask.shape !== "bezier" && <Slider label="مرکز X" value={mask.cx * 100} min={0} max={100} step={1} digits={0} unit="٪" onLive={(v) => live({ mask: { ...mask, cx: v / 100 } })} onEnd={() => edit.end("ماسک")} />}
              {mask.shape !== "bezier" && <Slider label="مرکز Y" value={mask.cy * 100} min={0} max={100} step={1} digits={0} unit="٪" onLive={(v) => live({ mask: { ...mask, cy: v / 100 } })} onEnd={() => edit.end("ماسک")} />}
              {mask.shape !== "bezier" && <Slider label="پهنا" value={mask.w * 100} min={2} max={100} step={1} digits={0} unit="٪" onLive={(v) => live({ mask: { ...mask, w: v / 100 } })} onEnd={() => edit.end("ماسک")} />}
              {mask.shape !== "bezier" && <Slider label="ارتفاع" value={mask.h * 100} min={2} max={100} step={1} digits={0} unit="٪" onLive={(v) => live({ mask: { ...mask, h: v / 100 } })} onEnd={() => edit.end("ماسک")} />}
              <Slider label="نرمیِ لبه" value={mask.feather * 100} min={0} max={50} step={1} digits={0} unit="٪" onLive={(v) => live({ mask: { ...mask, feather: v / 100 } })} onEnd={() => edit.end("ماسک")} />
              <Toggle label="وارونه" checked={mask.invert} onChange={(v) => set("ماسک", { mask: { ...mask, invert: v } })} />
            </>
          )}
        </Section>
      )}

      {!audioOnly && (
        <Section title="ترکیب و کلیدِ رنگی (Green screen)" testId="sec-composite" badge={chroma ? <span className="ws-dot" /> : undefined}>
          <label className="ws-field"><span>حالتِ ترکیب با لایهٔ زیرین</span>
            <select className="u-input" value={clip.blend ?? "normal"} data-testid="blend" onChange={(e) => set("حالتِ ترکیب", { blend: e.target.value as Blend })}>
              {eqBlend.map((b) => <option key={b.key} value={b.key}>{b.title}</option>)}
            </select>
          </label>
          <Toggle label="حذفِ پس‌زمینهٔ رنگی (کلیدِ رنگی)" checked={!!chroma} onChange={(v) => set("کلیدِ رنگی", { chroma: v ? { ...DEFAULT_CHROMA, ...(clip.chroma ?? {}), on: true } : { ...(clip.chroma ?? DEFAULT_CHROMA), on: false } })} />
          {chroma && (
            <div data-testid="chroma">
              <ColorField label="رنگِ پس‌زمینه" value={chroma.color} onChange={(v) => set("رنگِ کلید", { chroma: { ...chroma, color: v } })} />
              <Slider label="دامنهٔ رنگ" value={chroma.similarity} min={0.01} max={0.8} step={0.01} def={0.18} onLive={(v) => live({ chroma: { ...chroma, similarity: v } })} onEnd={() => edit.end("کلیدِ رنگی")} />
              <Slider label="نرمیِ لبه" value={chroma.blend} min={0} max={0.5} step={0.01} def={0.08} onLive={(v) => live({ chroma: { ...chroma, blend: v } })} onEnd={() => edit.end("کلیدِ رنگی")} />
              <Slider label="حذفِ بازتابِ رنگ (Spill)" value={chroma.spill} min={0} max={1} step={0.05} def={0.5} onLive={(v) => live({ chroma: { ...chroma, spill: v } })} onEnd={() => edit.end("کلیدِ رنگی")} />
              <p className="ws-hint">کیفیتِ لبه‌ها را با «پیش‌نمایشِ دقیق» ببینید؛ کلیدِ رنگی روی این قطعه باید بالای یک ترکِ تصویرِ دیگر باشد.</p>
            </div>
          )}
        </Section>
      )}

      {clip.shape && (
        <Section title="شکل" defaultOpen testId="sec-shape">
          <Chips value={clip.shape.shape} options={SHAPES} onPick={(k) => set("نوعِ شکل", { shape: { ...clip.shape!, shape: k } })} />
          <ColorField label="رنگِ پرکننده" value={clip.shape.fill} onChange={(v) => set("رنگِ شکل", { shape: { ...clip.shape!, fill: v } })} />
          <Toggle label="گرادیان" checked={!!clip.shape.fill2} onChange={(v) => set("گرادیانِ شکل", { shape: { ...clip.shape!, fill2: v ? "#38bdf8" : undefined } })} />
          {clip.shape.fill2 && <ColorField label="رنگِ دوم" value={clip.shape.fill2} onChange={(v) => set("رنگِ دومِ شکل", { shape: { ...clip.shape!, fill2: v } })} />}
          {clip.shape.fill2 && <Slider label="زاویهٔ گرادیان" value={clip.shape.angle ?? 90} min={-180} max={180} step={5} unit="°" digits={0} def={90} onLive={(v) => live({ shape: { ...clip.shape!, angle: v } as ShapeSpec })} onEnd={() => edit.end("گرادیان")} />}
          <Slider label="شفافیتِ رنگ" value={(clip.shape.fill_opacity ?? 1) * 100} min={0} max={100} step={1} unit="٪" digits={0} def={100} onLive={(v) => live({ shape: { ...clip.shape!, fill_opacity: v / 100 } })} onEnd={() => edit.end("شفافیتِ شکل")} />
          <ColorField label="رنگِ لبه" value={clip.shape.stroke ?? "#ffffff"} onChange={(v) => set("رنگِ لبه", { shape: { ...clip.shape!, stroke: v } })} />
          <Slider label="ضخامتِ لبه" value={clip.shape.stroke_w ?? 0} min={0} max={20} step={0.5} unit="٪" digits={1} def={0} onLive={(v) => live({ shape: { ...clip.shape!, stroke_w: v } })} onEnd={() => edit.end("لبهٔ شکل")} />
          {clip.shape.shape === "rounded" && <Slider label="گردیِ گوشه" value={clip.shape.radius ?? 18} min={0} max={50} step={1} unit="٪" digits={0} def={18} onLive={(v) => live({ shape: { ...clip.shape!, radius: v } })} onEnd={() => edit.end("گوشه")} />}
          {["star", "polygon", "burst"].includes(clip.shape.shape) && <Slider label="تعدادِ نقطه" value={clip.shape.points ?? 5} min={3} max={16} step={1} digits={0} def={5} onLive={(v) => live({ shape: { ...clip.shape!, points: v } })} onEnd={() => edit.end("نقطه‌های شکل")} />}
          {["star", "burst"].includes(clip.shape.shape) && <Slider label="عمقِ نقطه‌ها" value={(clip.shape.inner ?? 0.45) * 100} min={15} max={90} step={1} unit="٪" digits={0} def={45} onLive={(v) => live({ shape: { ...clip.shape!, inner: v / 100 } })} onEnd={() => edit.end("عمقِ ستاره")} />}
        </Section>
      )}

      {clip.kind !== "image" && (
        <Section title="سرعت، وارونه و فریمِ ثابت" testId="sec-speed" badge={ramp || clip.reverse || clip.speed !== 1 ? <span className="ws-dot" /> : undefined}>
          {!ramp && !clip.freeze && <Slider label="سرعت" value={clip.speed} min={0.25} max={4} step={0.05} unit="×" def={1} onLive={(v) => live({ speed: v })} onEnd={() => edit.end("سرعت")} />}
          <div className="flex flex-wrap gap-3">
            {!clip.freeze && <Toggle label="وارونه (از آخر به اول)" checked={!!clip.reverse} onChange={(v) => set("وارونه", { reverse: v })} />}
            <button type="button" className="ws-btn" onClick={onFreeze} disabled={!inside || clip.freeze} data-testid="freeze-frame" title="فریمِ سرِ پخش را ۲ ثانیه نگه می‌دارد">❄ فریمِ ثابت در سرِ پخش</button>
          </div>
          {clip.freeze && <p className="ws-hint">این قطعه یک فریمِ ثابت است؛ مدتش را با کشیدنِ لبه‌ها یا «تا منبع» عوض کنید.</p>}
          {!clip.freeze && (
            <>
              <div className="ws-group-title">منحنیِ سرعت (Speed Ramp)</div>
              <div className="flex flex-wrap gap-1">
                {(cat?.ramp_presets ?? []).map((r) => (
                  <button key={r.key} type="button" className={`ws-chip`} onClick={() => set(`منحنیِ سرعت: ${r.title}`, { ramp: r.ramp, speed: 1 })} data-ramp-preset={r.key}>{r.title}</button>
                ))}
                {ramp && <button type="button" className="ws-chip" onClick={() => set("حذفِ منحنیِ سرعت", { ramp: undefined })}>حذفِ منحنی</button>}
              </div>
              {ramp ? (
                <>
                  <RampEditor ramp={ramp} onLive={(r) => live({ ramp: r })} onEnd={() => edit.end("منحنیِ سرعت")} />
                  <p className="ws-hint">طولِ قطعه با این منحنی: {fa(Math.round(rampLen * 100) / 100)} ثانیه. روی نمودار دوبار کلیک = نقطهٔ تازه / حذف؛ نقطه‌ها را بکشید.</p>
                </>
              ) : (
                <p className="ws-hint">یک الگو بزنید تا نمودارِ سرعت (کند و تند شدن در طولِ قطعه) بیاید.</p>
              )}
            </>
          )}
        </Section>
      )}

      <Section title="محو شدن" testId="sec-fade">
        <Slider label="محو در ابتدا" value={clip.fade_in} min={0} max={Math.max(0.1, Math.min(5, len / 2))} step={0.05} unit="s" def={0} onLive={(v) => live({ fade_in: v })} onEnd={() => edit.end("محوِ ابتدا")} />
        <Slider label="محو در انتها" value={clip.fade_out} min={0} max={Math.max(0.1, Math.min(5, len / 2))} step={0.05} unit="s" def={0} onLive={(v) => live({ fade_out: v })} onEnd={() => edit.end("محوِ انتها")} />
      </Section>

      {!audioOnly && (
        <Section title="گذار از قطعهٔ قبلی" testId="sec-transition" badge={clip.transition ? <span className="ws-dot" /> : undefined}>
          <div className="flex flex-wrap gap-1" data-testid="transition">
            <button type="button" className={`ws-chip ${!clip.transition ? "is-on" : ""}`} onClick={() => set("گذار", { transition: null })} data-transition="null">بی‌گذار</button>
            <button type="button" className={`ws-chip ${clip.transition?.kind === "fade" ? "is-on" : ""}`} onClick={() => set("گذار", { transition: { kind: "fade", duration: clip.transition?.duration ?? 0.6 } })} data-transition="fade">محو به سیاه</button>
            <button type="button" className={`ws-chip ${clip.transition?.kind === "crossfade" ? "is-on" : ""}`} onClick={() => set("گذار", { transition: { kind: "crossfade", duration: clip.transition?.duration ?? 0.6 } })} data-transition="crossfade">محوشدنِ تدریجی</button>
          </div>
          {trKinds.length > 0 && (
            <>
              <div className="ws-group-title">کتابخانهٔ گذارها</div>
              <div className="flex flex-wrap gap-1 mb-1">
                {trGroups.map((g) => <button key={g.key} type="button" className={`ws-chip ${trGroup === g.key ? "is-on" : ""}`} onClick={() => setTrGroup(g.key)}>{g.title}</button>)}
              </div>
              <div className="tr-grid">
                {trKinds.filter((k) => k.group === trGroup).map((k) => (
                  <button key={k.key} type="button" className={`tr-cell ${clip.transition?.kind === k.key ? "is-on" : ""}`} data-xfade={k.key}
                    onClick={() => set(`گذار: ${k.title}`, { transition: { kind: k.key, duration: clip.transition?.duration ?? 0.8 } })}>
                    <i className={`tr-ico g-${k.group}`} />{k.title}
                  </button>
                ))}
              </div>
            </>
          )}
          {clip.transition && (
            <>
              <Slider label="مدتِ گذار" value={clip.transition.duration} min={0.1} max={2} step={0.05} unit="s" def={0.6}
                onLive={(v) => live({ transition: { ...clip.transition!, duration: v } })} onEnd={() => edit.end("مدتِ گذار")} />
              {transitionIsApproximate(clip.transition.kind) && <p className="ws-hint" style={{ color: "var(--warn)" }}>پیش‌نمایشِ فوریِ این گذار تقریبی است؛ شکلِ واقعی را با «پیش‌نمایشِ دقیق» ببینید.</p>}
            </>
          )}
          <p className="ws-hint">گذار دورِ برشِ دو قطعهٔ چسبیده می‌نشیند (نیمی از هر طرف). طولش را از روی تایم‌لاین هم می‌شود کشید.</p>
        </Section>
      )}

      <Section title="پیوند، J/L-cut و کپیِ ویژگی‌ها" testId="sec-link">
        <div className="flex flex-wrap gap-2">
          {track.kind === "video" && clip.kind === "video" && clip.has_audio && clip.audio_on && !clip.ref.startsWith("seq:") && (
            <button type="button" className="ws-btn" onClick={onExtractAudio} data-testid="extract-audio">جدا کردنِ صدا از تصویر</button>
          )}
          {linked && <button type="button" className="ws-btn" onClick={onUnlink} data-testid="unlink">قطعِ پیوند</button>}
          {linked && <button type="button" className="ws-btn" onClick={() => onJLCut("J")} title="صدا کمی زودتر از تصویر شروع می‌شود">برش J</button>}
          {linked && <button type="button" className="ws-btn" onClick={() => onJLCut("L")} title="صدا کمی بعد از تصویر ادامه می‌یابد">برش L</button>}
        </div>
        <p className="ws-hint">{linked ? "صدا و تصویر پیوسته‌اند (با هم جابه‌جا و برش می‌خورند؛ Alt هنگامِ کشیدنِ لبه = فقط یکی)." : "برای J-cut/L-cut اول صدا را از تصویر جدا کنید."}</p>
        <div className="ws-group-title">کپیِ ویژگی‌ها</div>
        <div className="flex flex-wrap gap-1">
          {ATTR_GROUPS.map((g) => (
            <button key={g.key} type="button" className={`ws-chip ${attrGroups.includes(g.key) ? "is-on" : ""}`} title={g.title}
              onClick={() => setAttrGroups((cur) => (cur.includes(g.key) ? cur.filter((x) => x !== g.key) : [...cur, g.key]))}>{g.title.split(" / ")[0]}</button>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <button type="button" className="ws-btn" onClick={() => onCopyAttrs(attrGroups)} data-testid="copy-attrs">کپی از این قطعه</button>
          <button type="button" className="ws-btn" onClick={onPasteAttrs} disabled={!hasClipboard} data-testid="paste-attrs">چسباندن روی انتخاب‌شده‌ها</button>
        </div>
      </Section>
      <p className="ws-hint">سرِ پخش: {timecode(playhead)}{inside ? "" : " (بیرونِ این قطعه)"} · مقدار در سرِ پخش: {fa(Math.round(valueAt(clip.kf?.opacity, rel, clip.opacity) * 100))}٪ شفافیت</p>
    </div>
  );
}
