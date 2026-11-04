import { useEffect, useState } from "react";

import Icon from "../../../../components/Icon";
import { Button, Card, EmptyState, SectionTitle, fa } from "../../../../components/ui";
import { useGet } from "../../api";
import { faAgo } from "../../format";
import type { DiscoveryJob, Paged } from "../../types";
import Pagination from "../Pagination";
import { JobBadge, LoadState } from "../bits";

const PAGE_SIZE = 8;

/** «ورودی‌های اخیر»: every CSV import, newest first; any of them can be reopened into the progress/report panel. */
export default function RecentJobs({ activeId, refreshKey, onOpen }: { activeId: number | null; refreshKey: number; onOpen: (id: number) => void }) {
  const [page, setPage] = useState(1);
  const [poll, setPoll] = useState<number | undefined>(undefined);
  const { data, loading, error, reload } = useGet<Paged<DiscoveryJob>>("/discovery/jobs/", { page, page_size: PAGE_SIZE, _k: refreshKey }, { poll });

  const busy = !!data?.results.some((j) => j.status === "queued" || j.status === "running");
  useEffect(() => setPoll(busy ? 4000 : undefined), [busy]);

  return (
    <Card>
      <SectionTitle
        action={
          <Button variant="ghost" size="sm" onClick={reload} disabled={loading} aria-label="به‌روزرسانیِ فهرست">
            <Icon name="refresh" size={14} />
          </Button>
        }
      >
        ورودی‌های اخیر
      </SectionTitle>
      <LoadState loading={loading && !data} error={error} onRetry={reload}>
        {data && data.results.length === 0 ? (
          <EmptyState icon="upload" title="هنوز فایلی وارد نشده">از تبِ «فایل CSV» اولین فایل را بیاورید.</EmptyState>
        ) : (
          data && (
            <>
              <div className="overflow-x-auto">
                <table className="u-table" data-testid="recent-jobs-table">
                  <thead>
                    <tr>
                      <th>فایل</th>
                      <th>وضعیت</th>
                      <th>ردیف</th>
                      <th>لیدِ تازه</th>
                      <th>تکراری</th>
                      <th>خطا</th>
                      <th>زمان</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.results.map((job) => (
                      <tr key={job.id} style={job.id === activeId ? { background: "var(--brand-soft)" } : undefined} data-testid={`job-row-${job.id}`}>
                        <td dir="auto" style={{ maxWidth: 220 }}>
                          <span className="block truncate" title={job.file_name}>
                            {job.file_name || `ورودی ${fa(job.id)}`}
                          </span>
                        </td>
                        <td>
                          <JobBadge status={job.status} label={job.status_label} />
                        </td>
                        <td className="u-num">{fa(job.processed_items)}/{fa(job.total_items)}</td>
                        <td className="u-num">{fa(job.created_count)}</td>
                        <td className="u-num">{fa(job.duplicate_count)}</td>
                        <td className="u-num">{fa(job.error_count)}</td>
                        <td className="u-num" style={{ color: "var(--text-3)" }}>{faAgo(job.queued_at)}</td>
                        <td>
                          <Button variant="secondary" size="sm" onClick={() => onOpen(job.id)} data-testid={`job-open-${job.id}`}>
                            بازکردن
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination page={page} pageSize={PAGE_SIZE} count={data.count} onPage={setPage} disabled={loading} />
            </>
          )
        )}
      </LoadState>
    </Card>
  );
}
