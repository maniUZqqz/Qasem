import { useState } from "react";

import { Badge, Button, Select } from "../../../components/ui";
import type { Kit, Operation, Tool } from "./api";
import OperationForm from "./OperationForm";

/**
 * فهرستِ کارهای یک ویرایش: هرکدام تیک (خاموش/روشن)، دلیل، تنظیمات و برداشتن دارد.
 * هم برای «اول نشانم بده» در حالتِ خودکار، هم برای «کارهایی که هوش مصنوعی انتخاب کرد» در حالتِ نیمه‌خودکار.
 */
export default function StepList({
  steps,
  onChange,
  tools,
  kit,
  nodeOn,
  allowAdd = true,
  spotImage = null,
  testId = "operations",
}: {
  steps: Operation[];
  onChange: (next: Operation[]) => void;
  tools: Record<string, Tool>;
  kit: Kit;
  nodeOn: boolean;
  allowAdd?: boolean;
  spotImage?: string | null;
  testId?: string;
}) {
  const [openAt, setOpenAt] = useState<number | null>(null);

  const update = (i: number, next: Operation) => onChange(steps.map((s, j) => (j === i ? next : s)));

  const add = (key: string) => {
    const t = tools[key];
    if (!t) return;
    const params: Record<string, unknown> = {};
    t.params.forEach((p) => (params[p.key] = p.default));
    const op: Operation = { tool: key, params, on: true, title: t.title, where: t.where, reason: t.help };
    const list = [...steps];
    const exportAt = list.findIndex((o) => o.tool === "export");
    if (exportAt >= 0 && key !== "export") list.splice(exportAt, 0, op);
    else list.push(op);
    setOpenAt(exportAt >= 0 && key !== "export" ? exportAt : list.length - 1);
    onChange(list);
  };

  return (
    <div>
      {steps.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--text-3)" }}>هنوز کاری نیست — از پایین ابزار اضافه کنید.</p>
      ) : (
        <div className="flex flex-col gap-2" data-testid={testId}>
          {steps.map((op, index) => {
            const t = tools[op.tool];
            if (!t) return null;
            const off = op.on === false;
            const where = op.where ?? t.where;
            return (
              <div key={`${op.tool}-${op.group ?? ""}-${index}`} className={`step-card ${off ? "is-off" : ""}`} data-step={op.tool}>
                <div className="flex flex-wrap items-start gap-3">
                  <input
                    type="checkbox" className="mt-1" checked={!off} aria-label={op.title ?? t.title}
                    onChange={() => update(index, { ...op, on: off })}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-bold" style={{ color: "var(--text)" }}>{op.title ?? t.title}</span>
                      <Badge tone={where === "server" ? "ok" : nodeOn ? "info" : "warn"}>
                        {where === "server" ? "سرورِ سایت" : nodeOn ? "سرورِ پردازش" : "سرورِ پردازش — منتظر"}
                      </Badge>
                      {op.optional && <Badge tone="neutral">اختیاری</Badge>}
                    </div>
                    <p className="text-sm" style={{ color: "var(--text-2)" }}>{op.reason || t.help}</p>
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setOpenAt(openAt === index ? null : index)}>
                      {openAt === index ? "بستنِ تنظیمات" : "تنظیمات"}
                    </Button>
                    <Button
                      size="sm" variant="ghost" title="برداشتنِ این کار" aria-label="برداشتنِ این کار"
                      onClick={() => {
                        onChange(steps.filter((_o, i) => i !== index));
                        setOpenAt(null);
                      }}
                    >
                      ×
                    </Button>
                  </div>
                </div>
                {openAt === index && (
                  <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
                    <OperationForm tool={t} params={op.params} kit={kit} spotImage={spotImage} onChange={(params) => update(index, { ...op, params })} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {allowAdd && (
        <div className="mt-3">
          <Select
            value="" onChange={(e) => e.target.value && add(e.target.value)} aria-label="افزودنِ ابزار" className="!w-auto"
          >
            <option value="">+ افزودنِ ابزار…</option>
            <optgroup label="سرورِ سایت (همین حالا)">
              {Object.values(tools).filter((t) => t.where === "server").map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
            </optgroup>
            <optgroup label="سرورِ پردازش (کیتِ PersianAiKit.Photo)">
              {Object.values(tools).filter((t) => t.where === "node").map((t) => <option key={t.key} value={t.key}>{t.title}</option>)}
            </optgroup>
          </Select>
        </div>
      )}
    </div>
  );
}
