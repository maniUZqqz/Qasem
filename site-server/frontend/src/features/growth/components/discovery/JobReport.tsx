import { useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, fa } from "../../../../components/ui";
import { download, g, problem, useGet } from "../../api";
import { useMeta } from "../../MetaContext";
import type { DiscoveryJob, JobRow, Paged, ResolveResult } from "../../types";
import { ConfirmDialog } from "../Modal";
import Pagination from "../Pagination";
import { LoadState } from "../bits";
import MergePreviewTable from "./MergePreviewTable";
import { BulkMergeDialog, RowMergeDialog } from "./ResolveDialogs";

type Tab = "error" | "duplicate" | "done";
const PAGE_SIZE = 50;

/** The first few filled cells of the original row, so a person recognises it. */
function rowSummary(raw: Record<string, string>): string {
  return Object.values(raw)
    .filter((v) => v && v.trim())
    .slice(0, 3)
    .join(" · ");
}

/** The row-level report of a finished import: errors, duplicates waiting for a decision, decisions made. */
export default function JobReport({ job, onChanged }: { job: DiscoveryJob; onChanged: () => void }) {
  const { kindLabel } = useMeta();
  const [tab, setTab] = useState<Tab>(job.duplicate_count > 0 && job.error_count === 0 ? "duplicate" : "error");
  const [page, setPage] = useState(1);
  const status = tab === "done" ? "merged,skipped,created" : tab;
  const rows = useGet<Paged<JobRow>>(`/discovery/jobs/${job.id}/rows/`, {
    status,
    page,
    with_merge_preview: tab === "duplicate" ? 1 : undefined,
  });
  const [openRow, setOpenRow] = useState<JobRow | null>(null);
  const [rowBusy, setRowBusy] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [skipAllOpen, setSkipAllOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const decided = job.merged_count + job.skipped_count;
  const nothing = job.error_count === 0 && job.duplicate_count === 0 && decided === 0;
  const changeTab = (next: Tab) => {
    setTab(next);
    setPage(1);
    setMessage(null);
  };
  const refresh = () => {
    rows.reload();
    onChanged();
  };

  const resolveRow = async (action: "merge" | "skip", row: JobRow, target?: number, overwrite: string[] = []) => {
    setRowBusy(true);
    setRowError(null);
    try {
      await g.post<ResolveResult>(`/discovery/jobs/${job.id}/resolve/`, {
        action,
        rows: [row.id],
        target_lead: target,
        overwrite_fields: overwrite,
      });
      setOpenRow(null);
      setMessage(action === "merge" ? `ردیف ${fa(row.row_number)} ادغام شد.` : `ردیف ${fa(row.row_number)} رد شد.`);
      refresh();
    } catch (err) {
      setRowError(problem(err).message);
    } finally {
      setRowBusy(false);
    }
  };

  const resolveAll = async (action: "merge" | "skip", overwrite: string[] = []) => {
    setBulkBusy(true);
    setBulkError(null);
    const total = { merged: 0, skipped: 0, created: 0 };
    try {
      for (let guard = 0; guard < 40; guard++) {
        const r = await g.post<ResolveResult>(`/discovery/jobs/${job.id}/resolve/`, { action, all: true, overwrite_fields: overwrite });
        total.merged += r.merged;
        total.skipped += r.skipped;
        total.created += r.created;
        if (r.remaining <= 0 || r.resolved === 0) break;
      }
      setBulkOpen(false);
      setSkipAllOpen(false);
      setMessage(
        action === "merge"
          ? `${fa(total.merged)} ردیف ادغام شد${total.created ? ` و ${fa(total.created)} لیدِ تازه ساخته شد` : ""}.`
          : `${fa(total.skipped)} ردیف رد شد.`,
      );
      refresh();
    } catch (err) {
      setBulkError(problem(err).message);
    } finally {
      setBulkBusy(false);
    }
  };

  const downloadErrors = async () => {
    setDownloadError(null);
    try {
      await download(`/discovery/jobs/${job.id}/errors.csv`, {}, `import-${job.id}-errors.csv`);
    } catch (err) {
      setDownloadError(problem(err).message);
    }
  };

  if (nothing) {
    return (
      <Alert tone="ok" title="همهٔ ردیف‌ها بدون مشکل ثبت شدند">
        نه ردیفِ خطادار بود و نه تکراری.
      </Alert>
    );
  }

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "error", label: "ردیف‌های خطادار", count: job.error_count },
    { key: "duplicate", label: "تکراری‌ها", count: job.duplicate_count },
    { key: "done", label: "تصمیم‌گرفته‌شده", count: decided },
  ];

  return (
    <div className="space-y-3" data-testid="job-report">
      <div className="u-tabs">
        {tabs.map((t) => (
          <button key={t.key} type="button" className={`u-tab ${tab === t.key ? "active" : ""}`} onClick={() => changeTab(t.key)} data-testid={`report-tab-${t.key}`}>
            {t.label} ({fa(t.count)})
          </button>
        ))}
      </div>

      {message && (
        <Alert tone="ok">
          <span data-testid="report-message">{message}</span>
        </Alert>
      )}
      {downloadError && <Alert tone="bad">{downloadError}</Alert>}

      {tab === "error" && (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={downloadErrors} disabled={job.error_count === 0} data-testid="download-errors">
            <Icon name="download" size={14} />
            دانلود فایل خطاها
          </Button>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            فایلی با ستون‌های اصلی و دلیلِ هر خطا؛ درستش کنید و دوباره وارد کنید.
          </span>
        </div>
      )}
      {tab === "duplicate" && job.duplicate_count > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setBulkOpen(true)} data-testid="merge-all">
            ادغامِ همه…
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setSkipAllOpen(true)} data-testid="skip-all">
            رد کردنِ همه
          </Button>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            هیچ تکراری‌ای خودکار ادغام نمی‌شود؛ تصمیم با شماست.
          </span>
        </div>
      )}

      <LoadState loading={rows.loading && !rows.data} error={rows.error} onRetry={rows.reload}>
        {rows.data && rows.data.results.length === 0 ? (
          <Card>
            <EmptyState icon="check" title={tab === "error" ? "ردیفِ خطادار نمانده" : tab === "duplicate" ? "تکراریِ منتظرِ تصمیم نمانده" : "هنوز تصمیمی گرفته نشده"} />
          </Card>
        ) : (
          rows.data && (
            <Card padded={false}>
              <div className="overflow-x-auto">
                <table className="u-table" data-testid="report-table">
                  <thead>
                    <tr>
                      <th>ردیف</th>
                      <th>محتوای ردیف</th>
                      <th>{tab === "error" ? "مشکل" : tab === "duplicate" ? "هم‌پوشانی با" : "نتیجه"}</th>
                      {tab === "duplicate" && <th />}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.data.results.map((row) => (
                      <tr key={row.id} data-testid={`report-row-${row.row_number}`}>
                        <td className="u-num">{fa(row.row_number)}</td>
                        <td dir="auto" style={{ maxWidth: 260 }}>
                          <span className="block truncate" title={rowSummary(row.raw)}>
                            {rowSummary(row.raw) || "—"}
                          </span>
                        </td>
                        <td>
                          {tab === "error" && (
                            <ul className="space-y-0.5 text-xs" style={{ color: "var(--bad)" }}>
                              {row.errors.map((e, i) => (
                                <li key={i}>{e.message}</li>
                              ))}
                            </ul>
                          )}
                          {tab === "duplicate" && (
                            <div className="space-y-1">
                              {row.matches.slice(0, 2).map((m) => (
                                <div key={m.lead_id} className="flex flex-wrap items-center gap-1.5 text-xs">
                                  <Link to={`/growth/leads/${m.lead_id}`} target="_blank" rel="noopener" dir="auto" className="font-medium">
                                    {m.name}
                                  </Link>
                                  {m.matched_on.map((x) => (
                                    <Badge key={x.kind + x.value} tone="info">
                                      {kindLabel(x.kind)}
                                    </Badge>
                                  ))}
                                </div>
                              ))}
                              {row.merge_preview && (
                                <details className="text-xs">
                                  <summary style={{ cursor: "pointer", color: "var(--text-3)" }}>مقایسه</summary>
                                  <div className="mt-2">
                                    <MergePreviewTable preview={row.merge_preview} overwrite={[]} onToggle={() => undefined} />
                                  </div>
                                </details>
                              )}
                            </div>
                          )}
                          {tab === "done" && <Badge tone={row.status === "skipped" ? "neutral" : "ok"}>{row.status_label}</Badge>}
                        </td>
                        {tab === "duplicate" && (
                          <td>
                            <div className="flex gap-1.5">
                              <Button size="sm" onClick={() => { setRowError(null); setOpenRow(row); }} data-testid={`row-merge-${row.row_number}`}>
                                ادغام…
                              </Button>
                              <Button size="sm" variant="secondary" onClick={() => resolveRow("skip", row)} disabled={rowBusy} data-testid={`row-skip-${row.row_number}`}>
                                رد
                              </Button>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-3">
                <Pagination page={page} pageSize={PAGE_SIZE} count={rows.data.count} onPage={setPage} disabled={rows.loading} />
              </div>
            </Card>
          )
        )}
      </LoadState>

      <RowMergeDialog
        row={openRow}
        busy={rowBusy}
        error={rowError}
        onMerge={(target, overwrite) => openRow && resolveRow("merge", openRow, target, overwrite)}
        onSkip={() => openRow && resolveRow("skip", openRow)}
        onClose={() => !rowBusy && setOpenRow(null)}
      />
      <BulkMergeDialog
        open={bulkOpen}
        count={job.duplicate_count}
        busy={bulkBusy}
        error={bulkError}
        onConfirm={(overwrite) => resolveAll("merge", overwrite)}
        onClose={() => !bulkBusy && setBulkOpen(false)}
      />
      <ConfirmDialog
        open={skipAllOpen}
        title="رد کردنِ همهٔ تکراری‌ها"
        message={`${fa(job.duplicate_count)} ردیفِ تکراری رد می‌شود و چیزی ثبت یا عوض نمی‌شود. ادامه می‌دهید؟`}
        confirmLabel="بله، رد شود"
        busy={bulkBusy}
        onConfirm={() => resolveAll("skip")}
        onClose={() => !bulkBusy && setSkipAllOpen(false)}
      />
    </div>
  );
}
