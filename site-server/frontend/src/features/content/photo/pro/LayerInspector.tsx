import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { Button, Select, fa } from "../../../../components/ui";
import type { Asset, FontInfo, Kit } from "../api";
import CurveEditor from "../manual/CurveEditor";
import type { Adjust, Curve } from "../manual/engine";
import { SECTIONS } from "../manual/model";
import { SectionBody } from "../manual/Sliders";
import type { Hist, ProActions } from "./panelTypes";
import RedeyeInspector from "./RedeyeInspector";
import { FxBlock, GroupInspector } from "./FxInspector";
import { effectivelyLocked } from "./tree";
import type { AdjustLayer, ImageLayer, Layer, ProState, RetouchLayer, ShapeLayer, TextLayer } from "./types";
import "./panels.css";

export type LayerInspectorProps = {
  state: ProState;
  hist: Hist;
  layer: Layer | null;
  actions: ProActions;
  fonts: FontInfo[];
  kit: Kit;
  assets: Asset[];
  /** (افزودنی) لوگوی فروشگاه، برای «جایگزینیِ تصویر» */
  storeLogo?: string | null;
  /** (افزودنی) اندازهٔ واقعیِ لایه روی بوم (کسری از پهنا) برای دکمه‌های هم‌ترازی */
  layerBox?: (id: string) => { w: number; h: number } | null;
  /** (افزودنی) ارتفاع÷پهنای بوم؛ بدونِ آن فقط «وسط» کار می‌کند */
  canvasAspect?: number;
};

// ───────────────────────────── ابزارک‌های کوچک

const WEIGHT_NAME: Record<number, string> = {
  100: "نازکِ ویژه", 200: "بسیار نازک", 300: "نازک", 400: "معمولی", 500: "متوسط", 600: "نیمه‌ضخیم", 700: "ضخیم", 800: "فوق‌ضخیم", 900: "سیاه",
};

const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

type EditApi<T extends Layer> = {
  live: (patch: Partial<T>) => void;
  apply: (label: string, patch: Partial<T>) => void;
  end: (label: string) => void;
};

function useEdit<T extends Layer>(hist: Hist, id: string, type: T["type"], tweak?: (patch: Partial<T>) => Partial<T>): EditApi<T> {
  const map = (patch: Partial<T>) => (s: ProState): ProState => {
    const p = tweak ? tweak(patch) : patch;
    return { ...s, layers: s.layers.map((l) => (l.id === id && l.type === type ? ({ ...l, ...p } as Layer) : l)) };
  };
  return {
    live: (patch) => hist.live(map(patch)),
    apply: (label, patch) => hist.apply(label, map(patch)),
    end: (label) => hist.end(label),
  };
}

/** لغزندهٔ استاندارد (همان قالبِ ws-slider): کشیدن ⇐ پیش‌نمایشِ زنده؛ رها کردن ⇐ ثبت در تاریخچه */
function Num({
  label, value, min, max, step, onLive, onEnd, fmt, testId, onReset,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onLive: (v: number) => void;
  onEnd: () => void;
  fmt?: (v: number) => string;
  testId?: string;
  onReset?: () => void;
}) {
  return (
    <label className="ws-slider">
      <span className="ws-slider-head">
        <span onDoubleClick={onReset}>{label}</span>
        <span className="ws-slider-val" dir="ltr">{fmt ? fmt(value) : fa(round(value))}</span>
      </span>
      <input
        type="range" min={min} max={max} step={step} value={value} aria-label={label} data-testid={testId}
        onChange={(e) => onLive(Number(e.target.value))} onPointerUp={onEnd} onKeyUp={onEnd} onBlur={onEnd} onDoubleClick={onReset}
      />
    </label>
  );
}

function Check({ checked, onChange, children, testId }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; testId?: string }) {
  return (
    <label className="pn-check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} data-testid={testId} />
      <span>{children}</span>
    </label>
  );
}

function ColorRow({ label, value, onLive, onEnd, testId }: { label: string; value: string; onLive: (v: string) => void; onEnd: () => void; testId?: string }) {
  return (
    <div className="pn-colorrow">
      <span>{label}</span>
      <input type="color" className="pn-color" value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : "#ffffff"} aria-label={label} data-testid={testId}
        onChange={(e) => onLive(e.target.value)} onBlur={onEnd} />
    </div>
  );
}

function Seg<V extends string | number>({ value, options, onPick, label }: { value: V; options: { value: V; label: string }[]; onPick: (v: V) => void; label: string }) {
  return (
    <div className="pn-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" className={o.value === value ? "is-on" : ""} aria-pressed={o.value === value} onClick={() => onPick(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Sub({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <div className="pn-sub">
      <div className="pn-sub-head">
        <span>{title}</span>
        {right}
      </div>
      {children}
    </div>
  );
}

/** پایانِ ویرایش بعد از چند لحظه بی‌کاری (برای textarea و انتخابگرِ رنگ) */
function useIdleEnd(hist: Hist, ms = 600) {
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<string | null>(null);
  const histRef = useRef(hist);
  histRef.current = hist;
  const flush = useCallback(() => {
    window.clearTimeout(timer.current);
    if (pending.current !== null) {
      const label = pending.current;
      pending.current = null;
      histRef.current.end(label);
    }
  }, []);
  const schedule = useCallback((label: string) => {
    pending.current = label;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(flush, ms);
  }, [flush, ms]);
  useEffect(() => flush, [flush]);
  return { schedule, flush };
}

// ───────────────────────────── جابه‌جایی و هم‌ترازی (برای تصویر/متن/شکل)

function TransformBlock({
  layer, hist, layerBox, canvasAspect,
}: {
  layer: ImageLayer | TextLayer | ShapeLayer;
  hist: Hist;
  layerBox?: (id: string) => { w: number; h: number } | null;
  canvasAspect?: number;
}) {
  const id = layer.id;
  const put = (patch: { cx?: number; cy?: number }) => (s: ProState): ProState => ({
    ...s, layers: s.layers.map((l) => (l.id === id && (l.type === "image" || l.type === "text" || l.type === "shape") ? ({ ...l, ...patch } as Layer) : l)),
  });
  const box = layerBox?.(id) ?? null;
  const th = (layer.rot * Math.PI) / 180;
  const bw = box ? Math.abs(box.w * Math.cos(th)) + Math.abs(box.h * Math.sin(th)) : 0;
  const bh = box ? Math.abs(box.w * Math.sin(th)) + Math.abs(box.h * Math.cos(th)) : 0;
  const asp = canvasAspect && canvasAspect > 0 ? canvasAspect : 0;
  const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
  const num = (key: "cx" | "cy", label: string) => (
    <label className="ws-field" style={{ margin: 0 }}>
      <span>{label}</span>
      <input
        type="number" className="u-input pn-num" min={-50} max={150} step={0.5} dir="ltr" aria-label={label} data-testid={`layer-${key}`}
        value={round(layer[key] * 100, 1)}
        onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v)) hist.live(put(key === "cx" ? { cx: v / 100 } : { cy: v / 100 })); }}
        onBlur={() => hist.end("جابه‌جایی")} onKeyUp={(e) => { if (e.key === "Enter") hist.end("جابه‌جایی"); }}
      />
    </label>
  );
  const go = (label: string, patch: { cx?: number; cy?: number }, enabled = true) => (
    <button type="button" disabled={!enabled} onClick={() => hist.apply(label, put(patch))}>{label.replace("هم‌ترازی ", "")}</button>
  );
  return (
    <Sub title="جایگاه">
      <div className="pn-pair">
        {num("cx", "افقی (٪)")}
        {num("cy", "عمودی (٪)")}
      </div>
      <div className="pn-align" data-testid="layer-align">
        {go("هم‌ترازی چپ", { cx: clamp01(bw / 2) }, !!box)}
        {go("هم‌ترازی وسطِ افقی", { cx: 0.5 })}
        {go("هم‌ترازی راست", { cx: clamp01(1 - bw / 2) }, !!box)}
        {go("هم‌ترازی بالا", { cy: clamp01(bh / 2 / (asp || 1)) }, !!box && !!asp)}
        {go("هم‌ترازی وسطِ عمودی", { cy: 0.5 })}
        {go("هم‌ترازی پایین", { cy: clamp01(1 - bh / 2 / (asp || 1)) }, !!box && !!asp)}
      </div>
    </Sub>
  );
}

function RotationSlider<T extends TextLayer | ImageLayer | ShapeLayer>({ layer, ed }: { layer: T; ed: EditApi<T> }) {
  return (
    <Num
      label="چرخش" value={layer.rot} min={-180} max={180} step={1} fmt={(v) => `${fa(round(v, 0))}°`} testId="layer-rot"
      onLive={(v) => ed.live({ rot: v } as Partial<T>)} onEnd={() => ed.end("چرخش")} onReset={() => ed.apply("چرخش", { rot: 0 } as Partial<T>)}
    />
  );
}

// ───────────────────────────── متن

const LINE_KEYS = new Set(["text", "size", "weight", "font", "letter_spacing", "line_height", "width", "align", "dir"]);

function TextInspector({ layer, hist, fonts }: { layer: TextLayer; hist: Hist; fonts: FontInfo[] }) {
  const ed = useEdit<TextLayer>(hist, layer.id, "text", (p) => (Object.keys(p).some((k) => LINE_KEYS.has(k)) ? { ...p, lines: undefined } : p));
  const idle = useIdleEnd(hist);
  const font = fonts.find((f) => f.key === layer.font);
  const weights = font?.weights?.length ? font.weights : [300, 400, 500, 600, 700, 800];
  const st = layer.stroke;
  const sh = layer.shadow;
  const bx = layer.box;
  const tl = layer.tile;
  return (
    <>
      <Sub title="متن">
        <textarea
          className="u-input pn-text" dir="auto" value={layer.text} maxLength={500} aria-label="متن" data-testid="text-input" placeholder="متنِ خود را بنویسید…"
          onChange={(e) => { ed.live({ text: e.target.value }); idle.schedule("متن"); }} onBlur={idle.flush}
        />
        <div className="pn-pair">
          <label className="ws-field" style={{ margin: 0 }}>
            <span>قلم</span>
            <Select className="pn-select-full" value={layer.font} aria-label="قلم" data-testid="text-font" onChange={(e) => ed.apply("قلمِ متن", { font: e.target.value })}>
              {fonts.length === 0 && <option value={layer.font}>وزیرمتن</option>}
              {fonts.map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}
            </Select>
          </label>
          <label className="ws-field" style={{ margin: 0 }}>
            <span>ضخامت</span>
            <Select className="pn-select-full" value={layer.weight} aria-label="ضخامتِ قلم" data-testid="text-weight" onChange={(e) => ed.apply("ضخامتِ قلم", { weight: Number(e.target.value) })}>
              {weights.map((w) => <option key={w} value={w}>{fa(w)} {WEIGHT_NAME[w] ?? ""}</option>)}
            </Select>
          </label>
        </div>
        <Num label="اندازه (٪ پهنای عکس)" value={layer.size * 100} min={0.5} max={50} step={0.5} testId="text-size"
          onLive={(v) => ed.live({ size: v / 100 })} onEnd={() => ed.end("اندازهٔ متن")} fmt={(v) => `${fa(round(v, 1))}٪`} />
        <ColorRow label="رنگِ متن" value={layer.color} testId="text-color" onLive={(v) => { ed.live({ color: v }); idle.schedule("رنگِ متن"); }} onEnd={idle.flush} />
        <Seg label="تراز" value={layer.align} onPick={(v) => ed.apply("ترازِ متن", { align: v })}
          options={[{ value: "right", label: "راست" }, { value: "center", label: "وسط" }, { value: "left", label: "چپ" }]} />
        <Seg label="جهت" value={layer.dir} onPick={(v) => ed.apply("جهتِ متن", { dir: v })}
          options={[{ value: "auto", label: "خودکار" }, { value: "rtl", label: "راست‌به‌چپ" }, { value: "ltr", label: "چپ‌به‌راست" }]} />
        <Num label="فاصلهٔ خط‌ها" value={layer.line_height} min={0.8} max={3} step={0.05} onLive={(v) => ed.live({ line_height: v })} onEnd={() => ed.end("فاصلهٔ خط‌ها")}
          fmt={(v) => fa(round(v, 2))} onReset={() => ed.apply("فاصلهٔ خط‌ها", { line_height: 1.3 })} />
        <Num label="فاصلهٔ حروف (em)" value={layer.letter_spacing} min={-0.1} max={1} step={0.01} onLive={(v) => ed.live({ letter_spacing: v })} onEnd={() => ed.end("فاصلهٔ حروف")}
          fmt={(v) => fa(round(v, 2))} onReset={() => ed.apply("فاصلهٔ حروف", { letter_spacing: 0 })} />
        <Num label="پهنای کادر (۰ = خودکار)" value={layer.width * 100} min={0} max={100} step={1} onLive={(v) => ed.live({ width: v / 100 })} onEnd={() => ed.end("پهنای کادر")}
          fmt={(v) => (v < 0.5 ? "خودکار" : `${fa(round(v, 0))}٪`)} />
        <RotationSlider layer={layer} ed={ed} />
      </Sub>

      <Sub title="دورِ حروف (Stroke)" right={<Check checked={!!st} testId="text-stroke" onChange={(v) => ed.apply("دورِ حروف", { stroke: v ? { w: 0.06, color: "#000000" } : null })}>فعال</Check>}>
        {st && (
          <>
            <Num label="ضخامت (٪ اندازهٔ قلم)" value={st.w * 100} min={0} max={30} step={0.5} fmt={(v) => `${fa(round(v, 1))}٪`}
              onLive={(v) => ed.live({ stroke: { ...st, w: v / 100 } })} onEnd={() => ed.end("ضخامتِ دور")} />
            <ColorRow label="رنگ" value={st.color} onLive={(v) => { ed.live({ stroke: { ...st, color: v } }); idle.schedule("رنگِ دور"); }} onEnd={idle.flush} />
          </>
        )}
      </Sub>

      <Sub title="سایه" right={<Check checked={!!sh} testId="text-shadow" onChange={(v) => ed.apply("سایهٔ متن", { shadow: v ? { color: "#000000", opacity: 0.5, blur: 0.08, dx: 0.03, dy: 0.03 } : null })}>فعال</Check>}>
        {sh && (
          <>
            <ColorRow label="رنگ" value={sh.color} onLive={(v) => { ed.live({ shadow: { ...sh, color: v } }); idle.schedule("رنگِ سایه"); }} onEnd={idle.flush} />
            <Num label="شدت" value={sh.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ shadow: { ...sh, opacity: v / 100 } })} onEnd={() => ed.end("شدتِ سایه")} />
            <Num label="محوشدگی" value={sh.blur * 100} min={0} max={50} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ shadow: { ...sh, blur: v / 100 } })} onEnd={() => ed.end("محوشدگیِ سایه")} />
            <Num label="جابه‌جاییِ افقی" value={sh.dx * 100} min={-30} max={30} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ shadow: { ...sh, dx: v / 100 } })} onEnd={() => ed.end("جابه‌جاییِ سایه")} />
            <Num label="جابه‌جاییِ عمودی" value={sh.dy * 100} min={-30} max={30} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ shadow: { ...sh, dy: v / 100 } })} onEnd={() => ed.end("جابه‌جاییِ سایه")} />
          </>
        )}
      </Sub>

      <Sub title="زمینهٔ کادر" right={<Check checked={!!bx} testId="text-box" onChange={(v) => ed.apply("زمینهٔ متن", { box: v ? { color: "#000000", opacity: 0.6, pad: 0.4, radius: 0.3 } : null })}>فعال</Check>}>
        {bx && (
          <>
            <ColorRow label="رنگ" value={bx.color} onLive={(v) => { ed.live({ box: { ...bx, color: v } }); idle.schedule("رنگِ زمینه"); }} onEnd={idle.flush} />
            <Num label="شدت" value={bx.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ box: { ...bx, opacity: v / 100 } })} onEnd={() => ed.end("شدتِ زمینه")} />
            <Num label="حاشیهٔ داخلی" value={bx.pad * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ box: { ...bx, pad: v / 100 } })} onEnd={() => ed.end("حاشیهٔ زمینه")} />
            <Num label="گردیِ گوشه" value={bx.radius * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ box: { ...bx, radius: v / 100 } })} onEnd={() => ed.end("گردیِ زمینه")} />
          </>
        )}
      </Sub>

      <Sub title="تکرار روی کلِ عکس (واترمارک)" right={<Check checked={!!tl} testId="text-tile" onChange={(v) => ed.apply("تکرارِ متن", { tile: v ? { angle: 28, gap: 1.6 } : null })}>فعال</Check>}>
        {tl ? (
          <>
            <Num label="زاویه" value={tl.angle} min={-90} max={90} step={1} fmt={(v) => `${fa(round(v, 0))}°`} onLive={(v) => ed.live({ tile: { ...tl, angle: v } })} onEnd={() => ed.end("زاویهٔ تکرار")} />
            <Num label="فاصله" value={tl.gap} min={1} max={4} step={0.1} fmt={(v) => fa(round(v, 1))} onLive={(v) => ed.live({ tile: { ...tl, gap: v } })} onEnd={() => ed.end("فاصلهٔ تکرار")} />
            <p className="pn-hint">در حالتِ تکرار، جایگاه و چرخشِ لایه اثر ندارد.</p>
          </>
        ) : null}
      </Sub>
    </>
  );
}

// ───────────────────────────── شکل

function ShapeInspector({ layer, hist }: { layer: ShapeLayer; hist: Hist }) {
  const ed = useEdit<ShapeLayer>(hist, layer.id, "shape");
  const idle = useIdleEnd(hist);
  const fill = layer.fill;
  const kind = fill ? fill.type : "none";
  const shapeName = layer.shape === "rect" ? "مستطیل" : layer.shape === "ellipse" ? "بیضی" : "خط";
  return (
    <>
      <Sub title={`شکل: ${shapeName}`}>
        {layer.shape !== "line" && (
          <>
            <Seg label="پرکردن" value={kind}
              onPick={(v) => ed.apply("پرکردنِ شکل", { fill: v === "none" ? null : v === "solid" ? { type: "solid", color: "#ffffff", opacity: 1 } : { type: "gradient", c0: "#7c5cff", c1: "#22d3ee", angle: 90 } })}
              options={[{ value: "none", label: "بدونِ پر" }, { value: "solid", label: "رنگِ ساده" }, { value: "gradient", label: "شیب" }]} />
            {fill?.type === "solid" && (
              <>
                <ColorRow label="رنگ" value={fill.color} onLive={(v) => { ed.live({ fill: { ...fill, color: v } }); idle.schedule("رنگِ شکل"); }} onEnd={idle.flush} />
                <Num label="شفافیتِ پر" value={fill.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ fill: { ...fill, opacity: v / 100 } })} onEnd={() => ed.end("شفافیتِ پر")} />
              </>
            )}
            {fill?.type === "gradient" && (
              <>
                <ColorRow label="رنگِ اول" value={fill.c0} onLive={(v) => { ed.live({ fill: { ...fill, c0: v } }); idle.schedule("رنگِ شیب"); }} onEnd={idle.flush} />
                <ColorRow label="رنگِ دوم" value={fill.c1} onLive={(v) => { ed.live({ fill: { ...fill, c1: v } }); idle.schedule("رنگِ شیب"); }} onEnd={idle.flush} />
                <Num label="زاویهٔ شیب" value={fill.angle} min={0} max={360} step={1} fmt={(v) => `${fa(round(v, 0))}°`} onLive={(v) => ed.live({ fill: { ...fill, angle: v } })} onEnd={() => ed.end("زاویهٔ شیب")} />
              </>
            )}
          </>
        )}
        <Check checked={!!layer.stroke} onChange={(v) => ed.apply("دورِ شکل", { stroke: v ? { color: "#ffffff", w: 0.006 } : null })}>خطِ دور</Check>
        {layer.stroke && (
          <>
            <ColorRow label="رنگِ خط" value={layer.stroke.color} onLive={(v) => { ed.live({ stroke: { ...layer.stroke!, color: v } }); idle.schedule("رنگِ خط"); }} onEnd={idle.flush} />
            <Num label="ضخامتِ خط (٪ پهنای عکس)" value={layer.stroke.w * 100} min={0} max={8} step={0.1} fmt={(v) => `${fa(round(v, 1))}٪`}
              onLive={(v) => ed.live({ stroke: { ...layer.stroke!, w: v / 100 } })} onEnd={() => ed.end("ضخامتِ خط")} />
          </>
        )}
      </Sub>
      <Sub title="اندازه">
        <Num label="پهنا (٪ پهنای عکس)" value={layer.w * 100} min={0.5} max={100} step={0.5} fmt={(v) => `${fa(round(v, 1))}٪`} onLive={(v) => ed.live({ w: v / 100 })} onEnd={() => ed.end("پهنای شکل")} />
        {layer.shape !== "line" && (
          <Num label="ارتفاع (٪ پهنای عکس)" value={layer.h * 100} min={0.5} max={100} step={0.5} fmt={(v) => `${fa(round(v, 1))}٪`} onLive={(v) => ed.live({ h: v / 100 })} onEnd={() => ed.end("ارتفاعِ شکل")} />
        )}
        {layer.shape === "rect" && (
          <Num label="گردیِ گوشه" value={layer.radius * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} onLive={(v) => ed.live({ radius: v / 100 })} onEnd={() => ed.end("گردیِ گوشه")} />
        )}
        <RotationSlider layer={layer} ed={ed} />
      </Sub>
    </>
  );
}

// ───────────────────────────── تصویر

function ImageInspector({ layer, hist, assets, storeLogo }: { layer: ImageLayer; hist: Hist; assets: Asset[]; storeLogo?: string | null }) {
  const ed = useEdit<ImageLayer>(hist, layer.id, "image");
  const [pick, setPick] = useState(false);
  const src = layer.src;
  if (src.kind === "paint") {
    return (
      <Sub title="لایهٔ نقاشی">
        <p className="pn-hint" data-testid="paint-source">روی این لایه با «قلمِ نقاشی» (N)، مداد (D) و پاک‌کن (Z) بکشید؛ سطلِ رنگ (U) ناحیه را پر می‌کند. لایه همیشه کلِ بوم را می‌پوشاند؛ شفافیت، حالتِ ترکیب و ماسکش در همین پنل است.</p>
      </Sub>
    );
  }
  const cur = src.kind === "asset" ? assets.find((a) => a.id === src.asset) : null;
  return (
    <>
      <Sub title="منبعِ تصویر">
        <p className="pn-hint" data-testid="image-source">{layer.src.kind === "logo" ? "لوگوی فروشگاه" : cur ? cur.title : "تصویری از کتابخانه"}</p>
        <div className="pn-actions">
          <button type="button" className="pn-btn" onClick={() => setPick((v) => !v)} aria-expanded={pick}>جایگزینی…</button>
          {storeLogo && <button type="button" className="pn-btn" onClick={() => ed.apply("لوگوی فروشگاه", { src: { kind: "logo" } })}>لوگوی فروشگاه</button>}
        </div>
        {pick && (
          <div className="pn-pick" data-testid="image-replace-pick">
            {assets.map((a) => (
              <button key={a.id} type="button" title={a.title} aria-label={a.title} onClick={() => { setPick(false); ed.apply("جایگزینیِ تصویر", { src: { kind: "asset", asset: a.id } }); }}>
                <img src={a.thumb} alt="" />
              </button>
            ))}
          </div>
        )}
      </Sub>
      <Sub title="اندازه و چرخش">
        <Num label="پهنا (٪ پهنای عکس)" value={layer.w * 100} min={1} max={150} step={0.5} fmt={(v) => `${fa(round(v, 1))}٪`} testId="image-width" onLive={(v) => ed.live({ w: v / 100 })} onEnd={() => ed.end("پهنای تصویر")} />
        <RotationSlider layer={layer} ed={ed} />
        <div className="pn-actions">
          <button type="button" className={`pn-btn ${layer.flip_h ? "is-on" : ""}`} aria-pressed={layer.flip_h} onClick={() => ed.apply("قرینهٔ افقی", { flip_h: !layer.flip_h })}>قرینهٔ افقی</button>
          <button type="button" className={`pn-btn ${layer.flip_v ? "is-on" : ""}`} aria-pressed={layer.flip_v} onClick={() => ed.apply("قرینهٔ عمودی", { flip_v: !layer.flip_v })}>قرینهٔ عمودی</button>
        </div>
      </Sub>
    </>
  );
}

// ───────────────────────────── لایهٔ تنظیم (اصلاحِ محلی)

const ADJUST_SECTIONS = ["basic", "curves", "hsl", "grading", "detail"];

function AdjustInspector({ layer, hist, kit }: { layer: AdjustLayer; hist: Hist; kit: Kit }) {
  const [open, setOpen] = useState<Record<string, boolean>>({ basic: true });
  const id = layer.id;
  const def = (key: string) => kit.params.find((p) => p.key === key)?.default ?? 0;
  const mapAdj = (fn: (a: Adjust) => Adjust) => (s: ProState): ProState => ({
    ...s, layers: s.layers.map((l) => (l.id === id && l.type === "adjust" ? { ...l, adjust: fn(l.adjust) } : l)),
  });
  const live = (key: string, v: number) =>
    hist.live(mapAdj((a) => {
      const n = { ...a };
      if (Math.abs(v - def(key)) < 1e-9) delete n[key];
      else n[key] = v;
      return n;
    }));
  const reset = (keys: string[], label: string) =>
    hist.apply(label, mapAdj((a) => {
      const n = { ...a };
      keys.forEach((k) => delete n[k]);
      return n;
    }));
  const hasCurve = !!(layer.curve.rgb || layer.curve.red || layer.curve.green || layer.curve.blue);
  const setCurve = (c: Curve, commit: boolean) => {
    hist.live((s) => ({ ...s, layers: s.layers.map((l) => (l.id === id && l.type === "adjust" ? { ...l, curve: c } : l)) }));
    if (commit) hist.end("منحنیِ لایه");
  };
  const touched = Object.keys(layer.adjust).length + (hasCurve ? 1 : 0);
  return (
    <div data-testid="adjust-inspector">
      <p className="pn-hint">این لایه فقط روی آنچه زیرش است اثر می‌گذارد؛ با ماسک (قلم، شیبِ خطی یا شعاعی) اثرش را محدود کنید و با «شدتِ اثر» کم‌وزیادش کنید.</p>
      <div className="pn-actions" style={{ marginBottom: 6 }}>
        <button type="button" className="pn-btn" disabled={!touched} data-testid="adjust-reset" onClick={() => hist.apply("بازنشانیِ لایهٔ تنظیم", (s) => ({ ...s, layers: s.layers.map((l) => (l.id === id && l.type === "adjust" ? { ...l, adjust: {}, curve: {} } : l)) }))}>
          بازنشانیِ همه
        </button>
      </div>
      {SECTIONS.filter((sec) => ADJUST_SECTIONS.includes(sec.key)).map((sec) => (
        <div key={sec.key} className="ws-acc" data-section={sec.key}>
          <button type="button" className="ws-acc-head" onClick={() => setOpen((o) => ({ ...o, [sec.key]: !o[sec.key] }))} aria-expanded={!!open[sec.key]}>
            <span>{sec.title}</span>
            {sec.groups.some((g) => kit.params.some((p) => p.group === g && p.key in layer.adjust)) && <i className="ws-dot" />}
            {sec.key === "curves" && hasCurve && <i className="ws-dot" />}
          </button>
          {open[sec.key] && (
            <>
              {sec.key === "curves" && <div className="mb-3"><CurveEditor value={layer.curve} onChange={setCurve} /></div>}
              <SectionBody kit={kit} section={sec} adjust={layer.adjust} onLive={live} onEnd={(l) => hist.end(l)} onReset={reset} />
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ───────────────────────────── روتوش

function RetouchInspector({ layer, hist }: { layer: RetouchLayer; hist: Hist }) {
  const id = layer.id;
  return (
    <Sub title="روتوش">
      <p className="pn-hint" data-testid="retouch-count">{fa(layer.strokes.length)} ضربه روی این لایه هست. با ابزارِ کلون (S) و قلمِ ترمیم روی عکس نقاشی کنید؛ برای انتخابِ منبع Alt+کلیک.</p>
      <Button size="sm" variant="secondary" disabled={!layer.strokes.length} data-testid="retouch-clear"
        onClick={() => hist.apply("پاک کردنِ ضربه‌ها", (s) => ({ ...s, layers: s.layers.map((l) => (l.id === id && l.type === "retouch" ? { ...l, strokes: [] } : l)) }))}>
        پاک کردنِ همهٔ ضربه‌ها
      </Button>
    </Sub>
  );
}

// ───────────────────────────── ریشه

export default function LayerInspector(props: LayerInspectorProps) {
  const { layer, hist, fonts, kit, assets } = props;
  if (!layer) return <p className="pn-hint" data-testid="inspector-empty">یک لایه را انتخاب کنید تا ویژگی‌هایش این‌جا بیاید.</p>;
  const body = (() => {
    switch (layer.type) {
      case "text": return <TextInspector layer={layer} hist={hist} fonts={fonts} />;
      case "shape": return <ShapeInspector layer={layer} hist={hist} />;
      case "image": return <ImageInspector layer={layer} hist={hist} assets={assets} storeLogo={props.storeLogo} />;
      case "adjust": return <AdjustInspector layer={layer} hist={hist} kit={kit} />;
      case "retouch": return <RetouchInspector layer={layer} hist={hist} />;
      case "redeye": return <RedeyeInspector layer={layer} hist={hist} />;
      case "group": return <GroupInspector layer={layer} state={props.state} hist={hist} actions={props.actions} />;
      default: return <p className="pn-hint">تنظیم‌های عکس در زبانهٔ «تنظیم» است؛ این‌جا فقط شفافیت، حالتِ ترکیب و ماسکِ لایهٔ عکس را می‌توان عوض کرد.</p>;
    }
  })();
  const transformable = (layer.type === "image" && layer.src.kind !== "paint") || layer.type === "text" || layer.type === "shape";
  const locked = effectivelyLocked(props.state.layers, layer);
  return (
    <div className="pn-root" data-testid="layer-inspector" data-layer-id={layer.id} data-type={layer.type}>
      <div className="pn-head">
        <span className="pn-title">{layer.name}</span>
        {locked && <span className="pn-count">{layer.locked ? "قفل است" : "قفلِ گروه"}</span>}
      </div>
      <fieldset className="pn-fieldset" disabled={locked}>
        <div className={locked ? "pn-locked" : undefined}>
          {body}
          {transformable && <FxBlock layer={layer as ImageLayer | TextLayer | ShapeLayer} hist={hist} />}
          {transformable && (
            <TransformBlock layer={layer as ImageLayer | TextLayer | ShapeLayer} hist={hist} layerBox={props.layerBox} canvasAspect={props.canvasAspect} />
          )}
        </div>
      </fieldset>
    </div>
  );
}
