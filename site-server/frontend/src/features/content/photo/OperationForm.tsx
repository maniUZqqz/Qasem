import { useState } from "react";

import { Input, Select, fa } from "../../../components/ui";
import type { Kit, ParamSpec, Params, Tool } from "./api";

type Spot = { x: number; y: number; r: number };

/** فرمِ پارامترهای یک کار — از روی فهرستِ ابزارها (catalog.py)، پس ابزارِ تازه فرمِ تازه نمی‌خواهد. */
export default function OperationForm({
  tool,
  params,
  onChange,
  kit,
  spotImage,
}: {
  tool: Tool;
  params: Params;
  onChange: (next: Params) => void;
  kit: Kit;
  /** عکسِ تنها عکسِ انتخاب‌شده — برای علامت زدنِ لکه‌ها */
  spotImage: string | null;
}) {
  const set = (key: string, value: unknown) => onChange({ ...params, [key]: value });

  if (tool.params.length === 0) {
    return (
      <p className="text-xs" style={{ color: "var(--text-3)" }}>
        تنظیمی ندارد — کیت خودش اندازه می‌گیرد و تصمیم می‌گیرد.
      </p>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {tool.params.map((p) => (
        <ParamField
          key={p.key}
          spec={p}
          value={params[p.key] ?? p.default}
          onChange={(v) => set(p.key, v)}
          kit={kit}
          spotImage={spotImage}
        />
      ))}
    </div>
  );
}

function ParamField({
  spec,
  value,
  onChange,
  kit,
  spotImage,
}: {
  spec: ParamSpec;
  value: unknown;
  onChange: (v: unknown) => void;
  kit: Kit;
  spotImage: string | null;
}) {
  const label = (
    <span className="mb-1 block text-xs font-medium" style={{ color: "var(--text-2)" }}>
      {spec.title}
    </span>
  );
  switch (spec.type) {
    case "number": {
      const n = Number(value);
      return (
        <label className="block">
          {label}
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={spec.min}
              max={spec.max}
              step={spec.step ?? 1}
              value={Number.isFinite(n) ? n : Number(spec.default)}
              onChange={(e) => onChange(Number(e.target.value))}
              className="flex-1"
              aria-label={spec.title}
            />
            <Input
              type="number"
              value={Number.isFinite(n) ? n : ""}
              min={spec.min}
              max={spec.max}
              step={spec.step ?? 1}
              onChange={(e) => onChange(Number(e.target.value))}
              className="!w-24"
            />
            {spec.unit && <span className="text-xs" style={{ color: "var(--text-3)" }}>{spec.unit}</span>}
          </div>
          {spec.help && <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>{spec.help}</span>}
        </label>
      );
    }
    case "select":
      return (
        <label className="block">
          {label}
          <Select value={String(value)} onChange={(e) => onChange(e.target.value)} aria-label={spec.title}>
            {spec.options?.map((o) => (
              <option key={o.value} value={o.value} title={o.help}>
                {o.label}
              </option>
            ))}
          </Select>
          {spec.options?.find((o) => o.value === String(value))?.help && (
            <span className="mt-1 block text-xs" style={{ color: "var(--text-3)" }}>
              {spec.options.find((o) => o.value === String(value))!.help}
            </span>
          )}
        </label>
      );
    case "bool":
      return (
        <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-2)" }}>
          <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
          {spec.title}
        </label>
      );
    case "text":
      return (
        <label className="block sm:col-span-2">
          {label}
          <Input
            value={String(value ?? "")}
            maxLength={spec.max}
            onChange={(e) => onChange(e.target.value)}
            placeholder={spec.help}
            aria-label={spec.title}
          />
        </label>
      );
    case "color":
      return (
        <label className="block">
          {label}
          <input
            type="color"
            value={String(value || "#ffffff")}
            onChange={(e) => onChange(e.target.value)}
            className="h-9 w-16 cursor-pointer rounded"
            aria-label={spec.title}
          />
        </label>
      );
    case "adjust":
      return (
        <div className="sm:col-span-2">
          <AdjustSliders kit={kit} value={(value as Record<string, number>) ?? {}} onChange={onChange} />
        </div>
      );
    case "spots":
      return (
        <div className="sm:col-span-2">
          <SpotPicker image={spotImage} value={(value as Spot[]) ?? []} onChange={onChange} />
        </div>
      );
    default:
      return null;
  }
}

/** ۵۸ لغزندهٔ کیت، گروه‌به‌گروه؛ فقط آن‌هایی که از پیش‌فرض فرق دارند فرستاده می‌شوند. */
function AdjustSliders({
  kit,
  value,
  onChange,
}: {
  kit: Kit;
  value: Record<string, number>;
  onChange: (v: Record<string, number>) => void;
}) {
  const setOne = (key: string, v: number, def: number) => {
    const next = { ...value };
    if (Math.abs(v - def) < 1e-9) delete next[key];
    else next[key] = v;
    onChange(next);
  };
  const changed = Object.keys(value).length;
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs" style={{ color: "var(--text-3)" }}>
        {changed ? `${fa(changed)} لغزنده تغییر کرده` : "همه روی پیش‌فرض — هر کدام را بکشید"}
        {changed > 0 && (
          <button type="button" className="ms-2 underline" onClick={() => onChange({})}>
            همه به پیش‌فرض
          </button>
        )}
      </span>
      {kit.groups.map((g) => {
        const params = kit.params.filter((p) => p.group === g.key);
        const n = params.filter((p) => p.key in value).length;
        return (
          <details key={g.key} className="rounded-lg p-2" style={{ border: "1px solid var(--line)" }} open={n > 0}>
            <summary className="cursor-pointer text-sm font-medium" style={{ color: "var(--text)" }}>
              {g.title}
              {n > 0 && <span className="ms-2 text-xs" style={{ color: "var(--brand)" }}>({fa(n)})</span>}
            </summary>
            <p className="mb-2 mt-1 text-xs" style={{ color: "var(--text-3)" }}>{g.help}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {params.map((p) => {
                const v = p.key in value ? value[p.key] : p.default;
                return (
                  <label key={p.key} className="block" title={p.help}>
                    <span className="flex justify-between text-xs" style={{ color: "var(--text-2)" }}>
                      <span>{p.title}</span>
                      <span dir="ltr">{fa(Math.round(v * 100) / 100)}{p.unit ? ` ${p.unit}` : ""}</span>
                    </span>
                    <input
                      type="range"
                      min={p.min}
                      max={p.max}
                      step={p.step}
                      value={v}
                      onChange={(e) => setOne(p.key, Number(e.target.value), p.default)}
                      onDoubleClick={() => setOne(p.key, p.default, p.default)}
                      className="w-full"
                      aria-label={p.title}
                    />
                  </label>
                );
              })}
            </div>
          </details>
        );
      })}
    </div>
  );
}

/** کلیک روی عکس ⇐ یک لکه (مختصاتِ نسبی، همان قراردادِ recipe.spots ِ کیت). */
function SpotPicker({
  image,
  value,
  onChange,
}: {
  image: string | null;
  value: Spot[];
  onChange: (v: Spot[]) => void;
}) {
  // r در کیت نسبت به ضلعِ کوتاه‌تر است؛ دایره روی صفحه به درصدِ عرض کشیده می‌شود
  const [aspect, setAspect] = useState(1);
  if (!image) {
    return (
      <p className="text-xs" style={{ color: "var(--warn)" }}>
        برای علامت زدنِ لکه‌ها دقیقاً یک عکس انتخاب کنید.
      </p>
    );
  }
  const r = value.length ? value[value.length - 1].r : 0.02;
  const widthPct = (s: Spot) => s.r * 200 * Math.min(1, 1 / aspect);
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs" style={{ color: "var(--text-3)" }}>
        روی هر لکه کلیک کنید ({fa(value.length)} لکه). کلیک روی دایره ⇐ برداشتن.
      </span>
      <div className="relative inline-block max-w-full self-start" dir="ltr">
        <img
          src={image}
          alt="علامت زدنِ لکه"
          className="block max-h-[60vh] max-w-full cursor-crosshair rounded-lg"
          data-testid="spot-image"
          onLoad={(e) => setAspect(e.currentTarget.naturalWidth / Math.max(1, e.currentTarget.naturalHeight))}
          onClick={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const x = (e.clientX - box.left) / box.width;
            const y = (e.clientY - box.top) / box.height;
            onChange([...value, { x: +x.toFixed(4), y: +y.toFixed(4), r }]);
          }}
        />
        {value.map((s, i) => (
          <button
            key={i}
            type="button"
            title="برداشتنِ لکه"
            onClick={() => onChange(value.filter((_s, j) => j !== i))}
            className="absolute rounded-full"
            style={{
              left: `${s.x * 100}%`,
              top: `${s.y * 100}%`,
              width: `${widthPct(s)}%`,
              aspectRatio: "1",
              transform: "translate(-50%, -50%)",
              border: "2px solid #f43f5e",
              background: "rgba(244,63,94,.15)",
            }}
          />
        ))}
      </div>
      <label className="flex items-center gap-2 text-xs" style={{ color: "var(--text-2)" }}>
        اندازهٔ آخرین لکه (لکهٔ بعدی هم همین)
        <input
          type="range"
          min={0.005}
          max={0.1}
          step={0.005}
          value={r}
          onChange={(e) =>
            onChange(value.length ? [...value.slice(0, -1), { ...value[value.length - 1], r: Number(e.target.value) }] : value)
          }
        />
      </label>
    </div>
  );
}
