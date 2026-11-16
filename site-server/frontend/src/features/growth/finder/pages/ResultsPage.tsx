import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Select, Table, fa } from "../../../../components/ui";
import { download, g, problem, useGet } from "../../api";
import { useDebounced } from "../../components/leads/hooks";
import Pagination from "../../components/Pagination";
import { num } from "../../format";
import LeadPanel from "../components/LeadPanel";
import ResultMap from "../components/ResultMap";
import { ScoreBadge, SOURCE_LABEL } from "../components/bits";
import { useFinder } from "../FinderLayout";
import type { MapPoint, Mission, Paged, Result } from "../types";

type Summary = { total: number; by_level: Record<string, number>; by_stage: Record<string, number>; cities: [string, number][] };

const FLAGS: [string, string][] = [
  ["has_phone", "تلفن"],
  ["has_email", "ایمیل"],
  ["has_website", "وب‌سایت"],
  ["has_instagram", "اینستاگرام"],
  ["has_geo", "روی نقشه"],
];
const ORDERINGS: [string, string][] = [
  ["-score", "بیشترین امتیاز"],
  ["score", "کمترین امتیاز"],
  ["name", "نام"],
  ["city", "شهر"],
  ["-created", "تازه‌ترین"],
];
const SELECTION_LIMIT = 200;

/** «نتیجه‌ها و نقشه»: the businesses the missions found - list and map, filters, tags, notes (in the lead window), CSV. The view lives in the URL. */
export default function ResultsPage() {
  const { meta, stageLabel } = useFinder();
  const [sp, setSp] = useSearchParams();
  const get = (k: string) => sp.get(k) ?? "";
  const [qInput, setQInput] = useState(get("q"));
  const debounced = useDebounced(qInput, 350);
  const view = get("view") === "map" ? "map" : "list";
  const page = Number(get("page")) || 1;

  const filterParams = useMemo(() => {
    const out: Record<string, string> = {};
    for (const k of ["mission", "q", "min_score", "stage", "city", "tag", "ordering", ...FLAGS.map(([f]) => f)]) if (sp.get(k)) out[k] = sp.get(k)!;
    return out;
  }, [sp]);

  const missions = useGet<Paged<Mission>>("/finder/missions/", { page_size: 100 });
  const results = useGet<Paged<Result>>("/finder/results/", { ...filterParams, page, page_size: 25 });
  const summary = useGet<Summary>("/finder/results/summary/", filterParams);
  const mapData = useGet<{ points: MapPoint[]; total: number; shown: number }>(view === "map" ? "/finder/results/map/" : null, filterParams);

  const [selected, setSelected] = useState<number[]>([]);
  const [open, setOpen] = useState<{ leadId: number; missionId: number | null } | null>(null);
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);

  const patch = useCallback(
    (changes: Record<string, string | null>, keepPage = false) => {
      const next = new URLSearchParams(sp);
      Object.entries(changes).forEach(([k, v]) => (v === null || v === "" ? next.delete(k) : next.set(k, v)));
      if (!keepPage) next.delete("page");
      setSp(next, { replace: false });
    },
    [sp, setSp],
  );
  useEffect(() => {
    if (debounced !== get("q")) patch({ q: debounced }, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  const rows = results.data?.results ?? [];
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const leadsOf = (ids: number[]) => rows.filter((r) => ids.includes(r.id));
  const selectedRows = leadsOf(selected);
  const tooMany = selected.length > SELECTION_LIMIT;

  const act = async (fn: () => Promise<string>) => {
    setBusy(true);
    setNotice(null);
    try {
      setNotice({ tone: "ok", text: await fn() });
      results.reload();
      summary.reload();
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(false);
    }
  };

  const addTag = () =>
    act(async () => {
      const r = await g.post<{ affected: number }>("/leads/bulk/", { ids: selectedRows.map((x) => x.lead_id), action: "add_tag", tag: tag.trim() });
      setTag("");
      return `برچسب «${tag.trim()}» روی ${fa(r.affected)} لید گذاشته شد.`;
    });
  const moveStage = (stage: string) =>
    act(async () => {
      for (const r of selectedRows) await g.post(`/finder/leads/${r.lead_id}/stage/`, { stage });
      return `${fa(selectedRows.length)} لید به «${stageLabel(stage)}» رفت.`;
    });
  const remind = (days: number) =>
    act(async () => {
      for (const r of selectedRows) await g.post(`/finder/leads/${r.lead_id}/reminders/`, { in_days: days, note: "پیگیری" });
      return `برای ${fa(selectedRows.length)} لید یادآوری ثبت شد.`;
    });
  const draft = (channel: string) =>
    act(async () => {
      const byMission = new Map<number, number[]>();
      selectedRows.forEach((r) => byMission.set(r.mission_id, [...(byMission.get(r.mission_id) ?? []), r.lead_id]));
      let made = 0;
      let skipped = 0;
      for (const [mission, ids] of byMission) {
        const r = await g.post<{ created: number; updated: number; skipped: unknown[] }>(`/finder/missions/${mission}/drafts/`, { lead_ids: ids, channels: [channel] });
        made += r.created + r.updated;
        skipped += r.skipped.length;
      }
      return `${fa(made)} پیش‌نویس نوشته شد${skipped ? ` (${fa(skipped)} لید این راهِ تماس را نداشت)` : ""}؛ چیزی فرستاده نشد. در «پیش‌نویسِ پیام‌ها» ببینید.`;
    });

  const exportCsv = async () => {
    setBusy(true);
    try {
      await download("/finder/results/export/", filterParams, "moshtari-yab.csv");
    } catch (err) {
      setNotice({ tone: "bad", text: problem(err).message });
    } finally {
      setBusy(false);
    }
  };

  const filterCount = Object.keys(filterParams).filter((k) => !["ordering", "mission"].includes(k)).length;

  return (
    <div className="space-y-4" data-testid="finder-results">
      {summary.data && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5" data-testid="results-summary">
          {[
            ["همهٔ نتیجه‌ها", summary.data.total],
            ["تناسبِ بالا", summary.data.by_level.high ?? 0],
            ["متوسط", summary.data.by_level.medium ?? 0],
            ["کم", summary.data.by_level.low ?? 0],
            ["مشتری شده", summary.data.by_stage.customer ?? 0],
          ].map(([label, value]) => (
            <Card key={label as string}>
              <div className="u-num text-xl font-extrabold" style={{ color: "var(--text)" }}>
                {num(value as number)}
              </div>
              <div className="text-xs" style={{ color: "var(--text-3)" }}>
                {label}
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="relative min-w-[14rem] flex-1">
            <Input value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="جست‌وجو: نام، شهر، دسته، سایت…" aria-label="جست‌وجو" data-testid="result-search" style={{ paddingInlineStart: 38 }} />
            <span className="pointer-events-none absolute top-1/2 -translate-y-1/2" style={{ insetInlineStart: 12, color: "var(--text-3)" }}>
              <Icon name="search" size={16} />
            </span>
          </div>
          <Select value={get("mission")} onChange={(e) => patch({ mission: e.target.value })} style={{ width: 200 }} aria-label="مأموریت" data-testid="filter-mission">
            <option value="">همهٔ مأموریت‌ها</option>
            {missions.data?.results.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
          <Select value={get("min_score")} onChange={(e) => patch({ min_score: e.target.value })} style={{ width: 150 }} aria-label="حداقل امتیاز" data-testid="filter-score">
            <option value="">هر امتیاز</option>
            <option value="45">متوسط به بالا (۴۵+)</option>
            <option value="70">فقط مناسب (۷۰+)</option>
          </Select>
          <Select value={get("stage")} onChange={(e) => patch({ stage: e.target.value })} style={{ width: 150 }} aria-label="مرحله" data-testid="filter-stage">
            <option value="">همهٔ مرحله‌ها</option>
            {meta?.stages.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
          <Select value={get("ordering") || "-score"} onChange={(e) => patch({ ordering: e.target.value })} style={{ width: 150 }} aria-label="ترتیب">
            {ORDERINGS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span style={{ color: "var(--text-3)" }}>باید داشته باشد:</span>
          {FLAGS.map(([f, label]) => (
            <label key={f} className="flex items-center gap-1">
              <input type="checkbox" checked={get(f) === "1"} onChange={(e) => patch({ [f]: e.target.checked ? "1" : null })} data-testid={`flag-${f}`} />
              {label}
            </label>
          ))}
          <Input value={get("city")} onChange={(e) => patch({ city: e.target.value })} placeholder="شهر" style={{ width: 110 }} aria-label="شهر" />
          <Input value={get("tag")} onChange={(e) => patch({ tag: e.target.value })} placeholder="برچسب" style={{ width: 110 }} aria-label="برچسب" />
          {filterCount > 0 && (
            <Button variant="ghost" size="sm" onClick={() => { setQInput(""); setSp(new URLSearchParams(get("mission") ? { mission: get("mission") } : {})); }}>
              پاک‌کردنِ فیلترها
            </Button>
          )}
          <span className="ms-auto flex gap-2">
            <Button variant={view === "list" ? "primary" : "secondary"} size="sm" onClick={() => patch({ view: null }, true)} data-testid="view-list">
              <Icon name="menu" size={14} />
              فهرست
            </Button>
            <Button variant={view === "map" ? "primary" : "secondary"} size="sm" onClick={() => patch({ view: "map" }, true)} data-testid="view-map">
              <Icon name="target" size={14} />
              نقشه
            </Button>
            <Button variant="secondary" size="sm" disabled={busy || !results.data?.count} onClick={exportCsv} data-testid="export-csv">
              <Icon name="download" size={14} />
              CSV
            </Button>
          </span>
        </div>
      </Card>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}

      {selected.length > 0 && (
        <Card>
          <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="bulk-bar">
            <b>{fa(selected.length)} انتخاب‌شده</b>
            <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
              لغو
            </Button>
            {tooMany && <Badge tone="bad">حداکثر {fa(SELECTION_LIMIT)} مورد</Badge>}
            <Input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="برچسب" style={{ width: 120 }} aria-label="برچسبِ تازه" data-testid="bulk-tag" />
            <Button size="sm" disabled={busy || tooMany || !tag.trim()} onClick={addTag} data-testid="bulk-tag-add">
              <Icon name="tag" size={13} />
              برچسب بزن
            </Button>
            <Select defaultValue="" onChange={(e) => e.target.value && moveStage(e.target.value)} style={{ width: 150 }} aria-label="انتقال به مرحله" disabled={busy || tooMany} data-testid="bulk-stage">
              <option value="">انتقال به مرحله…</option>
              {meta?.stages.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </Select>
            <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => remind(3)}>
              <Icon name="bell" size={13} />
              یادآوری ۳ روز دیگر
            </Button>
            <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => draft("sms")} data-testid="bulk-draft-sms">
              پیش‌نویسِ پیامک
            </Button>
            <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => draft("instagram_dm")}>
              پیش‌نویسِ دایرکت
            </Button>
            <Button variant="secondary" size="sm" disabled={busy || tooMany} onClick={() => draft("email")}>
              پیش‌نویسِ ایمیل
            </Button>
          </div>
        </Card>
      )}

      {view === "map" ? (
        <Card>
          {mapData.loading && !mapData.data ? (
            <div className="py-10 text-center" style={{ color: "var(--text-3)" }}>
              در حال بارگذاریِ نقشه…
            </div>
          ) : mapData.data && mapData.data.points.length ? (
            <ResultMap points={mapData.data.points} selectedId={null} onSelect={(p) => setOpen({ leadId: p.lead_id, missionId: get("mission") ? Number(get("mission")) : null })} />
          ) : (
            <EmptyState icon="target" title="نقطه‌ای با مختصات نیست">
              لیدهایی که از نقشه یا فهرست آمده‌اند مختصات دارند؛ فیلترها را شُل کنید.
            </EmptyState>
          )}
          {mapData.data && mapData.data.total > mapData.data.shown && (
            <p className="mt-2 text-xs" style={{ color: "var(--text-3)" }}>
              فقط {fa(mapData.data.shown)} نقطهٔ برتر از {fa(mapData.data.total)} نمایش داده شد؛ فیلتر کنید.
            </p>
          )}
        </Card>
      ) : (
        <Card padded={false}>
          {results.error ? (
            <div className="p-4">
              <Alert tone="bad">{results.error}</Alert>
            </div>
          ) : rows.length === 0 && !results.loading ? (
            <EmptyState icon="search" title="نتیجه‌ای نیست">
              یک مأموریت را اجرا کنید یا فیلترها را عوض کنید.
            </EmptyState>
          ) : (
            <Table>
              <thead>
                <tr>
                  <th style={{ width: 36 }}>
                    <input
                      type="checkbox"
                      aria-label="انتخابِ همهٔ این صفحه"
                      checked={rows.length > 0 && rows.every((r) => selected.includes(r.id))}
                      onChange={(e) => setSelected(e.target.checked ? Array.from(new Set([...selected, ...rows.map((r) => r.id)])) : selected.filter((id) => !rows.some((r) => r.id === id)))}
                    />
                  </th>
                  <th>کسب‌وکار</th>
                  <th>امتیاز</th>
                  <th>مرحله</th>
                  <th>تماس</th>
                  <th>منبع</th>
                  <th />
                </tr>
              </thead>
              <tbody data-testid="result-rows">
                {rows.map((r) => (
                  <tr key={r.id} data-testid="result-row">
                    <td>
                      <input type="checkbox" checked={selected.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`انتخاب ${r.name}`} />
                    </td>
                    <td>
                      <button type="button" className="text-start font-bold underline-offset-2 hover:underline" style={{ color: "var(--text)" }} onClick={() => setOpen({ leadId: r.lead_id, missionId: r.mission_id })}>
                        {r.name}
                      </button>
                      <div className="text-xs" style={{ color: "var(--text-3)" }}>
                        {[r.city, r.category].filter(Boolean).join(" · ")}
                      </div>
                      {r.tags.length > 0 && (
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          {r.tags.slice(0, 3).map((t) => (
                            <Badge key={t}>{t}</Badge>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <ScoreBadge score={r.score} level={r.level} reasons={r.reasons} />
                    </td>
                    <td>
                      <Badge tone={meta?.stages.find((s) => s.key === r.stage)?.tone ?? "neutral"}>{stageLabel(r.stage)}</Badge>
                    </td>
                    <td className="text-xs" dir="ltr" style={{ textAlign: "start" }}>
                      {r.phones.slice(0, 2).map((p) => (
                        <div key={p.value} className="u-num">
                          {p.mobile ? "📱 " : "☎ "}
                          {p.display}
                        </div>
                      ))}
                      {r.emails[0] && <div>{r.emails[0]}</div>}
                      {r.instagram && <div>@{r.instagram.split("/").filter(Boolean).pop()}</div>}
                    </td>
                    <td className="text-xs" style={{ color: "var(--text-3)" }}>
                      {r.sources.map((s) => SOURCE_LABEL[s] ?? s).join("، ") || "—"}
                    </td>
                    <td>
                      <Button variant="ghost" size="sm" onClick={() => setOpen({ leadId: r.lead_id, missionId: r.mission_id })} aria-label="باز کردن">
                        <Icon name="next" size={14} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
          {results.data && results.data.count > 25 && (
            <div className="p-3">
              <Pagination page={page} pageSize={25} count={results.data.count} onPage={(p) => patch({ page: String(p) }, true)} />
            </div>
          )}
        </Card>
      )}

      {open && <LeadPanel leadId={open.leadId} missionId={open.missionId} onClose={() => setOpen(null)} onChanged={() => { results.reload(); summary.reload(); }} />}
    </div>
  );
}
