import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, Spinner, fa } from "../../../../components/ui";
import JobOutputs from "../queue/JobOutputs";
import {
  DEVICE_FA,
  GROUP_FA,
  TRIGGER_FA,
  deviceTone,
  featureText,
  featureTone,
  kindPercent,
  mbText,
  offlineText,
  secondsText,
  stateText,
  stateTone,
  whenText,
  type AutoSettings,
  type BootFeature,
  type NodeBlock,
  type Overview,
  type Progress,
  type Run,
  type TestResult,
} from "./model";
import "./selftest.css";

/**
 * «آزمونِ خودکارِ سرورِ پردازش» (فقط کارکنان، ۱۴۰۵/۰۸/۲۱).
 *
 * برای هر قابلیتِ سرورِ پردازش یک کارِ واقعیِ کوچک: کارتِ گرافیک دیده می‌شود؟ رمزگذاریِ ویدیو روی کارت؟ مدلِ متنی و بینایی؟ تصویر؟
 * جداسازیِ پس‌زمینه؟ تشخیصِ گفتار؟ صدا؟ رندرِ ویرایشگر؟ و به‌روزرسانیِ از راه دور. خودکار پس از هر نسخهٔ تازه و هر شب اجرا می‌شود؛
 * این‌جا هم دکمهٔ «آزمونِ کامل» و «دوباره» برای هر مورد هست. زیرش: نصبِ خودکارِ نیازمندی‌ها، خودکارها (به‌روزرسانی، شروعِ
 * خودکار) و پیشرفتِ کلیِ صف. تا وقتی اجرایی در جریان است هر ۵ ثانیه، وگرنه هر ۲۰ ثانیه تازه می‌شود.
 */

const POLL_FAST = 5000;
const POLL_SLOW = 20000;

export default function SelfTestPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const { data: d } = await api.get<Overview>("/compute/selftests/");
      if (!alive.current) return;
      setData(d);
      setErr(null);
    } catch (e) {
      if (alive.current) setErr(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const fast = !!data?.nodes.some((n) => n.running || n.bootstrap?.summary?.installing);
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, fast ? POLL_FAST : POLL_SLOW);
    return () => window.clearInterval(t);
  }, [load, fast]);

  const act = async (id: string, fn: () => Promise<void>) => {
    setBusy(id);
    setNotice(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const startRun = (node: NodeBlock, deep: boolean) =>
    act(`run-${node.id}-${deep ? "deep" : "std"}`, async () => {
      const { data: r } = await api.post<Run & { already_running?: boolean }>("/compute/selftests/run/", { node: node.id, deep });
      if (r.already_running) setNotice("یک آزمون همین حالا روی این سرور در جریان است؛ همان نشان داده می‌شود.");
    });

  const rerun = (run: Run, key: string) =>
    act(`re-${run.id}-${key}`, async () => {
      await api.post(`/compute/selftests/${run.id}/rerun/`, { key });
    });

  const retryBoot = (node: NodeBlock) =>
    act(`boot-${node.id}`, async () => {
      await api.post(`/compute/nodes/${node.id}/bootstrap/`);
      setNotice("دستورِ «تلاش دوباره» برای سرور فرستاده شد؛ تا ۲۰ ثانیه برداشته می‌شود.");
    });

  const setAutostart = (node: NodeBlock, enabled: boolean) =>
    act(`auto-${node.id}`, async () => {
      await api.post(`/compute/nodes/${node.id}/autostart/`, { enabled });
      setNotice(enabled ? "شروعِ خودکار روشن شد؛ در اولین ارتباطِ بعدیِ سرور اعمال می‌شود." : "شروعِ خودکار خاموش شد؛ در اولین ارتباطِ بعدی اعمال می‌شود.");
    });

  const saveSettings = (patch: Partial<AutoSettings>) =>
    act("settings", async () => {
      await api.post("/compute/settings/", patch);
    });

  return (
    <div className="nmt">
      <PageHeader
        title="آزمونِ خودکارِ سرورِ پردازش"
        subtitle="برای هر قابلیت یک کارِ واقعیِ کوچک؛ هر بار که برنامهٔ سرورِ پردازش نسخهٔ تازه بگیرد و هر شب خودکار اجرا می‌شود."
        actions={
          <>
            <Link to="/tools/compute/queue" className="u-btn u-btn-secondary u-btn-sm no-underline">
              <Icon name="clock" size={13} /> صفِ پردازش
            </Link>
            <Link to="/tools/compute/report" className="u-btn u-btn-secondary u-btn-sm no-underline">
              <Icon name="chart" size={13} /> گزارش
            </Link>
            <Button size="sm" variant="secondary" onClick={() => void load()}>
              <Icon name="refresh" size={13} /> تازه‌سازی
            </Button>
          </>
        }
      />
      <ErrorBox message={err} />
      {notice && (
        <Alert tone="info">
          {notice}
        </Alert>
      )}

      {!data && !err && (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      )}

      {data && data.nodes.length === 0 && (
        <Card>
          <EmptyState icon="cpu" title="سرورِ پردازشی ثبت نشده">
            اول در صفحهٔ «سرورهای پردازش» یک سرور را با کلیدِ ثبت وصل کنید؛ بعد آزمون‌ها خودکار برایش اجرا می‌شوند.
          </EmptyState>
        </Card>
      )}

      {data?.nodes.map((n) => (
        <NodeSection key={n.id} node={n} busy={busy} onRun={startRun} onRerun={rerun} onBoot={retryBoot} onAutostart={setAutostart} />
      ))}

      {data && <ProgressCard progress={data.progress} />}
      {data && <SettingsCard s={data.settings} busy={busy === "settings"} onSave={saveSettings} />}
    </div>
  );
}

// ───────────────────────────────────────────── یک سرور

function NodeSection({
  node,
  busy,
  onRun,
  onRerun,
  onBoot,
  onAutostart,
}: {
  node: NodeBlock;
  busy: string | null;
  onRun: (n: NodeBlock, deep: boolean) => void;
  onRerun: (r: Run, key: string) => void;
  onBoot: (n: NodeBlock) => void;
  onAutostart: (n: NodeBlock, enabled: boolean) => void;
}) {
  const run = node.run;
  return (
    <Card padded={false}>
      <div className="nmt-sec">
        <div className="nmt-head">
          <span className={`nmt-dot ${node.online ? "online" : "offline"}`} />
          <span className="nmt-name">{node.name}</span>
          {node.online ? <Badge tone="ok">روشن</Badge> : <Badge tone="bad">خاموش</Badge>}
          {node.agent && (
            <span className="nmt-small">
              برنامه <span dir="ltr">v{node.agent}</span>
            </span>
          )}
          <div className="nmt-head-end">
            <Button size="sm" disabled={!node.online || busy !== null} onClick={() => onRun(node, false)}>
              {busy === `run-${node.id}-std` ? <Spinner size={12} /> : <Icon name="play" size={13} />} آزمونِ کامل
            </Button>
            <Button size="sm" variant="secondary" disabled={!node.online || busy !== null} onClick={() => onRun(node, true)}>
              {busy === `run-${node.id}-deep` ? <Spinner size={12} /> : <Icon name="film" size={13} />} آزمونِ عمیق (با ویدیوی طولانی)
            </Button>
          </div>
        </div>
        {!node.online && (
          <p className="nmt-small">
            سرورِ پردازش الان خاموش است{node.last_seen ? ` (آخرین ارتباط: ${whenText(node.last_seen)})` : ""}. به‌محضِ روشن شدن و وصل شدنِ برنامه، آزمون خودکار شروع می‌شود و کارهای
            منتظرِ صف هم یکی‌یکی انجام می‌شوند.
          </p>
        )}
        <GpuLine node={node} />
      </div>

      <div className="nmt-sec" style={{ borderTop: "1px solid var(--line)" }}>
        <div className="nmt-sec-title">
          <h2>نتیجهٔ آزمون</h2>
          {run && (
            <span>
              {TRIGGER_FA[run.trigger] ?? run.trigger} — {whenText(run.created)}
              {run.agent_version ? ` — نسخهٔ ${fa(run.agent_version)}` : ""}
            </span>
          )}
        </div>
        {!run ? (
          <p className="nmt-small">هنوز آزمونی اجرا نشده. بعد از وصل شدنِ سرور خودکار شروع می‌شود، یا دکمهٔ «آزمونِ کامل» را بزنید.</p>
        ) : (
          <RunView run={run} busy={busy} onRerun={onRerun} />
        )}
      </div>

      <div className="nmt-sec" style={{ borderTop: "1px solid var(--line)" }}>
        <BootstrapView node={node} busy={busy === `boot-${node.id}`} onRetry={() => onBoot(node)} />
      </div>

      <div className="nmt-sec" style={{ borderTop: "1px solid var(--line)" }}>
        <AutomationView node={node} busy={busy === `auto-${node.id}`} onAutostart={(e) => onAutostart(node, e)} />
      </div>
    </Card>
  );
}

function GpuLine({ node }: { node: NodeBlock }) {
  const g = node.gpu_info || {};
  const ff = g.ffmpeg || {};
  if (!g.name && !node.gpu && !ff.path) return null;
  return (
    <div className="nmt-chips">
      <span className={`nmt-chip ${g.visible === false ? "bad" : "ok"}`}>
        <Icon name="cpu" size={12} /> <span dir="ltr">{g.name || node.gpu || "GPU"}</span>
      </span>
      {g.driver && (
        <span className={`nmt-chip ltr ${g.driver_ok === false ? "warn" : ""}`}>درایور {g.driver}</span>
      )}
      {g.vram_total_mb ? (
        <span className="nmt-chip">
          حافظهٔ کارت: {mbText(g.vram_used_mb)} از {mbText(g.vram_total_mb)}
        </span>
      ) : null}
      {ff.path && (
        <span className={`nmt-chip ${ff.nvenc_h264 ? "ok" : "warn"}`}>
          رمزگذاریِ ویدیو روی کارت (NVENC): {ff.nvenc_h264 ? "کار می‌کند" : "ندارد"}
        </span>
      )}
      {ff.path && ff.cuda_decode ? <span className="nmt-chip ok">خواندنِ ویدیو روی کارت (NVDEC)</span> : null}
    </div>
  );
}

function RunView({ run, busy, onRerun }: { run: Run; busy: string | null; onRerun: (r: Run, key: string) => void }) {
  const s = run.summary;
  const results = run.results ?? [];
  const verdict =
    run.state === "RUNNING" ? (
      <Badge tone="info">
        <Spinner size={10} /> در حال اجرا
      </Badge>
    ) : run.state === "ABORTED" ? (
      <Badge tone="warn">نیمه‌کاره ماند</Badge>
    ) : s.ok ? (
      <Badge tone="ok">همه قبول</Badge>
    ) : (
      <Badge tone="bad">{fa(s.required_failed)} مورد رد شد</Badge>
    );
  const requeued = Object.entries(run.requeued || {}).filter(([, v]) => (v?.retried ?? 0) > 0);
  return (
    <>
      <div className="nmt-head">
        {verdict}
        {run.note && <span className="nmt-small">{run.note}</span>}
        {run.finished && <span className="nmt-small">پایان: {whenText(run.finished)}</span>}
      </div>
      <div className="nmt-tiles">
        <div className="nmt-tile">
          <b>{fa(s.total)}</b>
          <span>آزمون</span>
        </div>
        <div className="nmt-tile ok">
          <b>{fa(s.passed)}</b>
          <span>قبول</span>
        </div>
        <div className={`nmt-tile ${s.failed ? "bad" : ""}`}>
          <b>{fa(s.failed)}</b>
          <span>رد</span>
        </div>
        <div className="nmt-tile">
          <b>{fa(s.skipped)}</b>
          <span>اجرا نشد (قابلیت روی سرور نیست)</span>
        </div>
        <div className={`nmt-tile ${s.warnings ? "warn" : ""}`}>
          <b>{fa(s.warnings)}</b>
          <span>هشدارِ کارت/پردازنده</span>
        </div>
      </div>
      {requeued.length > 0 && (
        <Alert tone="ok" title="کارهای ناموفقِ قبلی دوباره به صف رفتند">
          {requeued.map(([k, v]) => `${results.find((r) => r.key === k)?.label ?? k}: ${fa(v.retried ?? 0)} کار`).join(" — ")}
        </Alert>
      )}
      <div className="nmt-list">
        {results.map((r) => (
          <TestRow key={r.key} r={r} busy={busy === `re-${run.id}-${r.key}`} disabled={busy !== null || !run.node_online} onRerun={() => onRerun(run, r.key)} />
        ))}
      </div>
    </>
  );
}

function TestRow({ r, busy, disabled, onRerun }: { r: TestResult; busy: boolean; disabled: boolean; onRerun: () => void }) {
  const running = r.state === "RUNNING" || r.state === "QUEUED" || r.state === "WAITING";
  const g = r.extra?.gpu;
  return (
    <div className="nmt-test">
      <div className="nmt-test-row">
        <Badge tone={stateTone(r.state)}>
          {running ? <Spinner size={10} /> : null} {stateText(r.state)}
        </Badge>
        <span className="nmt-test-title">{r.label}</span>
        {GROUP_FA[r.group] && <span className="nmt-small">{GROUP_FA[r.group]}</span>}
        {r.optional && <Badge tone="neutral">اختیاری</Badge>}
        {r.deep && <Badge tone="neutral">عمیق</Badge>}
        <div className="nmt-test-end">
          {r.device && DEVICE_FA[r.device] ? <Badge tone={deviceTone(r.device)}>{DEVICE_FA[r.device]}</Badge> : null}
          {r.seconds !== null && r.seconds !== undefined && <span className="nmt-small">{fa(secondsText(r.seconds))}</span>}
          <Button size="sm" variant="ghost" disabled={disabled || busy} onClick={onRerun}>
            {busy ? <Spinner size={12} /> : <Icon name="refresh" size={13} />} دوباره
          </Button>
        </div>
      </div>
      {r.detail ? <p className="nmt-detail">{r.detail}</p> : r.describe && r.state === "PENDING" ? <p className="nmt-small">{r.describe}</p> : null}
      {r.warning && <p className="nmt-warn">هشدار: {r.warning}</p>}
      {g && (g.util_max !== undefined || g.vram_max_mb !== undefined) && (
        <div className="nmt-gpu">
          {g.util_max !== undefined && (
            <span>
              کارت: میانگین {fa(Math.round(g.util_avg ?? 0))}٪ — بیشینه {fa(g.util_max)}٪
            </span>
          )}
          {g.vram_max_mb !== undefined && (
            <span>
              حافظهٔ کارت: تا {mbText(g.vram_max_mb)} از {mbText(g.vram_total_mb)}
            </span>
          )}
          {g.temp_max_c !== undefined && <span>دما: تا {fa(g.temp_max_c)}°</span>}
        </div>
      )}
      {r.artifacts && r.artifacts.length > 0 && <JobOutputs outputs={r.artifacts} />}
    </div>
  );
}

// ───────────────────────────────────────────── نصبِ خودکار

function BootstrapView({ node, busy, onRetry }: { node: NodeBlock; busy: boolean; onRetry: () => void }) {
  const b = node.bootstrap || {};
  const feats = Object.entries(b.features || {});
  const bad = feats.filter(([, f]) => f.state === "failed").length;
  return (
    <>
      <div className="nmt-sec-title">
        <h2>نصبِ خودکارِ نیازمندی‌ها</h2>
        <div className="nmt-head-end">
          {bad > 0 || feats.some(([, f]) => f.state === "waiting") ? (
            <Button size="sm" variant="secondary" disabled={!node.online || !node.can_bootstrap || busy} onClick={onRetry}>
              {busy ? <Spinner size={12} /> : <Icon name="refresh" size={13} />} تلاش دوباره
            </Button>
          ) : null}
        </div>
      </div>
      {feats.length === 0 ? (
        <p className="nmt-small">
          {node.online
            ? node.can_bootstrap
              ? "هنوز گزارشی از نصب نرسیده؛ چند دقیقه بعد از روشن شدنِ برنامه پدیدار می‌شود."
              : "برنامهٔ این سرور هنوز نصبِ خودکار را نمی‌شناسد؛ با اولین به‌روزرسانی (خودکار) یاد می‌گیرد."
            : "گزارشِ نصب وقتی سرور روشن شد می‌رسد."}
        </p>
      ) : (
        <div className="grid gap-2">
          {feats.map(([key, f]) => (
            <FeatureView key={key} id={key} f={f} />
          ))}
        </div>
      )}
      {b.errors && b.errors.length > 0 && (
        <Alert tone="warn" title="فایلِ نیازمندیِ خراب">
          {b.errors.map((e) => `${e.file}: ${e.error}`).join(" — ")}
        </Alert>
      )}
      <p className="nmt-small">
        هر قابلیت فقط یک فایلِ کوچک در پوشهٔ <code dir="ltr">requirements.d</code> برنامه است؛ سرور آن را خودش (از آینهٔ همین سایت، PyPI و hf-mirror) نصب می‌کند و کارهایی که به آن نیاز دارند تا آماده شدنش در صف می‌مانند.
      </p>
    </>
  );
}

function FeatureView({ id, f }: { id: string; f: BootFeature }) {
  if (!f.applicable) {
    return (
      <div className="nmt-feat">
        <div className="nmt-feat-head">
          <span className="nmt-feat-title">{f.title}</span>
          <Badge tone="neutral">لازم نیست</Badge>
          <span className="nmt-small">{f.why}</span>
        </div>
      </div>
    );
  }
  return (
    <div className="nmt-feat" data-feature={id}>
      <div className="nmt-feat-head">
        <span className="nmt-feat-title">{f.title}</span>
        <Badge tone={featureTone(f.state)}>
          {f.state === "installing" ? <Spinner size={10} /> : null} {featureText(f.state)}
        </Badge>
        {f.kinds.length > 0 && (
          <span className="nmt-small" dir="ltr">
            {f.kinds.join(", ")}
          </span>
        )}
      </div>
      {f.items
        .filter((it) => f.state !== "ready" || it.state !== "ready")
        .map((it) => (
          <div className="nmt-item" key={it.id}>
            <div className="nmt-item-row">
              <Badge tone={featureTone(it.state)}>{featureText(it.state)}</Badge>
              <span>{it.title}</span>
              {it.detail && <span className="nmt-small nmt-wrap">{it.detail}</span>}
              {it.tries > 0 && it.state === "failed" && <span className="nmt-small">تلاشِ {fa(it.tries)}</span>}
            </div>
            {it.state === "installing" && (
              <div className="nmt-bar">
                <span style={{ width: `${Math.round((it.progress ?? 0.05) * 100)}%` }} />
              </div>
            )}
            {it.error && <p className="nmt-warn nmt-wrap" dir="ltr">{it.error}</p>}
            {it.state === "failed" && it.tail.length > 0 && <pre className="nmt-tail">{it.tail.join("\n")}</pre>}
          </div>
        ))}
    </div>
  );
}

// ───────────────────────────────────────────── خودکارها

function AutomationView({ node, busy, onAutostart }: { node: NodeBlock; busy: boolean; onAutostart: (enabled: boolean) => void }) {
  const a = node.auto;
  const reg = node.autostart || {};
  const net = node.net || {};
  return (
    <>
      <div className="nmt-sec-title">
        <h2>خودکارها</h2>
      </div>
      <div className="nmt-chips">
        {a.auto_update ? (
          a.update_wanted ? (
            <span className="nmt-chip warn">
              نسخهٔ تازه {a.latest_version ? <span dir="ltr">v{a.latest_version}</span> : null} روی سایت است؛ به‌روزرسانی خودکار هنگامِ بی‌کار بودنِ سرور فرستاده می‌شود
            </span>
          ) : (
            <span className="nmt-chip ok">برنامهٔ سرور با سایت یکی است — به‌روزرسانیِ خودکار روشن</span>
          )
        ) : (
          <span className="nmt-chip">به‌روزرسانیِ خودکار خاموش است</span>
        )}
        {(a.update_note || "").length > 0 && <span className="nmt-chip">{a.update_note}</span>}
        {node.outbox?.pending ? <span className="nmt-chip warn">{fa(node.outbox.pending)} نتیجهٔ تمام‌شده منتظرِ رسیدن به سایت</span> : null}
        {net.offline_s ? <span className="nmt-chip bad">ارتباط با سایت از {offlineText(net.offline_s)} پیش قطع است؛ کار ادامه دارد و نتیجه‌ها نگه داشته می‌شوند تا ارتباط برگردد</span> : null}
        {node.lanes?.light ? <span className="nmt-chip">راهروی کارهای سبک کنارِ کارِ بلند: فعال</span> : null}
      </div>
      <label className="nmt-switch">
        <input type="checkbox" checked={node.autostart_wanted} disabled={busy} onChange={(e) => onAutostart(e.target.checked)} />
        <span>
          شروعِ خودکارِ برنامه هنگامِ روشن شدنِ کامپیوتر (یک میان‌برِ بی‌نیاز به دسترسیِ مدیر در پوشهٔ Startup همان کاربر)
          {reg.supported === false ? " — روی این کامپیوتر پشتیبانی نمی‌شود" : reg.registered ? " — ثبت شده است" : node.autostart_wanted ? " — در اولین ارتباط ثبت می‌شود" : ""}
        </span>
      </label>
    </>
  );
}

// ───────────────────────────────────────────── پیشرفتِ کلیِ صف

function ProgressCard({ progress }: { progress: Progress }) {
  const rows = Object.entries(progress.kinds).sort((a, b) => b[1].queued + b[1].running - (a[1].queued + a[1].running) || a[0].localeCompare(b[0]));
  const t = progress.totals;
  return (
    <Card padded={false}>
      <div className="nmt-sec">
        <div className="nmt-sec-title">
          <h2>پیشرفتِ کلیِ صف</h2>
          <span>{fa(progress.hours)} ساعتِ اخیر</span>
        </div>
        <div className="nmt-tiles">
          <div className="nmt-tile warn">
            <b>{fa(t.queued)}</b>
            <span>منتظرِ نوبت</span>
          </div>
          <div className="nmt-tile">
            <b>{fa(t.running)}</b>
            <span>در حال اجرا</span>
          </div>
          <div className="nmt-tile ok">
            <b>{fa(t.done)}</b>
            <span>انجام شد</span>
          </div>
          <div className={`nmt-tile ${t.failed ? "bad" : ""}`}>
            <b>{fa(t.failed)}</b>
            <span>ناموفق</span>
          </div>
          <div className="nmt-tile">
            <b>{fa(progress.percent)}٪</b>
            <span>پیشرفتِ کل</span>
          </div>
        </div>
        {rows.length === 0 ? (
          <p className="nmt-small">در این بازه کاری در صف نبوده است.</p>
        ) : (
          <div className="nmt-prog">
            {rows.map(([kind, r]) => (
              <div className="nmt-prog-row" key={kind}>
                <span className="nmt-prog-name">
                  {r.label || kind} <span className="nmt-small" dir="ltr">{r.label ? kind : ""}</span>
                </span>
                <div className="nmt-bar ok">
                  <span style={{ width: `${kindPercent(r)}%` }} />
                </div>
                <span className="nmt-prog-nums">
                  <span>صف {fa(r.queued)}</span>
                  <span>اجرا {fa(r.running)}</span>
                  <span>تمام {fa(r.done)}</span>
                  {r.failed > 0 && <span style={{ color: "var(--bad)" }}>ناموفق {fa(r.failed)}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
        <p className="nmt-small">کارهای کوتاه پشتِ یک کارِ بلند (مثلاً یک ویدیوی طولانی) معطل نمی‌مانند؛ دانلودها وقتی کارت بی‌کار است انجام می‌شوند.</p>
      </div>
    </Card>
  );
}

// ───────────────────────────────────────────── تنظیماتِ خودکارها

function SettingsCard({ s, busy, onSave }: { s: AutoSettings; busy: boolean; onSave: (patch: Partial<AutoSettings>) => void }) {
  const [time, setTime] = useState(s.nightly_time);
  const [burst, setBurst] = useState(String(s.short_burst));
  useEffect(() => setTime(s.nightly_time), [s.nightly_time]);
  useEffect(() => setBurst(String(s.short_burst)), [s.short_burst]);
  const toggle = (key: keyof AutoSettings, text: string) => (
    <label className="nmt-switch">
      <input type="checkbox" checked={Boolean(s[key])} disabled={busy} onChange={(e) => onSave({ [key]: e.target.checked } as Partial<AutoSettings>)} />
      <span>{text}</span>
    </label>
  );
  return (
    <Card padded={false}>
      <div className="nmt-sec">
        <div className="nmt-sec-title">
          <h2>تنظیمِ خودکارها</h2>
        </div>
        <div className="nmt-set">
          {toggle("auto_update", "به‌روزرسانیِ خودکارِ برنامهٔ سرورهای پردازش: وقتی نسخهٔ تازه روی سایت هست و سرور بی‌کار است، سایت خودش «به‌روزرسانی» را می‌فرستد.")}
          {toggle("auto_selftest", "آزمونِ کامل پس از هر نسخهٔ تازهٔ برنامه.")}
          {toggle("nightly_selftest", "آزمونِ کاملِ شبانه.")}
          {toggle("requeue_after_pass", "پس از قبول شدنِ یک قابلیت، کارهای قبلاً ناموفق/لغوشده‌ای که به‌خاطرِ سرور بوده‌اند (مثلاً صداهای MOSS ِ چغر) دوباره در صف بروند.")}
          <div className="nmt-set-row">
            <span>ساعتِ آزمونِ شبانه (وقتِ تهران):</span>
            <Input className="nmt-time" value={time} maxLength={5} onChange={(e) => setTime(e.target.value)} placeholder="03:30" />
            <Button size="sm" variant="secondary" disabled={busy || time === s.nightly_time} onClick={() => onSave({ nightly_time: time })}>
              ذخیره
            </Button>
          </div>
          <div className="nmt-set-row">
            <span>بیشترین کارِ کوتاهِ پشتِ هم، پیش از نوبتِ کارِ بلند:</span>
            <Input className="nmt-num" type="number" min={1} max={100} value={burst} onChange={(e) => setBurst(e.target.value)} />
            <Button size="sm" variant="secondary" disabled={busy || burst === String(s.short_burst)} onClick={() => onSave({ short_burst: Number(burst) })}>
              ذخیره
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
