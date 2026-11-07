import { useEffect, useId, useState } from "react";

import { api } from "../../../api/client";
import { Input } from "../../../components/ui";
import {
  DEFAULT_WHEN,
  WHEN_OPTIONS,
  settingsFromServer,
  whenError,
  whenSummary,
  type DownloadSettings,
  type WhenChoice,
} from "./schedule";

/**
 * انتخابگرِ «زمانِ دانلود» — هر جا که دانلودی شروع می‌شود (دانلودِ مدلِ هوش مصنوعی، دانلودِ مدل‌های صدا) کنارِ دکمه می‌آید.
 *
 *   ○ طبقِ تنظیمِ کلی   ○ الان   ○ در ساعتِ [۰۳:۰۰]   ○ در بازهٔ شبانه (طبقِ تنظیمات)
 *
 * پیش‌فرض «طبقِ تنظیمِ کلی» است: کارتِ «زمان‌بندیِ دانلود» در «سرورهای پردازش» می‌گوید دانلودها الان انجام شوند یا فقط شب.
 * زیرِ گزینه‌ها یک جملهٔ ساده می‌گوید با انتخابِ فعلی دانلود چه موقع شروع می‌شود. منطق در schedule.ts است (آزمون‌شده).
 * ساعت‌ها همه به وقتِ تهران‌اند.
 */

/** تنظیمِ کلیِ دانلودها (GET /compute/settings/ ؛ فقط کارکنان — همان کسانی که این کارت‌ها را می‌بینند)؛ نشد ⇒ null */
export function useDownloadSettings(enabled = true): DownloadSettings | null {
  const [settings, setSettings] = useState<DownloadSettings | null>(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    api
      .get("/compute/settings/")
      .then(({ data }) => {
        if (alive) setSettings(settingsFromServer(data));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [enabled]);
  return settings;
}

export { DEFAULT_WHEN };

export default function DownloadWhen({
  value,
  onChange,
  disabled = false,
  settings,
}: {
  value: WhenChoice;
  onChange: (next: WhenChoice) => void;
  disabled?: boolean;
  /** اگر والد تنظیمِ کلی را دارد بدهد؛ وگرنه خودِ انتخابگر یک بار می‌خواند */
  settings?: DownloadSettings | null;
}) {
  const group = useId();
  const own = useDownloadSettings(settings === undefined);
  const global = settings === undefined ? own : settings;
  const problem = whenError(value);

  return (
    <fieldset className="min-w-0 rounded-xl p-3" style={{ border: "1px solid var(--line)" }} disabled={disabled} data-testid="download-when">
      <legend className="px-1 text-sm font-bold" style={{ color: "var(--text)" }}>
        زمانِ دانلود
      </legend>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm" style={{ color: "var(--text-2)" }}>
        {WHEN_OPTIONS.map((o) => (
          <label key={o.mode} className="flex cursor-pointer items-center gap-2">
            <input
              type="radio"
              name={group}
              checked={value.mode === o.mode}
              onChange={() => onChange({ ...value, mode: o.mode })}
              data-testid={`when-${o.mode}`}
            />
            {o.label}
            {o.mode === "at" && (
              <Input
                type="time"
                dir="ltr"
                className="w-28"
                value={value.time}
                aria-label="ساعتِ شروعِ دانلود (به وقتِ تهران)"
                data-testid="when-time"
                onChange={(e) => onChange({ mode: "at", time: e.target.value })}
              />
            )}
          </label>
        ))}
      </div>
      <p className="mt-2 text-xs leading-6" style={{ color: problem ? "var(--bad)" : "var(--text-3)" }} data-testid="when-summary">
        {problem || whenSummary(value, global)}
      </p>
    </fieldset>
  );
}
