import { useEffect, useRef, useState } from "react";

import { api } from "../../../../api/client";
import { Alert, Badge, Spinner, fa } from "../../../../components/ui";
import type { Job } from "../../../../types";

/** «تدوینِ حرفه‌ای» از لحظهٔ صف تا خروجیِ نهایی: کارِ تدوین ← (در صورتِ خاموشی) تکمیلِ زیرنویس‌ها ← رندرِ هر اندازه روی سرورِ پردازش.
 *  همه‌چیز را از خودِ کارها می‌خواند؛ هیچ‌چیز را از خودش نمی‌سازد. */

const TERMINAL = ["COMPLETED", "FAILED", "CANCELLED"];

function useJob(id: number | null): Job | null {
  const [job, setJob] = useState<Job | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (!id) return undefined;
    let dead = false;
    let errors = 0;
    const tick = async () => {
      try {
        const { data } = await api.get<Job>(`/jobs/${id}/`);
        if (dead) return;
        errors = 0;
        setJob(data);
        if (TERMINAL.includes(data.state)) return;
      } catch {
        if (++errors > 8) return;
      }
      timer.current = window.setTimeout(() => void tick(), 4000);
    };
    void tick();
    return () => {
      dead = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [id]);
  return job;
}

export type Render = { size: string; title: string; project_id: number; job_id: number };
type Delivered = { project_id?: number; renders?: Render[]; skipped?: { title?: string; reason?: string }[] | string };
type Output = { output?: string; srt_url?: string; where?: string; audio_qc?: { clean?: boolean; problems?: string[]; lufs?: number } };

const STATE_TONE: Record<string, "ok" | "bad" | "warn" | "info"> = { COMPLETED: "ok", FAILED: "bad", CANCELLED: "warn" };
const stateText = (j: Job | null) => (!j ? "…" : j.state_label || j.current_step_label || j.state);

export function RenderLine({ render }: { render: Render }) {
  const job = useJob(render.job_id);
  const out = (job?.result ?? {}) as Output;
  const done = job?.state === "COMPLETED" && out.output;
  return (
    <li className="rounded-md border p-2" style={{ borderColor: "var(--line)" }} data-testid="polish-render">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <strong>{render.title}</strong>
        <Badge tone={STATE_TONE[job?.state ?? ""] ?? "info"}>{stateText(job)}</Badge>
        {job && !TERMINAL.includes(job.state) && <Spinner size={14} />}
        {done && out.where === "node" && <Badge tone="brand">روی کارتِ گرافیک ساخته شد</Badge>}
        {done && out.audio_qc && (out.audio_qc.clean ? <Badge tone="ok">صدا سالم</Badge> : <Badge tone="warn">{(out.audio_qc.problems ?? []).join("، ") || "صدا را بشنوید"}</Badge>)}
      </div>
      {job?.state === "FAILED" && <p className="mt-1 text-xs" style={{ color: "var(--bad)" }}>{job.error}</p>}
      {job && !TERMINAL.includes(job.state) && job.progress_step > 0 && <progress className="mt-1 w-full" value={job.progress_step} max={Math.max(1, job.total_steps)} />}
      {done && (
        <div className="mt-2 flex flex-col gap-2">
          <video src={out.output} controls preload="metadata" className="max-h-80 rounded-md" style={{ background: "#000" }} />
          <div className="flex flex-wrap gap-3 text-sm">
            <a href={out.output} download className="underline">دانلودِ ویدیو</a>
            {out.srt_url && <a href={out.srt_url} download className="underline">زیرنویس (فایلِ جدا)</a>}
          </div>
        </div>
      )}
    </li>
  );
}

function Renders({ delivered }: { delivered: Delivered }) {
  const renders = delivered.renders ?? [];
  const skipped = Array.isArray(delivered.skipped) ? delivered.skipped : [];
  return (
    <>
      {renders.length > 0 && <ul className="mt-2 flex flex-col gap-2">{renders.map((r) => <RenderLine key={r.job_id} render={r} />)}</ul>}
      {typeof delivered.skipped === "string" && <p className="mt-2 text-sm" style={{ color: "var(--warn)" }}>{delivered.skipped}</p>}
      {skipped.map((s, i) => <p key={i} className="mt-2 text-sm" style={{ color: "var(--warn)" }}>{s.title}: {s.reason}</p>)}
    </>
  );
}

export default function PolishStatus({ jobId }: { jobId: number }) {
  const job = useJob(jobId);
  const result = (job?.result ?? {}) as { delivered?: Delivered; waiting_node?: { job_id: number; steps: number; then_render?: boolean }; degraded?: string[] };
  const fillId = result.waiting_node?.job_id ?? null;
  const fill = useJob(fillId);
  const delivered = result.delivered ?? ((fill?.result ?? {}) as { delivered?: Delivered }).delivered;
  const failed = job?.state === "FAILED" || job?.state === "CANCELLED";
  return (
    <div data-testid="polish-status">
      <Alert tone={failed ? "bad" : job?.state === "COMPLETED" ? "ok" : "info"} title="تدوینِ حرفه‌ای">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>{failed ? (job?.error || "کار انجام نشد.") : stateText(job)}</span>
          {job && !TERMINAL.includes(job.state) && <Spinner size={14} />}
          {job && !TERMINAL.includes(job.state) && job.current_step_label && <span style={{ color: "var(--text-2)" }}>{job.current_step_label}</span>}
        </div>
        {job?.state === "QUEUED" && /منتظر/.test(job.current_step_label ?? "") && (
          <p className="mt-1 text-sm" data-testid="polish-waiting">
            کارِ شما در صفِ ماندگار است و همین‌که سرورِ پردازش (کامپیوترِ گرافیکی) روشن شود خودش شروع می‌شود؛ لازم نیست این صفحه باز بماند. اگر الان نتیجهٔ فوری می‌خواهید «⚡ تدوینِ سریع» را بزنید.
          </p>
        )}
        {job?.state === "COMPLETED" && !delivered && result.waiting_node && (
          <p className="mt-1 text-sm">
            {fa(result.waiting_node.steps)} مرحله (زیرنویس و …) منتظرِ سرورِ پردازش است؛ همین‌که روشن شود خودکار انجام می‌شود و بعدش ویدیو ساخته می‌شود. لازم نیست این صفحه باز بماند.
          </p>
        )}
        {job?.state === "COMPLETED" && !delivered && !result.waiting_node && <p className="mt-1 text-sm">پیش‌نویس در «کارگردان ← پیش‌نویس‌ها» آماده است.</p>}
        {(result.degraded ?? []).map((d, i) => <p key={i} className="mt-1 text-xs" style={{ color: "var(--text-2)" }}>{d}</p>)}
      </Alert>
      {delivered && <Renders delivered={delivered} />}
    </div>
  );
}
