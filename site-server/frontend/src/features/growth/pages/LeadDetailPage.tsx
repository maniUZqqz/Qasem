import { Link, useParams, useSearchParams } from "react-router-dom";

import Icon from "../../../components/Icon";
import { Alert, Button, Card, EmptyState, fa } from "../../../components/ui";
import { useGet } from "../api";
import { LoadState } from "../components/bits";
import ExtractionTab from "../components/extraction/ExtractionTab";
import ContactsTab from "../components/leads/ContactsTab";
import HistoryTab from "../components/leads/HistoryTab";
import InfoTab from "../components/leads/InfoTab";
import LeadHeader from "../components/leads/LeadHeader";
import NotesTab from "../components/leads/NotesTab";
import SummaryCards from "../components/leads/SummaryCards";
import type { LeadDetail } from "../types";

const TABS = [
  { key: "info", label: "اطلاعات" },
  { key: "contacts", label: "راه‌های تماس" },
  { key: "extraction", label: "استخراج" },
  { key: "notes", label: "یادداشت‌ها" },
  { key: "history", label: "تاریخچه" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

/** «جزئیات لید»: header + five tabs + a side column. The tab lives in the URL (`?tab=history`). */
export default function LeadDetailPage() {
  const { id } = useParams();
  const leadId = Number(id);
  const valid = Number.isInteger(leadId) && leadId > 0;
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as TabKey | null;
  const tab: TabKey = TABS.some((t) => t.key === requested) ? (requested as TabKey) : "info";
  const { data: lead, loading, error, reload, setData } = useGet<LeadDetail>(valid ? `/leads/${leadId}/` : null);

  const setTab = (key: TabKey) => {
    const next = new URLSearchParams(params);
    if (key === "info") next.delete("tab");
    else next.set("tab", key);
    setParams(next, { replace: true });
  };

  const notFound = !valid || (!!error && error.includes("404"));

  return (
    <div className="space-y-4" data-testid="growth-lead">
      <Link to="/growth/leads" className="u-back">
        <Icon name="back" size={15} />
        بازگشت به لیدها
      </Link>

      {notFound ? (
        <Card>
          <EmptyState
            icon="empty"
            title="این لید پیدا نشد"
            description="شاید حذف شده باشد یا آدرس درست نباشد."
            action={
              <Link to="/growth/leads" className="no-underline">
                <Button>رفتن به فهرست لیدها</Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <LoadState loading={loading && !lead} error={error} onRetry={reload}>
          {lead && (
            <>
              <LeadHeader lead={lead} onUpdated={setData} onReload={reload} />

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="min-w-0 space-y-4 lg:col-span-2">
                  <div className="u-tabs" role="tablist" aria-label="بخش‌های لید">
                    {TABS.map((t) => (
                      <button
                        key={t.key}
                        type="button"
                        role="tab"
                        aria-selected={t.key === tab}
                        className={`u-tab ${t.key === tab ? "active" : ""}`}
                        onClick={() => setTab(t.key)}
                        data-testid={`lead-tab-${t.key}`}
                      >
                        {t.label}
                        {t.key === "contacts" && ` (${fa(lead.contacts.length)})`}
                        {t.key === "notes" && lead.notes_count > 0 && ` (${fa(lead.notes_count)})`}
                      </button>
                    ))}
                  </div>

                  {tab === "info" && <InfoTab lead={lead} onSaved={setData} />}
                  {tab === "contacts" && <ContactsTab lead={lead} onChanged={reload} />}
                  {tab === "extraction" && <ExtractionTab lead={lead} onChanged={reload} />}
                  {tab === "notes" && <NotesTab leadId={lead.id} onChanged={reload} />}
                  {tab === "history" && <HistoryTab leadId={lead.id} />}
                </div>
                <div className="min-w-0 lg:col-span-1">
                  <SummaryCards lead={lead} />
                </div>
              </div>
            </>
          )}
          {!lead && error && !loading && <Alert tone="bad">{error}</Alert>}
        </LoadState>
      )}
    </div>
  );
}
