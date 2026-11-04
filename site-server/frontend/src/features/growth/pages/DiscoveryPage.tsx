import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import CsvWizard from "../components/discovery/CsvWizard";
import ManualForm from "../components/discovery/ManualForm";
import RecentJobs from "../components/discovery/RecentJobs";
import type { ManualMode } from "../types";

const TABS: { key: string; label: string; mode?: ManualMode }[] = [
  { key: "website", label: "آدرس وب‌سایت", mode: "website_url" },
  { key: "instagram", label: "پیج اینستاگرام", mode: "instagram_url" },
  { key: "name", label: "نام کسب‌وکار", mode: "business_name" },
  { key: "manual", label: "ثبت کامل", mode: "manual" },
  { key: "csv", label: "فایل CSV" },
];

/**
 * «کشف مشتری»: how businesses enter the database by hand - a website, an Instagram page (stored as given,
 * never fetched), a name, a full form, or a CSV file. The tab and the open import live in the URL
 * (`?tab=csv&job=12`) so a progress page can be linked and survives a refresh.
 */
export default function DiscoveryPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") ?? "website";
  const jobParam = Number(params.get("job"));
  const jobId = Number.isInteger(jobParam) && jobParam > 0 ? jobParam : null;
  const tab = jobId !== null ? "csv" : TABS.some((t) => t.key === requested) ? requested : "website";
  const [refreshKey, setRefreshKey] = useState(0);

  const update = (next: Record<string, string | null>) => {
    const merged = new URLSearchParams(params);
    Object.entries(next).forEach(([k, v]) => (v === null ? merged.delete(k) : merged.set(k, v)));
    setParams(merged, { replace: false });
  };
  const current = TABS.find((t) => t.key === tab) ?? TABS[0];

  return (
    <div className="space-y-5" data-testid="growth-discovery">
      <div className="u-tabs" role="tablist" aria-label="روش‌های کشف">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={t.key === tab}
            className={`u-tab ${t.key === tab ? "active" : ""}`}
            onClick={() => update({ tab: t.key, job: t.key === "csv" ? params.get("job") : null })}
            data-testid={`tab-${t.key}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {current.mode ? (
        <ManualForm key={current.mode} mode={current.mode} />
      ) : (
        <CsvWizard
          jobId={jobId}
          onJobChange={(id) => {
            update({ tab: "csv", job: id === null ? null : String(id) });
            setRefreshKey((k) => k + 1);
          }}
        />
      )}

      <RecentJobs
        activeId={jobId}
        refreshKey={refreshKey}
        onOpen={(id) => {
          update({ tab: "csv", job: String(id) });
          window.scrollTo({ top: 0, behavior: "smooth" });
        }}
      />
    </div>
  );
}
