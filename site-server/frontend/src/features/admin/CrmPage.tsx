import { useCallback, useEffect, useState } from "react";

import { api, errorMessage } from "../../api/client";
import Icon from "../../components/Icon";
import { StatRow, StatTile } from "../../components/charts";
import {
  Alert,
  Badge,
  Card,
  EmptyState,
  ErrorBox,
  SectionTitle,
  Spinner,
  Table,
  fa,
} from "../../components/ui";

/**
 * CRM به‌عنوان یک جریان.
 *
 * مرحله‌ها **عقب هم می‌روند**: مشتری‌ای که پول می‌دهد و دیگر استفاده
 * نمی‌کند، از «فعال» به «در حال از دست رفتن» برمی‌گردد — و همان مهم‌ترین
 * ردیف صفحه است.
 *
 * هیچ عدد «احتمال ریزش»ی اینجا نیست. هر ریسک یک **واقعه با تاریخ** است
 * («۱۴ روز است چیزی تولید نکرده»)، چون عددی که کسی نتواند بگوید از کجا
 * آمده، یک بار دنبالش می‌روند و بعد نادیده‌اش می‌گیرند.
 */

type Risk = { key: string; what: string; level: string };

type Row = {
  store_id: number;
  name: string;
  owner: string;
  stage: string;
  plan?: string;
  paying?: boolean;
  days_since_signup?: number;
  days_since_activity?: number | null;
  outputs?: number;
  published?: number;
  open_tickets?: number;
  channel?: string;
  risks?: Risk[];
};

/** دقیقاً همان چیزی که `crm.leads()` می‌دهد.
 *
 *  اینجا `created_at` **نیست** — سرور `days_waiting` می‌دهد، که عدد
 *  مفیدتری هم هست: «۳ روز منتظر» تصمیم را عوض می‌کند، تاریخِ خام نه. */
type Lead = {
  id: number;
  name: string;
  email: string;
  business: string;
  subject: string;
  status: string;
  status_title: string;
  days_waiting: number;
  unanswered: boolean;
  source: string;
};

type Board = {
  stages: { key: string; title: string; count: number; customers: Row[] }[];
  leads: Lead[];
  today: { unanswered_leads: Lead[]; at_risk: Row[] };
  totals: { leads: number; customers: number; paying: number; at_risk: number };
  note?: string;
};

const STAGE_TONE: Record<string, "neutral" | "info" | "brand" | "ok" | "warn" | "bad"> = {
  LEAD: "neutral",
  SIGNED_UP: "info",
  ONBOARDING: "brand",
  ACTIVE: "ok",
  SLIPPING: "warn",
  LAPSED: "bad",
};

function RiskList({ risks }: { risks?: Risk[] }) {
  if (!risks?.length) return <span style={{ color: "var(--text-3)" }}>—</span>;
  return (
    <div className="flex flex-col gap-1">
      {risks.map((r) => (
        <span
          key={r.key}
          className="inline-flex items-center gap-1 text-xs"
          style={{ color: r.level === "high" ? "var(--bad)" : "var(--warn)" }}
        >
          <Icon name="warn" size={12} />
          {r.what}
        </span>
      ))}
    </div>
  );
}

export default function CrmPage() {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Board>("/marketing/crm/");
      setBoard(data);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!board) {
    return (
      <div className="py-10 text-center">
        {error ? <ErrorBox message={error} /> : <Spinner />}
      </div>
    );
  }

  const { today, totals } = board;
  const hasWork = today.unanswered_leads.length > 0 || today.at_risk.length > 0;

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />

      <StatRow>
        <StatTile label="سرنخ‌ها" value={fa(totals.leads)} />
        <StatTile series="people" label="مشتری‌ها" value={fa(totals.customers)} />
        <StatTile series="revenue" label="پرداخت‌کننده" value={fa(totals.paying)} />
        <StatTile label="در معرض خطر" value={fa(totals.at_risk)} />
      </StatRow>

      {/* «امروز چه کار کنم» — تنها دلیل باز کردن این صفحه */}
      <Card>
        <SectionTitle>امروز</SectionTitle>
        {!hasWork ? (
          <EmptyState icon="ok" title="کاری نمانده">
            هیچ سرنخ بی‌جواب و هیچ مشتری در معرض خطری نیست.
          </EmptyState>
        ) : (
          <div className="space-y-4">
            {today.unanswered_leads.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-bold" style={{ color: "var(--warn)" }}>
                  {fa(today.unanswered_leads.length)} سرنخ بی‌جواب
                </h3>
                <Table>
                  <thead>
                    <tr>
                      <th>نام</th>
                      <th>ایمیل</th>
                      <th>موضوع</th>
                      <th>از کجا</th>
                      <th>انتظار</th>
                    </tr>
                  </thead>
                  <tbody>
                    {today.unanswered_leads.map((l) => (
                      <tr key={l.id}>
                        <td style={{ color: "var(--text)" }}>
                          {l.name || "—"}
                          {l.business && (
                            <span className="block text-xs" style={{ color: "var(--text-3)" }}>
                              {l.business}
                            </span>
                          )}
                        </td>
                        <td dir="ltr">{l.email || "—"}</td>
                        <td>{l.subject || "—"}</td>
                        <td dir="ltr" className="text-xs" style={{ color: "var(--text-3)" }}>
                          {l.source || "—"}
                        </td>
                        <td>
                          {/* روزِ انتظار، نه تاریخ: تصمیم را همین عدد عوض می‌کند */}
                          <Badge tone={l.days_waiting >= 2 ? "bad" : "warn"}>
                            {fa(l.days_waiting)} روز
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            )}

            {today.at_risk.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-bold" style={{ color: "var(--bad)" }}>
                  {fa(today.at_risk.length)} مشتری در معرض از دست رفتن
                </h3>
                <Table>
                  <thead>
                    <tr>
                      <th>فروشگاه</th>
                      <th>مالک</th>
                      <th>پلن</th>
                      <th>چرا</th>
                    </tr>
                  </thead>
                  <tbody>
                    {today.at_risk.map((r) => (
                      <tr key={r.store_id}>
                        <td style={{ color: "var(--text)", fontWeight: 500 }}>{r.name}</td>
                        <td>{r.owner}</td>
                        <td>{r.plan || "—"}</td>
                        <td>
                          <RiskList risks={r.risks} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* مرحله‌ها به ترتیب جریان — و «در حال از دست رفتن» بعد از «فعال»
          می‌آید چون واقعاً از آنجا برمی‌گردد */}
      <div className="grid gap-4 lg:grid-cols-2">
        {board.stages.map((stage) => (
          <Card key={stage.key}>
            <div className="mb-3 flex items-center gap-2">
              <Badge tone={STAGE_TONE[stage.key] ?? "neutral"}>{stage.title}</Badge>
              <span className="u-num text-sm" style={{ color: "var(--text-3)" }}>
                {fa(stage.count)}
              </span>
            </div>
            {stage.customers.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-3)" }}>
                کسی در این مرحله نیست.
              </p>
            ) : (
              <ul className="space-y-2">
                {stage.customers.map((r) => (
                  <li
                    key={r.store_id}
                    className="rounded-lg p-2.5"
                    style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold" style={{ color: "var(--text)" }}>
                        {r.name}
                      </span>
                      <span className="text-xs" style={{ color: "var(--text-3)" }}>
                        {r.owner}
                      </span>
                      {r.paying && <Badge tone="ok">{r.plan}</Badge>}
                      {r.channel && (
                        <span className="mr-auto text-xs" style={{ color: "var(--text-3)" }}>
                          از {r.channel}
                        </span>
                      )}
                    </div>
                    <div
                      className="mt-1 flex flex-wrap gap-3 text-xs"
                      style={{ color: "var(--text-3)" }}
                    >
                      <span>{fa(r.outputs ?? 0)} خروجی</span>
                      <span>{fa(r.published ?? 0)} منتشرشده</span>
                      {!!r.open_tickets && <span>{fa(r.open_tickets)} تیکت باز</span>}
                      {r.days_since_activity != null && (
                        <span>{fa(r.days_since_activity)} روز بی‌فعالیت</span>
                      )}
                    </div>
                    {!!r.risks?.length && (
                      <div className="mt-1.5">
                        <RiskList risks={r.risks} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>

      {board.note && (
        <Alert tone="info">
          {board.note}
        </Alert>
      )}
    </div>
  );
}
