import { useState } from "react";

import { Badge, Button, fa } from "../../../components/ui";
import type { ToolInfo, ToolParam } from "../ToolPicker";
import type { EditableOp, Param } from "./api";

/** فرمِ پارامترهای یک ابزارِ ویدیو، از روی فهرستِ ابزارهای سرور (tools.catalogue) — ابزارِ تازه فرمِ تازه نمی‌خواهد. */
export default function ToolForm({
  tool,
  values,
  onChange,
}: {
  tool: ToolInfo;
  values: Record<string, Param>;
  onChange: (next: Record<string, Param>) => void;
}) {
  const set = (name: string, v: Param) => onChange({ ...values, [name]: v });
  if (tool.params.length === 0) {
    return <p className="text-xs" style={{ color: "var(--text-3)" }}>تنظیمی ندارد.</p>;
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {tool.params.map((p) => (
        <Field key={p.name} p={p} value={values[p.name] ?? p.default} onChange={(v) => set(p.name, v)} />
      ))}
    </div>
  );
}

function Field({ p, value, onChange }: { p: ToolParam; value: Param; onChange: (v: Param) => void }) {
  const title = p.title + (p.kind === "seconds" ? " (ثانیه)" : "");
  if (p.kind === "choice") {
    return (
      <label className="block text-xs">
        <span className="mb-1 block" style={{ color: "var(--text-2)" }}>{title}</span>
        <select className="u-input" value={String(value)} onChange={(e) => onChange(e.target.value)} aria-label={p.title}>
          {p.choices.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
    );
  }
  if (p.kind === "bool") {
    return (
      <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} /> {p.title}
      </label>
    );
  }
  if (p.kind === "text") {
    return (
      <label className="block text-xs sm:col-span-2">
        <span className="mb-1 block" style={{ color: "var(--text-2)" }}>{title}</span>
        <input className="u-input" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} aria-label={p.title} />
      </label>
    );
  }
  const n = Number(value);
  const ranged = p.min !== null && p.max !== null && p.max - p.min <= 1000;
  const step = p.kind === "seconds" ? 0.1 : p.max !== null && p.min !== null && p.max - p.min <= 3 ? 0.01 : 1;
  return (
    <label className="block text-xs">
      <span className="mb-1 flex justify-between" style={{ color: "var(--text-2)" }}>
        <span>{title}</span>
        <span dir="ltr">{fa(Math.round(n * 100) / 100)}</span>
      </span>
      <div className="flex items-center gap-2">
        {ranged && (
          <input
            type="range" min={p.min ?? undefined} max={p.max ?? undefined} step={step} value={Number.isFinite(n) ? n : 0}
            onChange={(e) => onChange(Number(e.target.value))} className="flex-1" aria-label={p.title}
          />
        )}
        <input
          type="number" className="u-input !w-24" step={step} min={p.min ?? undefined} max={p.max ?? undefined}
          value={Number.isFinite(n) ? n : ""} onChange={(e) => onChange(Number(e.target.value))} aria-label={`${p.title} (عدد)`}
        />
      </div>
    </label>
  );
}

/** فهرستِ کارهای یک تدوین: هر کار تیک، دلیل، تنظیمات و برداشتن دارد. */
export function OpList({
  ops,
  onChange,
  tools,
  testId = "ops",
}: {
  ops: EditableOp[];
  onChange: (next: EditableOp[]) => void;
  tools: ToolInfo[];
  testId?: string;
}) {
  const [openAt, setOpenAt] = useState<number | null>(null);
  const update = (i: number, next: EditableOp) => onChange(ops.map((o, j) => (j === i ? next : o)));
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      {ops.map((op, i) => {
        const info = tools.find((t) => t.key === op.tool);
        return (
          <div key={`${op.tool}-${i}`} className="step-card" style={{ opacity: op.on ? 1 : 0.55 }} data-op={op.tool}>
            <div className="flex flex-wrap items-start gap-3">
              <input type="checkbox" className="mt-1" checked={op.on} aria-label={op.title} onChange={() => update(i, { ...op, on: !op.on })} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-bold" style={{ color: "var(--text)" }}>{op.title}</span>
                  {info && <Badge tone="neutral">{info.kind === "CUT" ? "برش" : info.kind === "AUDIO_FILTER" ? "صدا" : info.kind === "OVERLAY" ? "روی تصویر" : "تصویر"}</Badge>}
                </div>
                {op.reason && <p className="text-sm" style={{ color: "var(--text-2)" }}>{op.reason}</p>}
                {op.notes.map((n) => <p key={n} className="text-xs" style={{ color: "var(--warn)" }}>{n}</p>)}
              </div>
              <div className="flex gap-1">
                {info && info.params.length > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => setOpenAt(openAt === i ? null : i)}>
                    {openAt === i ? "بستنِ تنظیمات" : "تنظیمات"}
                  </Button>
                )}
                <Button size="sm" variant="ghost" aria-label="برداشتن" onClick={() => { onChange(ops.filter((_o, j) => j !== i)); setOpenAt(null); }}>×</Button>
              </div>
            </div>
            {openAt === i && info && (
              <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
                <ToolForm tool={info} values={op.params} onChange={(params) => update(i, { ...op, params })} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
