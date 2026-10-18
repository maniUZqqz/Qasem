import { useEffect, useState } from "react";

import { Job } from "../types";
import { Spinner } from "./ui";

/** After this long a run is unusual enough to offer a way out. */
const LONG_RUN_SECONDS = 8 * 60;

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s} ثانیه`;
  return `${m} دقیقه و ${s} ثانیه`;
}

/**
 * Unified progress box for AI jobs (beter.md #2/#8): step label, determinate
 * or animated indeterminate bar, and a live elapsed-time counter so the user
 * can see the system is alive during long local-model runs.
 *
 * `onCancel` is what keeps a panel from ever being locked: whatever the server
 * is doing, this button gives the control back (beter.md v2 #1/#2).
 */
export default function JobProgress({
  job,
  fallbackLabel = "در صف پردازش…",
  startedAt = null,
  onCancel,
}: {
  job: Job | null;
  fallbackLabel?: string;
  startedAt?: number | null;
  onCancel?: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // the job row's own creation time wins (it survives a page refresh); the
  // click time covers the window before the job even exists
  const start = job ? new Date(job.created_at).getTime() : (startedAt ?? now);
  const elapsed = Math.max(0, Math.floor((now - start) / 1000));
  const hasSteps = (job?.total_steps ?? 0) > 0;
  const percent = hasSteps
    ? Math.min(100, Math.round(((job?.progress_step ?? 0) / (job?.total_steps ?? 1)) * 100))
    : null;
  const tooLong = elapsed > LONG_RUN_SECONDS;

  return (
    <div className="mb-4 rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-900">
      <div className="flex items-center gap-2">
        <Spinner />
        <span className="font-medium">{job?.current_step_label || fallbackLabel}</span>
        {hasSteps && (
          <span className="text-xs text-violet-700">
            (مرحله {job!.progress_step} از {job!.total_steps})
          </span>
        )}
        {onCancel && (
          <button
            onClick={onCancel}
            className="mr-auto rounded-full border border-violet-300 px-3 py-1 text-xs text-violet-700 transition hover:bg-violet-100"
          >
            لغو
          </button>
        )}
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-violet-100">
        {percent !== null ? (
          <div
            className="h-full rounded-full bg-violet-600 transition-all duration-700"
            style={{ width: `${Math.max(percent, 4)}%` }}
          />
        ) : (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-violet-400" />
        )}
      </div>
      <p className="mt-2 text-xs text-violet-700">
        ⏱ {formatElapsed(elapsed)} گذشته — مدل‌های AI لوکال کند هستند؛ سیستم در حال کار است و
        این صفحه خودکار به‌روز می‌شود. می‌توانید صفحه را ترک کنید و برگردید.
      </p>
      {tooLong && (
        <p className="mt-1 text-xs font-medium text-amber-700">
          ⚠️ این کار غیرعادی طولانی شده. اگر مدل روی سیستم جا نشده باشد ممکن است تمام نشود —
          می‌توانید «لغو» بزنید و دوباره امتحان کنید.
        </p>
      )}
    </div>
  );
}
