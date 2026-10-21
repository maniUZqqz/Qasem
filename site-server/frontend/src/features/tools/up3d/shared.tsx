import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button } from "../../../components/ui";
import { P, dur, errMsg, fa, up3d } from "./api";
import type { Catalog, Job, JobState, Status } from "./types";

/**
 * قطعه‌های مشترکِ بخشِ سه‌بعدی: برچسبِ وضعیت، مراحلِ کار، خطِ کار، پیامِ کوتاه، پرس‌وجوی دوره‌ای، دفترِ دارایی‌ها،
 * و قطعه‌های «جریانِ راهنما»: بخشِ شماره‌دار، تنظیماتِ پیشرفتهٔ تاشو، هشدارِ «منتظرِ کارگر».
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
      {job.waiting && job.waiting.eligible.length === 0 && (
        <div className="mt-1 text-xs font-semibold" style={{ color: "var(--warn)" }}>
          منتظرِ کارگر —{" "}
          {job.waiting.needs_gpu && !job.waiting.allow_cpu ? "این کیفیت کارگرِ GPU می‌خواهد و کارگرِ GPU آنلاین نیست" : "هیچ کارگری آنلاین نیست"}
        </div>
      )}
      {action && <div className="mt-1.5">{action}</div>}
    </div>
  );
}

// ───────────────────────── جریانِ راهنما: بخشِ شماره‌دار، تنظیماتِ پیشرفته، منتظرِ کارگر

/** یک گامِ شماره‌دار: عنوان + یک خطِ راهنما + محتوا. همهٔ صفحه‌های سه‌بعدی از همین می‌سازند تا یک‌دست باشند. */
export function Section({
  n,
  title,
  help,
  children,
  id,
  action,
}: {
  n: number;
  title: ReactNode;
  help?: ReactNode;
  children: ReactNode;
  id?: string;
  action?: ReactNode;
}) {
  return (
    <section id={id} className="u-card u3d-section p-5">
      <div className="u3d-section-h">
        <span className="u3d-num">{fa(n)}</span>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold leading-tight" style={{ color: "var(--text)" }}>
            {title}
          </h2>
          {help && (
            <p className="mt-1 text-xs leading-5" style={{ color: "var(--text-3)" }}>
              {help}
            </p>
          )}
        </div>
        {action && <div className="flex flex-wrap gap-2">{action}</div>}
      </div>
      <div className="mt-4 space-y-3">{children}</div>
    </section>
  );
}

/** گزینه‌های کم‌کاربرد، تاشو — حذف نمی‌شوند، فقط از جلوی چشمِ تازه‌کار کنار می‌روند. */
export function Advanced({
  title = "تنظیماتِ پیشرفته",
  hint = "اختیاری — پیش‌فرض‌ها برای شروع کافی‌اند",
  children,
  open,
}: {
  title?: string;
  hint?: string;
  children: ReactNode;
  open?: boolean;
}) {
  return (
    <details className="u3d-adv" open={open}>
      <summary>
        <Icon name="settings" size={14} />
        {title}
        {hint && <span className="u3d-adv-hint">{hint}</span>}
      </summary>
      <div className="u3d-adv-body">{children}</div>
    </details>
  );
}

/**
 * کارِ آماده ولی بی‌کارگر: می‌گوید چرا (GPU لازم است / کسی آنلاین نیست)، کدام کارگرها آنلاین‌اند،
 * و سه راهِ پیشِ رو: اجرا روی CPU، راه‌اندازیِ کارگرِ GPU، لغو.
 */
export function WaitingAlert({ job, onAllowCpu, onCancel }: { job: Job; onAllowCpu?: (id: number) => void; onCancel?: (id: number) => void }) {
  const w = job.waiting;
  const toast = useToast();
  const [busyNode, setBusyNode] = useState<number | null>(null);
  if (!w) return null;
  const ready = w.eligible.length > 0;
  const gpuOnly = w.needs_gpu && !w.allow_cpu;
  const canCpu = !ready && gpuOnly && w.online.length > 0;
  // سرورِ پردازشِ GPU آنلاین است ولی کارگرِ سه‌بعدی‌اش نه ⇐ همین‌جا روشنش کن
  const idleGpuNodes = (w.gpu_nodes || []).filter((n) => n.online && !n.worker_online);
  const enable = async (id: number, name: string) => {
    setBusyNode(id);
    try {
      await up3d.setNode3d(id, true);
      toast(`«رندرِ سه‌بعدی» روی ${name} روشن شد؛ اگر Blender ندارد یک بار دانلود می‌کند (چند دقیقه)`);
    } catch (e) {
      toast(errMsg(e), true);
    } finally {
      setBusyNode(null);
    }
  };
  return (
    <Alert
      tone={ready ? "info" : "warn"}
      title={
        ready
          ? `کارگرِ «${w.eligible.join("، ")}» آماده است؛ کارِ #${fa(job.id)} تا چند ثانیهٔ دیگر شروع می‌شود`
          : `کارِ #${fa(job.id)} منتظرِ کارگر است و هیچ کارگرِ مناسبی آنلاین نیست`
      }
    >
      {!ready && (
        <div>
          {gpuOnly ? `کیفیتِ «${job.profile}» کارگرِ GPU می‌خواهد. ` : ""}
          {w.online.length
            ? `کارگرهای آنلاین: ${w.online.join("، ")}${gpuOnly ? " (CPU؛ برای این کیفیت مناسب نیستند)" : ""}.`
            : "هیچ کارگری آنلاین نیست."}
          {job.estimate_seconds ? ` تخمینِ زمان: ~${dur(job.estimate_seconds)}.` : ""}
        </div>
      )}
      {idleGpuNodes.length > 0 && (
        <div className="mt-1">
          {idleGpuNodes.map((n) => (
            <div key={n.id} className="mt-1 flex flex-wrap items-center gap-2">
              <span>
                سرورِ پردازشِ <b>{n.name}</b> ({Array.isArray(n.gpu) ? n.gpu.join("، ") : n.gpu}) آنلاین است ولی «رندرِ سه‌بعدی»اش
                {n.worker3d_running ? " در حالِ راه‌افتادن است (شاید Blender را دانلود می‌کند)" : " روشن نیست"}.
              </span>
              {!n.worker3d_running && (
                <Button size="sm" variant="secondary" disabled={busyNode === n.id} onClick={() => void enable(n.id, n.name)}>
                  روشن کردنِ رندرِ سه‌بعدی روی {n.name}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {canCpu && onAllowCpu && (
          <Button size="sm" variant="secondary" onClick={() => onAllowCpu(job.id)}>
            اجرا روی CPU (کند ولی راه می‌افتد)
          </Button>
        )}
        <Link to={P.workers()} className="u-btn u-btn-ghost u-btn-sm">
          راه‌اندازیِ کارگرِ GPU
        </Link>
        {onCancel && (
          <Button size="sm" variant="danger" onClick={() => onCancel(job.id)}>
            لغوِ کار
          </Button>
        )}
      </div>
    </Alert>
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

export function useCatalog(): { cat: Catalog | null; error: string | null; reload: () => Promise<void> } {
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
  /** بعد از نصب/حذفِ بستهٔ دارایی: دفتر از نو (برای همهٔ صفحه‌ها) */
  const reload = useCallback(async () => {
    try {
      setCat(await loadCatalog(true));
      setError(null);
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);
  return { cat, error, reload };
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
