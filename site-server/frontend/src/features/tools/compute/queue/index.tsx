import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, Select, Spinner, fa } from "../../../../components/ui";
import DeviceInfo, { DeviceChip } from "./DeviceInfo";
import JobOutputs from "./JobOutputs";
import {
  KIND_OPTIONS,
  MAX_SIZE,
  PAGE_SIZE,
  RETRY_LABEL,
  TABS,
  absoluteTime,
  buildQuery,
  bulkCancelConfirm,
  bulkCancelPlan,
  bulkRetryConfirm,
  bulkRetryNotice,
  bulkRetryPlan,
  retryNotice,
  type BulkRetryResult,
  cancelConfirm,
  cancelNotice,
  capabilityTotals,
  defaultTab,
  emptyText,
  nodeView,
  originLabel,
  positionView,
  progressPercent,
  queueWarning,
  relativeTime,
  shortUid,
  statusTone,
  waitView,
  type QueueJob,
  type QueueListing,
  type QueueNode,
  type Tab,
} from "./model";
import StoreJobsPanel from "./StoreJobs";
import "./queue.css";

/**
 * صفِ پردازش.
 *
 * کارهایی که باید روی سرورِ پردازش (کامپیوترِ گرافیکی) انجام شوند، اگر آن سرور خاموش باشد در صف می‌مانند و با روشن
 * شدنش خودکار اجرا می‌شوند؛ هیچ کاری فقط به‌خاطرِ خاموش بودنِ سرور ناموفق نمی‌شود. این صفحه همان صف را نشان می‌دهد:
 * چه کاری منتظر است، چرا، نفرِ چندم است، و اجازه می‌دهد کاری را لغو یا دوباره امتحان کنی.
 *
 * بازخوانی هر ۵ ثانیه تا وقتی زبانهٔ مرورگر دیده می‌شود. ردیف‌های قبلی تا رسیدنِ پاسخِ تازه می‌مانند (بدونِ پرش)،
 * و بازبودنِ جزئیات و جای اسکرول با بازخوانی عوض نمی‌شود (کلیدِ ردیف شناسهٔ کار است).
 */

const POLL_MS = 5000;

export default function ComputeQueuePage() {
  const [tab, setTab] = useState<Tab>("waiting");
  const [kindKey, setKindKey] = useState("");
  const [search, setSearch] = useState("");
  /** جستجوی تأخیری (۳۵۰ میلی‌ثانیه پس از آخرین حرف) */
  const [q, setQ] = useState("");
  /** چند ردیف نشان داده شود؛ «نمایش بیشتر» صد تا اضافه می‌کند (همیشه از ردیفِ اول، تا با بازخوانی ردیفی جا نیفتد یا دوبار نیاید) */
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [data, setData] = useState<QueueListing | null>(null);
  /** داده‌ای که در دست است جوابِ کدام پرس‌وجوست؛ اگر با پرس‌وجوی فعلی فرق کند، ردیف‌ها کم‌رنگ‌اند تا پاسخِ تازه برسد */
  const [dataKey, setDataKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [openRows, setOpenRows] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<Record<string, "cancel" | "retry">>({});
  const [bulkBusy, setBulkBusy] = useState(false);
  /** تا کاربر خودش تب را عوض نکرده، بعد از اولین پاسخ تبِ پیش‌فرض (منتظر یا همه) انتخاب می‌شود */
  const autoTab = useRef(true);
  const runRef = useRef<(() => void) | null>(null);
  const noticeTimer = useRef<number | null>(null);

  const query = buildQuery({ tab, kindKey, q, limit });

  useEffect(() => {
    const t = window.setTimeout(() => {
      setQ(search.trim());
      setLimit(PAGE_SIZE);
    }, 350);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(
    () => () => {
      if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    },
    [],
  );

  useEffect(() => {
    let alive = true;
    let inflight = false;
    let again = false;

    const run = async () => {
      if (inflight) {
        again = true; // یک بازخوانیِ دیگر بعد از این یکی (مثلاً بلافاصله بعد از لغو)
        return;
      }
      inflight = true;
      setRefreshing(true);
      try {
        const { data: d } = await api.get<QueueListing>(`/compute/queue/?${query}`);
        if (!alive) return;
        setData(d);
        setDataKey(query);
        setError(null);
        setLoadedAt(Date.now());
        if (autoTab.current) {
          autoTab.current = false;
          const wanted = defaultTab(d.counts);
          if (wanted !== "waiting") setTab(wanted);
        }
      } catch (err) {
        if (alive) setError(errorMessage(err));
      } finally {
        inflight = false;
        if (alive) {
          setRefreshing(false);
          if (again) {
            again = false;
            void run();
          }
        }
      }
    };

    runRef.current = () => void run();
    void run();
    const timer = window.setInterval(() => {
      if (!document.hidden) void run();
    }, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) void run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      runRef.current = null;
    };
  }, [query]);

  const flash = (text: string) => {
    setNotice(text);
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 6000);
  };

  const pickTab = (next: Tab) => {
    autoTab.current = false;
    setTab(next);
    setLimit(PAGE_SIZE);
  };

  const pickKind = (key: string) => {
    setKindKey(key);
    setLimit(PAGE_SIZE);
  };

  const clearFilters = () => {
    setKindKey("");
    setSearch("");
    setQ("");
    setLimit(PAGE_SIZE);
  };

  const act = async (job: QueueJob, what: "cancel" | "retry") => {
    if (what === "cancel" && !window.confirm(cancelConfirm(job))) return;
    setBusy((b) => ({ ...b, [job.uid]: what }));
    setActionError(null);
    try {
      const { data: updated } = await api.post<QueueJob>(`/compute/queue/${job.uid}/${what}/`);
      // ردیف همین حالا تازه می‌شود؛ بازخوانیِ بعدی جای درستش (تب) را هم روشن می‌کند
      setData((d) => (d ? { ...d, jobs: d.jobs.map((j) => (j.uid === job.uid ? updated : j)) } : d));
      flash(what === "cancel" ? cancelNotice(job) : retryNotice(updated));
      runRef.current?.();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy((b) => {
        const next = { ...b };
        delete next[job.uid];
        return next;
      });
    }
  };

  const plan = bulkCancelPlan(kindKey, q);
  const cancelAllWaiting = async () => {
    const count = data?.total ?? 0;
    if (!plan.allowed || count <= 0 || !window.confirm(bulkCancelConfirm(count, kindKey))) return;
    setBulkBusy(true);
    setActionError(null);
    try {
      const { data: res } = await api.post<{ cancelled: number }>("/compute/queue/cancel-waiting/", plan.kind ? { kind: plan.kind } : {});
      flash(`${fa(res.cancelled)} کار لغو شد.`);
      runRef.current?.();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const retryPlan = bulkRetryPlan(tab, kindKey, q);
  const retryAll = async () => {
    const count = data?.total ?? 0;
    if (!retryPlan.allowed || count <= 0 || !window.confirm(bulkRetryConfirm(count, tab, kindKey))) return;
    setBulkBusy(true);
    setActionError(null);
    try {
      const { data: res } = await api.post<BulkRetryResult>(
        "/compute/queue/retry-failed/",
        retryPlan.kind ? { state: retryPlan.state, kind: retryPlan.kind } : { state: retryPlan.state },
      );
      flash(bulkRetryNotice(res));
      runRef.current?.();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBulkBusy(false);
    }
  };

  const toggleRow = (uid: string) => setOpenRows((o) => ({ ...o, [uid]: !o[uid] }));

  const jobs = data?.jobs ?? [];
  const counts = data?.counts;
  const stale = dataKey !== query;
  const filtered = Boolean(q || kindKey);
  const warning = data ? queueWarning(data.nodes, data.counts.waiting) : null;

  // «۲ از ۵» فقط وقتی همهٔ منتظرها بارگذاری شده‌اند و فیلتری نیست؛ وگرنه فقط شمارهٔ جایگاه
  const waitingLoaded = jobs.filter((j) => j.group === "waiting").length;
  const completeQueue = !filtered && !stale && (tab === "waiting" || tab === "all") && counts !== undefined && waitingLoaded === counts.waiting;
  const capTotals = completeQueue ? capabilityTotals(jobs) : {};

  const total = data?.total ?? 0;
  const canMore = jobs.length < total && limit < MAX_SIZE;
  const capped = jobs.length < total && limit >= MAX_SIZE;

  return (
    <div className="nmq space-y-4">
      <PageHeader
        title="صفِ پردازش"
        subtitle="کارهایی که به سرورِ پردازش می‌روند اگر آن سرور خاموش باشد در صف می‌مانند و با روشن شدنش خودکار انجام می‌شوند؛ هیچ کاری فقط به‌خاطرِ خاموش بودنِ سرور ناموفق نمی‌شود."
        actions={
          <>
            <Link to="/tools/compute" className="u-btn u-btn-secondary u-btn-sm no-underline">
              سرورهای پردازش
            </Link>
            <Link to="/tools/compute/report" className="u-btn u-btn-secondary u-btn-sm no-underline">
              گزارشِ سرورها
            </Link>
          </>
        }
      />

      {data && <NodeStrip nodes={data.nodes} />}

      {warning && (
        <Alert tone="warn" title={warning.title}>
          <ol className="nmq-steps">
            {warning.steps.map((s, i) => (
              <li key={s}>
                <b>{fa(i + 1)}.</b>
                <span>{s}</span>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
            کارها از دست نمی‌روند؛ همین که سرور روشن شد، به‌ترتیب انجام می‌شوند.
          </p>
        </Alert>
      )}

      {(tab === "failed" || tab === "cancelled" || tab === "all") && <StoreJobsPanel onChanged={() => runRef.current?.()} />}

      {!data && !error && (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      )}
      {!data && error && <ErrorBox message={error} />}

      {data && (
        <Card padded={false}>
          <nav className="u-tabs px-2" role="tablist" aria-label="وضعیتِ کارها">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={`u-tab ${tab === t.key ? "active" : ""}`}
                onClick={() => pickTab(t.key)}
              >
                {t.label}
                <span className={`nmq-count ${t.key === "failed" && (counts?.failed ?? 0) > 0 ? "bad" : ""} ${t.key === "waiting" && (counts?.waiting ?? 0) > 0 && warning ? "warn" : ""}`}>
                  {fa(counts?.[t.key] ?? 0)}
                </span>
              </button>
            ))}
          </nav>

          <div className="nmq-toolbar">
            <Select
              aria-label="نوعِ کار"
              value={kindKey}
              onChange={(e) => pickKind(e.target.value)}
              className="nmq-kind"
            >
              {KIND_OPTIONS.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </Select>
            <Input
              type="search"
              aria-label="جستجو در کارها"
              placeholder="جستجو (شناسهٔ کار، نامِ کار، پیام، سرور…)"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="nmq-search"
            />
            <div className="nmq-toolbar-end">
              {tab === "waiting" && (
                <Button
                  variant="danger"
                  size="sm"
                  disabled={bulkBusy || !plan.allowed || total <= 0}
                  title={plan.allowed ? "همهٔ کارهای منتظرِ همین فهرست را لغو می‌کند" : plan.hint}
                  onClick={() => void cancelAllWaiting()}
                >
                  {bulkBusy ? <Spinner size={14} /> : <Icon name="x" size={14} />}
                  لغوِ همهٔ منتظرها
                </Button>
              )}
              {(tab === "failed" || tab === "cancelled") && (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={bulkBusy || !retryPlan.allowed || total <= 0}
                  title={retryPlan.allowed ? "همهٔ کارهای همین فهرست را که دوباره‌شدنی‌اند دوباره پردازش می‌کند" : retryPlan.hint}
                  onClick={() => void retryAll()}
                  data-testid="queue-retry-all"
                >
                  {bulkBusy ? <Spinner size={14} /> : <Icon name="refresh" size={14} />}
                  {tab === "failed" ? "پردازشِ دوبارهٔ همهٔ ناموفق‌ها" : "پردازشِ دوبارهٔ همهٔ لغوشده‌ها"}
                </Button>
              )}
              <span className="nmq-updated" title="فهرست هر ۵ ثانیه خودکار تازه می‌شود">
                آخرین به‌روزرسانی: <Ago at={loadedAt} />
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => runRef.current?.()}
                aria-label="تازه‌سازی"
                title="تازه‌سازی"
                style={{ padding: 7 }}
              >
                <span className={refreshing ? "nmq-spin" : ""} style={{ display: "inline-flex" }}>
                  <Icon name="refresh" size={16} />
                </span>
              </Button>
            </div>
          </div>

          {notice && (
            <div className="px-4 pt-3" role="status">
              <Alert tone="ok">{notice}</Alert>
            </div>
          )}
          {(actionError || error) && (
            <div className="px-4 pt-3">
              <ErrorBox message={actionError ?? error} />
            </div>
          )}

          <div className="nmq-wrap">
            {jobs.length > 0 && (
              <div className="nmq-head" aria-hidden="true">
                <span>کار</span>
                <span>وضعیت</span>
                <span>جایگاه</span>
                <span>منتظر مانده</span>
                <span>سرور</span>
                <span>زمانِ ثبت</span>
                <span />
              </div>
            )}

            <div className="nmq-list" data-stale={stale ? "1" : undefined} aria-busy={stale}>
              {jobs.map((job) => (
                <JobItem
                  key={job.uid}
                  job={job}
                  open={Boolean(openRows[job.uid])}
                  busy={busy[job.uid]}
                  capTotal={capTotals[job.capability]}
                  onToggle={() => toggleRow(job.uid)}
                  onAct={(what) => void act(job, what)}
                />
              ))}
            </div>

            {jobs.length === 0 && (stale ? (
              <div className="py-10 text-center">
                <Spinner />
              </div>
            ) : (
              <EmptyState
                icon={!filtered && tab === "waiting" ? "ok" : "empty"}
                description={emptyText(tab, filtered)}
                action={
                  filtered ? (
                    <Button variant="secondary" size="sm" onClick={clearFilters}>
                      پاک کردنِ فیلترها
                    </Button>
                  ) : undefined
                }
              />
            ))}
          </div>

          {jobs.length > 0 && (
            <div className="nmq-foot">
              <span>
                {fa(jobs.length)} از {fa(total)} کار
              </span>
              {canMore && (
                <Button variant="secondary" size="sm" onClick={() => setLimit((l) => Math.min(MAX_SIZE, l + PAGE_SIZE))}>
                  نمایش بیشتر
                </Button>
              )}
              {capped && <span>فقط {fa(MAX_SIZE)} کارِ اول نشان داده می‌شود؛ برای دیدنِ بقیه فیلتر بگذارید.</span>}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/** «۳ ثانیه پیش» که خودش هر ثانیه تازه می‌شود، بی‌آنکه کلِ صفحه دوباره رسم شود. */
function Ago({ at }: { at: number | null }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  if (!at) return <>—</>;
  return <>{relativeTime(new Date(at).toISOString())}</>;
}

function NodeStrip({ nodes }: { nodes: QueueNode[] }) {
  if (nodes.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--text-3)" }}>
        هنوز سرورِ پردازشی ثبت نشده است.
      </p>
    );
  }
  return (
    <div className="nmq-nodes" aria-label="سرورهای پردازش">
      {nodes.map((n) => {
        const v = nodeView(n);
        return (
          <div key={n.id} className="nmq-node" title={`${n.name}: ${v.label}`}>
            <span className={`nmq-dot ${v.state}`} aria-hidden="true" />
            <span className="nmq-node-name">{n.name}</span>
            <span className={`nmq-node-state ${v.state}`}>{v.label}</span>
            <span className="nmq-node-meta">{v.seen}</span>
            {v.version && <span className="nmq-node-meta">{v.version}</span>}
          </div>
        );
      })}
    </div>
  );
}

function JobItem({
  job,
  open,
  busy,
  capTotal,
  onToggle,
  onAct,
}: {
  job: QueueJob;
  open: boolean;
  busy?: "cancel" | "retry";
  capTotal?: number;
  onToggle: () => void;
  onAct: (what: "cancel" | "retry") => void;
}) {
  const pos = positionView(job, capTotal);
  const wait = waitView(job);
  const tone = statusTone(job);
  const pct = progressPercent(job.progress);
  const cancelling = job.group === "running" && !job.can_cancel;
  const sub = [job.kind_label !== job.title ? job.kind_label : "", job.store ? `فروشگاهِ ${job.store}` : ""].filter(Boolean).join(" · ");

  return (
    <div className={`nmq-item ${job.group}`}>
      <div className="nmq-row">
        <div className="nmq-cell nmq-c-title">
          <button type="button" className="nmq-title" aria-expanded={open} onClick={onToggle} title="دیدنِ جزئیات">
            <Icon name={open ? "up" : "down"} size={14} />
            <span className="nmq-title-text">
              <span className="nmq-title-main">{job.title}</span>
              <span className="nmq-sub">
                <span dir="ltr" className="nmq-mono nmq-id" title={`شناسهٔ کار: ${job.uid}`}>
                  #{job.short_id ?? shortUid(job.uid)}
                </span>
                {sub ? ` · ${sub}` : ""}
              </span>
            </span>
          </button>
        </div>

        <div className="nmq-cell nmq-c-status">
          <Badge tone={tone}>{job.status_text}</Badge>
          {job.group === "running" && (
            <div className="u-meter nmq-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
              <span
                className={pct > 0 ? "" : "nmq-indeterminate"}
                style={pct > 0 ? { width: `${pct}%`, background: "var(--brand)" } : { background: "var(--brand)" }}
              />
            </div>
          )}
        </div>

        <div className="nmq-cell nmq-c-pos" data-label="جایگاه">
          <span className="u-num nmq-main">{pos.main}</span>
          {pos.sub && <span className="nmq-small">{pos.sub}</span>}
        </div>

        <div className="nmq-cell nmq-c-wait" data-label="منتظر مانده">
          <span className="nmq-main">{wait.main}</span>
          {wait.sub && <span className="nmq-small">{wait.sub}</span>}
        </div>

        <div className="nmq-cell nmq-c-node" data-label="سرور">
          <span className="nmq-main">{job.node ?? "—"}</span>
          {!job.node && job.node_wanted && <span className="nmq-small">می‌خواهد: {job.node_wanted}</span>}
          <DeviceChip job={job} />
        </div>

        <div className="nmq-cell nmq-c-created" data-label="زمانِ ثبت">
          <span className="nmq-main" title={absoluteTime(job.created)}>
            {relativeTime(job.created)}
          </span>
        </div>

        <div className="nmq-cell nmq-c-act">
          {job.can_cancel && (
            <Button variant="secondary" size="sm" disabled={Boolean(busy)} onClick={() => onAct("cancel")}>
              {busy === "cancel" ? <Spinner size={13} /> : <Icon name="x" size={13} />}
              لغو
            </Button>
          )}
          {job.can_retry && (
            <Button
              variant="secondary"
              size="sm"
              disabled={Boolean(busy)}
              onClick={() => onAct("retry")}
              title={job.retry_hint || undefined}
            >
              {busy === "retry" ? <Spinner size={13} /> : <Icon name="refresh" size={13} />}
              {RETRY_LABEL}
            </Button>
          )}
          {cancelling && <span className="nmq-small">در حال لغو…</span>}
        </div>
      </div>

      {open && <JobDetails job={job} />}
    </div>
  );
}

function JobDetails({ job }: { job: QueueJob }) {
  const origin = originLabel(job.origin);
  const times: [string, string | null][] = [
    ["ثبت در صف", job.queued_at ?? job.created],
    ["شروع", job.claimed],
    ["پایان", job.finished],
  ];
  return (
    <div className="nmq-detail">
      {job.parked && (
        <p className="nmq-note">کارِ شما در صفحهٔ خودش (مثلاً تولیدِ تصویر) هم «در صف» نشان داده می‌شود.</p>
      )}

      {job.error && (
        <div>
          <div className="nmq-detail-head">
            <b>متنِ خطا</b>
            <CopyButton text={job.error} />
          </div>
          <pre className="nmq-err" dir="ltr">
            {job.error}
          </pre>
        </div>
      )}

      {job.input && (job.input.text || job.input.system) ? (
        <div>
          <div className="nmq-detail-head">
            <b>ورودی{job.input.model ? ` — ${job.input.model}` : ""}</b>
            <CopyButton text={job.input.text || job.input.system || ""} />
          </div>
          <pre className="nmq-io" dir="auto">
            {job.input.text || job.input.system}
          </pre>
        </div>
      ) : null}

      {job.outputs && job.outputs.length > 0 ? (
        <JobOutputs outputs={job.outputs} />
      ) : job.group === "done" ? (
        <p className="nmq-note">این کار خروجیِ فایلی نداشت (نتیجه‌اش مستقیم به همان صفحه‌ای رفت که آن را فرستاد).</p>
      ) : null}

      <DeviceInfo job={job} />

      {job.retry_hint && (job.group === "failed" || job.group === "cancelled") && (
        <p className="nmq-note">
          <b>{job.can_retry ? `${RETRY_LABEL}: ` : "پردازشِ دوباره از این‌جا نمی‌شود: "}</b>
          {job.retry_hint}
        </p>
      )}

      {job.message && job.message !== job.status_text && (
        <p className="nmq-msg">
          <b>پیام: </b>
          {job.message}
        </p>
      )}

      <dl className="nmq-kv">
        {job.max_attempts > 0 && (
          <div>
            <dt>تلاش</dt>
            <dd>
              {fa(job.attempts)} از {fa(job.max_attempts)}
            </dd>
          </div>
        )}
        {job.lost_count > 0 && (
          <div>
            <dd>{fa(job.lost_count)} بار سرور وسطِ کار قطع شد (از تلاش‌ها کم نشد)</dd>
          </div>
        )}
        {origin && (
          <div>
            <dt>از کجا</dt>
            <dd>{origin}</dd>
          </div>
        )}
        {job.model && (
          <div>
            <dt>مدل</dt>
            <dd dir="ltr">{job.model}</dd>
          </div>
        )}
        {job.node_wanted && (
          <div>
            <dt>سرورِ خواسته‌شده</dt>
            <dd>{job.node_wanted}</dd>
          </div>
        )}
        {job.scheduled_for && (
          <div>
            <dt>شروعِ زمان‌بندی‌شده</dt>
            <dd>{absoluteTime(job.scheduled_for)}</dd>
          </div>
        )}
        {job.window && (
          <div>
            <dt>بازهٔ مجاز (وقتِ تهران)</dt>
            <dd dir="ltr">{fa(job.window)}</dd>
          </div>
        )}
        {times.map(([label, iso]) =>
          iso ? (
            <div key={label}>
              <dt>{label}</dt>
              <dd title={absoluteTime(iso)}>{relativeTime(iso)}</dd>
            </div>
          ) : (
            <Fragment key={label} />
          ),
        )}
        <div>
          <dt>شناسه</dt>
          <dd dir="ltr" className="nmq-mono" title={job.uid}>
            {shortUid(job.uid)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** رونوشتِ متن. روی نشانیِ بدونِ https (مثل این پنل) `navigator.clipboard` نیست، پس روشِ قدیمی هم دارد. */
function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );
  const copy = async () => {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
      document.body.appendChild(ta);
      ta.select();
      try {
        ok = document.execCommand("copy");
      } catch {
        ok = false;
      }
      ta.remove();
    }
    if (ok) {
      setDone(true);
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setDone(false), 2000);
    }
  };
  return (
    <button type="button" className="nmq-copy" onClick={() => void copy()}>
      <Icon name={done ? "check" : "copy"} size={13} />
      {done ? "کپی شد" : "کپی"}
    </button>
  );
}
