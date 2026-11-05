import { ReactNode, useEffect, useRef, useState } from "react";

import { fa } from "../../../../components/ui";
import "./controls.css";

/** دکمهٔ لوزیِ کلیدفریم کنارِ یک ویژگی: توخالی = بی‌کلید، نیمه = کلیدفریم دارد (ولی نه این‌جا)، پر = کلید درست در سرِ پخش */
export function KfDiamond({ has, here, onToggle, title }: { has: boolean; here: boolean; onToggle: () => void; title?: string }) {
  return (
    <button
      type="button"
      className={`kf-diamond ${has ? "has" : ""} ${here ? "here" : ""}`}
      title={title ?? (here ? "حذفِ کلیدفریم در این لحظه" : has ? "افزودنِ کلیدفریم در این لحظه" : "شروعِ انیمیشن (کلیدفریم)")}
      aria-label="کلیدفریم"
      aria-pressed={here}
      onClick={onToggle}
    />
  );
}

/** لغزنده با مقدار، دکمهٔ بازنشانی و (اختیاری) لوزیِ کلیدفریم. `onLive` هنگامِ کشیدن، `onEnd` هنگامِ رها شدن. */
export function Slider({
  label, value, min, max, step = 0.01, unit = "", def, onLive, onEnd, kf, digits = 2, fmt,
}: {
  label: string; value: number; min: number; max: number; step?: number; unit?: string; def?: number;
  onLive: (v: number) => void; onEnd: () => void;
  kf?: { has: boolean; here: boolean; onToggle: () => void };
  digits?: number;
  fmt?: (v: number) => string;
}) {
  const shown = fmt ? fmt(value) : `${fa(Math.round(value * 10 ** digits) / 10 ** digits)}${unit}`;
  const changed = def !== undefined && Math.abs(value - def) > 1e-6;
  return (
    <label className="ws-slider pro-slider" data-field={label}>
      <span className="ws-slider-head">
        <span className={changed ? "is-changed" : ""}>{label}</span>
        <span className="pro-slider-tools">
          {kf && <KfDiamond {...kf} />}
          {def !== undefined && changed && (
            <button type="button" className="pro-reset" title="بازنشانی" aria-label={`بازنشانی ${label}`} onClick={() => { onLive(def); onEnd(); }}>↺</button>
          )}
          <span className="ws-slider-val" dir="ltr">{shown}</span>
        </span>
      </span>
      <input
        type="range" min={min} max={max} step={step} value={Number.isFinite(value) ? value : 0} aria-label={label}
        onChange={(e) => onLive(Number(e.target.value))} onPointerUp={onEnd} onKeyUp={onEnd} onBlur={onEnd}
        onDoubleClick={() => { if (def !== undefined) { onLive(def); onEnd(); } }}
      />
    </label>
  );
}

export function Num({ label, value, step = 0.1, min = 0, max, onChange }: { label: string; value: number; step?: number; min?: number; max?: number; onChange: (v: number) => void }) {
  return (
    <label className="ws-field">
      <span>{label}</span>
      <input className="u-input" type="number" step={step} min={min} max={max} value={Math.round(value * 1000) / 1000} aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

/** بخشِ تاشو (accordion) */
export function Section({ title, children, defaultOpen = false, badge, testId }: { title: string; children: ReactNode; defaultOpen?: boolean; badge?: ReactNode; testId?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  const box = useRef<HTMLElement>(null);
  // «منوی کامل» و «جستجوی ابزار» با این رویداد یک بخشِ تاشو را باز می‌کنند و به آن می‌روند (data-testid = نشانی)
  useEffect(() => {
    if (!testId) return;
    const on = (e: Event) => {
      if ((e as CustomEvent<{ testId?: string }>).detail?.testId !== testId) return;
      setOpen(true);
      window.setTimeout(() => box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 60);
    };
    window.addEventListener("nm-open-section", on);
    return () => window.removeEventListener("nm-open-section", on);
  }, [testId]);
  return (
    <section ref={box} className="ws-acc pro-sec" data-testid={testId} data-open={open ? "1" : "0"}>
      <button type="button" className="ws-acc-head" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span>{title}</span>
        {badge}
        <span aria-hidden>{open ? "▾" : "◂"}</span>
      </button>
      {open && <div className="pro-sec-body">{children}</div>}
    </section>
  );
}

/** ردیفِ چیپ‌ها (تک‌انتخابی) */
export function Chips<T extends string>({ value, options, onPick }: { value: T | undefined; options: { key: T; title: string }[]; onPick: (k: T) => void }) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button key={o.key} type="button" className={`ws-chip ${value === o.key ? "is-on" : ""}`} aria-pressed={value === o.key} onClick={() => onPick(o.key)}>{o.title}</button>
      ))}
    </div>
  );
}

export function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="ws-check"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /> {label}</label>
  );
}

export function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="ws-field pro-color"><span>{label}</span>
      <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : "#ffffff"} aria-label={label} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
