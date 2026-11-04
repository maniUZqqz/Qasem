import { Link } from "react-router-dom";

import { Card, SectionTitle } from "../../../../components/ui";
import { faDate, faDateTime, sourceText } from "../../format";
import type { LeadDetail } from "../../types";
import { InfoRow } from "../bits";

/** The side column of the lead page: dates, origin, and every «منبع» (how and when we found the lead). */
export default function SummaryCards({ lead }: { lead: LeadDetail }) {
  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>خلاصه</SectionTitle>
        <div data-testid="lead-summary">
          <InfoRow label="ثبت">{faDateTime(lead.created_at)}</InfoRow>
          <InfoRow label="آخرین تغییر">{faDateTime(lead.updated_at)}</InfoRow>
          <InfoRow label="روشِ کشف">{lead.origin_label}</InfoRow>
          <InfoRow label="ثبت‌کننده">{lead.created_by_name || "—"}</InfoRow>
          <InfoRow label="کشور">{lead.country_name || "—"}</InfoRow>
          <InfoRow label="یادداشت‌ها">{lead.notes_count}</InfoRow>
          <InfoRow label="راه‌های تماس">{lead.contacts.length}</InfoRow>
        </div>
      </Card>
      <Card>
        <SectionTitle>منبع‌ها</SectionTitle>
        {lead.sources.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            منبعی ثبت نشده.
          </p>
        ) : (
          <ul className="space-y-3" data-testid="lead-sources">
            {lead.sources.map((s) => (
              <li key={s.id} className="text-sm">
                <div className="font-medium" style={{ color: "var(--text)" }}>
                  {s.provider_label}
                </div>
                <div className="text-xs leading-6" style={{ color: "var(--text-3)" }}>
                  {sourceText(s.source)} · {faDate(s.discovered_at)}
                  {s.created_by ? ` · ${s.created_by}` : ""}
                </div>
                <div className="flex flex-wrap gap-x-3 text-xs">
                  {s.job_id && (
                    <Link to={`/growth/discovery?tab=csv&job=${s.job_id}`}>ورودیِ {s.job_id}</Link>
                  )}
                  {s.source_url && (
                    <a href={s.source_url} target="_blank" rel="noopener noreferrer" dir="ltr" style={{ unicodeBidi: "plaintext" }}>
                      {s.source_url.replace(/^https?:\/\//, "")}
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
