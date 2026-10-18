import { useState } from "react";

import { Button } from "../../components/ui";

export type ToolParam = {
  name: string;
  title: string;
  kind: "number" | "seconds" | "text" | "choice" | "bool";
  default: number | string | boolean;
  min: number | null;
  max: number | null;
  choices: string[];
  required: boolean;
};

export type ToolInfo = {
  key: string;
  title: string;
  kind: string;
  why: string;
  params: ToolParam[];
};

type Value = number | string | boolean;

/**
 * Add one editing tool by hand — noise removal, a cut, a watermark…
 *
 * The backend's tool catalogue came with every video list and was dropped on
 * the floor, so «دستی» mode could only ever produce an empty plan. Whatever is
 * added here goes through the same validation as the model's proposals: an
 * out-of-range number is clamped and the plan says so.
 */
export default function ToolPicker({
  tools,
  hasAudio,
  busy,
  onAdd,
}: {
  tools: ToolInfo[];
  hasAudio: boolean;
  busy: boolean;
  onAdd: (operation: { tool: string; params: Record<string, Value> }) => void;
}) {
  const [key, setKey] = useState("");
  const [values, setValues] = useState<Record<string, Value>>({});
  const tool = tools.find((t) => t.key === key);

  const choose = (next: string) => {
    setKey(next);
    const chosen = tools.find((t) => t.key === next);
    setValues(
      Object.fromEntries((chosen?.params ?? []).map((p) => [p.name, p.default])),
    );
  };

  return (
    <div
      className="mt-3 flex flex-col gap-2 rounded-xl p-3"
      style={{ border: "1px dashed var(--line)" }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <select
          className="u-input w-56"
          value={key}
          onChange={(e) => choose(e.target.value)}
        >
          <option value="">افزودن ابزار به دست خودتان…</option>
          {tools.map((t) => (
            <option key={t.key} value={t.key} disabled={!hasAudio && t.kind === "AUDIO_FILTER"}>
              {t.title}
            </option>
          ))}
        </select>
        {tool?.params.map((param) => (
          <label key={param.name} className="flex flex-col gap-1 text-xs">
            <span style={{ color: "var(--text-2)" }}>
              {param.title}
              {param.kind === "seconds" ? " (ثانیه)" : ""}
            </span>
            {param.kind === "choice" ? (
              <select
                className="u-input"
                value={String(values[param.name] ?? "")}
                onChange={(e) => setValues({ ...values, [param.name]: e.target.value })}
              >
                {param.choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : param.kind === "bool" ? (
              <input
                type="checkbox"
                checked={Boolean(values[param.name])}
                onChange={(e) => setValues({ ...values, [param.name]: e.target.checked })}
              />
            ) : param.kind === "text" ? (
              <input
                className="u-input w-40"
                value={String(values[param.name] ?? "")}
                onChange={(e) => setValues({ ...values, [param.name]: e.target.value })}
              />
            ) : (
              <input
                type="number"
                className="u-input w-24"
                step={param.kind === "seconds" ? 0.1 : 1}
                min={param.min ?? undefined}
                max={param.max ?? undefined}
                value={Number(values[param.name] ?? 0)}
                onChange={(e) => setValues({ ...values, [param.name]: Number(e.target.value) })}
              />
            )}
          </label>
        ))}
        <Button
          size="sm"
          variant="secondary"
          disabled={!tool || busy}
          onClick={() => {
            if (!tool) return;
            onAdd({ tool: tool.key, params: values });
            setKey("");
            setValues({});
          }}
        >
          اضافه کن
        </Button>
      </div>
      {tool && (
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          {tool.why}
        </p>
      )}
    </div>
  );
}
