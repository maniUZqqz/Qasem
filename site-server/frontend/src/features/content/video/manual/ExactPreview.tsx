import { useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import { Alert, Badge, Spinner, fa } from "../../../../components/ui";
import { useJobRunner } from "../../../../hooks/useJobRunner";
import type { Job } from "../../../../types";
import { videoApi } from "../api";
import { timecode } from "./model";
import "./text.css";

type Props = {
  storeId: string;
  projectId: number | null;
  /** پروژهٔ فعلیِ ویرایشگر (نه نسخهٔ ذخیره‌شده)؛ سرور همین را رندر می‌کند */
  getData: () => unknown;
  t0: number;
  t1: number;
  /** پروژه را ذخیره می‌کند (اگر هنوز نیست می‌سازد) و شناسه را برمی‌گرداند */
  ensureSaved: () => Promise<number | null>;
  onClose: () => void;
};

type Result = { url: string; t0: number; t1: number; size: string; seconds: number; notes: string[] };

const MAX_SECONDS = 20;

/**
 * «پیش‌نمایشِ دقیقِ این بازه»: همان گرافِ رندرِ نهایی برای چند ثانیه در کیفیتِ پایین روی سرور ساخته و این‌جا پخش می‌شود.
 * پیش‌نمایشِ فوریِ مرورگر برای چیزهایی که مرورگر دقیق نمی‌تواند (ثابت‌کردن، حذفِ نویز، گذارهای xfade، کیفیتِ chroma key، منحنیِ سرعت …) کافی نیست.
 */
export default function ExactPreview({ storeId, projectId, getData, t0, t1, ensureSaved, onClose }: Props) {
  const to = Math.min(t1, t0 + MAX_SECONDS);
  const clamped = t1 > to + 0.01;
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const jobId = useRef<number | null>(null);
  const started = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const onDone = useCallback(async () => {
    const id = jobId.current;
    if (id === null) return;
    try {
      const { data } = await api.get<Job>(`/jobs/${id}/`);
      const r = data.result as Partial<Result> | undefined;
      if (alive.current && r?.url) setResult({ url: r.url, t0: r.t0 ?? t0, t1: r.t1 ?? to, size: r.size ?? "", seconds: r.seconds ?? to - t0, notes: r.notes ?? [] });
      else if (alive.current) setError("پیش‌نمایش ساخته شد ولی فایلش پیدا نشد؛ دوباره امتحان کنید.");
    } catch (err) {
      if (alive.current) setError(errorMessage(err));
    }
  }, [t0, to]);
  const runner = useJobRunner(onDone);

  const run = useCallback(async () => {
    setError(null);
    setResult(null);
    setStarting(true);
    try {
      const id = await ensureSaved();
      if (!id) {
        setError("پروژه ذخیره نشد؛ پیش‌نمایشِ دقیق شروع نشد.");
        return;
      }
      runner.begin();
      const r = await videoApi.preview(storeId, id, { t0, t1: to, height: 360, data: getData() });
      jobId.current = r.job_id;
      runner.track(r.job_id);
    } catch (err) {
      runner.fail(errorMessage(err));
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeId, t0, to, ensureSaved, getData]);

  // همین که باز شد شروع می‌شود (یک بار؛ StrictMode دو بار نمی‌سازد)
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void run();
  }, [run]);

  const label = runner.job?.current_step_label || "";
  const percent = runner.job && runner.job.total_steps === 100 ? Math.max(0, Math.min(100, runner.job.progress_step)) : 0;
  const queued = /صف/.test(label);
  const busy = starting || runner.running;
  const err = error || runner.error;
  const range = `${timecode(t0).slice(0, 5)} تا ${timecode(to).slice(0, 5)}`;

  return (
    <div className="xprev" role="dialog" aria-label="پیش‌نمایشِ دقیقِ این بازه" data-testid="exact-preview" dir="rtl">
      <div className="xprev-head">
        <Badge tone="brand">پیش‌نمایشِ دقیق (رندرِ سرور)</Badge>
        <span className="ws-muted" dir="ltr">{range}</span>
        <span className="ws-spacer" />
        <button type="button" className="ws-btn" onClick={onClose} aria-label="بستنِ پیش‌نمایشِ دقیق" data-testid="exact-close">× بستن</button>
      </div>

      {busy && (
        <div className="xprev-wait" data-testid="exact-wait">
          <div className="xp-bar" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <i style={{ width: `${queued || (starting && !runner.job) ? 5 : Math.max(5, percent)}%` }} />
          </div>
          <div className="ws-muted"><Spinner size={12} /> {starting && !runner.job ? "در حالِ ذخیره و ثبتِ درخواست…" : label || "در حالِ ساختنِ پیش‌نمایش…"}</div>
          {queued && <div className="ws-hint">سرور الان رندرِ دیگری دارد؛ نوبتِ شما که شد شروع می‌شود.</div>}
          <button type="button" className="ws-btn" onClick={() => { void runner.cancel(); setStarting(false); setError("پیش‌نمایش لغو شد."); }} data-testid="exact-cancel">لغو</button>
        </div>
      )}

      {!busy && err && (
        <div className="xprev-wait">
          <Alert tone="bad" title="پیش‌نمایشِ دقیق ساخته نشد">{err}</Alert>
          <button type="button" className="ws-btn mt-2" onClick={() => { started.current = true; void run(); }} data-testid="exact-retry">دوباره امتحان کن</button>
        </div>
      )}

      {!busy && !err && result && (
        <div className="xprev-body">
          <video className="xprev-video" src={result.url} controls autoPlay loop playsInline data-testid="exact-video" />
          <div className="ws-muted">
            این همان گرافِ رندرِ نهایی است در کیفیتِ پایین (<span dir="ltr">{result.size}</span>، {fa(Math.round(result.seconds * 10) / 10)} ثانیه) — شامل چیزهایی که پیش‌نمایشِ فوریِ مرورگر فقط تقریب می‌زند.
          </div>
          {result.notes.map((n, i) => <p key={i} className="xp-warn">{n}</p>)}
        </div>
      )}
      {clamped && <p className="ws-hint">پیش‌نمایشِ دقیق حداکثر {fa(MAX_SECONDS)} ثانیه است؛ از سرِ بازه همان‌قدر ساخته شد.</p>}
    </div>
  );
}
