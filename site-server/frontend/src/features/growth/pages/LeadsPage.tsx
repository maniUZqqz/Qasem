import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Select } from "../../../components/ui";
import { download, problem, useGet } from "../api";
import { LoadState } from "../components/bits";
import ExtractionProgress from "../components/extraction/ExtractionProgress";
import { startExtraction } from "../components/extraction/api";
import BulkBar from "../components/leads/BulkBar";
import LeadFiltersPanel from "../components/leads/LeadFiltersPanel";
import LeadTable from "../components/leads/LeadTable";
import { useDebounced } from "../components/leads/hooks";
import { PAGE_SIZES, activeFilterCount, isNarrowed, readFilters, toParams, type LeadFilters } from "../components/leads/queryState";
import Pagination from "../components/Pagination";
import { num } from "../format";
import type { LeadRow, Paged, TagWithCount } from "../types";

/** «دیتابیس لیدها»: search, filters, sorting, paging and bulk actions; the whole view lives in the URL. */
export default function LeadsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const filters = useMemo(() => readFilters(params), [params]);
  const apiParams = useMemo(() => toParams(filters), [filters]);
  const { data, loading, error, reload } = useGet<Paged<LeadRow>>("/leads/", apiParams);
  const tags = useGet<TagWithCount[]>("/tags/");

  const [selected, setSelected] = useState<number[]>([]);
  const [showFilters, setShowFilters] = useState(activeFilterCount(filters) > 0);
  const [qInput, setQInput] = useState(filters.q);
  const debouncedQ = useDebounced(qInput, 350);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState<{ tone: "bad" | "ok"; text: string } | null>(null);
  const [extractJob, setExtractJob] = useState<number | null>(null);

  const update = useCallback(
    (patch: Partial<LeadFilters>, replace = false) => {
      const next: LeadFilters = { ...filters, ...patch };
      if (!("page" in patch)) next.page = 1;
      if (!("page" in patch) && !("page_size" in patch) && !("ordering" in patch)) setSelected([]);
      const entries = Object.entries(toParams(next)).map(([k, v]) => [k, String(v)]);
      setParams(new URLSearchParams(entries), { replace });
    },
    [filters, setParams],
  );

  // the search box writes to the URL after a pause; the URL drives the box when it changes from outside
  useEffect(() => {
    if (debouncedQ !== filters.q) update({ q: debouncedQ }, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);
  useEffect(() => setQInput(filters.q), [filters.q]);

  const clearAll = () => {
    setQInput("");
    setParams(new URLSearchParams(), { replace: false });
    setSelected([]);
  };

  const onSort = (field: string) => update({ ordering: filters.ordering === field ? `-${field}` : field });
  const rows = data?.results ?? [];
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const togglePage = (all: boolean) =>
    setSelected((s) => (all ? Array.from(new Set([...s, ...rows.map((r) => r.id)])) : s.filter((id) => !rows.some((r) => r.id === id))));

  const exportAll = async () => {
    setExporting(true);
    setNotice(null);
    try {
      const { page: _page, page_size: _size, ...rest } = apiParams;
      void _page;
      void _size;
      await download("/leads/export/", rest, "growth-leads.csv");
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setExporting(false);
    }
  };

  const extract = async (ids: number[]) => {
    setNotice(null);
    try {
      const job = await startExtraction(ids);
      setExtractJob(job.id);
    } catch (err) {
      setNotice({ tone: "bad", text: err instanceof Error ? err.message : "شروع نشد." });
    }
  };

  const narrowed = isNarrowed(filters);
  const filterCount = activeFilterCount(filters);

  return (
    <div className="space-y-4" data-testid="growth-leads">
      <Card>
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="relative min-w-[14rem] flex-1">
            <Input
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              placeholder="جست‌وجو: نام، آدرس، شهر، تلفن، ایمیل…"
              aria-label="جست‌وجو در لیدها"
              data-testid="lead-search"
              style={{ paddingInlineStart: 38 }}
            />
            <span className="pointer-events-none absolute top-1/2 -translate-y-1/2" style={{ insetInlineStart: 12, color: "var(--text-3)" }}>
              <Icon name="search" size={16} />
            </span>
          </div>
          <Button variant={showFilters ? "primary" : "secondary"} onClick={() => setShowFilters((v) => !v)} aria-expanded={showFilters} data-testid="filters-toggle">
            <Icon name="filter" size={15} />
            فیلترها
            {filterCount > 0 && <Badge tone="brand">{num(filterCount)}</Badge>}
          </Button>
          <Button variant="secondary" onClick={exportAll} disabled={exporting || !data || data.count === 0} data-testid="export-all">
            <Icon name="download" size={15} />
            {exporting ? "در حال آماده‌سازی…" : "خروجیِ CSV"}
          </Button>
          <Link to="/growth/discovery" className="no-underline">
            <Button>
              <Icon name="plus" size={15} />
              لیدِ تازه
            </Button>
          </Link>
        </div>
        {showFilters && (
          <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--line)" }}>
            <LeadFiltersPanel filters={filters} tags={tags.data ?? []} onChange={(patch) => update(patch)} onClear={clearAll} />
          </div>
        )}
      </Card>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}

      {selected.length > 0 && (
        <BulkBar
          ids={selected}
          onClear={() => setSelected([])}
          onChanged={(clear) => {
            if (clear) setSelected([]);
            reload();
            tags.reload();
          }}
          onExtract={extract}
          onCampaign={(ids) => navigate(`/growth/outreach?new=1&lead_ids=${ids.join(",")}`)}
        />
      )}

      <LoadState loading={loading && !data} error={error} onRetry={reload}>
        {data && data.count === 0 ? (
          <Card>
            {narrowed ? (
              <EmptyState
                icon="search"
                title="نتیجه‌ای پیدا نشد"
                description="هیچ لیدی با این جست‌وجو و فیلترها نمی‌خواند."
                action={
                  <Button variant="secondary" onClick={clearAll} data-testid="empty-clear">
                    پاک کردنِ فیلترها
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon="users"
                title="هنوز لیدی ثبت نشده"
                description="با آدرسِ سایت یا پیجِ اینستاگرام شروع کنید، یا یک فایل CSV بیاورید."
                action={
                  <Link to="/growth/discovery" className="no-underline">
                    <Button data-testid="empty-discovery">رفتن به کشفِ مشتری</Button>
                  </Link>
                }
              />
            )}
          </Card>
        ) : (
          data && (
            <>
              <LeadTable rows={rows} selected={selected} onToggle={toggle} onTogglePage={togglePage} ordering={filters.ordering} onSort={onSort} busy={loading} />
              <div className="flex flex-wrap items-center justify-between gap-3">
                <Pagination page={filters.page} pageSize={filters.page_size} count={data.count} onPage={(page) => update({ page })} disabled={loading} />
                <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text-3)" }}>
                  در هر صفحه
                  <Select value={filters.page_size} onChange={(e) => update({ page_size: Number(e.target.value) })} style={{ width: 80 }} data-testid="page-size">
                    {PAGE_SIZES.map((s) => (
                      <option key={s} value={s}>
                        {num(s)}
                      </option>
                    ))}
                  </Select>
                </label>
              </div>
            </>
          )
        )}
      </LoadState>

      {extractJob !== null && <ExtractionProgress key={extractJob} jobId={extractJob} floating onClose={() => setExtractJob(null)} onFinished={() => reload()} />}
    </div>
  );
}
