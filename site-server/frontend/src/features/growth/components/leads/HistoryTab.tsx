import { useState } from "react";

import { Badge, Card, EmptyState, Select } from "../../../../components/ui";
import { useGet } from "../../api";
import { faDateTime } from "../../format";
import { useMeta } from "../../MetaContext";
import type { Activity, Paged } from "../../types";
import Pagination from "../Pagination";
import { LoadState } from "../bits";

const FIELD_FA: Record<string, string> = {
  business_name: "نام", category: "دسته", description: "توضیحات", city: "شهر", country: "کشور", website: "وب‌سایت", instagram_url: "اینستاگرام",
  "profile.language": "زبان", "profile.business_type": "نوع کسب‌وکار", "profile.address": "نشانی",
  "profile.product_categories": "دسته‌های محصول", "profile.product_names": "نام محصولات",
  instagram: "اینستاگرام", language: "زبان", business_type: "نوع کسب‌وکار", address: "نشانی", product_categories: "دسته‌های محصول", product_names: "نام محصولات",
};
const label = (f: string) => FIELD_FA[f] ?? f;
const OUTCOME_FA: Record<string, string> = {
  sent: "ارسال شد", manual_sent: "دستی فرستاده شد", no_form: "فرم نداشت", needs_login: "ورود لازم داشت", skipped: "رد شد", failed: "ناموفق",
};

const text = (v: unknown): string => (typeof v === "string" ? v : v === null || v === undefined ? "" : Array.isArray(v) ? v.join("، ") : String(v));
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The details line of one history event: old -> new values, the exact message of a queue outcome, merge results. */
function Details({ item }: { item: Activity }) {
  const d = item.data ?? {};
  const changes = isRecord(d.changes) ? d.changes : null;
  const message = typeof d.message_text === "string" ? d.message_text : "";
  const outcome = typeof d.outcome === "string" ? d.outcome : "";
  const lists: [string, unknown][] = [
    ["جای خالی پر شد", d.filled],
    ["جایگزین شد", d.overwritten],
    ["فرق داشتند و دست نخوردند", d.conflicts],
  ];
  const shownLists = lists.filter(([, v]) => Array.isArray(v) && v.length > 0);
  // old/new strings are readable only for contact edits (status events carry codes; their summary is already in words)
  const old = item.kind === "contact_updated" && typeof d.old === "string" ? d.old : "";
  const next = item.kind === "contact_updated" && typeof d.new === "string" ? d.new : "";
  if (!changes && !message && !shownLists.length && !(old && next)) return null;
  return (
    <div className="mt-1.5 space-y-1.5 text-xs" style={{ color: "var(--text-2)" }}>
      {changes &&
        Object.entries(changes).map(([field, change]) =>
          isRecord(change) ? (
            <div key={field} dir="auto" data-testid="change-line">
              <b>{label(field)}:</b> <span style={{ color: "var(--text-3)", textDecoration: "line-through" }}>{text(change.old) || "خالی"}</span> ← <span>{text(change.new) || "خالی"}</span>
            </div>
          ) : null,
        )}
      {old && next && !changes && (
        <div dir="auto">
          <span style={{ color: "var(--text-3)", textDecoration: "line-through" }}>{old}</span> ← <span>{next}</span>
        </div>
      )}
      {shownLists.map(([title, v]) => (
        <div key={title} dir="auto">
          <b>{title}:</b> {(v as unknown[]).map((x) => label(text(x))).join("، ")}
        </div>
      ))}
      {outcome && (
        <div>
          <b>نتیجه:</b> {OUTCOME_FA[outcome] ?? outcome}
          {typeof d.target_url === "string" && d.target_url && (
            <>
              {" "}
              · <a href={d.target_url} target="_blank" rel="noopener noreferrer" dir="ltr">صفحهٔ هدف</a>
            </>
          )}
          {typeof d.note === "string" && d.note && <> · {d.note}</>}
        </div>
      )}
      {message && (
        <div>
          <div className="mb-1 font-bold">متنِ دقیقِ پیام:</div>
          <pre className="whitespace-pre-wrap rounded-lg p-2.5 text-xs leading-6" dir="auto" style={{ background: "var(--surface-2)", border: "1px solid var(--line)", fontFamily: "inherit" }} data-testid="exact-message">
            {message}
          </pre>
        </div>
      )}
    </div>
  );
}

/** The «تاریخچه» tab: everything that happened to the lead, newest first, filterable by kind. */
export default function HistoryTab({ leadId }: { leadId: number }) {
  const { meta } = useMeta();
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useGet<Paged<Activity>>(`/leads/${leadId}/activity/`, { page, kind: kind || undefined });

  return (
    <div className="space-y-3" data-testid="history-tab">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm" style={{ color: "var(--text-3)" }}>
          نوعِ رویداد:
        </span>
        <Select
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setPage(1);
          }}
          style={{ width: 200 }}
          aria-label="نوعِ رویداد"
          data-testid="history-kind"
        >
          <option value="">همه</option>
          {(meta?.activity_kinds ?? []).map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </Select>
      </div>
      <LoadState loading={loading && !data} error={error} onRetry={reload}>
        {data && data.results.length === 0 ? (
          <Card>
            <EmptyState icon="clock" title="رویدادی نیست" />
          </Card>
        ) : (
          data && (
            <Card>
              <ul className="divide-y" style={{ borderColor: "var(--line)" }}>
                {data.results.map((a) => (
                  <li key={a.id} className="py-3" data-testid="history-item" data-kind={a.kind}>
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge>{a.kind_label}</Badge>
                      {a.summary && (
                        <span className="min-w-0 break-words" dir="auto" style={{ color: "var(--text)" }}>
                          {a.summary}
                        </span>
                      )}
                      <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
                        {a.actor_name ? `${a.actor_name} · ` : ""}
                        {faDateTime(a.created_at)}
                      </span>
                    </div>
                    <Details item={a} />
                  </li>
                ))}
              </ul>
              <Pagination page={page} pageSize={25} count={data.count} onPage={setPage} disabled={loading} />
            </Card>
          )
        )}
      </LoadState>
    </div>
  );
}
