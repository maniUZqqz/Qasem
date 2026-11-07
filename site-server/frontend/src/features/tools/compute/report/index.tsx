import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage } from "../../../../api/client";
import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, ErrorBox, Input, PageHeader, Select, Spinner, Stat, Table } from "../../../../components/ui";
import { CopyButton, LineChart, StatTable, TimelineBar, type StatRow } from "./parts";
import {
  AUDIO_LABELS,
  CHARTS,
  CSV_LABELS,
  DEFAULT_RANGE,
  LEVEL_OPTIONS,
  PAGE_SIZE,
  POLL_MS,
  PRESETS,
  TABS,
  TEXT,
  agentVersionView,
  downloadProgressText,
  downloadStateTone,
  dur,
  faVersion,
  errorSourceLabel,
  errorTextFromBody,
  fmtBytes,
  fmtMb,
  fmtSpeed,
  jalaliDateTime,
  lastSeenText,
  levelLabel,
  levelTone,
  logsQuery,
  logsTruncatedNote,
  nodeState,
  pageInfo,
  parseRetention,
  rangeText,
  relativeTime,
  reportQuery,
  resourceRows,
  runDuration,
  scheduleText,
  serviceChips,
  shouldPoll,
  sortNodes,
  summaryTiles,
  tehranIsoDate,
  toFa,
  uptimeNote,
  uptimeText,
  validateCustomRange,
  csvPath,
  type CsvSection,
  type DownloadActive,
  type ErrorItem,
  type LogsData,
  type RangeSel,
  type ReportData,
  type ReportNode,
  type TabKey,
  type Tone,
} from "./model";
import "./report.css";

/**
 * گزارشِ سرورهای پردازش (فقط کارکنان).
 *
 * یک درخواست (`/compute/report/`) کلِ صفحه را می‌سازد: سرورها (روشن/خاموش، منابع، نمودار، مدل‌ها)، آمارِ کارها، خطاها با توضیحِ ساده
 * و دانلودها؛ لاگ‌ها از `/compute/report/logs/` با فیلتر و صفحه‌بندی می‌آیند. هر ۳۰ ثانیه، فقط تا وقتی زبانهٔ مرورگر دیده می‌شود،
 * تازه می‌شود؛ داده‌ای که در دست است تا رسیدنِ پاسخِ تازه می‌ماند (بدونِ پرش).
 */

type Live<T> = { data: T | null; stale: boolean; error: string | null; loadedAt: number | null; refreshing: boolean; reload: () => void };

function useLive<T>(path: string | null): Live<T> {
  const [data, setData] = useState<T | null>(null);
  const [dataPath, setDataPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const reloadRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    if (!path) {
      reloadRef.current = () => undefined;
      return undefined;
    }
    let alive = true;
    let inflight = false;
    let again = false;
    const run = async () => {
      if (inflight) {
        again = true;
        return;
      }
      inflight = true;
      setRefreshing(true);
      try {
        const { data: d } = await api.get<T>(path);
        if (!alive) return;
        setData(d);
        setDataPath(path);
        setError(null);
        setLoadedAt(Date.now());
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
    reloadRef.current = () => void run();
    void run();
    const timer = window.setInterval(() => {
      if (shouldPoll(document.hidden, inflight)) void run();
    }, POLL_MS);
    const onVisible = () => {
      if (shouldPoll(document.hidden, inflight)) void run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [path]);

  return { data, stale: data !== null && dataPath !== path, error, loadedAt, refreshing, reload: () => reloadRef.current() };
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

function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 4000); // فایرفاکس: آزاد کردنِ فوری دانلود را نیمه‌کاره می‌گذارد
}

export default function ComputeReportPage() {
  const [sel, setSel] = useState<RangeSel>(DEFAULT_RANGE);
  const [nodeId, setNodeId] = useState<number | null>(null);
  const [tab, setTab] = useState<TabKey>("overview");
  const [customOpen, setCustomOpen] = useState(false);
  const [fromText, setFromText] = useState("");
  const [toText, setToText] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);
  const [nodeList, setNodeList] = useState<{ id: number; name: string }[]>([]);
  const [csvBusy, setCsvBusy] = useState<string | null>(null);
  const [csvError, setCsvError] = useState<string | null>(null);

  // لاگ‌ها
  const [level, setLevel] = useState("all");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);

  const report = useLive<ReportData>(`/compute/report/?${reportQuery(sel, nodeId)}`);
  const logs = useLive<LogsData>(tab === "logs" ? `/compute/report/logs/?${logsQuery({ sel, nodeId, level, q, offset })}` : null);
  const data = report.data;

  useEffect(() => {
    if (data && nodeId === null) setNodeList(data.nodes.map((n) => ({ id: n.id, name: n.name })));
  }, [data, nodeId]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setQ(search.trim());
      setOffset(0);
    }, 350);
    return () => window.clearTimeout(t);
  }, [search]);

  const pickPreset = (key: RangeSel["preset"]) => {
    setOffset(0);
    if (key === "custom") {
      setCustomOpen(true);
      return;
    }
    setCustomOpen(false);
    setCustomError(null);
    setSel({ preset: key });
  };

  const applyCustom = () => {
    const r = validateCustomRange(fromText, toText, tehranIsoDate(Date.now()));
    if (!r.ok) {
      setCustomError(r.error);
      return;
    }
    setCustomError(null);
    setOffset(0);
    setSel({ preset: "custom", from: r.from, to: r.to });
  };

  const downloadCsv = async (section: CsvSection, extra: { level?: string; q?: string } = {}) => {
    setCsvBusy(section);
    setCsvError(null);
    try {
      const res = await api.get<Blob>(csvPath(section, sel, nodeId, extra), { responseType: "blob" });
      const header = String((res.headers as unknown as Record<string, unknown>)["content-disposition"] ?? "");
      const name = /filename="?([^";]+)"?/.exec(header)?.[1] ?? `compute-${section}.csv`;
      saveBlob(res.data, name);
    } catch (err) {
      const body = (err as { response?: { data?: unknown } }).response?.data;
      setCsvError(body instanceof Blob ? errorTextFromBody(await body.text()) : errorMessage(err));
    } finally {
      setCsvBusy(null);
    }
  };

  const csvButton = (section: CsvSection, extra: { level?: string; q?: string } = {}) => (
    <Button variant="secondary" size="sm" disabled={csvBusy !== null} onClick={() => void downloadCsv(section, extra)} title={`${TEXT.csv}: ${CSV_LABELS[section]}`}>
      {csvBusy === section ? <Spinner size={13} /> : <Icon name="download" size={13} />}
      {csvBusy === section ? TEXT.csvBusy : `${TEXT.csv}: ${CSV_LABELS[section]}`}
    </Button>
  );

  const stale = report.stale;
  const nodes = data?.nodes ?? [];

  return (
    <div className="nmr space-y-4">
      <PageHeader
        title={TEXT.title}
        subtitle={TEXT.subtitle}
        actions={
          <>
            <Link to="/tools/compute/queue" className="u-btn u-btn-secondary u-btn-sm no-underline">
              {TEXT.queueLink}
            </Link>
            <Link to="/tools/compute" className="u-btn u-btn-secondary u-btn-sm no-underline">
              {TEXT.serversLink}
            </Link>
          </>
        }
      />

      <Card padded={false}>
        <div className="nmr-bar">
          <div className="nmr-range" role="group" aria-label="بازهٔ زمانی">
            {PRESETS.map((p) => {
              const active = p.key === "custom" ? customOpen || sel.preset === "custom" : !customOpen && sel.preset === p.key;
              return (
                <Button key={p.key} variant={active ? "primary" : "secondary"} size="sm" aria-pressed={active} onClick={() => pickPreset(p.key)}>
                  {p.label}
                </Button>
              );
            })}
          </div>
          {(customOpen || sel.preset === "custom") && (
            <div>
              <div className="nmr-custom">
                <label>
                  {TEXT.customFrom}
                  <Input className="nmr-date" inputMode="numeric" placeholder={TEXT.customPlaceholder} value={fromText} onChange={(e) => setFromText(e.target.value)} />
                </label>
                <label>
                  {TEXT.customTo}
                  <Input className="nmr-date" inputMode="numeric" placeholder={TEXT.customPlaceholder} value={toText} onChange={(e) => setToText(e.target.value)} />
                </label>
                <Button size="sm" onClick={applyCustom}>
                  {TEXT.apply}
                </Button>
              </div>
              {customError ? <p className="nmr-err mt-2">{customError}</p> : <p className="nmr-note mt-2">{TEXT.customHint}</p>}
            </div>
          )}
          <div className="nmr-bar-row">
            <Select aria-label={TEXT.nodeFilter} value={nodeId ?? ""} onChange={(e) => { setNodeId(e.target.value ? Number(e.target.value) : null); setOffset(0); }} className="nmr-node-select">
              <option value="">{TEXT.allNodes}</option>
              {nodeList.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name}
                </option>
              ))}
            </Select>
            {data && <span className="nmr-small">{rangeText(data.range)}</span>}
            <div className="nmr-bar-end">
              <span className="nmr-small" title="گزارش هر ۳۰ ثانیه خودکار تازه می‌شود">
                {TEXT.updatedAt}: <Ago at={report.loadedAt} />
              </span>
              <Button variant="ghost" size="sm" onClick={() => { report.reload(); logs.reload(); }} aria-label={TEXT.refresh} title={TEXT.refresh} style={{ padding: 7 }}>
                <span className={report.refreshing ? "nmr-spin" : ""} style={{ display: "inline-flex" }}>
                  <Icon name="refresh" size={16} />
                </span>
              </Button>
            </div>
          </div>
        </div>
      </Card>

      <ErrorBox message={report.error ?? csvError} />

      {!data && !report.error && (
        <div className="py-10 text-center">
          <Spinner />
        </div>
      )}

      {data && (
        <div className="nmr-stale space-y-4" data-stale={stale ? "1" : undefined} aria-busy={stale}>
          <div className="nmr-tiles u-stat-row">
            {summaryTiles(data).map((t) => (
              <Stat key={t.key} label={t.label} value={t.value} hint={t.hint || undefined} tone={t.tone} />
            ))}
          </div>

          <Card padded={false}>
            <nav className="u-tabs px-2" role="tablist" aria-label="بخش‌های گزارش">
              {TABS.map((t) => (
                <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} className={`u-tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
                  {t.label}
                </button>
              ))}
            </nav>
          </Card>

          {tab === "overview" && <Overview data={data} nodes={nodes} csv={csvButton} />}
          {tab === "jobs" && <JobsTab data={data} csv={csvButton} />}
          {tab === "errors" && <ErrorsTab data={data} csv={csvButton} />}
          {tab === "logs" && (
            <LogsTab
              live={logs}
              level={level}
              onLevel={(v) => { setLevel(v); setOffset(0); }}
              search={search}
              onSearch={setSearch}
              offset={offset}
              onOffset={setOffset}
              csv={() => csvButton("logs", { level, q })}
            />
          )}
          {tab === "downloads" && <DownloadsTab data={data} csv={csvButton} />}

          <RetentionCard data={data} onSaved={report.reload} />
        </div>
      )}
    </div>
  );
}

type CsvBtn = (section: CsvSection, extra?: { level?: string; q?: string }) => ReactNode;

// ───────────────────────────────────────────────────────────── سرورها

function Overview({ data, nodes, csv }: { data: ReportData; nodes: ReportNode[]; csv: CsvBtn }) {
  if (nodes.length === 0) return <Card><EmptyState icon="cpu" description={TEXT.noNodes} /></Card>;
  const lo = Date.parse(data.range.start) / 1000;
  const hi = Date.parse(data.range.end) / 1000;
  return (
    <div className="space-y-4">
      {sortNodes(nodes).map((n) => (
        <NodeCard key={n.id} node={n} lo={lo} hi={hi} csv={csv} />
      ))}
      <Card>
        <div className="nmr-sec-title" style={{ marginBottom: 8 }}>
          {TEXT.versions}
          <span>
            {TEXT.siteVersion}: {data.site_version ? faVersion(data.site_version) : "—"}
          </span>
        </div>
        <div className="nmr-chips">
          {data.agent_versions.map((v) => (
            <span key={v.version} className={`nmr-chip plain ${v.latest ? "on" : ""}`} title={v.nodes.join("، ")}>
              {v.version === "نامعلوم" ? v.version : `نسخهٔ ${faVersion(v.version)}`} — {v.nodes.join("، ")}
              {v.latest ? " (تازه‌ترین)" : ""}
            </span>
          ))}
        </div>
      </Card>
    </div>
  );
}

function NodeCard({ node, lo, hi, csv }: { node: ReportNode; lo: number; hi: number; csv: CsvBtn }) {
  const st = nodeState(node);
  const ver = agentVersionView(node);
  const rows = resourceRows(node);
  const up = node.uptime;
  const chips = serviceChips(node.services);
  const note = uptimeNote(up);
  return (
    <Card padded={false} className={`nmr-node ${st.state === "disabled" ? "disabled" : ""}`}>
      <div className="nmr-node-head">
        <span className={`nmr-dot ${st.state}`} aria-hidden="true" />
        <span className="nmr-node-name">{node.name}</span>
        <Badge tone={st.tone}>{st.label}</Badge>
        <div className="nmr-node-head-end">
          <Badge tone={ver.tone}>{ver.text}</Badge>
          {ver.note && <span className="nmr-small">{ver.note}</span>}
        </div>
      </div>
      <div className="nmr-meta">
        <span>
          <b>آخرین حضور: </b>
          {lastSeenText(node.last_seen)}
        </span>
        {node.hostname && (
          <span>
            <b>کامپیوتر: </b>
            <span dir="ltr">{node.hostname}</span>
          </span>
        )}
        {node.gpu && (
          <span>
            <b>کارتِ گرافیک: </b>
            <span dir="ltr">{node.gpu}</span>
          </span>
        )}
      </div>

      <div className="nmr-sec">
        <div className="nmr-sec-title">سرویس‌ها</div>
        <div className="nmr-chips">
          {chips.map((c) => (
            <span key={c.key} className={`nmr-chip ${c.on ? "on" : ""}`}>
              {c.label}: {c.on ? "روشن" : "خاموش"}
            </span>
          ))}
        </div>
      </div>

      <div className="nmr-sec">
        <div className="nmr-sec-title">
          {TEXT.resourcesNow}
          {!node.online && <span>آخرین مقدارِ گزارش‌شده</span>}
        </div>
        <div className="nmr-res">
          {rows.map((r) => (
            <div key={r.key} className="nmr-res-item">
              <span className="nmr-res-label">{r.label}</span>
              <span className="nmr-res-value">{r.value}</span>
              {r.pct !== null && (
                <div className="u-meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(r.pct)}>
                  <span style={{ width: `${Math.min(100, Math.max(0, r.pct))}%`, background: r.tone === "neutral" ? "var(--info)" : `var(--${r.tone})` }} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="nmr-sec">
        <div className="nmr-sec-title">
          {TEXT.timeline}
          <span>
            {uptimeText(up)}
            {up.sessions > 0 ? ` · ${toFa(up.sessions)} نوبتِ اتصال` : ""}
          </span>
        </div>
        <TimelineBar segments={node.segments} lo={lo} hi={hi} />
        <p className="nmr-note">{TEXT.timelineHint}</p>
        {note && <p className="nmr-note">{note}</p>}
      </div>

      <details className="nmr-det" open>
        <summary>{TEXT.chartsTitle}</summary>
        <div className="nmr-det-body">
          <div className="nmr-charts">
            {CHARTS.map((c) => (
              <LineChart
                key={c.key}
                title={c.label}
                points={node.series[c.key]}
                lo={lo}
                hi={hi}
                unit={c.unit}
                max={c.max}
                tone={c.key === "gpu_temp_c" ? "warn" : c.key === "disk_free_gb" ? "ok" : c.key === "gpu_util_pct" ? "info" : "brand"}
              />
            ))}
          </div>
          <div className="nmr-bar-row">{csv("samples")}</div>
        </div>
      </details>

      <details className="nmr-det">
        <summary>{TEXT.models}</summary>
        <div className="nmr-det-body">
          <ModelsBlock node={node} />
        </div>
      </details>

      <details className="nmr-det">
        <summary>
          {TEXT.sessions}
          <span className="nmr-small">{toFa(node.sessions.length)}{node.sessions_truncated ? "+" : ""}</span>
        </summary>
        <div className="nmr-det-body">
          {node.sessions.length === 0 ? (
            <p className="nmr-note">{TEXT.noSessions}</p>
          ) : (
            <div className="nmr-tablewrap">
              <Table>
                <thead>
                  <tr>
                    <th>شروع</th>
                    <th>پایان</th>
                    <th className="num">مدت</th>
                    <th>نسخه</th>
                  </tr>
                </thead>
                <tbody>
                  {node.sessions.slice(0, 50).map((s, i) => (
                    <tr key={i}>
                      <td>{jalaliDateTime(s.started)}</td>
                      <td>{s.ongoing ? <Badge tone="ok">هنوز وصل است</Badge> : jalaliDateTime(s.ended)}</td>
                      <td className="num">{dur(Math.round(s.minutes * 60))}</td>
                      <td>{s.agent ? faVersion(s.agent) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
          <div className="nmr-bar-row">{csv("sessions")}</div>
        </div>
      </details>

      <details className="nmr-det">
        <summary>
          کارهای این سرور
          <span className="nmr-small">{toFa(node.jobs.count)} کار</span>
        </summary>
        <div className="nmr-det-body">
          {node.jobs_by_kind.length === 0 ? (
            <p className="nmr-note">{TEXT.noJobs}</p>
          ) : (
            <StatTable
              firstColumn="نوعِ کار"
              rows={node.jobs_by_kind.map((k) => ({ key: k.kind, label: k.kind_label, stat: k }))}
              total={node.jobs}
            />
          )}
        </div>
      </details>
    </Card>
  );
}

function ModelsBlock({ node }: { node: ReportNode }) {
  const m = node.models;
  const audio = Object.entries(m.audio);
  const comfy = Object.entries(m.comfy);
  const empty = m.ollama.length === 0 && audio.length === 0 && comfy.length === 0 && m.packages.length === 0;
  if (empty) return <p className="nmr-note">{TEXT.noModels}</p>;
  return (
    <>
      {(m.ollama.length > 0 || node.services.ollama) && (
        <div className="space-y-2">
          <div className="nmr-sec-title">
            مدل‌های Ollama
            <span>{toFa(m.ollama.length)} مدل</span>
          </div>
          {m.ollama.length === 0 ? (
            <p className="nmr-note">مدلی گزارش نشده.</p>
          ) : (
            <div className="nmr-chips">
              {m.ollama.map((x) => (
                <span key={x} className="nmr-chip plain ltr">
                  {x}
                </span>
              ))}
            </div>
          )}
          {m.ollama_stale && <p className="nmr-note">Ollama الان خاموش است؛ این فهرست از آخرین باری است که روشن بود یا از روی دیسک خوانده شده.</p>}
        </div>
      )}
      {audio.length > 0 && (
        <div className="space-y-2">
          <div className="nmr-sec-title">مدل‌های صدا</div>
          <div className="nmr-chips">
            {audio.map(([k, on]) => (
              <span key={k} className={`nmr-chip ${on ? "on" : ""}`}>
                {AUDIO_LABELS[k] ?? k}: {on ? "نصب است" : "نصب نیست"}
              </span>
            ))}
            {m.voice_clone && <span className="nmr-chip on">کلونِ صدا: نصب است</span>}
          </div>
        </div>
      )}
      {comfy.length > 0 && (
        <div className="space-y-2">
          <div className="nmr-sec-title">
            مدل‌های ComfyUI
            <span>{toFa(m.comfy_count)} فایل</span>
          </div>
          <div className="nmr-chips">
            {comfy.map(([k, list]) => (
              <span key={k} className="nmr-chip plain" title={list.join("\n")}>
                <span dir="ltr">{k}</span>: {toFa(list.length)}
              </span>
            ))}
          </div>
        </div>
      )}
      {m.packages.length > 0 && (
        <div className="space-y-2">
          <div className="nmr-sec-title">بسته‌های مدلِ سرور</div>
          <div className="nmr-chips">
            {m.packages.map((p) => (
              <span key={p.key} className={`nmr-chip ${p.installed ? "on" : ""}`}>
                {p.title}: {p.installed ? "کامل" : p.missing_mb > 0 ? `${fmtMb(p.missing_mb)} مانده` : "نصب نیست"}
              </span>
            ))}
          </div>
        </div>
      )}
      {m.download_running && <Alert tone="info">دانلودِ مدل‌ها روی این سرور در جریان است؛ پیشرفتش در بخشِ «دانلودها» می‌آید.</Alert>}
      {m.download_error && (
        <div>
          <div className="nmr-rawhead">
            <b>آخرین خطای دانلودِ مدل</b>
            <CopyButton text={m.download_error} />
          </div>
          <pre className="nmr-raw" dir="ltr">
            {m.download_error}
          </pre>
        </div>
      )}
    </>
  );
}

// ───────────────────────────────────────────────────────────── آمارِ کارها

function JobsTab({ data, csv }: { data: ReportData; csv: CsvBtn }) {
  const [by, setBy] = useState<"kind" | "node">("kind");
  const kinds: StatRow[] = data.jobs.per_kind.map((k) => ({
    key: k.kind,
    label: (
      <>
        {k.kind_label}
        <span className="nmr-small nmr-mono" dir="ltr">
          {" "}
          {k.kind}
        </span>
      </>
    ),
    stat: k,
  }));
  const perNode: StatRow[] = data.nodes.map((n) => ({ key: String(n.id), label: n.name, stat: n.jobs }));
  const total = data.jobs.totals;
  return (
    <Card padded={false}>
      <div className="nmr-toolbar">
        <div className="nmr-seg" role="group" aria-label="دسته‌بندی">
          <button type="button" className={by === "kind" ? "on" : ""} onClick={() => setBy("kind")}>
            {TEXT.jobsByKind}
          </button>
          <button type="button" className={by === "node" ? "on" : ""} onClick={() => setBy("node")}>
            {TEXT.jobsByNode}
          </button>
        </div>
        <div className="nmr-bar-end">{csv("jobs")}</div>
      </div>
      {total.count === 0 ? (
        <EmptyState icon="empty" description={TEXT.noJobs} />
      ) : (
        <div className="p-4 space-y-3">
          <StatTable firstColumn={by === "kind" ? "نوعِ کار" : "سرور"} rows={by === "kind" ? kinds : perNode} total={total} />
          <p className="nmr-note">
            میانگینِ اجرا فقط از کارهای تمام‌شده حساب می‌شود و میانگینِ انتظار، مدتی است که کار پیش از شروع در صف ماند. کارهای در صف یا در حالِ اجرا در ستونِ «تعداد» می‌آیند ولی موفق یا ناموفق شمرده نمی‌شوند.
          </p>
          {by === "kind" && data.jobs.per_kind.some((k) => k.p95_run_s != null) && (
            <div className="nmr-chips">
              {data.jobs.per_kind
                .filter((k) => k.p95_run_s != null)
                .slice(0, 8)
                .map((k) => (
                  <span key={k.kind} className="nmr-chip plain">
                    {k.kind_label}: نیمی از کارها تا {runDuration(k.p50_run_s ?? null)}، ۹۵٪ تا {runDuration(k.p95_run_s ?? null)}
                  </span>
                ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── خطاها

function ErrorCard({ e }: { e: ErrorItem }) {
  return (
    <div>
      <div className="nmr-item-head">
        <Badge tone={levelTone(e.level)}>{errorSourceLabel(e.source)}</Badge>
        {e.source === "job" && <b>{e.kind_label}</b>}
        {e.node && <span>سرور: {e.node}</span>}
        <span title={jalaliDateTime(e.at)}>
          {jalaliDateTime(e.at)} · {relativeTime(e.at)}
        </span>
      </div>
      <p className="nmr-what">{e.explain.what}</p>
      <p className="nmr-advice">
        <b>پیشنهاد: </b>
        {e.explain.advice}
      </p>
      <div>
        <div className="nmr-rawhead">
          <span>{TEXT.rawError}</span>
          <CopyButton text={e.text} />
        </div>
        <pre className="nmr-raw" dir="ltr">
          {e.text}
        </pre>
      </div>
    </div>
  );
}

function ErrorsTab({ data, csv }: { data: ReportData; csv: CsvBtn }) {
  return (
    <Card padded={false}>
      <div className="nmr-toolbar">
        <span className="nmr-small">{data.errors.length ? `${toFa(data.errors.length)} مورد` : ""}</span>
        <div className="nmr-bar-end">{csv("errors")}</div>
      </div>
      {data.error_groups.length > 0 && (
        <div className="nmr-groups" aria-label={TEXT.errorTop}>
          {data.error_groups.map((g) => (
            <span key={g.code} className="nmr-group">
              <b>{toFa(g.count)}</b>
              <span>{g.what}</span>
            </span>
          ))}
        </div>
      )}
      {data.errors.length === 0 ? (
        <EmptyState icon="ok" description={TEXT.noErrors} />
      ) : (
        <div className="nmr-list">
          {data.errors.map((e, i) => (
            <ErrorCard key={`${e.source}-${e.uid ?? i}-${e.at}-${i}`} e={e} />
          ))}
        </div>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── لاگ‌ها

function LogsTab({
  live,
  level,
  onLevel,
  search,
  onSearch,
  offset,
  onOffset,
  csv,
}: {
  live: Live<LogsData>;
  level: string;
  onLevel: (v: string) => void;
  search: string;
  onSearch: (v: string) => void;
  offset: number;
  onOffset: (n: number) => void;
  csv: () => ReactNode;
}) {
  const d = live.data;
  const lines = d?.lines ?? [];
  const total = d?.total ?? 0;
  return (
    <Card padded={false}>
      <div className="nmr-toolbar">
        <Select aria-label="سطحِ لاگ" value={level} onChange={(e) => onLevel(e.target.value)} className="nmr-level">
          {LEVEL_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </Select>
        <Input type="search" aria-label={TEXT.logsSearch} placeholder={`${TEXT.logsSearch}…`} value={search} onChange={(e) => onSearch(e.target.value)} className="nmr-search" />
        <div className="nmr-bar-end">{csv()}</div>
      </div>
      <ErrorBox message={live.error} />
      {!d && !live.error && (
        <div className="py-8 text-center">
          <Spinner />
        </div>
      )}
      {d && lines.length === 0 && <EmptyState icon="empty" description={TEXT.logsEmpty} />}
      {d && lines.length > 0 && (
        <div className="nmr-list nmr-stale" data-stale={live.stale ? "1" : undefined}>
          {lines.map((l) => (
            <div key={l.id}>
              <div className="nmr-item-head">
                <Badge tone={levelTone(l.level)}>{levelLabel(l.level)}</Badge>
                <b>{l.node}</b>
                <span>{jalaliDateTime(l.ts)}</span>
              </div>
              {l.explain && (
                <>
                  <p className="nmr-what">{l.explain.what}</p>
                  <p className="nmr-advice">
                    <b>پیشنهاد: </b>
                    {l.explain.advice}
                  </p>
                </>
              )}
              <div>
                <pre className={`nmr-raw ${l.explain ? "" : "plain"}`} dir="auto">
                  {l.message}
                </pre>
                <div style={{ marginTop: 4 }}>
                  <CopyButton text={l.message} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {d && (
        <div className="nmr-foot">
          <span>
            {pageInfo(total, d.offset, lines.length)}
            {d.truncated ? ` · ${logsTruncatedNote(d.kept_per_node)}` : ""}
          </span>
          <span className="nmr-bar-row">
            <Button variant="secondary" size="sm" disabled={offset <= 0} onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}>
              {TEXT.prev}
            </Button>
            <Button variant="secondary" size="sm" disabled={offset + PAGE_SIZE >= total} onClick={() => onOffset(offset + PAGE_SIZE)}>
              {TEXT.next}
            </Button>
          </span>
        </div>
      )}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────── دانلودها

function ActiveDownload({ d }: { d: DownloadActive }) {
  const pct = d.percent ?? 0;
  return (
    <div className="nmr-dl">
      <div className="nmr-item-head">
        <span className="nmr-dl-title">{d.title}</span>
        {d.node && <Badge tone="neutral">{d.node}</Badge>}
        {d.source === "node" && <span className="nmr-small">دانلودِ پس‌زمینهٔ خودِ سرور</span>}
      </div>
      <div className="u-meter" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <span className={d.percent === null ? "nmr-indeterminate" : ""} style={d.percent === null ? { background: "var(--brand)" } : { width: `${Math.min(100, pct)}%`, background: "var(--brand)" }} />
      </div>
      <span className="nmr-small">{downloadProgressText(d)}</span>
      {d.message && d.source === "node" && (
        <span className="nmr-small">
          در حالِ گرفتن: <span dir="ltr">{d.message}</span>
        </span>
      )}
      {d.attempt !== null && d.max_attempts ? <span className="nmr-small">تلاشِ {toFa(d.attempt)} از {toFa(d.max_attempts)}</span> : null}
      {d.failed && d.failed.length > 0 && (
        <span className="nmr-small" style={{ color: "var(--bad)" }} dir="ltr">
          {d.failed.join(" | ")}
        </span>
      )}
    </div>
  );
}

function DownloadsTab({ data, csv }: { data: ReportData; csv: CsvBtn }) {
  const { active, waiting, history } = data.downloads;
  return (
    <div className="space-y-4">
      <Card padded={false}>
        <div className="nmr-toolbar">
          <b>{TEXT.downloadsActive}</b>
          <div className="nmr-bar-end">{csv("downloads")}</div>
        </div>
        {active.length === 0 ? <EmptyState icon="download" description={TEXT.noActiveDownloads} /> : active.map((d, i) => <ActiveDownload key={d.uid ?? `${d.node}-${i}`} d={d} />)}
      </Card>

      <Card padded={false}>
        <div className="nmr-toolbar">
          <b>{TEXT.downloadsWaiting}</b>
        </div>
        {waiting.length === 0 ? (
          <EmptyState icon="clock" description={TEXT.noWaitingDownloads} />
        ) : (
          waiting.map((w) => (
            <div key={w.uid} className="nmr-dl">
              <span className="nmr-dl-title">{w.title}</span>
              <span className="nmr-small">{w.status_text}</span>
              {scheduleText({ scheduled_for: w.scheduled_for, window: w.window }) && <span className="nmr-small">{scheduleText({ scheduled_for: w.scheduled_for, window: w.window })}</span>}
              {w.node_wanted && <span className="nmr-small">سرورِ خواسته‌شده: {w.node_wanted}</span>}
            </div>
          ))
        )}
      </Card>

      <Card padded={false}>
        <div className="nmr-toolbar">
          <b>{TEXT.downloadsHistory}</b>
        </div>
        {history.length === 0 ? (
          <EmptyState icon="empty" description={TEXT.noDownloadHistory} />
        ) : (
          <div className="nmr-tablewrap">
            <Table>
              <thead>
                <tr>
                  <th className="wrap">دانلود</th>
                  <th>سرور</th>
                  <th>وضعیت</th>
                  <th>پایان</th>
                  <th className="num">مدت</th>
                  <th className="num">حجم</th>
                  <th className="num">سرعت</th>
                  <th className="wrap">زمان‌بندی / خطا</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => {
                  const tone: Tone = downloadStateTone(h.state);
                  return (
                    <tr key={h.uid}>
                      <td className="wrap">{h.title}</td>
                      <td>{h.node ?? "—"}</td>
                      <td>
                        <Badge tone={tone}>{h.state_label}</Badge>
                      </td>
                      <td>{jalaliDateTime(h.finished ?? h.created)}</td>
                      <td className="num">{runDuration(h.run_s)}</td>
                      <td className="num">{h.bytes ? fmtBytes(h.bytes) : "—"}</td>
                      <td className="num">{fmtSpeed(h.speed_bps) || "—"}</td>
                      <td className="wrap">
                        {[scheduleText(h), h.explain].filter(Boolean).join(" · ") || "—"}
                        {h.error && (
                          <span className="nmr-small nmr-mono" dir="ltr" style={{ display: "block" }}>
                            {h.error}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ───────────────────────────────────────────────────────────── نگه‌داریِ آمار

function RetentionCard({ data, onSaved }: { data: ReportData; onSaved: () => void }) {
  const current = data.range.retention_days;
  const [text, setText] = useState(toFa(current));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (!dirty) setText(toFa(current));
  }, [current, dirty]);

  const save = async () => {
    const r = parseRetention(text);
    if (!r.ok) {
      setMsg({ ok: false, text: r.error });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      await api.post("/compute/settings/", { retention_days: r.days });
      setDirty(false);
      setMsg({ ok: true, text: TEXT.retentionSaved });
      onSaved();
    } catch (err) {
      setMsg({ ok: false, text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <div className="nmr-sec-title" style={{ marginBottom: 8 }}>
        {TEXT.settingsTitle}
      </div>
      <div className="nmr-set">
        <label>
          {TEXT.retentionLabel}
          <Input
            className="nmr-days"
            inputMode="numeric"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setDirty(true);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
            }}
          />
        </label>
        <Button size="sm" disabled={busy || !dirty} onClick={() => void save()}>
          {busy && <Spinner size={13} />}
          {TEXT.retentionSave}
        </Button>
      </div>
      <p className="nmr-note mt-2">{TEXT.retentionHint}</p>
      {msg && (
        <div className="mt-2" role="status">
          {msg.ok ? <Alert tone="ok">{msg.text}</Alert> : <p className="nmr-err">{msg.text}</p>}
        </div>
      )}
    </Card>
  );
}
