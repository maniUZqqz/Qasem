import { useState } from "react";

import Icon from "../../../../components/Icon";
import { Badge, Input, Spinner } from "../../../../components/ui";
import { useGet } from "../../api";
import { asList, useDebounced } from "../../outreach/api";
import type { LeadRow, Paged } from "../../types";
import { shortUrl } from "../../format";
import { Ltr } from "./shared";

/**
 * Search the lead database (`GET /growth/leads/?q=`) and pick one lead (`multi=false`) or several.
 * The chosen leads are kept by the caller as plain `LeadRow`s.
 */
export default function LeadPicker({
  selected,
  onChange,
  multi = false,
  placeholder = "نام، سایت، تلفن یا شهرِ لید را بنویسید…",
}: {
  selected: LeadRow[];
  onChange: (next: LeadRow[]) => void;
  multi?: boolean;
  placeholder?: string;
}) {
  const [q, setQ] = useState("");
  const search = useDebounced(q.trim(), 350);
  const list = useGet<Paged<LeadRow> | LeadRow[]>("/leads/", { q: search || undefined, page_size: 8 });
  const rows = asList(list.data);
  const isSelected = (id: number) => selected.some((l) => l.id === id);

  const toggle = (lead: LeadRow) => {
    if (!multi) return onChange([lead]);
    onChange(isSelected(lead.id) ? selected.filter((l) => l.id !== lead.id) : [...selected, lead]);
  };

  return (
    <div className="space-y-2" data-testid="lead-picker">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="lead-picker-selected">
          {selected.map((lead) => (
            <span key={lead.id} className="u-badge u-badge-brand inline-flex items-center gap-1">
              {lead.display_name}
              <button type="button" onClick={() => onChange(selected.filter((l) => l.id !== lead.id))} aria-label={`برداشتن ${lead.display_name}`} className="inline-grid place-items-center">
                <Icon name="x" size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={placeholder} aria-label="جست‌وجوی لید" data-testid="lead-picker-search" />
      <div className="max-h-56 overflow-y-auto rounded-xl" style={{ border: "1px solid var(--line)" }}>
        {list.loading && !list.data ? (
          <div className="py-4 text-center">
            <Spinner size={18} />
          </div>
        ) : list.error ? (
          <div className="p-3 text-sm" style={{ color: "var(--bad)" }}>
            {list.error}
          </div>
        ) : rows.length === 0 ? (
          <div className="p-3 text-center text-sm" style={{ color: "var(--text-3)" }}>
            لیدی پیدا نشد.
          </div>
        ) : (
          <ul>
            {rows.map((lead) => {
              const on = isSelected(lead.id);
              return (
                <li key={lead.id}>
                  <button
                    type="button"
                    onClick={() => toggle(lead)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-start text-sm"
                    style={{ background: on ? "var(--brand-soft)" : "transparent", borderBottom: "1px solid var(--line)" }}
                    data-testid="lead-picker-row"
                    aria-pressed={on}
                  >
                    <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md" style={{ border: "1px solid var(--line-strong)", background: on ? "var(--brand)" : "transparent", color: "#fff" }}>
                      {on && <Icon name="check" size={12} strokeWidth={3} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium" style={{ color: "var(--text)" }}>
                        {lead.display_name}
                      </span>
                      <span className="block truncate text-xs" style={{ color: "var(--text-3)" }}>
                        {[lead.city, lead.website ? shortUrl(lead.website) : ""].filter(Boolean).map((part, i) => (i === 1 ? <Ltr key={i}>{part}</Ltr> : <span key={i}>{part} · </span>))}
                      </span>
                    </span>
                    {lead.do_not_contact && <Badge tone="bad">تماس نگیر</Badge>}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
