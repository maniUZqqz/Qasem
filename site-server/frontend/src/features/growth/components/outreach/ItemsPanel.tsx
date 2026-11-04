import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import Icon from "../../../../components/Icon";
import { Alert, Badge, Button, Card, EmptyState, Input, Table, fa } from "../../../../components/ui";
import { g, useGet } from "../../api";
import { shortUrl } from "../../format";
import { asList, countOf, useAction, useDebounced } from "../../outreach/api";
import { COUNTER_ORDER, GUESS_LABEL, itemLeadId, itemLeadName, itemStatus, reasonText } from "../../outreach/labels";
import type { ApproveResult, Campaign, CampaignStatusInfo, GrowthSettings, OutreachItem } from "../../outreach/types";
import type { Paged } from "../../types";
import { LoadState } from "../bits";
import { ConfirmDialog } from "../Modal";
import Pagination from "../Pagination";
import { ChannelBadge, RecipientText } from "./ChannelBits";
import ReviewDialog from "./ReviewDialog";
import { Flash, ItemStatusBadge, Ltr } from "./shared";

const PAGE_SIZE = 25;
const UNSENDABLE = ["sent", "sending", "handed_off"];

function ApprovalCell({ item }: { item: OutreachItem }) {
  const a = item.approval;
  if (item.status === "approved" && a?.valid) return <Badge tone="ok">تأییدِ معتبر</Badge>;
  if (a && !a.valid) return <Badge tone="warn">تأیید باطل شد</Badge>;
  return <span style={{ color: "var(--text-3)" }}>—</span>;
}

function AttemptCell({ item }: { item: OutreachItem }) {
  const a = item.attempt;
  if (!a) return <span style={{ color: "var(--text-3)" }}>—</span>;
  const guess = GUESS_LABEL[a.success_guess];
  if (item.channel && item.channel !== "contact_form") {
    // e-mail / SMS: there is no HTTP status; say what the mail server / the phone did
    const label: Record<string, string> = { smtp_accepted: "سرورِ ایمیل پذیرفت", queued_on_phone: "در صفِ گوشی", sent_by_phone: "گوشی فرستاد", delivered: "تحویل شد", failed_on_phone: "گوشی نتوانست", cancelled_before_sent: "پیش از ارسال لغو شد" };
    return (
      <span className="inline-flex flex-wrap items-center gap-1">
        <Badge tone={a.success_guess === "likely_failure" ? "bad" : a.success_guess === "likely_success" ? "ok" : "info"}>{label[a.outcome] ?? a.outcome ?? a.method}</Badge>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge tone={a.status_code >= 200 && a.status_code < 400 ? "ok" : "bad"}>
        <span dir="ltr">{a.status_code || "—"}</span>
      </Badge>
      {guess && <Badge tone={guess.tone}>{guess.label}</Badge>}
    </span>
  );
}

/**
 * The items of a campaign: filter by status, search, select, approve / revoke / remove in batches,
 * and open the review dialog (exact message + dry run) per item.
 */
export default function ItemsPanel({
  campaign,
  status,
  settings,
  refreshKey,
  filter,
  onFilter,
  onChanged,
}: {
  campaign: Campaign;
  status: CampaignStatusInfo;
  settings: GrowthSettings | null;
  refreshKey: string;
  filter: string;
  onFilter: (value: string) => void;
  onChanged: () => void;
}) {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const search = useDebounced(q.trim(), 350);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [reviewIndex, setReviewIndex] = useState<number | null>(null);
  const [askAll, setAskAll] = useState(false);
  const [askRemove, setAskRemove] = useState(false);
  const [result, setResult] = useState<ApproveResult | null>(null);
  const [note, setNote] = useState<{ tone: "ok" | "warn" | "bad"; text: string } | null>(null);
  const act = useAction();

  const list = useGet<Paged<OutreachItem> | OutreachItem[]>(`/outreach/campaigns/${campaign.id}/items/`, {
    status: filter === "all" ? undefined : filter,
    q: search || undefined,
    page,
    page_size: PAGE_SIZE,
  });
  const rows = asList(list.data);
  const count = countOf(list.data);

  // parent counters changed (a job moved things along): reload quietly
  const reloadRef = useRef(list.reload);
  reloadRef.current = list.reload;
  const first = useRef(true);
  const reviewing = useRef(false);
  reviewing.current = reviewIndex !== null;
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    // while an item is open for review the list must not reshuffle under it (it reloads when the dialog closes)
    if (!reviewing.current) reloadRef.current();
  }, [refreshKey]);

  useEffect(() => {
    setPage(1);
    setSelected(new Set());
  }, [filter, search]);
  useEffect(() => setSelected(new Set()), [page]);

  const counts = status.counts;
  const tabs = useMemo(() => COUNTER_ORDER.filter((s) => (counts[s] ?? 0) > 0), [counts]);
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allOnPage = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const toggleAll = () => setSelected(allOnPage ? new Set() : new Set(rows.map((r) => r.id)));

  const picked = rows.filter((r) => selected.has(r.id));
  const pickedReady = picked.filter((r) => r.status === "ready");
  const pickedApproved = picked.filter((r) => r.status === "approved");
  const pickedRemovable = picked.filter((r) => !UNSENDABLE.includes(r.status));

  const afterApprove = (r: ApproveResult) => {
    setResult(r);
    setNote(null);
    setSelected(new Set());
    onChanged();
    list.reload();
  };

  const approveSelected = async () => {
    const r = await act.run(() => g.post<ApproveResult>(`/outreach/campaigns/${campaign.id}/approve/`, { item_ids: pickedReady.map((i) => i.id) }));
    if (r) afterApprove(r);
  };
  const approveAll = async () => {
    const r = await act.run(() => g.post<ApproveResult>(`/outreach/campaigns/${campaign.id}/approve/`, { all_ready: true }));
    setAskAll(false);
    if (r) afterApprove(r);
  };
  const revokeSelected = async () => {
    const r = await act.run(() => g.post(`/outreach/campaigns/${campaign.id}/revoke/`, { item_ids: pickedApproved.map((i) => i.id) }));
    if (r !== undefined) {
      setResult(null);
      setNote({ tone: "ok", text: `تأییدِ ${fa(pickedApproved.length)} مورد لغو شد؛ این موردها دیگر ارسال نمی‌شوند تا دوباره تأیید کنید.` });
      setSelected(new Set());
      onChanged();
      list.reload();
    }
  };
  const removeSelected = async () => {
    const r = await act.run(() => g.post(`/outreach/campaigns/${campaign.id}/remove-items/`, { item_ids: pickedRemovable.map((i) => i.id) }));
    setAskRemove(false);
    if (r !== undefined) {
      setResult(null);
      setNote({ tone: "ok", text: `${fa(pickedRemovable.length)} مورد از کمپین برداشته شد.` });
      setSelected(new Set());
      onChanged();
      list.reload();
    }
  };

  const approvedCount = counts.approved ?? 0;
  const readyCount = counts.ready ?? 0;
  const finished = campaign.status === "completed" || campaign.status === "cancelled";

  return (
    <div className="space-y-4" data-testid="items-panel">
      {/* ------------------------------------------------------------ filters + batch buttons */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="فیلترِ وضعیت">
          <button type="button" role="tab" aria-selected={filter === "all"} onClick={() => onFilter("all")} className={`u-btn u-btn-sm ${filter === "all" ? "u-btn-primary" : "u-btn-secondary"}`}>
            همه ({fa(total)})
          </button>
          {tabs.map((s) => (
            <button key={s} type="button" role="tab" aria-selected={filter === s} onClick={() => onFilter(s)} className={`u-btn u-btn-sm ${filter === s ? "u-btn-primary" : "u-btn-secondary"}`} data-testid={`filter-${s}`}>
              {itemStatus(s).label} ({fa(counts[s])})
            </button>
          ))}
        </div>
        <div className="w-full sm:w-64">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جست‌وجو در موردها…" aria-label="جست‌وجو" data-testid="items-search" />
        </div>
      </div>

      {note && (
        <Flash tone={note.tone} onClose={() => setNote(null)}>
          {note.text}
        </Flash>
      )}
      {result && (
        <div data-testid="approve-result">
          <Alert tone={result.approved > 0 ? "ok" : "warn"} title={`${fa(result.approved)} مورد تأیید شد`}>
            <p>
              این موردها در نوبتِ ارسال‌اند. تأییدِ همهٔ تأییدشده‌ها: {fa(approvedCount)} مورد. سقفِ باقی‌ماندهٔ امروز: {fa(status.cap_remaining)} از {fa(status.daily_cap)}.
              {approvedCount > status.cap_remaining ? " بیشتر از سقفِ امروز تأیید شده؛ باقی‌اش روزِ بعد می‌رود." : ""}
            </p>
            {result.refused.length > 0 && (
              <div className="mt-2">
                <b>{fa(result.refused.length)} مورد تأیید نشد:</b>
                <ul className="list-disc ps-5">
                  {result.refused.slice(0, 8).map((r) => (
                    <li key={r.item_id}>
                      مورد {fa(r.item_id)}: {r.text}
                    </li>
                  ))}
                  {result.refused.length > 8 && <li>و {fa(result.refused.length - 8)} موردِ دیگر</li>}
                </ul>
              </div>
            )}
          </Alert>
        </div>
      )}
      {act.error && <Flash tone="bad">{act.error.message}</Flash>}

      {campaign.mode === "auto" && !finished && (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => setAskAll(true)} disabled={readyCount === 0 || act.busy || !settings} data-testid="approve-all-ready">
            <Icon name="check" size={16} />
            تأییدِ همهٔ آماده‌ها ({fa(readyCount)})
          </Button>
          <span className="text-xs" style={{ color: "var(--text-3)" }}>
            تأییدشده تا حالا: {fa(approvedCount)} · سقفِ باقی‌ماندهٔ امروز: {fa(status.cap_remaining)}
          </span>
        </div>
      )}

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl p-3" style={{ background: "var(--brand-soft)", border: "1px solid var(--line)" }} data-testid="batch-bar">
          <b className="text-sm" style={{ color: "var(--text)" }}>
            {fa(selected.size)} مورد انتخاب شده
          </b>
          {campaign.mode === "auto" && (
            <>
              <Button size="sm" onClick={approveSelected} disabled={pickedReady.length === 0 || act.busy} data-testid="approve-selected" title={pickedReady.length === 0 ? "بینِ انتخاب‌شده‌ها موردِ «آمادهٔ تأیید» نیست" : undefined}>
                <Icon name="check" size={14} />
                تأییدِ انتخاب‌شده ({fa(pickedReady.length)})
              </Button>
              <Button size="sm" variant="secondary" onClick={revokeSelected} disabled={pickedApproved.length === 0 || act.busy} data-testid="revoke-selected">
                لغوِ تأیید ({fa(pickedApproved.length)})
              </Button>
            </>
          )}
          <Button size="sm" variant="danger" onClick={() => setAskRemove(true)} disabled={pickedRemovable.length === 0 || act.busy} data-testid="remove-selected">
            <Icon name="trash" size={14} />
            حذف از کمپین ({fa(pickedRemovable.length)})
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            برداشتنِ انتخاب
          </Button>
        </div>
      )}

      {/* ------------------------------------------------------------ the table */}
      <Card padded={false}>
        <div className="p-2">
          <LoadState loading={list.loading && !list.data} error={list.error} onRetry={list.reload}>
            {rows.length === 0 ? (
              <EmptyState icon="inbox" title={search || filter !== "all" ? "موردی پیدا نشد" : "هنوز لیدی در کمپین نیست"}>
                {search || filter !== "all" ? "فیلتر یا جست‌وجو را عوض کنید." : "لید اضافه کنید: از «دیتابیس لیدها» چند لید را انتخاب کنید و «افزودن به کمپین» را بزنید."}
              </EmptyState>
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <th style={{ width: 36 }}>
                        <input type="checkbox" checked={allOnPage} onChange={toggleAll} aria-label="انتخابِ همهٔ این صفحه" />
                      </th>
                      <th className="text-start">لید</th>
                      <th className="text-start">کانال و مقصد</th>
                      <th className="text-start">وضعیت</th>
                      <th className="text-start">تأیید</th>
                      <th className="text-start">ارسال</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((item, i) => {
                      const reason = reasonText(item);
                      const leadId = itemLeadId(item);
                      return (
                        <tr key={item.id} data-testid="item-row" data-status={item.status}>
                          <td>
                            <input type="checkbox" checked={selected.has(item.id)} onChange={() => toggle(item.id)} aria-label={`انتخابِ ${itemLeadName(item)}`} />
                          </td>
                          <td className="min-w-[10rem]">
                            {leadId ? (
                              <Link to={`/growth/leads/${leadId}`} className="font-medium no-underline" style={{ color: "var(--text)" }}>
                                {itemLeadName(item)}
                              </Link>
                            ) : (
                              itemLeadName(item)
                            )}
                            {item.domain && (
                              <div className="text-xs" style={{ color: "var(--text-3)" }}>
                                <Ltr>{item.domain}</Ltr>
                              </div>
                            )}
                          </td>
                          <td className="max-w-[14rem]">
                            <div className="mb-1">
                              <ChannelBadge channel={item.channel} label={item.channel_label} />
                            </div>
                            {item.target_url && (item.channel ?? "contact_form") === "contact_form" ? (
                              <a href={item.target_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--brand-strong)" }}>
                                <Ltr className="text-xs">{shortUrl(item.target_url)}</Ltr>
                              </a>
                            ) : (
                              <RecipientText item={item} />
                            )}
                          </td>
                          <td className="min-w-[9rem]">
                            <ItemStatusBadge status={item.status} label={item.status_label} />
                            {reason && (
                              <div className="mt-1 text-xs leading-5" style={{ color: "var(--text-3)" }}>
                                {reason}
                              </div>
                            )}
                          </td>
                          <td>
                            <ApprovalCell item={item} />
                          </td>
                          <td>
                            <AttemptCell item={item} />
                          </td>
                          <td className="text-end">
                            <Button size="sm" variant="secondary" onClick={() => setReviewIndex(i)} data-testid="item-review">
                              بررسی
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </Table>
                <Pagination page={page} pageSize={PAGE_SIZE} count={count} onPage={setPage} disabled={list.loading} />
              </>
            )}
          </LoadState>
        </div>
      </Card>

      <ReviewDialog
        open={reviewIndex !== null}
        campaignId={campaign.id}
        itemIds={rows.map((r) => r.id)}
        index={reviewIndex ?? 0}
        onIndex={(i) => setReviewIndex(Math.max(0, Math.min(rows.length - 1, i)))}
        onClose={() => {
          setReviewIndex(null);
          list.reload();
        }}
        onChanged={() => {
          onChanged();
        }}
        settings={settings}
        capRemaining={status.cap_remaining}
      />

      <ConfirmDialog
        open={askAll}
        title="همهٔ موردهای آماده تأیید شوند؟"
        confirmLabel={`بله، ${fa(readyCount)} مورد تأیید شود`}
        busy={act.busy}
        onConfirm={approveAll}
        onClose={() => setAskAll(false)}
        message={
          <div className="space-y-2">
            <p>
              <b>{fa(readyCount)}</b> موردِ «آمادهٔ تأیید» تأیید می‌شود. هر کدام قبل از ارسال دوباره بررسی می‌شود و اگر فرمش عوض شده باشد نمی‌رود.
            </p>
            <p>
              سقفِ باقی‌ماندهٔ امروز: <b>{fa(status.cap_remaining)}</b> از {fa(status.daily_cap)}. موردهای بیشتر از سقف روزِ بعد می‌روند (با «ادامهٔ ارسال»).
            </p>
            <p style={{ color: "var(--text-3)" }}>پیش از تأیید، چند موردِ نمونه را با «بررسی» ببینید.</p>
          </div>
        }
      />
      <ConfirmDialog
        open={askRemove}
        title="از کمپین برداشته شود؟"
        danger
        confirmLabel={`بله، ${fa(pickedRemovable.length)} مورد برداشته شود`}
        busy={act.busy}
        onConfirm={removeSelected}
        onClose={() => setAskRemove(false)}
        message="این موردها از کمپین حذف می‌شوند (لیدها در دیتابیس می‌مانند). موردهای ارسال‌شده حذف نمی‌شوند."
      />
    </div>
  );
}
