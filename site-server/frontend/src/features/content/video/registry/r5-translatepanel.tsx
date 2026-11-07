import { useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import { Alert, Spinner, fa } from "../../../../components/ui";
import { videoApi } from "../api";
import { MAX_LINES, TRANSLATE_LANGS, applyTranslation, captionLines, langTitle, resultItems } from "../manual/r5translate";
import type { PanelProps } from "./types";

type JobLite = { state: string; error?: string; current_step_label?: string; progress_step?: number; total_steps?: number; result?: unknown };

/** ترجمهٔ زیرنویس: خط‌های زیرنویسِ تایم‌لاین به زبانِ دیگر ترجمه می‌شوند (سرورِ پردازش یا سرویسِ هوش مصنوعی)؛ ترجمه روی ترکِ تازه می‌نشیند و اصل می‌ماند */
export function TranslatePanel({ api: ws }: PanelProps) {
  const lines = captionLines(ws.project);
  const [lang, setLang] = useState("en");
  const [mode, setMode] = useState<"new" | "replace">("new");
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const stop = useRef(false);
  useEffect(() => () => { stop.current = true; }, []);

  const run = async () => {
    const batch = lines.slice(0, MAX_LINES);
    if (!batch.length) return;
    stop.current = false;
    setBusy(true); setError(null); setLabel("در صفِ ترجمه…");
    try {
      const { job_id } = await videoApi.translateCaptions(ws.storeId, { lang, clips: batch });
      for (let i = 0; i < 300 && !stop.current; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const { data: job } = await api.get<JobLite>(`/jobs/${job_id}/`);
        if (job.state === "FAILED" || job.state === "CANCELLED") { setError(job.error || "ترجمه ناموفق بود."); return; }
        if (job.state === "COMPLETED") {
          const items = resultItems(job.result);
          if (!items) { setError("جوابِ ترجمه درست نبود؛ دوباره امتحان کنید."); return; }
          ws.apply(`ترجمهٔ زیرنویس به ${langTitle(lang)}`, (p) => applyTranslation(p, items, lang, mode));
          ws.notice(mode === "new" ? `${fa(items.length)} خط ترجمه شد و روی ترکِ «ترجمه (${langTitle(lang)})» نشست؛ اصل دست‌نخورده است.` : `${fa(items.length)} خط ترجمه شد و جای متنِ قبلی نشست (برگشت: Ctrl+Z).`);
          return;
        }
        setLabel(job.current_step_label || (job.state === "RUNNING" ? "در حال ترجمه…" : "در صفِ ترجمه…"));
      }
      if (!stop.current) setError("ترجمه بیش از حد طول کشید؛ بعداً دوباره امتحان کنید.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!lines.length) {
    return (
      <div data-testid="tr-empty">
        <p className="ws-hint">زیرنویسی روی تایم‌لاین نیست. اول «زیرنویسِ خودکار» بسازید یا یک فایلِ SRT بیاورید، بعد این‌جا به زبانِ دیگر ترجمه‌اش کنید.</p>
        <button type="button" className="ws-btn primary" onClick={() => ws.setTab("captions")} data-testid="tr-make-captions">رفتن به ساختنِ زیرنویس</button>
      </div>
    );
  }
  return (
    <div data-testid="translate-panel">
      <p className="ws-hint">{fa(lines.length)} خط زیرنویس پیدا شد{lines.length > MAX_LINES ? ` (در هر بار فقط ${fa(MAX_LINES)} خطِ اول ترجمه می‌شود)` : ""}.</p>
      <div className="hv-tabs" role="radiogroup" aria-label="زبانِ مقصد">
        {TRANSLATE_LANGS.map((l) => (
          <button key={l.key} type="button" role="radio" aria-checked={lang === l.key} className={`ws-chip ${lang === l.key ? "is-on" : ""}`} disabled={busy} onClick={() => setLang(l.key)} data-testid={`tr-lang-${l.key}`}>{l.title}</button>
        ))}
      </div>
      <div className="mk-top">
        <label className="fx-check"><input type="radio" name="tr-mode" checked={mode === "new"} disabled={busy} onChange={() => setMode("new")} data-testid="tr-mode-new" /><span>روی ترکِ تازه (اصل بماند)</span></label>
        <label className="fx-check"><input type="radio" name="tr-mode" checked={mode === "replace"} disabled={busy} onChange={() => setMode("replace")} data-testid="tr-mode-replace" /><span>جای متنِ قبلی</span></label>
      </div>
      <div className="mk-top">
        <button type="button" className="ws-btn primary" disabled={busy} onClick={() => void run()} data-testid="tr-start">{busy ? "در حال ترجمه…" : `ترجمه به ${langTitle(lang)}`}</button>
        {busy && <button type="button" className="ws-btn" onClick={() => { stop.current = true; setBusy(false); }} data-testid="tr-cancel">رها کردن</button>}
      </div>
      {busy && <div className="ws-muted" data-testid="tr-status"><Spinner size={12} /> {label}</div>}
      {error && <div className="mt-2"><Alert tone="bad" title="ترجمه انجام نشد">{error}</Alert></div>}
      <p className="ws-hint">ترجمه با هوش مصنوعی انجام می‌شود (اول سرورِ پردازش، وگرنه سرویسِ ابری). اگر هیچ‌کدام در دسترس نباشد دلیلش این‌جا نوشته می‌شود و می‌توانید بعداً دوباره بزنید. زمانِ هر خط همان زمانِ اصل می‌ماند؛ برای زبان‌های راست‌به‌چپ نیازی به تغییر نیست.</p>
    </div>
  );
}
