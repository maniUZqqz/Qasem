import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "../../../components/ui";
import { P, dur, errMsg, fa, up3d } from "./api";
import type { Catalog, Job, JobState, Status } from "./types";

/**
 * قطعه‌های مشترکِ بخشِ سه‌بعدی: برچسبِ وضعیت، مراحلِ کار، خطِ کار، پیامِ کوتاه، پرس‌وجوی دوره‌ای و دفترِ دارایی‌ها.
 */

// ───────────────────────── وضعیتِ کار

const STATE_FA: Record<JobState, string> = {
  PENDING: "در صف",
  PLANNING: "برنامه‌ریزی",
  PLANNED: "برنامه آماده",
  SCENE_BUILDING: "ساختِ صحنه",
  RENDERING: "رندر",
  QUALITY_CHECK: "کنترلِ کیفیت",
  ASSEMBLING: "مونتاژ",
  COMPLETED: "تمام",
  FAILED: "ناموفق",
  CANCELLED: "لغو",
};

const RENDER_SEQ: JobState[] = ["PENDING", "PLANNED", "SCENE_BUILDING", "RENDERING", "QUALITY_CHECK", "ASSEMBLING", "COMPLETED"];
const PLAN_SEQ: JobState[] = ["PENDING", "PLANNING", "COMPLETED"];
const OTHER_SEQ: JobState[] = ["PENDING", "PLANNED", "SCENE_BUILDING", "RENDERING", "QUALITY_CHECK", "COMPLETED"];

export function StateBadge({ job }: { job: Job }) {
  const tone =
    job.state === "COMPLETED"
      ? job.qc?.result === "fail"
        ? "warn"
        : "ok"
      : job.state === "FAILED"
        ? "bad"
        : job.state === "CANCELLED"
          ? "neutral"
          : "info";
  return (
    <Badge tone={tone}>
      {!job.final && (
        <span
          aria-hidden
          style={{ width: 7, height: 7, borderRadius: "50%", background: "currentColor", animation: "u3d-pulse 1.2s infinite" }}
        />
      )}
      {job.state_label || STATE_FA[job.state] || job.state}
    </Badge>
  );
}

/** مراحلِ کار به ترتیب، با مرحلهٔ فعلی و ناموفق/لغو در انتها. */
export function JobSteps({ job }: { job: Job }) {
  const seq = job.kind === "plan" ? PLAN_SEQ : job.kind === "render" ? RENDER_SEQ : OTHER_SEQ;
  let idx = seq.indexOf(job.state);
  if (job.state === "FAILED" || job.state === "CANCELLED") idx = -1;
  return (
    <div className="u3d-steps">
      {seq.map((s, i) => {
        let cls = "";
        if (idx >= 0 && i < idx) cls = "done";
        if (i === idx) cls = job.state === "COMPLETED" ? "done" : "now";
        return (
          <span key={s} className={cls}>
            {STATE_FA[s]}
          </span>
        );
      })}
      {idx < 0 && <span className="fail">{STATE_FA[job.state]}</span>}
    </div>
  );
}

export function Bar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="u3d-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${pct}%` }} />
    </div>
  );
}

/** یک کار در یک نگاه: نوع و شماره، وضعیت، پروفایل/فریم/مانده/کارگر، نوارِ پیشرفت، پیام. */
export function JobLine({ job, action }: { job: Job; action?: ReactNode }) {
  const eta = job.eta_seconds
    ? ` · مانده ~${dur(job.eta_seconds)}`
    : job.state !== "COMPLETED" && job.estimate_seconds && !job.final
      ? ` · تخمین ~${dur(job.estimate_seconds)}`
      : "";
  const frames = job.frames_total ? ` · فریم ${fa(job.frames_done)}/${fa(job.frames_total)}` : "";
  return (
    <div className="rounded-xl px-3 py-2" style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}>
      <div className="flex items-center justify-between gap-2">
        <Link to={P.job(job.id)} className="text-sm font-bold" style={{ color: "var(--text)" }}>
          {job.kind_label} #{fa(job.id)}
        </Link>
        <StateBadge job={job} />
      </div>
      <div className="mt-0.5 text-xs" style={{ color: "var(--text-3)" }}>
        <span className="u3d-mono">{job.profile || ""}</span>
        {frames}
        {eta}
        {job.worker ? ` · ${job.worker}` : ""}
        {job.project_title ? ` · ${job.project_title}` : ""}
      </div>
      {!job.final && (
        <div className="mt-1.5">
          <Bar value={job.progress || 0} />
        </div>
      )}
      {job.message && (
        <div className="mt-1 text-xs" style={{ color: "var(--text-3)" }}>
          {job.message}
        </div>
      )}
      {action && <div className="mt-1.5">{action}</div>}
    </div>
  );
}

// ───────────────────────── پیامِ کوتاه

type Toast = { id: number; text: string; bad: boolean };
type ToastFn = (text: string, bad?: boolean) => void;

const ToastCtx = createContext<ToastFn>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const seq = useRef(0);
  const toast = useCallback<ToastFn>((text, bad = false) => {
    const id = ++seq.current;
    setItems((prev) => [...prev, { id, text, bad }]);
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), bad ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div className="u3d-toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`u3d-toast ${t.bad ? "bad" : ""}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast(): ToastFn {
  return useContext(ToastCtx);
}

// ───────────────────────── پرس‌وجوی دوره‌ای

/**
 * `fn` را بلافاصله و بعد هر `ms` میلی‌ثانیه صدا می‌زند تا وقتی `true` برگرداند یا کامپوننت برود.
 * خطا حلقه را نمی‌کُشد (شبکه قطع شد ⇐ دورِ بعد دوباره). `deps` عوض شود، از نو شروع می‌کند.
 */
export function usePoll(fn: () => Promise<boolean | void>, ms: number, deps: unknown[]) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      if (stopped) return;
      try {
        if ((await ref.current()) === true) stopped = true;
      } catch {
        /* دورِ بعد دوباره */
      }
      if (!stopped) timer = window.setTimeout(tick, ms);
    };
    void tick();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

// ───────────────────────── دفترِ دارایی‌ها (یک بار برای همهٔ صفحه‌ها)

let catalogCache: Promise<Catalog> | null = null;

export function loadCatalog(force = false): Promise<Catalog> {
  if (!catalogCache || force) {
    catalogCache = up3d.catalog().catch((e) => {
      catalogCache = null;
      throw e;
    });
  }
  return catalogCache;
}

export function useCatalog(): { cat: Catalog | null; error: string | null } {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    loadCatalog()
      .then((c) => alive && setCat(c))
      .catch((e) => alive && setError(errMsg(e)));
    return () => {
      alive = false;
    };
  }, []);
  return { cat, error };
}

export function useStatus(pollMs = 0): Status | null {
  const [st, setSt] = useState<Status | null>(null);
  usePoll(
    async () => {
      setSt(await up3d.status());
      return pollMs === 0;
    },
    pollMs || 1000,
    [pollMs],
  );
  return st;
}

// ───────────────────────── تب‌های دکمه‌ای (داخلِ یک کارت)

export function ButtonTabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: ReactNode }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="u-tabs mb-3">
      {tabs.map((t) => (
        <button key={t.id} type="button" className={`u-tab ${value === t.id ? "active" : ""}`} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Muted({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`text-sm ${className}`} style={{ color: "var(--text-3)" }}>
      {children}
    </p>
  );
}
