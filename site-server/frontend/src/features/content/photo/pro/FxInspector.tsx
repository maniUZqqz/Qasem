import { ReactNode, useCallback, useEffect, useRef } from "react";

import { Select, fa } from "../../../../components/ui";
import type { Hist, ProActions } from "./panelTypes";
import { descendantIds } from "./tree";
import {
  BLEND_MODES, BlendMode, FxGlow, FxShadow, FxStroke, GroupLayer, ImageLayer, Layer, LayerFx, ProState, ShapeLayer, TextLayer,
} from "./types";
import "./panels.css";

/** بازرسِ «جلوه‌های لایه» (سایه، درخشش، دورخطِ بیرونی) برای تصویر/متن/شکل + بازرسِ گروه. هر دو با پیش‌نمایشِ زنده (hist.live / hist.end). */

const round = (v: number, d = 2) => Math.round(v * 10 ** d) / 10 ** d;

export const DEFAULT_SHADOW: FxShadow = { color: "#000000", opacity: 0.5, blur: 0.012, dx: 0.01, dy: 0.01 };
export const DEFAULT_STROKE: FxStroke = { color: "#ffffff", w: 0.004, opacity: 1 };
export const DEFAULT_GLOW: FxGlow = { color: "#ffd479", opacity: 0.8, blur: 0.02, size: 0.006 };

function Num({
  label, value, min, max, step, onLive, onEnd, fmt, testId,
}: {
  label: string; value: number; min: number; max: number; step: number; onLive: (v: number) => void; onEnd: () => void; fmt?: (v: number) => string; testId?: string;
}) {
  return (
    <label className="ws-slider">
      <span className="ws-slider-head">
        <span>{label}</span>
        <span className="ws-slider-val" dir="ltr">{fmt ? fmt(value) : fa(round(value))}</span>
      </span>
      <input
        type="range" min={min} max={max} step={step} value={value} aria-label={label} data-testid={testId}
        onChange={(e) => onLive(Number(e.target.value))} onPointerUp={onEnd} onKeyUp={onEnd} onBlur={onEnd}
      />
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

function Sub({ title, children, right }: { title: string; children?: ReactNode; right?: ReactNode }) {
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

function Check({ checked, onChange, children, testId }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; testId?: string }) {
  return (
    <label className="pn-check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} data-testid={testId} />
      <span>{children}</span>
    </label>
  );
}

/** پایانِ ویرایش بعد از چند لحظه بی‌کاری (برای انتخابگرِ رنگ و نام) */
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

const pct = (v: number) => `${fa(round(v, 1))}٪`;

type FxHost = ImageLayer | TextLayer | ShapeLayer;
const EMPTY: LayerFx = { shadow: null, stroke: null, glow: null };

/** «جلوه‌های لایه»: سایه، درخشش، دورخط — پیش از حالتِ ترکیب/پیدایی/ماسک در خودِ لایه پخته می‌شوند؛ طول‌ها کسری از پهنای عکس */
export function FxBlock({ layer, hist }: { layer: FxHost; hist: Hist }) {
  const id = layer.id;
  const idle = useIdleEnd(hist);
  const fx: LayerFx = layer.fx ?? EMPTY;
  const put = (next: LayerFx) => (s: ProState): ProState => ({
    ...s,
    layers: s.layers.map((l) => (l.id === id && (l.type === "image" || l.type === "text" || l.type === "shape")
      ? ({ ...l, fx: next.shadow || next.stroke || next.glow ? next : null } as Layer) : l)),
  });
  const live = (next: LayerFx) => hist.live(put(next));
  const apply = (label: string, next: LayerFx) => hist.apply(label, put(next));
  const sh = fx.shadow;
  const st = fx.stroke;
  const gl = fx.glow;
  return (
    <div className="pn-fxbox" data-testid="fx-block">
      <div className="pn-sub-head" style={{ marginBottom: 6 }}><span>جلوه‌های لایه</span></div>

      <Sub title="سایهٔ لایه" right={<Check checked={!!sh} testId="fx-shadow" onChange={(v) => apply("سایهٔ لایه", { ...fx, shadow: v ? DEFAULT_SHADOW : null })}>فعال</Check>}>
        {sh && (
          <>
            <ColorRow label="رنگ" value={sh.color} testId="fx-shadow-color" onLive={(v) => { live({ ...fx, shadow: { ...sh, color: v } }); idle.schedule("رنگِ سایه"); }} onEnd={idle.flush} />
            <Num label="شدت" value={sh.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} testId="fx-shadow-opacity"
              onLive={(v) => live({ ...fx, shadow: { ...sh, opacity: v / 100 } })} onEnd={() => hist.end("شدتِ سایه")} />
            <Num label="محوشدگی (٪ پهنای عکس)" value={sh.blur * 100} min={0} max={10} step={0.1} fmt={pct} testId="fx-shadow-blur"
              onLive={(v) => live({ ...fx, shadow: { ...sh, blur: v / 100 } })} onEnd={() => hist.end("محوشدگیِ سایه")} />
            <Num label="جابه‌جاییِ افقی" value={sh.dx * 100} min={-10} max={10} step={0.1} fmt={pct} testId="fx-shadow-dx"
              onLive={(v) => live({ ...fx, shadow: { ...sh, dx: v / 100 } })} onEnd={() => hist.end("جابه‌جاییِ سایه")} />
            <Num label="جابه‌جاییِ عمودی" value={sh.dy * 100} min={-10} max={10} step={0.1} fmt={pct} testId="fx-shadow-dy"
              onLive={(v) => live({ ...fx, shadow: { ...sh, dy: v / 100 } })} onEnd={() => hist.end("جابه‌جاییِ سایه")} />
          </>
        )}
      </Sub>

      <Sub title="درخششِ لایه" right={<Check checked={!!gl} testId="fx-glow" onChange={(v) => apply("درخششِ لایه", { ...fx, glow: v ? DEFAULT_GLOW : null })}>فعال</Check>}>
        {gl && (
          <>
            <ColorRow label="رنگ" value={gl.color} testId="fx-glow-color" onLive={(v) => { live({ ...fx, glow: { ...gl, color: v } }); idle.schedule("رنگِ درخشش"); }} onEnd={idle.flush} />
            <Num label="شدت" value={gl.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} testId="fx-glow-opacity"
              onLive={(v) => live({ ...fx, glow: { ...gl, opacity: v / 100 } })} onEnd={() => hist.end("شدتِ درخشش")} />
            <Num label="پخش‌شدگی (محو، ٪ پهنای عکس)" value={gl.blur * 100} min={0} max={10} step={0.1} fmt={pct} testId="fx-glow-blur"
              onLive={(v) => live({ ...fx, glow: { ...gl, blur: v / 100 } })} onEnd={() => hist.end("پخش‌شدگیِ درخشش")} />
            <Num label="اندازه (گسترشِ لبه)" value={gl.size * 100} min={0} max={3} step={0.05} fmt={(v) => `${fa(round(v, 2))}٪`} testId="fx-glow-size"
              onLive={(v) => live({ ...fx, glow: { ...gl, size: v / 100 } })} onEnd={() => hist.end("اندازهٔ درخشش")} />
          </>
        )}
      </Sub>

      <Sub title="دورِ لایه (خطِ بیرونی)" right={<Check checked={!!st} testId="fx-stroke" onChange={(v) => apply("دورِ لایه", { ...fx, stroke: v ? DEFAULT_STROKE : null })}>فعال</Check>}>
        {st && (
          <>
            <ColorRow label="رنگ" value={st.color} testId="fx-stroke-color" onLive={(v) => { live({ ...fx, stroke: { ...st, color: v } }); idle.schedule("رنگِ دور"); }} onEnd={idle.flush} />
            <Num label="ضخامت (٪ پهنای عکس)" value={st.w * 100} min={0} max={3} step={0.05} fmt={(v) => `${fa(round(v, 2))}٪`} testId="fx-stroke-w"
              onLive={(v) => live({ ...fx, stroke: { ...st, w: v / 100 } })} onEnd={() => hist.end("ضخامتِ دورِ لایه")} />
            <Num label="شدت" value={st.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} testId="fx-stroke-opacity"
              onLive={(v) => live({ ...fx, stroke: { ...st, opacity: v / 100 } })} onEnd={() => hist.end("شدتِ دورِ لایه")} />
          </>
        )}
      </Sub>
      <p className="pn-hint">جلوه‌ها پیش از حالتِ ترکیب، شفافیت و ماسک در خودِ لایه ساخته می‌شوند و با لایه می‌چرخند.</p>
    </div>
  );
}

/** بازرسِ گروه: نام، شفافیت، حالتِ ترکیب، بسته/باز؛ ماسکِ گروه از نوارِ زیرِ فهرستِ لایه‌ها (مثلِ هر لایه) */
export function GroupInspector({ layer, state, hist, actions }: { layer: GroupLayer; state: ProState; hist: Hist; actions: ProActions }) {
  const id = layer.id;
  const idle = useIdleEnd(hist);
  const kids = descendantIds(state.layers, id).length;
  const map = (fn: (l: GroupLayer) => GroupLayer) => (s: ProState): ProState => ({
    ...s, layers: s.layers.map((l) => (l.id === id && l.type === "group" ? fn(l) : l)),
  });
  return (
    <div data-testid="group-inspector">
      <Sub title="گروه" right={<span className="pn-count" data-testid="group-count">{fa(kids)} لایه</span>}>
        <label className="ws-field" style={{ margin: 0 }}>
          <span>نام</span>
          <input
            className="u-input" value={layer.name} maxLength={60} aria-label="نامِ گروه" data-testid="group-name"
            onChange={(e) => { hist.live(map((l) => ({ ...l, name: e.target.value.slice(0, 60) }))); idle.schedule("نامِ گروه"); }} onBlur={idle.flush}
          />
        </label>
        <Num label="شفافیتِ گروه" value={layer.opacity * 100} min={0} max={100} step={1} fmt={(v) => `${fa(round(v, 0))}٪`} testId="group-opacity"
          onLive={(v) => hist.live(map((l) => ({ ...l, opacity: v / 100 })))} onEnd={() => hist.end("شفافیتِ گروه")} />
        <label className="ws-field" style={{ margin: 0 }}>
          <span>حالتِ ترکیبِ گروه</span>
          <Select className="pn-select-full" value={layer.blend} aria-label="حالتِ ترکیبِ گروه" data-testid="group-blend"
            onChange={(e) => hist.apply("حالتِ ترکیبِ گروه", map((l) => ({ ...l, blend: e.target.value as BlendMode })))}>
            {BLEND_MODES.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
          </Select>
        </label>
        <Check checked={!layer.collapsed} testId="group-open" onChange={(v) => actions.setCollapsed(id, !v)}>باز (لایه‌های داخل در فهرست دیده شوند)</Check>
        <div className="pn-actions" style={{ marginTop: 4 }}>
          <button type="button" className="pn-btn" data-testid="group-inspector-ungroup" disabled={layer.locked} onClick={() => actions.ungroup(id)}>بازکردنِ گروه</button>
        </div>
      </Sub>
      <p className="pn-hint">
        گروه جدا ترکیب می‌شود: لایه‌های داخلش اول با هم روی یک بومِ شفاف می‌نشینند و بعد کلِ گروه با شفافیت، حالتِ ترکیب و ماسکِ خودش روی بقیه می‌آید؛
        لایهٔ تنظیم یا روتوشِ داخلِ گروه فقط روی محتوای همان گروه اثر می‌گذارد. با ابزارِ جابه‌جایی (V) روی لایه‌های گروه بکشید تا همهٔ لایه‌ها با هم بروند.
        ماسکِ گروه را از «افزودنِ ماسک» (زیرِ فهرست) بسازید؛ قلمِ ماسک (B) روی گروه هم کار می‌کند.
      </p>
    </div>
  );
}
