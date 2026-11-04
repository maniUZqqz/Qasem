import { useState } from "react";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, fa } from "../../../../components/ui";
import { useGet } from "../../api";
import { bytes, faDateTime, shortUrl } from "../../format";
import type { ExtractionLeadRuns, ExtractionRunInfo, LeadDetail } from "../../types";
import { LoadState } from "../bits";
import ExtractionProgress from "./ExtractionProgress";
import { FIELD_LABEL, PAGE_KIND_LABEL, REASON_LABEL, ROBOTS_LABEL, startExtraction } from "./api";

const ltr = { direction: "ltr", textAlign: "left", unicodeBidi: "plaintext" } as const;
const runTone = (s: string) => (s === "done" ? "ok" : s === "failed" ? "bad" : s === "skipped" ? "neutral" : "brand");

function RunCard({ run }: { run: ExtractionRunInfo }) {
  return (
    <div className="space-y-3" data-testid="extract-run" data-run-id={run.id}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={runTone(run.status)}>{run.status_label}</Badge>
        {run.reason_label && <span style={{ color: "var(--text-2)" }}>{run.reason_label}</span>}
        <span style={{ color: "var(--text-3)" }}>
          · {fa(run.pages_fetched)} صفحه خوانده شد · {fa(run.contacts_added)} راهِ تماسِ تازه · {ROBOTS_LABEL[run.robots_state] ?? run.robots_state}
        </span>
        <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
          اجرای {fa(run.id)} · {faDateTime(run.started_at ?? run.finished_at)}
        </span>
      </div>

      <div>
        <h4 className="mb-1.5 text-sm font-bold" style={{ color: "var(--text)" }}>
          چه پیدا شد
        </h4>
        {run.findings.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            در صفحه‌هایی که خوانده شد چیزِ قابل‌ثبتی دیده نشد؛ چیزی هم ساخته نشد.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="u-table" data-testid="findings-table">
              <thead>
                <tr>
                  <th>فیلد</th>
                  <th>مقدار</th>
                  <th>صفحهٔ منبع</th>
                  <th>مدرک</th>
                  <th>اطمینان</th>
                  <th>نتیجه</th>
                </tr>
              </thead>
              <tbody>
                {run.findings.map((f, i) => (
                  <tr key={`${f.field}-${f.value}-${i}`} data-testid="finding-row">
                    <td className="font-medium" style={{ color: "var(--text)" }}>
                      {FIELD_LABEL[f.field] ?? f.field}
                    </td>
                    <td style={{ ...ltr, maxWidth: 260 }}>
                      <span className="block break-words">{f.value}</span>
                    </td>
                    <td style={{ maxWidth: 200 }}>
                      {f.source_url ? (
                        <a href={f.source_url} target="_blank" rel="noopener noreferrer" className="block truncate" style={ltr}>
                          {shortUrl(f.source_url)}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td dir="auto" style={{ maxWidth: 200 }}>
                      {f.evidence || "—"}
                    </td>
                    <td className="u-num">{f.confidence === null ? "—" : `${fa(f.confidence)}٪`}</td>
                    <td>
                      <Badge tone={f.applied ? "ok" : "neutral"}>{REASON_LABEL[f.reason] ?? f.reason}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <details>
        <summary className="cursor-pointer text-sm font-bold" style={{ color: "var(--text-2)" }}>
          صفحه‌هایی که سراغشان رفتیم ({fa(run.pages.length)})
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="u-table" data-testid="pages-table">
            <thead>
              <tr>
                <th>صفحه</th>
                <th>نوع</th>
                <th>کدِ پاسخ</th>
                <th>نتیجه</th>
                <th>زمان</th>
                <th>حجم</th>
              </tr>
            </thead>
            <tbody>
              {run.pages.map((p, i) => (
                <tr key={`${p.url}-${i}`}>
                  <td style={{ ...ltr, maxWidth: 260 }}>
                    <a href={p.url} target="_blank" rel="noopener noreferrer" className="block truncate">
                      {shortUrl(p.url)}
                    </a>
                  </td>
                  <td>{PAGE_KIND_LABEL[p.kind] ?? p.kind}</td>
                  <td className="u-num">{p.status ? fa(p.status) : "—"}</td>
                  <td>
                    <Badge tone={p.outcome === "ok" ? "ok" : "warn"}>{p.outcome_label}</Badge>
                    {p.note && (
                      <span className="mr-1.5 text-xs" style={{ color: "var(--text-3)" }}>
                        {p.note}
                      </span>
                    )}
                  </td>
                  <td className="u-num">{fa(p.elapsed_ms)}ms</td>
                  <td className="u-num">{p.bytes ? bytes(p.bytes) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/**
 * The «استخراج» tab: run the extractor on this lead's own website and see exactly what it found, on which page,
 * with what evidence and confidence - and what it did with each value.
 */
export default function ExtractionTab({ lead, onChanged }: { lead: LeadDetail; onChanged: () => void }) {
  const runs = useGet<ExtractionLeadRuns>(`/leads/${lead.id}/extraction/`);
  const [jobId, setJobId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const [force, setForce] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const job = await startExtraction([lead.id], force);
      setJobId(job.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "شروع نشد.");
    } finally {
      setStarting(false);
    }
  };

  const absent = !!runs.error && runs.error.includes("404");
  const list = runs.data?.runs ?? [];

  return (
    <div className="space-y-4" data-testid="extraction-tab">
      <Card>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={start} disabled={starting || !lead.website || jobId !== null} data-testid="extract-start">
              <Icon name="search" size={15} />
              {starting ? "در حال شروع…" : "اجرای استخراج از سایت"}
            </Button>
            <label className="flex cursor-pointer items-center gap-1.5 text-sm" style={{ color: "var(--text-2)" }}>
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} data-testid="extract-force" />
              حتی اگر به‌تازگی خوانده شده
            </label>
            {!lead.website && (
              <span className="text-sm" style={{ color: "var(--warn)" }} data-testid="extract-no-website">
                این لید وب‌سایت ندارد؛ اول آدرسِ سایت را در تبِ «اطلاعات» بنویسید.
              </span>
            )}
          </div>
          {error && <Alert tone="bad">{error}</Alert>}
          <ul className="list-disc space-y-1 pr-5 text-xs leading-6" style={{ color: "var(--text-3)" }}>
            <li>فقط صفحه‌های خودِ سایتِ همین لید (صفحهٔ اصلی، تماس با ما، دربارهٔ ما، پشتیبانی) خوانده می‌شود؛ حداکثر ۵ صفحه.</li>
            <li>قبل از هر صفحه robots.txt سایت رعایت می‌شود و بینِ دو درخواست به یک سایت فاصله می‌افتد.</li>
            <li>فقط چیزی که در صفحه نوشته شده ثبت می‌شود، همراهِ آدرسِ صفحه و مدرک؛ هیچ‌چیز حدس زده یا ساخته نمی‌شود.</li>
            <li>چیزی وارد فرم نمی‌شود، وارد حسابی نمی‌شویم، و اینستاگرام باز نمی‌شود.</li>
            <li>مقدارهایی که لید از قبل دارد جایگزین نمی‌شوند؛ فقط جای خالی‌ها پر می‌شود.</li>
          </ul>
        </div>
      </Card>

      {jobId !== null && (
        <Card>
          <ExtractionProgress
            key={jobId}
            jobId={jobId}
            onFinished={() => {
              runs.reload();
              onChanged();
            }}
          />
        </Card>
      )}

      {absent ? (
        <Alert tone="warn">بخشِ استخراجِ اطلاعاتِ تماس در این نسخه هنوز فعال نیست.</Alert>
      ) : (
        <LoadState loading={runs.loading && !runs.data} error={runs.error} onRetry={runs.reload}>
          {list.length === 0 ? (
            <Card>
              <EmptyState icon="search" title="هنوز استخراجی برای این لید انجام نشده">دکمهٔ بالا را بزنید تا سایتِ لید خوانده شود.</EmptyState>
            </Card>
          ) : (
            <div className="space-y-3">
              {list.map((run, index) => (
                <Card key={run.id}>
                  {index === 0 ? (
                    <RunCard run={run} />
                  ) : (
                    <details>
                      <summary className="cursor-pointer text-sm font-medium" style={{ color: "var(--text-2)" }}>
                        اجرای قبلی: {run.status_label} · {faDateTime(run.started_at ?? run.finished_at)}
                      </summary>
                      <div className="mt-3">
                        <RunCard run={run} />
                      </div>
                    </details>
                  )}
                </Card>
              ))}
            </div>
          )}
        </LoadState>
      )}
    </div>
  );
}
