import { useState } from "react";

import { Badge, Select, fa } from "../../../../components/ui";
import type { FontInfo } from "../api";
import type { DParamSpec, DReport, DStep, DTool } from "./api";
import { COLOR_FA, OPT_FA, PRIMARY, TOOL_ICON, paramText } from "./labels";

const TOKENS = ["auto", "text", "text_dim", "accent", "accent_text", "plate", "bg_a", "bg_b", "white", "black"];
const isHex = (v: unknown): v is string => typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v);

type Props = {
  step: DStep;
  tool: DTool | undefined;
  slots: { key: string; title: string }[];
  fonts: FontInfo[];
  report?: DReport[string];
  onChange: (s: DStep) => void;
};

/** یک مرحلهٔ طراحی: خاموش/روشن، دلیلِ فارسی، و ویرایشِ پارامترهای مهم (بقیه پشتِ «گزینه‌های بیشتر») */
export default function StepEditor({ step, tool, slots, fonts, report, onChange }: Props) {
  const [more, setMore] = useState(false);
  const primary = PRIMARY[step.tool] ?? [];
  const specs = tool?.params ?? [];
  const shown = specs.filter((p) => primary.includes(p.key));
  const rest = specs.filter((p) => !primary.includes(p.key) && !["adjust", "curve", "preset"].includes(p.type));
  const set = (key: string, v: unknown) => onChange({ ...step, params: { ...step.params, [key]: v } });
  const adjustN = Object.keys((step.params.adjust as Record<string, number>) ?? {}).length;

  return (
    <li className={`dz-step ${step.on ? "" : "is-off"} ${report && !report.ok && step.on ? "is-skip" : ""}`} data-step={step.id} data-tool={step.tool}>
      <div className="dz-step-head">
        <label className="dz-switch" title={step.on ? "این مرحله فعال است؛ برای حذف خاموشش کنید" : "این مرحله خاموش است"}>
          <input type="checkbox" checked={step.on} onChange={(e) => onChange({ ...step, on: e.target.checked })} aria-label={`مرحلهٔ «${step.title}»`} />
          <span />
        </label>
        <span className="dz-step-ico" aria-hidden="true">{TOOL_ICON[step.tool] ?? "•"}</span>
        <b className="dz-step-title">{step.title}</b>
        {step.ai && <Badge tone="info">پیشنهادِ هوش مصنوعی</Badge>}
        {tool?.deferred && <Badge tone="warn">دستی</Badge>}
      </div>
      {step.why && <p className="dz-step-why">{step.why}</p>}
      {report && step.on && report.note && <p className={`dz-step-note ${report.ok ? "" : "bad"}`}>{report.note}</p>}
      {step.on && (shown.length > 0 || adjustN > 0) && (
        <div className="dz-params">
          {adjustN > 0 && step.tool === "grade" && (
            <div className="dz-field wide">
              <span>لغزنده‌ها</span>
              <span className="dz-chips">
                {Object.entries(step.params.adjust as Record<string, number>).map(([k, v]) => (
                  <i key={k} className="dz-chip" dir="ltr">{k} {fa(v > 0 ? `+${v}` : String(v))}</i>
                ))}
              </span>
            </div>
          )}
          {shown.map((p) => (
            <Field key={p.key} spec={p} value={step.params[p.key]} slots={slots} fonts={fonts} onChange={(v) => set(p.key, v)} />
          ))}
          {rest.length > 0 && (
            <button type="button" className="dz-link" onClick={() => setMore((m) => !m)} aria-expanded={more}>
              {more ? "گزینه‌های کمتر" : "گزینه‌های بیشتر"}
            </button>
          )}
          {more && rest.map((p) => (
            <Field key={p.key} spec={p} value={step.params[p.key]} slots={slots} fonts={fonts} onChange={(v) => set(p.key, v)} />
          ))}
        </div>
      )}
    </li>
  );
}

function Field({ spec, value, slots, fonts, onChange }: { spec: DParamSpec; value: unknown; slots: { key: string; title: string }[]; fonts: FontInfo[]; onChange: (v: unknown) => void }) {
  const wide = spec.type === "str";
  const label = <span>{spec.title}</span>;
  if (spec.type === "bool") {
    return (
      <label className="dz-field check">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  }
  if (spec.type === "str") {
    const long = (spec.max_len ?? 0) > 60;
    return (
      <label className={`dz-field ${wide ? "wide" : ""}`}>
        {label}
        {long ? (
          <textarea className="u-input" rows={2} maxLength={spec.max_len ?? 200} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
        ) : (
          <input className="u-input" maxLength={spec.max_len ?? 90} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
        )}
      </label>
    );
  }
  if (spec.type === "num" || spec.type === "int") {
    const min = spec.min ?? 0;
    const max = spec.max ?? 1;
    const step = spec.type === "int" ? 1 : max - min > 20 ? 1 : 0.01;
    return (
      <label className="dz-field">
        {label}
        <span className="dz-range">
          <input type="range" min={min} max={max} step={step} value={Number(value ?? spec.default ?? 0)} onChange={(e) => onChange(Number(e.target.value))} aria-label={spec.title} />
          <b dir="ltr">{paramText(Number(value ?? 0))}</b>
        </span>
      </label>
    );
  }
  if (spec.type === "color") {
    const v = String(value ?? "auto");
    return (
      <label className="dz-field">
        {label}
        <span className="dz-color">
          <Select value={isHex(v) ? "#custom" : v} onChange={(e) => onChange(e.target.value === "#custom" ? "#d97706" : e.target.value)} aria-label={spec.title}>
            {TOKENS.map((t) => <option key={t} value={t}>{COLOR_FA[t]}</option>)}
            <option value="#custom">رنگِ دلخواه…</option>
          </Select>
          {isHex(v) && <input type="color" value={v} onChange={(e) => onChange(e.target.value)} aria-label="انتخابِ رنگ" />}
        </span>
      </label>
    );
  }
  if (spec.type === "font") {
    return (
      <label className="dz-field">
        {label}
        <Select value={String(value ?? "vazirmatn")} onChange={(e) => onChange(e.target.value)} aria-label={spec.title}>
          {(fonts.length ? fonts : [{ key: "vazirmatn", title: "وزیرمتن" } as FontInfo]).map((f) => <option key={f.key} value={f.key}>{f.title}</option>)}
        </Select>
      </label>
    );
  }
  if (spec.type === "enum") {
    const isSlot = spec.key === "slot";
    const opts = isSlot ? slots.map((s) => [s.key, s.title] as const) : (spec.options ?? []).map((o) => [o, OPT_FA[spec.key]?.[o] ?? OPT_FA.format?.[o] ?? o] as const);
    return (
      <label className="dz-field">
        {label}
        <Select value={String(value ?? spec.default)} onChange={(e) => onChange(e.target.value)} aria-label={spec.title}>
          {opts.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
        </Select>
      </label>
    );
  }
  return null;
}
