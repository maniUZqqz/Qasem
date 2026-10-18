import { Field, Select } from "../../../../components/ui";
import type { ParamSpec } from "../types";
import { ColorInput, DraftInput, DraftNumber } from "./fields";

/**
 * ورودی‌های یک دارایی از روی `params` ِ manifest ِ آن (رنگ، فهرست، عدد، بله/خیر، فایل، متن).
 * مقدارِ نوشته‌شده هم‌نوعِ spec است: bool ⇐ boolean، number ⇐ number، بقیه ⇐ string.
 */
export default function ParamInputs({
  spec,
  values,
  onChange,
  onFile,
}: {
  spec?: Record<string, ParamSpec>;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  onFile?: (key: string, file: File) => void;
}) {
  if (!spec) return null;
  return (
    <>
      {Object.entries(spec).map(([k, s]) => {
        const cur = values[k] != null ? values[k] : s.default != null ? s.default : "";
        const lbl = s.label || k;
        if (s.type === "enum") {
          return (
            <Field key={k} label={lbl}>
              <Select value={String(cur)} onChange={(e) => onChange(k, e.target.value)}>
                {(s.values || []).map((v) => (
                  <option key={String(v)} value={String(v)}>
                    {String(v).split("/").pop()?.replace(".mhclo", "") ?? String(v)}
                  </option>
                ))}
              </Select>
            </Field>
          );
        }
        if (s.type === "color") {
          return (
            <Field key={k} label={lbl}>
              <ColorInput value={String(cur || "#ffffff")} onCommit={(v) => onChange(k, v)} />
            </Field>
          );
        }
        if (s.type === "bool") {
          return (
            <label key={k} className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={Boolean(cur)} onChange={(e) => onChange(k, e.target.checked)} />
              {lbl}
            </label>
          );
        }
        if (s.type === "number" || s.type === "int") {
          return (
            <Field key={k} label={lbl} hint={s.min != null && s.max != null ? `${s.min} تا ${s.max}` : undefined}>
              <DraftNumber
                value={typeof cur === "number" ? cur : cur === "" ? null : Number(cur)}
                step={s.type === "int" ? 1 : 0.1}
                min={s.min}
                max={s.max}
                onCommit={(v) => onChange(k, v == null ? s.default : v)}
              />
            </Field>
          );
        }
        if (s.type === "file") {
          const name = cur ? String(cur).split(/[\\/]/).pop() : "";
          return (
            <Field key={k} label={lbl} hint={name ? `فایل: ${name}` : undefined}>
              <input
                type="file"
                className="u-input"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f && onFile) onFile(k, f);
                }}
              />
            </Field>
          );
        }
        return (
          <Field key={k} label={lbl}>
            <DraftInput value={String(cur ?? "")} onCommit={(v) => onChange(k, v)} />
          </Field>
        );
      })}
    </>
  );
}
