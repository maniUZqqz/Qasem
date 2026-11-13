import { useState } from "react";

import { api, studioError } from "./api";
import { Check, Help } from "./common";

export type DesignValue = { style: string; components: string[] };
type Opts = {
  styles: { key: string; label: string; en: string; mood: string; colors: { primary: string; bg: string; text: string } }[];
  components: { key: string; label: string; cat: string; cat_label: string }[];
  max_components: number;
};

/**
 * «حالتِ AI»: کاربر یک سبکِ طراحی و (اگر خواست) چند قطعه را سنجاق می‌کند. به مدل فقط همین‌ها و چند قطعهٔ مرتبط می‌رسد، نه کلِ کتابخانه
 * (ai_context.py سقفِ اندازه دارد). هیچ‌چیز بی‌تأیید اعمال نمی‌شود؛ Diff را می‌بینی.
 */
export default function DesignPicker({ value, onChange }: { value: DesignValue; onChange: (v: DesignValue) => void }) {
  const [opts, setOpts] = useState<Opts | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (opts) return;
    api
      .get<Opts>("/studio/ai/design-options/")
      .then((r) => setOpts(r.data))
      .catch((e) => setError(studioError(e)));
  }
  const max = opts?.max_components ?? 5;
  const groups = opts ? Array.from(new Set(opts.components.map((c) => c.cat))) : [];
  return (
    <details className="rounded-xl p-3" style={{ border: "1px solid var(--line)" }} onToggle={(e) => e.currentTarget.open && load()} data-testid="design-picker">
      <summary className="cursor-pointer text-sm font-bold" style={{ color: "var(--text-2)" }}>
        سبکِ طراحی و قطعه‌های آماده (اختیاری){value.style ? ` — ${opts?.styles.find((s) => s.key === value.style)?.label ?? value.style}` : ""}
      </summary>
      <div className="mt-3 space-y-3">
        {error && <p className="text-sm" style={{ color: "var(--bad)" }}>{error}</p>}
        {!opts && !error && <p className="text-sm" style={{ color: "var(--text-3)" }}>در حالِ خواندن…</p>}
        {opts && (
          <>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                سبکِ طراحی
              </span>
              <select className="w-full rounded-lg px-3 py-2 text-sm" style={{ background: "var(--surface-2, transparent)", border: "1px solid var(--line)", color: "var(--text)" }} value={value.style} onChange={(e) => onChange({ ...value, style: e.target.value })} data-testid="design-style">
                <option value="">بدونِ سبک (همان ظاهرِ فعلی)</option>
                {opts.styles.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label} — {s.mood}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <span className="mb-1.5 block text-sm font-medium" style={{ color: "var(--text-2)" }}>
                قطعه‌هایی که حتماً باشند (حداکثر {max}؛ خالی = خودمان مرتبط‌ترین‌ها را از روی توضیح پیشنهاد می‌دهیم)
              </span>
              <div className="space-y-2">
                {groups.map((g) => (
                  <div key={g} className="flex flex-wrap items-center gap-x-4 gap-y-1">
                    <b className="w-28 text-xs" style={{ color: "var(--text-3)" }}>
                      {opts.components.find((c) => c.cat === g)?.cat_label}
                    </b>
                    {opts.components
                      .filter((c) => c.cat === g)
                      .map((c) => {
                        const on = value.components.includes(c.key);
                        return (
                          <span key={c.key} style={{ opacity: !on && value.components.length >= max ? 0.45 : 1 }}>
                            <Check
                              label={c.label}
                              checked={on}
                              onChange={(v) => {
                                if (v && value.components.length >= max) return;
                                onChange({ ...value, components: v ? [...value.components, c.key] : value.components.filter((x) => x !== c.key) });
                              }}
                            />
                          </span>
                        );
                      })}
                  </div>
                ))}
              </div>
            </div>
            <Help>به هوشِ مصنوعی فقط همین سبک و چند قطعهٔ مرتبط داده می‌شود، نه کلِ کتابخانه؛ همین باعث می‌شود نتیجه بهتر و حرفه‌ای‌تر شود.</Help>
          </>
        )}
      </div>
    </details>
  );
}
