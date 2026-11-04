import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Button, Card, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { faDateTime } from "../../format";
import type { DiscoveryJob } from "../../types";
import { ConfirmDialog } from "../Modal";
import { JobBadge, LoadState } from "../bits";
import JobReport from "./JobReport";

const POLL_MS = 1500;

function Counter({ label, value, tone, testId }: { label: string; value: number; tone?: string; testId: string }) {
  return (
    <div className="rounded-xl px-3 py-2" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }} data-testid={testId}>
      <div className="u-num text-xl font-extrabold" style={{ color: tone ?? "var(--text)" }}>
        {fa(value)}
      </div>
      <div className="text-xs" style={{ color: "var(--text-3)" }}>
        {label}
      </div>
    </div>
  );
}

/**
 * One CSV import: live progress while it runs (polled every 1.5 s), cancel / resume, and - once it has
 * finished - the row-level report. Mount it with `key={jobId}`.
 */
export default function JobPanel({ jobId }: { jobId: number }) {
  const [poll, setPoll] = useState<number | undefined>(POLL_MS);
  const { data: job, error, reload } = useGet<DiscoveryJob>(`/discovery/jobs/${jobId}/`, undefined, { poll });
  const [cancelOpen, setCancelOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const running = !job || job.status === "queued" || job.status === "running";
  useEffect(() => {
    setPoll(running ? POLL_MS : undefined);
  }, [running]);

  const act = async (path: "cancel" | "resume") => {
    setBusy(true);
    setActionError(null);
    try {
      await g.post(`/discovery/jobs/${jobId}/${path}/`);
      setCancelOpen(false);
      reload();
      setPoll(POLL_MS);
    } catch (err) {
      setActionError(problem(err).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <LoadState loading={!job && !error} error={job ? null : error} onRetry={reload}>
        {job && (
          <div className="space-y-4" data-testid="job-panel">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-bold" dir="auto" style={{ color: "var(--text)" }}>
                {job.file_name || `ورودی ${fa(job.id)}`}
              </h3>
              <span data-testid="job-status">
                <JobBadge status={job.status} label={job.status_label} />
              </span>
              <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
                ورودی {fa(job.id)} · شروع: {faDateTime(job.started_at ?? job.queued_at)}
                {job.finished_at ? ` · پایان: ${faDateTime(job.finished_at)}` : ""}
              </span>
            </div>

            <div>
              <div className="mb-1 flex items-center justify-between text-sm" style={{ color: "var(--text-2)" }}>
                <span data-testid="job-progress-text">
                  {fa(job.processed_items)} از {fa(job.total_items)} {job.kind === "search" ? "مورد" : "ردیف"}
                </span>
                <span className="u-num font-bold">{fa(job.progress)}٪</span>
              </div>
              <div
                className="u-meter"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={job.progress}
                aria-label="پیشرفتِ ورود"
                data-testid="job-progress"
                data-progress={job.progress}
              >
                <span
                  style={{
                    width: `${job.progress}%`,
                    background: job.status === "failed" ? "var(--bad)" : job.status === "cancelled" ? "var(--warn)" : job.status === "completed" ? "var(--ok)" : "var(--brand)",
                    transition: "width .4s",
                  }}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              <Counter label="لیدِ تازه" value={job.created_count} tone="var(--ok)" testId="count-created" />
              <Counter label="تکراری، منتظرِ تصمیم" value={job.duplicate_count} tone={job.duplicate_count ? "var(--warn)" : undefined} testId="count-duplicate" />
              <Counter label="ادغام‌شده" value={job.merged_count} testId="count-merged" />
              <Counter label="ردشده" value={job.skipped_count} testId="count-skipped" />
              <Counter label="ردیفِ خطادار" value={job.error_count} tone={job.error_count ? "var(--bad)" : undefined} testId="count-error" />
            </div>

            {job.kind === "search" && job.attribution && (
              <p className="text-xs" style={{ color: "var(--text-3)" }} data-testid="job-attribution">
                منبع:{" "}
                {job.params.attribution_url ? (
                  <a href={job.params.attribution_url} target="_blank" rel="noopener noreferrer" dir="auto" style={{ color: "var(--brand-strong)" }}>
                    {job.attribution}
                  </a>
                ) : (
                  <span dir="auto">{job.attribution}</span>
                )}
              </p>
            )}
            {job.kind === "search" && job.status === "completed" && job.total_items === 0 && (
              <Alert tone="warn" title="چیزی پیدا نشد">
                {job.params.empty_note || "هیچ موردی با این مشخصات پیدا نشد."}
              </Alert>
            )}
            {job.params.extract_after && job.status !== "completed" && (
              <p className="text-xs" style={{ color: "var(--text-3)" }}>
                پس از پایانِ ورود، خواندنِ راه‌های تماس از سایتِ لیدهای تازه هم خودکار شروع می‌شود.
              </p>
            )}
            {job.cancel_requested && running && (
              <Alert tone="warn">درخواستِ لغو ثبت شد؛ کار در اولین فرصت می‌ایستد.</Alert>
            )}
            {job.stalled && running && (
              <Alert
                tone="warn"
                title="کار متوقف شده به نظر می‌رسد"
                action={
                  job.can_resume && (
                    <Button size="sm" onClick={() => act("resume")} disabled={busy}>
                      ادامه بده
                    </Button>
                  )
                }
              >
                مدتی است پیشرفتی نکرده؛ شاید سرور یا کارگرِ پس‌زمینه دوباره راه‌اندازی شده. «ادامه بده» از جایی که مانده ادامه می‌دهد و چیزی دوبار ثبت نمی‌شود.
              </Alert>
            )}
            {job.status === "failed" && (
              <Alert
                tone="bad"
                title="ورود با خطا متوقف شد"
                action={
                  job.can_resume && (
                    <Button size="sm" onClick={() => act("resume")} disabled={busy} data-testid="job-resume">
                      <Icon name="refresh" size={14} />
                      ادامه بده
                    </Button>
                  )
                }
              >
                {job.error || "دلیلش ثبت نشد."} {job.kind === "search" ? "مواردی که تا اینجا ثبت شده‌اند می‌مانند." : "ردیف‌هایی که تا اینجا ثبت شده‌اند می‌مانند."}
              </Alert>
            )}
            {job.status === "cancelled" && <Alert tone="warn">ورود لغو شد؛ ردیف‌هایی که قبلاً ثبت شده بودند می‌مانند.</Alert>}
            {actionError && <Alert tone="bad">{actionError}</Alert>}

            <div className="flex flex-wrap items-center gap-2">
              {running && (
                <Button variant="danger" size="sm" onClick={() => setCancelOpen(true)} disabled={busy || job.cancel_requested} data-testid="job-cancel">
                  لغوِ ورود
                </Button>
              )}
              {!running && job.created_count + job.merged_count > 0 && (
                <Link to={`/growth/leads?source_job=${job.id}&archived=all`} className="no-underline" data-testid="job-leads-link">
                  <Button variant="secondary" size="sm">
                    <Icon name="users" size={14} />
                    مشاهدهٔ لیدهای این ورودی
                  </Button>
                </Link>
              )}
            </div>

            {!running && <JobReport job={job} onChanged={reload} />}
          </div>
        )}
      </LoadState>

      <ConfirmDialog
        open={cancelOpen}
        title="لغوِ ورود؟"
        message="ردیف‌هایی که تا الان ثبت شده‌اند می‌مانند؛ بقیه ثبت نمی‌شوند."
        confirmLabel="بله، لغو شود"
        danger
        busy={busy}
        onConfirm={() => act("cancel")}
        onClose={() => !busy && setCancelOpen(false)}
      />
    </Card>
  );
}
