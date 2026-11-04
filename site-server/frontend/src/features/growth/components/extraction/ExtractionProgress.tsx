import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import Icon from "../../../../components/Icon";
import { Alert, Button, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import type { ExtractionJobDetail } from "../../types";
import { JobBadge } from "../bits";

const POLL_MS = 2000;

/**
 * Live progress of one extraction job (polled every 2 s). `floating` draws it as a small card in the corner
 * (the lead list); otherwise it is an inline block (the lead's «استخراج» tab). `onFinished` fires once.
 */
export default function ExtractionProgress({
  jobId,
  floating = false,
  onClose,
  onFinished,
}: {
  jobId: number;
  floating?: boolean;
  onClose?: () => void;
  onFinished?: (job: ExtractionJobDetail) => void;
}) {
  const [poll, setPoll] = useState<number | undefined>(POLL_MS);
  const { data: job, error, reload } = useGet<ExtractionJobDetail>(`/extraction/jobs/${jobId}/`, undefined, { poll });
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const running = !job || job.status === "queued" || job.status === "running";

  useEffect(() => setPoll(running ? POLL_MS : undefined), [running]);
  useEffect(() => {
    if (job && !running) onFinished?.(job);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, running]);

  const act = async (path: "cancel" | "resume") => {
    setBusy(true);
    setActionError(null);
    try {
      await g.post(`/extraction/jobs/${jobId}/${path}/`);
      reload();
      setPoll(POLL_MS);
    } catch (err) {
      setActionError(problem(err).message);
    } finally {
      setBusy(false);
    }
  };

  const body = (
    <div className="space-y-2.5" data-testid="extract-progress">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold" style={{ color: "var(--text)" }}>
          استخراجِ اطلاعاتِ تماس
        </span>
        {job && (
          <span data-testid="extract-status">
            <JobBadge status={job.status} label={job.status_label} />
          </span>
        )}
        {onClose && (
          <button type="button" className="u-btn u-btn-ghost u-btn-sm mr-auto" onClick={onClose} aria-label="بستن">
            <Icon name="x" size={14} />
          </button>
        )}
      </div>
      {error && !job && <Alert tone="bad">{error}</Alert>}
      {job && (
        <>
          <div className="u-meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress} aria-label="پیشرفتِ استخراج">
            <span
              style={{
                width: `${job.progress}%`,
                background: job.status === "failed" ? "var(--bad)" : job.status === "completed" ? "var(--ok)" : "var(--brand)",
                transition: "width .4s",
              }}
            />
          </div>
          <p className="text-xs leading-6" style={{ color: "var(--text-2)" }} data-testid="extract-counts">
            {fa(job.processed_items)} از {fa(job.total_items)} لید · {fa(job.pages_fetched)} صفحه خوانده شد · {fa(job.contacts_added)} راهِ تماسِ تازه
            {job.runs_failed > 0 && ` · ${fa(job.runs_failed)} ناموفق`}
            {job.runs_skipped > 0 && ` · ${fa(job.runs_skipped)} ردشده (بدونِ سایت یا تازه‌خوانده)`}
          </p>
          {job.status === "failed" && <Alert tone="bad">{job.error || "کار با خطا متوقف شد."}</Alert>}
          {job.stalled && running && <Alert tone="warn">پیشرفتی دیده نمی‌شود؛ شاید کارگرِ پس‌زمینه دوباره راه افتاده.</Alert>}
          <div className="flex flex-wrap gap-2">
            {running && (
              <Button size="sm" variant="danger" onClick={() => act("cancel")} disabled={busy} data-testid="extract-cancel">
                لغو
              </Button>
            )}
            {job.can_resume && (
              <Button size="sm" onClick={() => act("resume")} disabled={busy}>
                ادامه بده
              </Button>
            )}
          </div>
        </>
      )}
      {actionError && <Alert tone="bad">{actionError}</Alert>}
    </div>
  );

  if (!floating) return body;
  // Portalled to <body>: the page root keeps a CSS transform after its entrance animation, and a transformed ancestor
  // makes `position: fixed` relative to the page instead of the screen.
  return createPortal(
    <div
      className="u-card p-4"
      style={{ position: "fixed", insetBlockEnd: 16, insetInlineStart: 16, zIndex: 40, width: "min(24rem, calc(100vw - 2rem))", background: "var(--void-2)", borderColor: "var(--line-strong)" }}
      role="status"
    >
      {body}
    </div>,
    document.body,
  );
}
