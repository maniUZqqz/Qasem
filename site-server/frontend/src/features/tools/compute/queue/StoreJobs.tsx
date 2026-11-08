import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, ErrorBox, Spinner, fa } from "../../../../components/ui";
import {
  RETRY_LABEL,
  RETRY_NOTICE,
  absoluteTime,
  bulkRetryNotice,
  relativeTime,
  shortError,
  storeJobsTitle,
  type BulkRetryResult,
  type StoreJob,
  type StoreJobsListing,
} from "./model";

/**
 * «کارهای فروشگاه‌ها که ناموفق یا لغو شدند» — کپشن، تحلیلِ محصول، تصویر، ویدیو، صداگذاری، تدوین…
 *
 * هر کدام را می‌شود «پردازشِ دوباره» زد: همان کار با همان ورودی‌ها از اول دوباره فرستاده می‌شود (apps.jobs.retry)؛ اگر به
 * سرورِ پردازش نیاز داشته باشد، در صف می‌ماند تا سرور آماده شود. اعتبار را خودِ کار مثلِ بارِ اول حساب می‌کند.
 */
export default function StoreJobsPanel({ onChanged }: { onChanged?: () => void }) {
  const [data, setData] = useState<StoreJobsListing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | "all-failed" | "all-cancelled" | null>(null);
  const [open, setOpen] = useState(true);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<StoreJobsListing>("/compute/store-jobs/?state=bad&days=7&limit=50");
      setData(d);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 15000);
    return () => window.clearInterval(t);
  }, [load]);

  const retryOne = async (job: StoreJob) => {
    setBusy(job.id);
    setError(null);
    try {
      const { data: d } = await api.post<StoreJob & { notice?: string }>(`/compute/store-jobs/${job.id}/retry/`);
      setNotice(d.notice || RETRY_NOTICE);
      await load();
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const retryAll = async (state: "failed" | "cancelled") => {
    const n = state === "failed" ? data?.counts.FAILED ?? 0 : data?.counts.CANCELLED ?? 0;
    const what = state === "failed" ? "ناموفق" : "لغوشده";
    if (!n || !window.confirm(`همهٔ ${fa(n)} کارِ ${what}ِ فروشگاه‌ها (۷ روزِ اخیر) دوباره پردازش شوند؟`)) return;
    setBusy(state === "failed" ? "all-failed" : "all-cancelled");
    setError(null);
    try {
      const { data: r } = await api.post<BulkRetryResult>("/compute/store-jobs/retry-all/", { state, days: 7 });
      setNotice(bulkRetryNotice(r));
      await load();
      onChanged?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  if (!data && !error) return null;
  const jobs = data?.jobs ?? [];

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          className="flex items-center gap-2 text-right font-bold"
          style={{ color: "var(--text)" }}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <Icon name={open ? "up" : "down"} size={14} />
          {data ? storeJobsTitle(data) : "کارهای فروشگاه‌ها"}
        </button>
        {data && (
          <div className="flex flex-wrap gap-2">
            {data.counts.FAILED > 0 && (
              <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => void retryAll("failed")}>
                {busy === "all-failed" ? <Spinner size={13} /> : <Icon name="refresh" size={13} />}
                پردازشِ دوبارهٔ همهٔ ناموفق‌ها
              </Button>
            )}
            {data.counts.CANCELLED > 0 && (
              <Button variant="ghost" size="sm" disabled={busy !== null} onClick={() => void retryAll("cancelled")}>
                {busy === "all-cancelled" ? <Spinner size={13} /> : <Icon name="refresh" size={13} />}
                پردازشِ دوبارهٔ لغوشده‌ها
              </Button>
            )}
          </div>
        )}
      </div>
      <p className="mt-1 text-xs leading-6" style={{ color: "var(--text-3)" }}>
        همان کار با همان ورودی‌ها از اول دوباره فرستاده می‌شود؛ اگر سرورِ پردازش لازم باشد، در صف می‌ماند تا آماده شود.
      </p>

      {notice && (
        <div className="mt-3" role="status">
          <Alert tone="ok">{notice}</Alert>
        </div>
      )}
      <div className="mt-2">
        <ErrorBox message={error} />
      </div>

      {open && jobs.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5">
          {jobs.map((j) => (
            <li
              key={j.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2"
              style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <b style={{ color: "var(--text)" }}>{j.type_label}</b>
                  <Badge tone={j.state === "FAILED" ? "bad" : "neutral"}>{j.state_label}</Badge>
                  {j.store && <span className="text-xs" style={{ color: "var(--text-3)" }}>فروشگاهِ {j.store}</span>}
                  {j.retry_count > 0 && <Badge tone="warn">تلاش {fa(j.retry_count + 1)}</Badge>}
                  <span className="text-xs" style={{ color: "var(--text-3)" }} title={absoluteTime(j.updated)}>
                    {relativeTime(j.updated)}
                  </span>
                </div>
                {j.error && (
                  <p className="mt-0.5 text-xs leading-6" style={{ color: "var(--bad)" }} title={j.error}>
                    {shortError(j.error)}
                  </p>
                )}
              </div>
              {j.can_retry ? (
                <Button variant="secondary" size="sm" disabled={busy !== null} onClick={() => void retryOne(j)}>
                  {busy === j.id ? <Spinner size={13} /> : <Icon name="refresh" size={13} />}
                  {RETRY_LABEL}
                </Button>
              ) : (
                <span className="text-xs" style={{ color: "var(--text-3)" }}>
                  از صفحهٔ خودش دوباره بسازید
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {open && data && data.total > jobs.length && (
        <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
          {fa(jobs.length)} کارِ آخر از {fa(data.total)} کار نشان داده شد.
        </p>
      )}
    </Card>
  );
}
