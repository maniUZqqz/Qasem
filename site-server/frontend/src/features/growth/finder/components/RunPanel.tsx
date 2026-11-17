import { useEffect, useMemo, useRef, useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, fa } from "../../../../components/ui";
import { g, problem, useGet } from "../../api";
import { bytes, faAgo, faDateTime, num } from "../../format";
import type { LogRow, RunDetail, RunSummary } from "../types";
import { Meterbar, SOURCE_LABEL, TASK_STATUS_LABEL } from "./bits";

const STAGES = ["plan", "discover", "dedupe", "enrich", "finalize", "done"];
const STAGE_FA: Record<string, string> = { plan: "برنامه", discover: "پیدا کردن", dedupe: "یکی‌کردن", enrich: "تکمیل", finalize: "ساختنِ لید", done: "پایان" };
const ACTIVE = (r: { status: string }) => r.status === "queued" || r.status === "running";

function statusTone(run: RunSummary): "ok" | "bad" | "info" | "warn" | "neutral" {
  if (run.paused) return "warn";
  if (run.status === "completed") return run.tasks.waiting_node ? "info" : "ok";
  if (run.status === "failed") return "bad";
  if (run.status === "cancelled") return "neutral";
  return "info";
}

/**
 * One run, live: the six stages, progress, what was found, what the crawl used, the diary, and the controls (pause / resume / cancel).
 * While the run is active it polls every 3 seconds; a finished run is loaded once. The diary only scrolls by itself when you are
 * already at its bottom, so reading older lines is never interrupted.
 */
export default function RunPanel({ runId, onChanged }: { runId: number; onChanged?: () => void }) {
  const [poll, setPoll] = useState(3000);
  const { data: run, error, reload } = useGet<RunDetail>(`/finder/runs/${runId}/`, undefined, { poll });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const logBox = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    if (run) setPoll(ACTIVE(run) && !run.paused ? 3000 : run.tasks.waiting_node ? 20000 : 0);
  }, [run?.status, run?.paused, run?.tasks.waiting_node]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const el = logBox.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [run?.logs.length]);

  const act = async (action: "pause" | "resume" | "cancel" | "sync-node") => {
    setBusy(true);
    setNotice(null);
    try {
      await g.post(`/finder/runs/${runId}/${action}/`);
      if (action === "sync-node") setNotice("وضعیتِ سرورِ پردازش بررسی شد.");
      reload();
      onChanged?.();
    } catch (err) {
      setNotice(problem(err).message);
    } finally {
      setBusy(false);
    }
  };

  const sources = useMemo(() => Object.entries(run?.by_source ?? {}), [run?.by_source]);
  if (error && !run) return <Alert tone="bad">{error}</Alert>;
  if (!run) return null;
  const idx = Math.max(0, STAGES.indexOf(run.stage));
  const active = ACTIVE(run);

  return (
    <Card className="space-y-4" >
      <div data-testid="run-panel" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-bold" style={{ color: "var(--text)" }}>
              اجرای {fa(run.id)}
            </h3>
            <Badge tone={statusTone(run)}>{run.state_label}</Badge>
            {run.trigger === "schedule" && <Badge>زمان‌بندی</Badge>}
            {run.stalled && <Badge tone="warn">کند/بی‌حرکت</Badge>}
            <span className="text-xs" style={{ color: "var(--text-3)" }}>
              {run.started_at ? `شروع ${faAgo(run.started_at)}` : `در صف از ${faAgo(run.queued_at)}`}
              {run.finished_at ? ` · پایان ${faDateTime(run.finished_at)}` : ""}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {active && !run.paused && (
              <Button variant="secondary" size="sm" disabled={busy || run.pause_requested} onClick={() => act("pause")} data-testid="run-pause">
                <Icon name="pause" size={14} />
                {run.pause_requested ? "در حالِ توقف…" : "توقفِ موقت"}
              </Button>
            )}
            {(run.paused || run.status === "failed" || run.stalled || (run.status === "queued" && !!run.parked_until)) && run.status !== "cancelled" && run.status !== "completed" && (
              <Button size="sm" disabled={busy} onClick={() => act("resume")} data-testid="run-resume">
                <Icon name="play" size={14} />
                ادامه
              </Button>
            )}
            {run.status !== "completed" && run.status !== "cancelled" && (
              <Button variant="danger" size="sm" disabled={busy || run.cancel_requested} onClick={() => act("cancel")} data-testid="run-cancel">
                <Icon name="stop" size={14} />
                لغو
              </Button>
            )}
            {run.tasks.waiting_node > 0 && (
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => act("sync-node")} data-testid="run-sync-node">
                <Icon name="refresh" size={14} />
                بررسیِ سرورِ پردازش
              </Button>
            )}
          </div>
        </div>

        <ol className="flex flex-wrap items-center gap-1.5" aria-label="مرحله‌ها">
          {STAGES.map((s, i) => (
            <li key={s} className="flex items-center gap-1.5">
              <span
                className="rounded-full px-2.5 py-1 text-xs font-bold"
                style={{
                  background: i < idx || run.status === "completed" ? "var(--ok-soft)" : i === idx ? "var(--brand-soft, var(--info-soft))" : "var(--surface-2)",
                  color: i < idx || run.status === "completed" ? "var(--ok)" : i === idx ? "var(--brand)" : "var(--text-3)",
                }}
                aria-current={i === idx ? "step" : undefined}
              >
                {STAGE_FA[s]}
              </span>
              {i < STAGES.length - 1 && <span style={{ color: "var(--text-3)" }}>›</span>}
            </li>
          ))}
        </ol>

        <div>
          <div className="mb-1 flex items-center justify-between text-xs" style={{ color: "var(--text-3)" }}>
            <span data-testid="run-message">{run.message || run.stage_label}</span>
            <span className="u-num">{fa(run.progress)}٪</span>
          </div>
          <Meterbar value={run.progress} tone={run.status === "failed" ? "var(--bad)" : "var(--brand)"} />
        </div>

        {run.parked_until && run.status === "queued" && !run.paused && (
          <Alert tone="info">سرویسِ بیرونی (مثلاً سرورِ نقشه) شلوغ است؛ اجرا می‌خوابد و {faDateTime(run.parked_until)} خودش ادامه می‌دهد.</Alert>
        )}
        {run.error && <Alert tone="bad">{run.error}</Alert>}
        {run.tasks.waiting_node > 0 && (
          <Alert tone="info" title="بعضی کارها منتظرِ سرورِ پردازش‌اند">
            {fa(run.tasks.waiting_node)} کار (سایت‌های جاوااسکریپتی، پیج‌های اینستاگرام یا خواندنِ انبوه) در صفِ ماندگار است. اجرا منتظرشان نمی‌ماند؛ با روشن‌شدنِ سرورِ پردازش خودکار انجام و به لیدها اضافه می‌شوند. کاری لازم نیست.
          </Alert>
        )}
        {run.city_report && run.city_report.empty.length > 0 && (
          <Alert tone="warn" title={`برای ${run.city_report.empty.join("، ")} چیزی پیدا نشد`}>
            <ul className="list-disc space-y-0.5 ps-5" data-testid="empty-cities">
              {run.city_report.empty.map((c) => (
                <li key={c}>
                  <b>{c}</b>: {run.city_report?.notes[c] ?? ""}
                </li>
              ))}
            </ul>
          </Alert>
        )}
        {notice && <Alert tone="info">{notice}</Alert>}

        <div className="grid grid-cols-2 gap-2 md:grid-cols-6" data-testid="run-counters">
          {[
            ["پیداشده", run.found],
            ["پس از یکی‌کردن", run.unique],
            ["لیدِ تازه", run.created],
            ["ادغام در لیدِ موجود", run.merged],
            ["ردشده", run.skipped],
            ["صفحهٔ خوانده‌شده", run.pages],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-xl p-2.5 text-center" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
              <div className="u-num text-lg font-extrabold" style={{ color: "var(--text)" }}>
                {num(value as number)}
              </div>
              <div className="text-xs" style={{ color: "var(--text-3)" }}>
                {label}
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs" style={{ color: "var(--text-3)" }}>
          کارها: {fa(run.tasks.done)} از {fa(run.tasks.total)} انجام شد{run.tasks.failed ? `، ${fa(run.tasks.failed)} ناموفق` : ""} · حجمِ دریافتی {bytes(run.bytes)} · {fa(run.cache_hits)} صفحه از حافظه{run.usage?.seconds ? ` · ${fa(Math.round(run.usage.seconds / 60))} دقیقه` : ""}{run.out_of_area ? ` · ${fa(run.out_of_area)} مورد از شهرِ دیگر کنار گذاشته شد` : ""}
        </p>

        {run.city_report && Object.keys(run.city_report.cities).length > 1 && (
          <p className="text-xs" style={{ color: "var(--text-3)" }} data-testid="city-leads">
            لیدِ هر شهر: {Object.entries(run.city_report.cities).map(([c, v]) => `${c} ${fa(v.leads)}`).join(" · ")}
          </p>
        )}

        {sources.length > 0 && (
          <div className="flex flex-wrap gap-2" data-testid="run-sources">
            {sources.map(([src, st]) => (
              <span key={src} className="rounded-xl px-2.5 py-1.5 text-xs" style={{ background: "var(--surface-2)", border: "1px solid var(--line)", color: "var(--text-2)" }}>
                <b>{SOURCE_LABEL[src] ?? src}</b>:{" "}
                {Object.entries(st)
                  .map(([k, v]) => `${fa(v)} ${TASK_STATUS_LABEL[k] ?? k}`)
                  .join("، ")}
              </span>
            ))}
          </div>
        )}

        {run.sample.length > 0 && (
          <p className="text-xs" style={{ color: "var(--text-3)" }}>
            تازه‌ترین‌ها: {run.sample.map((s) => s.name).join("، ")}
          </p>
        )}

        <div>
          <div className="mb-1 text-sm font-bold" style={{ color: "var(--text-2)" }}>
            گزارشِ اجرا
          </div>
          <div
            ref={logBox}
            onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
            }}
            className="max-h-56 space-y-1 overflow-auto rounded-xl p-3 text-xs leading-6"
            style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
            data-testid="run-log"
          >
            {run.logs.map((l: LogRow) => (
              <div key={l.id} style={{ color: l.level === "error" ? "var(--bad)" : l.level === "warn" ? "var(--warn)" : "var(--text-2)" }}>
                {l.message}
              </div>
            ))}
            {!run.logs.length && <span style={{ color: "var(--text-3)" }}>هنوز چیزی ثبت نشده.</span>}
          </div>
        </div>
      </div>
    </Card>
  );
}
