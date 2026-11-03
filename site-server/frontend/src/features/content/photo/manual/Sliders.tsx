import { useState } from "react";

import { fa } from "../../../../components/ui";
import type { Kit, KitParam } from "../api";
import type { Adjust } from "./engine";
import type { Section } from "./model";

/** یک لغزندهٔ Camera Raw: کشیدن ⇐ پیش‌نمایشِ زنده؛ رها کردن ⇐ ثبت در تاریخچه؛ دوبار کلیک روی نام ⇐ بازنشانی. */
export function ParamSlider({
  p,
  value,
  onLive,
  onEnd,
  onReset,
}: {
  p: KitParam;
  value: number;
  onLive: (v: number) => void;
  onEnd: () => void;
  onReset: () => void;
}) {
  const changed = Math.abs(value - p.default) > 1e-9;
  const gradient =
    p.key === "temperature"
      ? "linear-gradient(90deg,#3b82f6,#e5e7eb,#f59e0b)"
      : p.key === "tint"
        ? "linear-gradient(90deg,#22c55e,#e5e7eb,#d946ef)"
        : undefined;
  return (
    <label className="ws-slider" title={p.help} data-param={p.key}>
      <span className="ws-slider-head">
        <span className={changed ? "is-changed" : ""} onDoubleClick={onReset}>
          {p.title}
        </span>
        <span className="ws-slider-val" dir="ltr">
          {fa(Math.round(value * 100) / 100)}
          {p.unit ? ` ${p.unit}` : ""}
        </span>
      </span>
      <input
        type="range"
        min={p.min}
        max={p.max}
        step={p.step}
        value={value}
        aria-label={p.title}
        style={gradient ? { background: gradient } : undefined}
        onChange={(e) => onLive(Number(e.target.value))}
        onPointerUp={onEnd}
        onKeyUp={onEnd}
        onBlur={onEnd}
        onDoubleClick={onReset}
      />
    </label>
  );
}

const HSL_TABS = [
  { key: "Hue", title: "فام" },
  { key: "Sat", title: "اشباع" },
  { key: "Lum", title: "روشنی" },
];

/** محتوای یک بخشِ پنل (Basic، HSL، …) با بازنشانیِ همان بخش */
export function SectionBody({
  kit,
  section,
  adjust,
  onLive,
  onEnd,
  onReset,
}: {
  kit: Kit;
  section: Section;
  adjust: Adjust;
  onLive: (key: string, v: number) => void;
  onEnd: (label: string) => void;
  onReset: (keys: string[], label: string) => void;
}) {
  const [hslTab, setHslTab] = useState("Hue");
  const get = (p: KitParam) => (p.key in adjust ? adjust[p.key] : p.default);
  return (
    <div className="ws-section-body">
      {section.groups.map((gk) => {
        const group = kit.groups.find((g) => g.key === gk);
        let params = kit.params.filter((p) => p.group === gk);
        if (gk === "hsl") params = params.filter((p) => p.key.endsWith(hslTab));
        const allKeys = kit.params.filter((p) => p.group === gk).map((p) => p.key);
        return (
          <div key={gk} className="ws-group" data-group={gk}>
            {section.groups.length > 1 && <div className="ws-group-title">{group?.title}</div>}
            {gk === "hsl" && (
              <div className="mb-2 flex gap-1">
                {HSL_TABS.map((t) => (
                  <button key={t.key} type="button" className={`ws-chip ${hslTab === t.key ? "is-on" : ""}`} onClick={() => setHslTab(t.key)}>
                    {t.title}
                  </button>
                ))}
              </div>
            )}
            {params.map((p) => (
              <ParamSlider
                key={p.key}
                p={p}
                value={get(p)}
                onLive={(v) => onLive(p.key, v)}
                onEnd={() => onEnd(p.title)}
                onReset={() => onReset([p.key], `بازنشانیِ ${p.title}`)}
              />
            ))}
            {allKeys.some((k) => k in adjust) && (
              <button type="button" className="ws-link" onClick={() => onReset(allKeys, `بازنشانیِ ${group?.title ?? section.title}`)}>
                بازنشانیِ «{group?.title}»
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
