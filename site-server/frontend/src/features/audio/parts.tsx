import { Alert, Badge } from "../../components/ui";
import { AudioOverview, EngineKey, VoiceOption } from "./api";

/** Is this engine usable right now? When not, the exact fix (run Download-Models.bat, start the node …). */
export function EngineStatus({ overview, keys }: { overview: AudioOverview; keys: EngineKey[] }) {
  const engines = keys.map((k) => ({ key: k, ...overview.status.engines[k] }));
  const down = engines.filter((e) => !e.ready);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: "var(--text-3)" }}>
        {engines.map((e) => (
          <Badge key={e.key} tone={e.ready ? "ok" : "warn"}>
            {e.label} — {e.ready ? `آماده روی ${e.online_on.join("، ")}` : "آماده نیست"}
          </Badge>
        ))}
        <span>
          مجوز: {engines.map((e) => `${e.label}: ${e.license}`).join(" · ")} (استفادهٔ تجاری مجاز)
        </span>
      </div>
      {down.map((e) => (
        <Alert key={e.key} tone="warn" title={`${e.label} (${e.what})`}>
          {e.message}
        </Alert>
      ))}
    </div>
  );
}

const GROUP_ORDER = ["MOSS-TTS فارسی (تجاری مجاز)", "صداهای کلون‌شدهٔ شما", "Piper (آفلاین)", "Edge (آنلاین)"];

/**
 * Every voice the shop can speak in, grouped by where it runs and what its licence allows. The same picker
 * in «گفتار» and in the video studio.
 */
export function VoicePicker({
  voices,
  value,
  onChange,
  compact = false,
}: {
  voices: VoiceOption[];
  value: string;
  onChange: (id: string) => void;
  compact?: boolean;
}) {
  const groups = GROUP_ORDER.map((g) => ({ g, rows: voices.filter((v) => v.group === g) }))
    .concat([{ g: "سایر", rows: voices.filter((v) => !GROUP_ORDER.includes(v.group)) }])
    .filter((x) => x.rows.length);
  if (compact) {
    return (
      <select className="u-input" value={value} onChange={(e) => onChange(e.target.value)} aria-label="صدا">
        {groups.map(({ g, rows }) => (
          <optgroup key={g} label={g}>
            {rows.map((v) => (
              <option key={v.id} value={v.id} disabled={!v.available}>
                {v.name}
                {v.gender === "female" ? " (زن)" : v.gender === "male" ? " (مرد)" : ""}
                {v.commercial ? "" : " — غیرتجاری"}
                {v.available ? "" : " — آماده نیست"}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {groups.map(({ g, rows }) => (
        <div key={g}>
          <div className="mb-1 text-xs font-bold" style={{ color: "var(--text-3)" }}>
            {g}
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {rows.map((v) => {
              const active = v.id === value;
              return (
                <button
                  key={v.id}
                  type="button"
                  disabled={!v.available}
                  onClick={() => onChange(v.id)}
                  title={v.available ? v.note : v.why}
                  className="rounded-xl p-2 text-right disabled:opacity-50"
                  style={{
                    border: `2px solid ${active ? "var(--brand)" : "var(--line)"}`,
                    background: active ? "var(--brand-soft)" : "transparent",
                  }}
                >
                  <div className="flex flex-wrap items-center gap-1 text-sm font-bold" style={{ color: "var(--text)" }}>
                    {v.name}
                    {v.gender && (
                      <span className="text-xs font-normal" style={{ color: "var(--text-3)" }}>
                        {v.gender === "female" ? "زن" : "مرد"}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 text-xs" style={{ color: v.commercial ? "var(--text-3)" : "var(--warn)" }}>
                    {v.available ? v.note : v.why.length > 60 ? "الان آماده نیست (پیامِ بالا)" : v.why}
                    {!v.commercial && " · فقط غیرتجاری"}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function randomSeed() {
  return Math.floor(Math.random() * 2_000_000_000);
}
