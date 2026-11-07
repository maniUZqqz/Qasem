import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../api/client";
import Icon from "../../../components/Icon";
import { Alert, Button, Card, ErrorBox, Input, SectionTitle, Spinner } from "../../../components/ui";
import {
  DEFAULT_SETTINGS,
  IMMEDIATE_NOTE,
  describeSettings,
  sameSettings,
  settingsBody,
  settingsError,
  settingsFromServer,
  type DownloadMode,
  type DownloadSettings,
} from "./schedule";

/**
 * «زمان‌بندیِ دانلود» — تنظیمِ کلیِ زمانِ دانلودها در «سرورهای پردازش».
 *
 * مدل‌های هوش مصنوعی و مدل‌های صدا و ویدیو چند گیگابایت‌اند و اینترنتِ سرورِ پردازش را پر می‌کنند. این‌جا می‌گویید دانلودها
 * همین که خواسته شدند شروع شوند یا فقط در یک بازهٔ شبانه (پیش‌فرض ۰۲:۰۰ تا ۰۷:۰۰ به وقتِ تهران). هر دانلود را هم موقعِ زدنِ دکمه
 * می‌شود برای یک ساعتِ دیگر گذاشت (DownloadWhen).
 *
 * ذخیره: POST /compute/settings/ {download_mode, download_window} (apps.compute.api). عاملِ سرورِ پردازش (۲٫۶ به بعد) همین تنظیم
 * را با هر heartbeat می‌گیرد و دانلودهای خودش را هم از بازه بیرون نمی‌برد. منطقِ خالص: schedule.ts (آزمون‌شده).
 */
export default function DownloadScheduleCard() {
  const [saved, setSaved] = useState<DownloadSettings | null>(null);
  const [form, setForm] = useState<DownloadSettings>(DEFAULT_SETTINGS);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/compute/settings/");
      const s = settingsFromServer(data);
      setSaved(s);
      setForm(s);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const edit = (next: Partial<DownloadSettings>) => {
    setNote(null);
    setError(null);
    setForm((f) => ({ ...f, ...next }));
  };

  const problem = settingsError(form);
  const changed = saved !== null && !sameSettings(saved, form);

  const save = async () => {
    const body = settingsBody(form);
    if (!body) {
      setError(problem || "تنظیم درست نیست.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post("/compute/settings/", body);
      const s = settingsFromServer(data);
      setSaved(s);
      setForm(s);
      setNote("ذخیره شد.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const modes: { key: DownloadMode; title: string; sub: string }[] = [
    { key: "now", title: "همین الان", sub: "دانلود همین که خواسته شد شروع می‌شود." },
    { key: "window", title: "فقط در بازهٔ شبانه", sub: "دانلود تا شب صبر می‌کند و در ساعتِ بازه خودکار شروع می‌شود." },
  ];

  return (
    <Card>
      <SectionTitle>
        <span className="flex items-center gap-2" data-testid="download-schedule">
          <Icon name="clock" size={16} /> زمان‌بندیِ دانلود
        </span>
      </SectionTitle>
      <p className="mb-3 text-sm leading-7" style={{ color: "var(--text-2)" }}>
        مدل‌های هوش مصنوعی و مدل‌های صدا و ویدیو چند گیگابایت‌اند و اینترنتِ سرورِ پردازش را پر می‌کنند. این‌جا می‌گویید دانلودها
        همین الان انجام شوند یا فقط شب‌ها. همهٔ ساعت‌ها <b>به وقتِ تهران</b> است. هر دانلود را موقعِ زدنِ دکمه‌اش هم می‌توانید برای
        یک ساعتِ دیگر بگذارید.
      </p>
      <ErrorBox message={loadError} />
      {!saved && !loadError && <Spinner />}
      {saved && (
        <div className="flex flex-col gap-3">
          <div className="grid gap-2 md:grid-cols-2" role="radiogroup" aria-label="زمانِ دانلودها">
            {modes.map((m) => {
              const on = form.mode === m.key;
              return (
                <label
                  key={m.key}
                  className="flex cursor-pointer items-start gap-3 rounded-xl p-3"
                  style={{ background: on ? "var(--brand-soft)" : "var(--surface-2)", border: `1.5px solid ${on ? "var(--brand)" : "var(--line)"}` }}
                >
                  <input
                    type="radio"
                    name="download-mode"
                    className="mt-1.5"
                    checked={on}
                    disabled={busy}
                    data-testid={`download-mode-${m.key}`}
                    onChange={() => edit({ mode: m.key })}
                  />
                  <span>
                    <b style={{ color: "var(--text)" }}>{m.title}</b>
                    <span className="block text-sm leading-6" style={{ color: "var(--text-3)" }}>{m.sub}</span>
                  </span>
                </label>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2 text-sm" style={{ color: "var(--text-2)", opacity: form.mode === "window" ? 1 : 0.55 }}>
            <span>بازهٔ شبانه: از ساعتِ</span>
            <Input
              type="time"
              dir="ltr"
              className="w-28"
              value={form.start}
              disabled={busy || form.mode !== "window"}
              aria-label="شروعِ بازهٔ شبانه (به وقتِ تهران)"
              data-testid="download-start"
              onChange={(e) => edit({ start: e.target.value })}
            />
            <span>تا</span>
            <Input
              type="time"
              dir="ltr"
              className="w-28"
              value={form.end}
              disabled={busy || form.mode !== "window"}
              aria-label="پایانِ بازهٔ شبانه (به وقتِ تهران)"
              data-testid="download-end"
              onChange={(e) => edit({ end: e.target.value })}
            />
            <span className="text-xs" style={{ color: "var(--text-3)" }}>(به وقتِ تهران؛ پیش‌فرض ۰۲:۰۰ تا ۰۷:۰۰)</span>
          </div>

          <p className="text-sm leading-7" style={{ color: problem ? "var(--bad)" : "var(--text-2)" }} data-testid="download-describe">
            {problem || describeSettings(form)}
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => void save()} disabled={busy || !changed || Boolean(problem)} data-testid="download-save">
              {busy ? <Spinner size={13} /> : <Icon name="check" size={13} />} ذخیره
            </Button>
            {note && !changed && <span className="text-sm" style={{ color: "var(--ok)" }}>{note}</span>}
          </div>
          <ErrorBox message={error} />
          <Alert tone="info">{IMMEDIATE_NOTE}</Alert>
        </div>
      )}
    </Card>
  );
}
